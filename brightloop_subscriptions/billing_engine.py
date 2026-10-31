"""
Core Billing Engine, Recurring Calculations, Discounts, Taxes, and Lifecycle Logic.
"""

from datetime import datetime, date, timedelta
import calendar
from database import get_db, rows_to_dicts


def add_billing_interval(start_dt: date, frequency: str) -> date:
    """Adds a billing interval (daily, weekly, monthly, yearly) handling month-end bounds."""
    freq = frequency.lower()
    if freq == "daily":
        return start_dt + timedelta(days=1)
    elif freq == "weekly":
        return start_dt + timedelta(weeks=1)
    elif freq == "monthly":
        year = start_dt.year
        month = start_dt.month + 1
        if month > 12:
            month = 1
            year += 1
        max_days = calendar.monthrange(year, month)[1]
        day = min(start_dt.day, max_days)
        return date(year, month, day)
    elif freq == "yearly":
        try:
            return start_dt.replace(year=start_dt.year + 1)
        except ValueError:
            # Leap year Feb 29 -> Feb 28
            return start_dt.replace(year=start_dt.year + 1, day=28)
    return start_dt + timedelta(days=30)


def calculate_due_date(issue_dt: date, payment_terms: str) -> date:
    """Calculates invoice due date based on payment terms."""
    terms = (payment_terms or "Net 30").strip().lower()
    if "receipt" in terms:
        return issue_dt
    elif "15" in terms:
        return issue_dt + timedelta(days=15)
    elif "30" in terms:
        return issue_dt + timedelta(days=30)
    elif "60" in terms:
        return issue_dt + timedelta(days=60)
    elif "90" in terms:
        return issue_dt + timedelta(days=90)
    return issue_dt + timedelta(days=30)


def generate_subscription_number(conn) -> str:
    """Generates next unique sequential subscription number: SUB-YYYY-XXXX."""
    current_year = datetime.now().year
    cursor = conn.cursor()
    cursor.execute("""
        SELECT subscription_number FROM subscriptions 
        WHERE subscription_number LIKE ? 
        ORDER BY id DESC LIMIT 1
    """, (f"SUB-{current_year}-%",))
    row = cursor.fetchone()
    if row:
        last_num = row["subscription_number"]
        try:
            seq = int(last_num.split("-")[-1]) + 1
        except Exception:
            seq = 1
    else:
        seq = 1
    return f"SUB-{current_year}-{seq:04d}"


def generate_invoice_number(conn) -> str:
    """Generates next unique sequential invoice number: INV-YYYY-XXXX."""
    current_year = datetime.now().year
    cursor = conn.cursor()
    cursor.execute("""
        SELECT invoice_number FROM invoices 
        WHERE invoice_number LIKE ? 
        ORDER BY id DESC LIMIT 1
    """, (f"INV-{current_year}-%",))
    row = cursor.fetchone()
    if row:
        last_num = row["invoice_number"]
        try:
            seq = int(last_num.split("-")[-1]) + 1
        except Exception:
            seq = 1
    else:
        seq = 1
    return f"INV-{current_year}-{seq:04d}"


def evaluate_discount(cursor, discount_id: int | None, lines_subtotal: float, total_quantity: int, current_date: date, product_subtotals: dict[int, float] = None) -> tuple[float, str | None, int | None]:
    """
    Evaluates discount eligibility based on:
    - active status
    - date range (start_date <= current_date <= end_date)
    - max_uses limit vs used_count
    - min_purchase_amount
    - min_quantity
    - scope ('whole_subscription' or 'specific_product')
    Returns (discount_amount, discount_code, discount_id_to_increment).
    """
    if not discount_id:
        return 0.0, None, None

    cursor.execute("SELECT * FROM discounts WHERE id = ?", (discount_id,))
    disc = cursor.fetchone()
    if not disc or not disc["is_active"]:
        return 0.0, None, None

    # Check date validity
    if disc["start_date"]:
        start_d = datetime.strptime(disc["start_date"], "%Y-%m-%d").date()
        if current_date < start_d:
            return 0.0, None, None
    if disc["end_date"]:
        end_d = datetime.strptime(disc["end_date"], "%Y-%m-%d").date()
        if current_date > end_d:
            return 0.0, None, None

    # Check max uses
    if disc["max_uses"] is not None and disc["used_count"] >= disc["max_uses"]:
        return 0.0, None, None

    # Check minimum quantity
    if disc["min_quantity"] and total_quantity < disc["min_quantity"]:
        return 0.0, None, None

    # Check minimum purchase amount
    if disc["min_purchase_amount"] and lines_subtotal < disc["min_purchase_amount"]:
        return 0.0, None, None

    discount_amount = 0.0
    scope = disc["scope"]

    if scope == "whole_subscription":
        base_amount = lines_subtotal
        if disc["discount_type"] == "percentage":
            discount_amount = round(base_amount * (disc["value"] / 100.0), 2)
        else: # fixed
            discount_amount = min(base_amount, float(disc["value"]))
    elif scope == "specific_product":
        prod_id = disc["applicable_product_id"]
        prod_amount = (product_subtotals or {}).get(prod_id, 0.0)
        if prod_amount > 0:
            if disc["discount_type"] == "percentage":
                discount_amount = round(prod_amount * (disc["value"] / 100.0), 2)
            else: # fixed
                discount_amount = min(prod_amount, float(disc["value"]))

    return discount_amount, disc["code"], disc["id"]


def generate_invoice_for_subscription(cursor, subscription_id: int, billing_date: date) -> dict | None:
    """
    Creates an invoice for a specific subscription as of billing_date.
    Idempotent: will not create duplicate invoices for the same subscription period.
    """
    cursor.execute("""
        SELECT s.*, p.billing_frequency, p.name as plan_name, p.auto_close_on_end,
               u.name as customer_name, u.email as customer_email, u.company_name
        FROM subscriptions s
        JOIN plans p ON s.plan_id = p.id
        JOIN users u ON s.customer_id = u.id
        WHERE s.id = ?
    """, (subscription_id,))
    sub = cursor.fetchone()
    if not sub:
        return None

    if sub["status"] != "active":
        return None

    # Check expiry
    if sub["expiry_date"]:
        exp_d = datetime.strptime(sub["expiry_date"], "%Y-%m-%d").date()
        if billing_date > exp_d and sub["auto_close_on_end"]:
            cursor.execute("UPDATE subscriptions SET status = 'closed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (sub["id"],))
            return None

    # Check duplicate invoice: Has an invoice already been issued for this period?
    # We define period start as sub['last_billing_date'] or sub['start_date']
    period_start_str = sub["last_billing_date"] or sub["start_date"]
    cursor.execute("""
        SELECT id, invoice_number FROM invoices
        WHERE subscription_id = ? AND issue_date = ?
    """, (sub["id"], billing_date.strftime("%Y-%m-%d")))
    existing = cursor.fetchone()
    if existing:
        # Already billed for this issue date! Avoid duplicate billing.
        return None

    # Fetch subscription lines
    cursor.execute("""
        SELECT sl.*, p.name as product_name, pv.variant_name, pv.price_adjustment,
               t.name as tax_name, t.rate as tax_rate, t.is_fixed as tax_is_fixed
        FROM subscription_lines sl
        JOIN products p ON sl.product_id = p.id
        LEFT JOIN product_variants pv ON sl.variant_id = pv.id
        LEFT JOIN taxes t ON sl.tax_id = t.id
        WHERE sl.subscription_id = ?
    """, (sub["id"],))
    lines = cursor.fetchall()

    if not lines:
        return None

    # Calculate line items, taxes, discounts
    lines_subtotal = 0.0
    total_quantity = 0
    product_subtotals = {}
    tax_total = 0.0

    processed_lines = []
    for line in lines:
        qty = line["quantity"]
        unit_price = line["unit_price"]
        line_sub = round(qty * unit_price, 2)
        lines_subtotal += line_sub
        total_quantity += qty
        product_subtotals[line["product_id"]] = product_subtotals.get(line["product_id"], 0.0) + line_sub

        # Tax calculation
        line_tax = 0.0
        tax_rate = line["tax_rate"] or 0.0
        if tax_rate > 0:
            if line["tax_is_fixed"]:
                line_tax = round(tax_rate * qty, 2)
            else:
                line_tax = round(line_sub * (tax_rate / 100.0), 2)
        tax_total += line_tax

        desc = line["product_name"]
        if line["variant_name"]:
            desc += f" ({line['variant_name']})"

        processed_lines.append({
            "product_id": line["product_id"],
            "variant_id": line["variant_id"],
            "description": desc,
            "quantity": qty,
            "unit_price": unit_price,
            "tax_rate": tax_rate,
            "tax_amount": line_tax,
            "line_total": line_sub + line_tax
        })

    # Discount calculation
    discount_amount, discount_code, disc_id_to_inc = evaluate_discount(
        cursor, sub["discount_id"], lines_subtotal, total_quantity, billing_date, product_subtotals
    )

    if disc_id_to_inc:
        cursor.execute("UPDATE discounts SET used_count = used_count + 1 WHERE id = ?", (disc_id_to_inc,))

    total_amount = round(max(0.0, lines_subtotal - discount_amount + tax_total), 2)
    due_date = calculate_due_date(billing_date, sub["payment_terms"])

    # Calculate billing period
    period_start = datetime.strptime(period_start_str, "%Y-%m-%d").date()
    period_end = add_billing_interval(period_start, sub["billing_frequency"]) - timedelta(days=1)

    # Next billing date
    next_billing = add_billing_interval(billing_date, sub["billing_frequency"])

    # Create Invoice record
    inv_number = generate_invoice_number(cursor.connection)
    cursor.execute("""
        INSERT INTO invoices (
            invoice_number, subscription_id, customer_id, issue_date, due_date,
            status, subtotal, discount_amount, tax_amount, total_amount,
            amount_paid, balance_due, billing_period_start, billing_period_end, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        inv_number, sub["id"], sub["customer_id"],
        billing_date.strftime("%Y-%m-%d"),
        due_date.strftime("%Y-%m-%d"),
        "draft", # Invoices start in draft according to scene ("moves from Draft to Confirmed to Paid")
        lines_subtotal, discount_amount, tax_total, total_amount,
        0.0, total_amount,
        period_start.strftime("%Y-%m-%d"),
        period_end.strftime("%Y-%m-%d"),
        f"Generated automatically for subscription {sub['subscription_number']}"
    ))
    invoice_id = cursor.lastrowid

    # Insert invoice lines
    for pl in processed_lines:
        cursor.execute("""
            INSERT INTO invoice_lines (
                invoice_id, product_id, variant_id, description,
                quantity, unit_price, tax_rate, tax_amount, line_total
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            invoice_id, pl["product_id"], pl["variant_id"], pl["description"],
            pl["quantity"], pl["unit_price"], pl["tax_rate"], pl["tax_amount"], pl["line_total"]
        ))

    # Advance subscription billing dates
    cursor.execute("""
        UPDATE subscriptions
        SET last_billing_date = ?,
            next_billing_date = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (billing_date.strftime("%Y-%m-%d"), next_billing.strftime("%Y-%m-%d"), sub["id"]))

    # Check if subscription should auto-close
    if sub["expiry_date"] and sub["auto_close_on_end"]:
        exp_d = datetime.strptime(sub["expiry_date"], "%Y-%m-%d").date()
        if next_billing > exp_d:
            cursor.execute("UPDATE subscriptions SET status = 'closed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (sub["id"],))

    # Audit log
    cursor.execute("""
        INSERT INTO activity_logs (user_id, action, entity_type, entity_id, details)
        VALUES (?, 'INVOICE_GENERATED', 'invoice', ?, ?)
    """, (sub["created_by"], invoice_id, f"Invoice {inv_number} generated for {sub['subscription_number']} (Total: ${total_amount:,.2f})"))

    return {
        "invoice_id": invoice_id,
        "invoice_number": inv_number,
        "subscription_number": sub["subscription_number"],
        "customer_name": sub["customer_name"],
        "total_amount": total_amount,
        "issue_date": billing_date.strftime("%Y-%m-%d"),
        "due_date": due_date.strftime("%Y-%m-%d")
    }


def run_billing_day(as_of_date: date = None) -> dict:
    """
    Executes 'Billing Day' across the entire subscription portfolio.
    Finds all active subscriptions due on or before as_of_date and generates invoices.
    Guarantees no duplicate billing and no skipped subscriptions.
    """
    if as_of_date is None:
        as_of_date = date.today()

    target_date_str = as_of_date.strftime("%Y-%m-%d")

    with get_db() as conn:
        cursor = conn.cursor()

        # Find eligible subscriptions:
        # Active status, next_billing_date <= target_date_str
        cursor.execute("""
            SELECT id, subscription_number, next_billing_date
            FROM subscriptions
            WHERE status = 'active'
              AND (next_billing_date <= ? OR next_billing_date IS NULL)
            ORDER BY id ASC
        """, (target_date_str,))
        due_subscriptions = cursor.fetchall()

        generated_invoices = []
        skipped_count = 0

        for sub in due_subscriptions:
            inv_res = generate_invoice_for_subscription(cursor, sub["id"], as_of_date)
            if inv_res:
                generated_invoices.append(inv_res)
            else:
                skipped_count += 1

        return {
            "billing_date": target_date_str,
            "total_due": len(due_subscriptions),
            "invoices_generated": len(generated_invoices),
            "skipped_or_closed": skipped_count,
            "invoices": generated_invoices
        }


def preview_billing_day(as_of_date: date = None) -> list[dict]:
    """
    Previews subscriptions that will be processed on billing day without modifying data.
    """
    if as_of_date is None:
        as_of_date = date.today()

    target_date_str = as_of_date.strftime("%Y-%m-%d")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id, s.subscription_number, s.status, s.next_billing_date, s.last_billing_date,
                   u.name as customer_name, u.company_name, u.email as customer_email,
                   p.name as plan_name, p.billing_frequency,
                   (SELECT SUM(subtotal) FROM subscription_lines WHERE subscription_id = s.id) as estimated_subtotal
            FROM subscriptions s
            JOIN users u ON s.customer_id = u.id
            JOIN plans p ON s.plan_id = p.id
            WHERE s.status = 'active'
              AND (s.next_billing_date <= ? OR s.next_billing_date IS NULL)
            ORDER BY s.next_billing_date ASC
        """, (target_date_str,))
        return rows_to_dicts(cursor.fetchall())


def record_payment(invoice_id: int, amount: float, payment_method: str, payment_date: date, reference_note: str = "", recorded_by: int = None) -> tuple[bool, str, dict | None]:
    """
    Records a payment against an invoice.
    Supports partial and full payments. Automatically updates invoice status to 'paid' when balance is settled.
    """
    if amount <= 0:
        return False, "Payment amount must be greater than zero.", None

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
        inv = cursor.fetchone()
        if not inv:
            return False, "Invoice not found.", None

        if inv["status"] == "cancelled":
            return False, "Cannot record payment on a cancelled invoice.", None

        new_paid = round(inv["amount_paid"] + amount, 2)
        new_balance = round(max(0.0, inv["total_amount"] - new_paid), 2)
        new_status = "paid" if new_balance <= 0.005 else "confirmed"

        # Record payment
        cursor.execute("""
            INSERT INTO payments (invoice_id, amount, payment_method, payment_date, reference_note, recorded_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (invoice_id, amount, payment_method, payment_date.strftime("%Y-%m-%d"), reference_note, recorded_by))
        payment_id = cursor.lastrowid

        # Update invoice
        cursor.execute("""
            UPDATE invoices
            SET amount_paid = ?,
                balance_due = ?,
                status = ?
            WHERE id = ?
        """, (new_paid, new_balance, new_status, invoice_id))

        # Log activity
        cursor.execute("""
            INSERT INTO activity_logs (user_id, action, entity_type, entity_id, details)
            VALUES (?, 'PAYMENT_RECORDED', 'payment', ?, ?)
        """, (recorded_by, payment_id, f"Payment of ${amount:,.2f} recorded for {inv['invoice_number']} via {payment_method}"))

        return True, "Payment recorded successfully.", {
            "payment_id": payment_id,
            "invoice_number": inv["invoice_number"],
            "amount": amount,
            "balance_due": new_balance,
            "status": new_status
        }


def get_finance_summary(filter_plan: int = None, filter_customer: int = None, start_date: str = None, end_date: str = None) -> dict:
    """
    Provides real-time aggregated metrics for the Finance Lead:
    - Active Subscriptions count
    - MRR (Monthly Recurring Revenue) & ARR
    - Total Revenue Collected
    - Total Outstanding Receivables
    - Overdue Invoices and aging analysis
    Optimized for high performance (< 2 seconds response time).
    """
    with get_db() as conn:
        cursor = conn.cursor()
        today_str = date.today().strftime("%Y-%m-%d")

        # 1. Active Subscriptions Count & Plan Breakdown
        sub_query = """
            SELECT s.id, s.plan_id, p.billing_frequency, p.name as plan_name,
                   (SELECT COALESCE(SUM(subtotal), 0) FROM subscription_lines WHERE subscription_id = s.id) as subtotal
            FROM subscriptions s
            JOIN plans p ON s.plan_id = p.id
            WHERE s.status = 'active'
        """
        params = []
        if filter_plan:
            sub_query += " AND s.plan_id = ?"
            params.append(filter_plan)
        if filter_customer:
            sub_query += " AND s.customer_id = ?"
            params.append(filter_customer)

        cursor.execute(sub_query, params)
        active_subs = cursor.fetchall()
        active_count = len(active_subs)

        # Normalize to MRR
        total_mrr = 0.0
        plan_breakdown = {}
        for sub in active_subs:
            sub_val = float(sub["subtotal"])
            freq = sub["billing_frequency"].lower()
            if freq == "daily":
                norm_mrr = sub_val * 30.0
            elif freq == "weekly":
                norm_mrr = sub_val * 52.0 / 12.0
            elif freq == "monthly":
                norm_mrr = sub_val
            elif freq == "yearly":
                norm_mrr = sub_val / 12.0
            else:
                norm_mrr = sub_val

            total_mrr += norm_mrr
            pname = sub["plan_name"]
            plan_breakdown[pname] = plan_breakdown.get(pname, 0.0) + norm_mrr

        arr = round(total_mrr * 12.0, 2)
        total_mrr = round(total_mrr, 2)

        # 2. Payments / Revenue Collected
        pay_query = "SELECT COALESCE(SUM(amount), 0) as total_collected FROM payments WHERE 1=1"
        pay_params = []
        if start_date:
            pay_query += " AND payment_date >= ?"
            pay_params.append(start_date)
        if end_date:
            pay_query += " AND payment_date <= ?"
            pay_params.append(end_date)
        cursor.execute(pay_query, pay_params)
        total_collected = round(cursor.fetchone()["total_collected"], 2)

        # 3. Outstanding Receivables (Unpaid or Partially Paid Invoices)
        cursor.execute("""
            SELECT COALESCE(SUM(balance_due), 0) as total_outstanding
            FROM invoices
            WHERE status IN ('draft', 'confirmed') AND balance_due > 0
        """)
        total_outstanding = round(cursor.fetchone()["total_outstanding"], 2)

        # 4. Overdue Invoices
        cursor.execute("""
            SELECT i.*, u.name as customer_name, u.company_name, u.email as customer_email,
                   ROUND(julianday('now') - julianday(i.due_date)) as days_overdue
            FROM invoices i
            JOIN users u ON i.customer_id = u.id
            WHERE i.status IN ('draft', 'confirmed')
              AND i.due_date < ?
              AND i.balance_due > 0
            ORDER BY i.due_date ASC
        """, (today_str,))
        overdue_rows = cursor.fetchall()
        overdue_invoices = rows_to_dicts(overdue_rows)
        overdue_total = round(sum(inv["balance_due"] for inv in overdue_invoices), 2)

        # 5. Overdue Aging Buckets
        aging = {"1_15_days": 0.0, "16_30_days": 0.0, "31_60_days": 0.0, "60_plus_days": 0.0}
        for o in overdue_invoices:
            days = o.get("days_overdue", 0) or 0
            bal = o["balance_due"]
            if days <= 15:
                aging["1_15_days"] += bal
            elif days <= 30:
                aging["16_30_days"] += bal
            elif days <= 60:
                aging["31_60_days"] += bal
            else:
                aging["60_plus_days"] += bal

        for k in aging:
            aging[k] = round(aging[k], 2)

        # 6. Status distribution of all subscriptions
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM subscriptions
            GROUP BY status
        """)
        status_dist = {row["status"]: row["count"] for row in cursor.fetchall()}

        return {
            "active_subscriptions_count": active_count,
            "mrr": total_mrr,
            "arr": arr,
            "total_revenue_collected": total_collected,
            "total_outstanding": total_outstanding,
            "overdue_count": len(overdue_invoices),
            "overdue_total": overdue_total,
            "overdue_invoices": overdue_invoices,
            "aging": aging,
            "plan_mrr_breakdown": plan_breakdown,
            "status_distribution": status_dist
        }

