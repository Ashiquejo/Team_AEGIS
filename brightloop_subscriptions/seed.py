"""
Seed script to populate Brightloop Software with realistic, comprehensive demo data.
"""

from datetime import datetime, date, timedelta
from database import init_db, get_db
from auth import hash_password


def seed_all():
    print("Initializing database...")
    init_db()

    with get_db() as conn:
        cursor = conn.cursor()

        # Clean up existing data for fresh seed
        cursor.execute("DELETE FROM activity_logs;")
        cursor.execute("DELETE FROM payments;")
        cursor.execute("DELETE FROM invoice_lines;")
        cursor.execute("DELETE FROM invoices;")
        cursor.execute("DELETE FROM subscription_lines;")
        cursor.execute("DELETE FROM subscriptions;")
        cursor.execute("DELETE FROM quotation_template_lines;")
        cursor.execute("DELETE FROM quotation_templates;")
        cursor.execute("DELETE FROM discounts;")
        cursor.execute("DELETE FROM taxes;")
        cursor.execute("DELETE FROM product_variants;")
        cursor.execute("DELETE FROM products;")
        cursor.execute("DELETE FROM plans;")
        cursor.execute("DELETE FROM password_resets;")
        cursor.execute("DELETE FROM users;")
        cursor.execute("DELETE FROM sqlite_sequence;")

        # 1. Users
        users = [
            ("admin@brightloop.com", hash_password("Admin@1234#"), "admin", "Alex Mercer (Admin)", "Brightloop HQ", "+1-555-0100"),
            ("sarah.staff@brightloop.com", hash_password("Staff@1234#"), "staff", "Sarah Jenkins (Sales & Ops)", "Brightloop Operations", "+1-555-0101"),
            ("mark.staff@brightloop.com", hash_password("Staff@1234#"), "staff", "Mark Chen (Billing Ops)", "Brightloop Operations", "+1-555-0102"),
            ("acme@shops.com", hash_password("Customer@1234#"), "customer", "John Acme", "Acme Corner Shop", "+1-555-0201"),
            ("techcorp@enterprise.com", hash_password("Customer@1234#"), "customer", "Elena Rostova", "Global TechCorp Inc.", "+1-555-0202"),
            ("harper@growthlab.io", hash_password("Customer@1234#"), "customer", "Harper Lee", "GrowthLab Digital", "+1-555-0203"),
            ("david@novabooks.com", hash_password("Customer@1234#"), "customer", "David Nova", "Nova Books & Retail", "+1-555-0204"),
            ("rachel@solotech.org", hash_password("Customer@1234#"), "customer", "Rachel Adams", "SoloTech Solutions", "+1-555-0205"),
        ]
        cursor.executemany("""
            INSERT INTO users (email, password_hash, role, name, company_name, phone)
            VALUES (?, ?, ?, ?, ?, ?)
        """, users)

        admin_id = 1
        staff_id = 2
        acme_id = 4
        techcorp_id = 5
        growthlab_id = 6
        novabooks_id = 7
        solotech_id = 8

        # 2. Taxes
        cursor.execute("""
            INSERT INTO taxes (name, rate, is_fixed, is_default, description)
            VALUES 
            ('Standard VAT 10%', 10.0, 0, 1, 'Standard 10% Value Added Tax on business software'),
            ('Software Sales Tax 5%', 5.0, 0, 0, 'State software services tax'),
            ('Zero Tax 0%', 0.0, 0, 0, 'Exempt B2B international sales')
        """)
        vat_tax_id = 1
        sales_tax_id = 2
        zero_tax_id = 3

        # 3. Products
        cursor.execute("""
            INSERT INTO products (name, type, sales_price, cost_price, notes)
            VALUES
            ('Cloud ERP Core', 'software', 400.0, 120.0, 'Core enterprise cloud subscription with multi-ledger support'),
            ('Analytics Pro Add-On', 'addon', 150.0, 40.0, 'Real-time cohort and financial forecasting engine'),
            ('Dedicated Storage (1TB)', 'addon', 80.0, 20.0, 'High availability cloud storage volume'),
            ('Priority 24/7 SLA Support', 'service', 250.0, 80.0, 'Dedicated technical account manager with 15min SLA')
        """)
        erp_id = 1
        analytics_id = 2
        storage_id = 3
        support_id = 4

        # 4. Product Variants (specifically Odoo Brand adds 560 as required by prompt)
        cursor.execute("""
            INSERT INTO product_variants (product_id, variant_name, price_adjustment, sku)
            VALUES
            (?, 'Standard Edition', 0.0, 'ERP-STD'),
            (?, 'Odoo Brand Edition', 560.0, 'ERP-ODOO-560'),
            (?, 'Enterprise Custom Edition', 1200.0, 'ERP-ENT-CUST'),
            (?, 'Standard 1TB', 0.0, 'STOR-1TB'),
            (?, 'Encrypted NVMe 1TB', 40.0, 'STOR-NVME-40')
        """, (erp_id, erp_id, erp_id, storage_id, storage_id))
        variant_std_id = 1
        variant_odoo_id = 2
        variant_ent_id = 3

        # 5. Plans (with daily, weekly, monthly, yearly, and lifecycle options)
        cursor.execute("""
            INSERT INTO plans (name, code, description, billing_frequency, base_price, min_quantity, available_from, available_to, auto_close_on_end, can_close_early, can_pause, can_renew)
            VALUES
            ('Monthly Cloud Pro', 'PLAN-M-PRO', 'Full-featured monthly subscription for growing businesses', 'monthly', 400.0, 1, '2026-01-01', '2027-12-31', 0, 1, 1, 1),
            ('Yearly Enterprise Suite', 'PLAN-Y-ENT', 'Comprehensive yearly plan with enterprise SLA and volume discount options', 'yearly', 4200.0, 5, '2026-01-01', '2027-12-31', 1, 1, 0, 1),
            ('Weekly Growth Sprint', 'PLAN-W-GROW', 'Flexible weekly billing for agile teams and rapid rollouts', 'weekly', 120.0, 1, '2026-01-01', '2027-12-31', 1, 1, 1, 1),
            ('Daily Sandbox Trial', 'PLAN-D-TRIAL', 'Daily developer sandbox with automated shutdown upon conclusion', 'daily', 15.0, 1, '2026-01-01', '2027-12-31', 1, 0, 0, 0)
        """)
        monthly_plan_id = 1
        yearly_plan_id = 2
        weekly_plan_id = 3
        daily_plan_id = 4

        # 6. Discounts (Admin only)
        cursor.execute("""
            INSERT INTO discounts (code, description, discount_type, value, min_purchase_amount, min_quantity, start_date, end_date, max_uses, used_count, scope, applicable_product_id, is_active, created_by)
            VALUES
            ('VOLUME15', '15% Volume Discount for teams with 10+ seats', 'percentage', 15.0, 0.0, 10, '2026-01-01', '2027-12-31', 50, 3, 'whole_subscription', NULL, 1, ?),
            ('ENTERPRISE200', '$200 Fixed Off for large enterprise contracts above $2,000', 'fixed', 200.0, 2000.0, 0, '2026-01-01', '2027-12-31', 20, 1, 'whole_subscription', NULL, 1, ?),
            ('ODOO10', '10% Launch Promotion for Odoo Brand ERP line', 'percentage', 10.0, 0.0, 0, '2026-01-01', '2027-12-31', 10, 2, 'specific_product', ?, 1, ?),
            ('EXPIRED50', '$50 Flash Coupon (Expired)', 'fixed', 50.0, 0.0, 0, '2026-01-01', '2026-02-01', 5, 5, 'whole_subscription', NULL, 1, ?)
        """, (admin_id, admin_id, erp_id, admin_id, admin_id))
        discount_volume_id = 1
        discount_ent_id = 2
        discount_odoo_id = 3

        # 7. Quotation Templates
        cursor.execute("""
            INSERT INTO quotation_templates (name, plan_id, validity_days, notes)
            VALUES
            ('Standard SaaS Growth Offer', ?, 30, 'Standard onboarding template for mid-market accounts'),
            ('Enterprise Annual Contract Template', ?, 15, 'High-touch yearly enterprise package with Odoo edition and 24/7 SLA')
        """, (monthly_plan_id, yearly_plan_id))
        template_saas_id = 1
        template_ent_id = 2

        # Template lines
        cursor.execute("""
            INSERT INTO quotation_template_lines (template_id, product_id, variant_id, quantity, unit_price, tax_id)
            VALUES
            (?, ?, ?, 2, 400.0, ?),
            (?, ?, NULL, 1, 150.0, ?),
            (?, ?, ?, 10, 960.0, ?), -- 400 + 560 Odoo variant
            (?, ?, NULL, 1, 250.0, ?)
        """, (
            template_saas_id, erp_id, variant_std_id, vat_tax_id,
            template_saas_id, analytics_id, vat_tax_id,
            template_ent_id, erp_id, variant_odoo_id, vat_tax_id,
            template_ent_id, support_id, vat_tax_id
        ))

        # 8. Subscriptions across all workflow stages
        today = date.today()
        yesterday = today - timedelta(days=1)
        next_month = today + timedelta(days=30)
        last_month = today - timedelta(days=30)
        two_months_ago = today - timedelta(days=60)

        # SUB-0001: Acme Corner Shop (Active Monthly Plan with Standard ERP)
        cursor.execute("""
            INSERT INTO subscriptions (
                subscription_number, customer_id, plan_id, status, start_date, expiry_date,
                next_billing_date, last_billing_date, payment_terms, discount_id, notes, created_by
            ) VALUES (
                'SUB-2026-0001', ?, ?, 'active', ?, ?, ?, ?, 'Net 15', NULL, 'Small retail shop, standard plan', ?
            )
        """, (acme_id, monthly_plan_id, two_months_ago.strftime("%Y-%m-%d"), (today + timedelta(days=300)).strftime("%Y-%m-%d"),
              today.strftime("%Y-%m-%d"), last_month.strftime("%Y-%m-%d"), staff_id))
        sub1_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO subscription_lines (subscription_id, product_id, variant_id, quantity, unit_price, tax_id, subtotal)
            VALUES (?, ?, ?, 1, 400.0, ?, 400.0)
        """, (sub1_id, erp_id, variant_std_id, vat_tax_id))

        # SUB-0002: Global TechCorp (Active Yearly Enterprise with Odoo Brand Edition + 560 and Volume Discount)
        cursor.execute("""
            INSERT INTO subscriptions (
                subscription_number, customer_id, plan_id, status, start_date, expiry_date,
                next_billing_date, last_billing_date, payment_terms, discount_id, notes, created_by
            ) VALUES (
                'SUB-2026-0002', ?, ?, 'active', ?, ?, ?, ?, 'Net 30', ?, '12 seats with Odoo brand variant and 24/7 SLA', ?
            )
        """, (techcorp_id, yearly_plan_id, last_month.strftime("%Y-%m-%d"), (last_month + timedelta(days=365)).strftime("%Y-%m-%d"),
              today.strftime("%Y-%m-%d"), last_month.strftime("%Y-%m-%d"), discount_volume_id, staff_id))
        sub2_id = cursor.lastrowid
        # 12 seats of ERP Odoo Brand ($400 + $560 = $960 each = $11,520) + Support ($250)
        cursor.execute("""
            INSERT INTO subscription_lines (subscription_id, product_id, variant_id, quantity, unit_price, tax_id, subtotal)
            VALUES 
            (?, ?, ?, 12, 960.0, ?, 11520.0),
            (?, ?, NULL, 1, 250.0, ?, 250.0)
        """, (sub2_id, erp_id, variant_odoo_id, vat_tax_id, sub2_id, support_id, vat_tax_id))

        # SUB-0003: GrowthLab Digital (Quotation stage - ready for customer approval)
        cursor.execute("""
            INSERT INTO subscriptions (
                subscription_number, customer_id, plan_id, status, start_date, expiry_date,
                next_billing_date, payment_terms, discount_id, notes, created_by
            ) VALUES (
                'SUB-2026-0003', ?, ?, 'quotation', ?, ?, ?, 'Net 15', NULL, 'Pending customer review via portal', ?
            )
        """, (growthlab_id, monthly_plan_id, today.strftime("%Y-%m-%d"), (today + timedelta(days=30)).strftime("%Y-%m-%d"),
              today.strftime("%Y-%m-%d"), staff_id))
        sub3_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO subscription_lines (subscription_id, product_id, variant_id, quantity, unit_price, tax_id, subtotal)
            VALUES 
            (?, ?, ?, 3, 400.0, ?, 1200.0),
            (?, ?, NULL, 3, 150.0, ?, 450.0)
        """, (sub3_id, erp_id, variant_std_id, sales_tax_id, sub3_id, analytics_id, sales_tax_id))

        # SUB-0004: Nova Books (Draft stage - sales rep working on quote)
        cursor.execute("""
            INSERT INTO subscriptions (
                subscription_number, customer_id, plan_id, status, start_date, expiry_date,
                next_billing_date, payment_terms, discount_id, notes, created_by
            ) VALUES (
                'SUB-2026-0004', ?, ?, 'draft', ?, ?, ?, 'Due upon receipt', NULL, 'Internal draft pricing', ?
            )
        """, (novabooks_id, weekly_plan_id, (today + timedelta(days=2)).strftime("%Y-%m-%d"), (today + timedelta(days=90)).strftime("%Y-%m-%d"),
              (today + timedelta(days=2)).strftime("%Y-%m-%d"), staff_id))
        sub4_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO subscription_lines (subscription_id, product_id, variant_id, quantity, unit_price, tax_id, subtotal)
            VALUES (?, ?, NULL, 2, 80.0, ?, 160.0)
        """, (sub4_id, storage_id, vat_tax_id))

        # SUB-0005: SoloTech Solutions (Closed/Completed)
        cursor.execute("""
            INSERT INTO subscriptions (
                subscription_number, customer_id, plan_id, status, start_date, expiry_date,
                next_billing_date, last_billing_date, payment_terms, discount_id, notes, created_by
            ) VALUES (
                'SUB-2026-0005', ?, ?, 'closed', ?, ?, NULL, ?, 'Net 30', NULL, 'Completed contract, plan auto-closed', ?
            )
        """, (solotech_id, daily_plan_id, (today - timedelta(days=20)).strftime("%Y-%m-%d"), (today - timedelta(days=5)).strftime("%Y-%m-%d"),
              (today - timedelta(days=5)).strftime("%Y-%m-%d"), admin_id))
        sub5_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO subscription_lines (subscription_id, product_id, variant_id, quantity, unit_price, tax_id, subtotal)
            VALUES (?, ?, ?, 1, 15.0, ?, 15.0)
        """, (sub5_id, erp_id, variant_std_id, vat_tax_id))

        # 9. Invoices (Draft, Confirmed, Paid, and Overdue)
        # INV-0001: Acme Shop - Paid
        cursor.execute("""
            INSERT INTO invoices (
                invoice_number, subscription_id, customer_id, issue_date, due_date, status,
                subtotal, discount_amount, tax_amount, total_amount, amount_paid, balance_due,
                billing_period_start, billing_period_end, notes
            ) VALUES (
                'INV-2026-0001', ?, ?, ?, ?, 'paid',
                400.0, 0.0, 40.0, 440.0, 440.0, 0.0,
                ?, ?, 'Initial monthly subscription invoice'
            )
        """, (sub1_id, acme_id, two_months_ago.strftime("%Y-%m-%d"), (two_months_ago + timedelta(days=15)).strftime("%Y-%m-%d"),
              two_months_ago.strftime("%Y-%m-%d"), (two_months_ago + timedelta(days=29)).strftime("%Y-%m-%d")))
        inv1_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO invoice_lines (invoice_id, product_id, variant_id, description, quantity, unit_price, tax_rate, tax_amount, line_total)
            VALUES (?, ?, ?, 'Cloud ERP Core (Standard Edition)', 1, 400.0, 10.0, 40.0, 440.0)
        """, (inv1_id, erp_id, variant_std_id))

        # Payment for INV-0001
        cursor.execute("""
            INSERT INTO payments (invoice_id, amount, payment_method, payment_date, reference_note, recorded_by)
            VALUES (?, 440.0, 'Credit Card', ?, 'Stripe charge ch_3M5x4... paid in full', ?)
        """, (inv1_id, (two_months_ago + timedelta(days=2)).strftime("%Y-%m-%d"), staff_id))

        # INV-0002: Acme Shop - Confirmed & Overdue (chase scenario!)
        # Due 10 days ago, $440 still outstanding
        ten_days_ago = today - timedelta(days=10)
        cursor.execute("""
            INSERT INTO invoices (
                invoice_number, subscription_id, customer_id, issue_date, due_date, status,
                subtotal, discount_amount, tax_amount, total_amount, amount_paid, balance_due,
                billing_period_start, billing_period_end, notes
            ) VALUES (
                'INV-2026-0002', ?, ?, ?, ?, 'confirmed',
                400.0, 0.0, 40.0, 440.0, 0.0, 440.0,
                ?, ?, 'Monthly renewal invoice - OVERDUE'
            )
        """, (sub1_id, acme_id, (ten_days_ago - timedelta(days=15)).strftime("%Y-%m-%d"), ten_days_ago.strftime("%Y-%m-%d"),
              last_month.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")))
        inv2_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO invoice_lines (invoice_id, product_id, variant_id, description, quantity, unit_price, tax_rate, tax_amount, line_total)
            VALUES (?, ?, ?, 'Cloud ERP Core (Standard Edition)', 1, 400.0, 10.0, 40.0, 440.0)
        """, (inv2_id, erp_id, variant_std_id))

        # INV-0003: Global TechCorp - Confirmed, Partial Payment
        # Subtotal: $11,770; 15% volume discount (-$1,765.50) + 10% tax on discounted amount
        cursor.execute("""
            INSERT INTO invoices (
                invoice_number, subscription_id, customer_id, issue_date, due_date, status,
                subtotal, discount_amount, tax_amount, total_amount, amount_paid, balance_due,
                billing_period_start, billing_period_end, notes
            ) VALUES (
                'INV-2026-0003', ?, ?, ?, ?, 'confirmed',
                11770.0, 1765.50, 1000.45, 11004.95, 5000.0, 6004.95,
                ?, ?, 'Annual enterprise contract with Odoo Edition and 15% volume discount'
            )
        """, (sub2_id, techcorp_id, last_month.strftime("%Y-%m-%d"), (last_month + timedelta(days=30)).strftime("%Y-%m-%d"),
              last_month.strftime("%Y-%m-%d"), (last_month + timedelta(days=364)).strftime("%Y-%m-%d")))
        inv3_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO invoice_lines (invoice_id, product_id, variant_id, description, quantity, unit_price, tax_rate, tax_amount, line_total)
            VALUES 
            (?, ?, ?, 'Cloud ERP Core (Odoo Brand Edition) [12 Seats]', 12, 960.0, 10.0, 979.20, 10771.20),
            (?, ?, NULL, 'Priority 24/7 SLA Support', 1, 250.0, 10.0, 21.25, 233.75)
        """, (inv3_id, erp_id, variant_odoo_id, inv3_id, support_id))

        # Partial payment for INV-0003
        cursor.execute("""
            INSERT INTO payments (invoice_id, amount, payment_method, payment_date, reference_note, recorded_by)
            VALUES (?, 5000.0, 'Bank Transfer', ?, 'Wire transfer Ref# WIRE-982181 (50% upfront)', ?)
        """, (inv3_id, (last_month + timedelta(days=5)).strftime("%Y-%m-%d"), staff_id))

        # INV-0004: SoloTech - Paid
        cursor.execute("""
            INSERT INTO invoices (
                invoice_number, subscription_id, customer_id, issue_date, due_date, status,
                subtotal, discount_amount, tax_amount, total_amount, amount_paid, balance_due,
                billing_period_start, billing_period_end, notes
            ) VALUES (
                'INV-2026-0004', ?, ?, ?, ?, 'paid',
                225.0, 0.0, 22.5, 247.5, 247.5, 0.0,
                ?, ?, '15 days sandbox trial'
            )
        """, (sub5_id, solotech_id, (today - timedelta(days=20)).strftime("%Y-%m-%d"), (today - timedelta(days=5)).strftime("%Y-%m-%d"),
              (today - timedelta(days=20)).strftime("%Y-%m-%d"), (today - timedelta(days=5)).strftime("%Y-%m-%d")))
        inv4_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO invoice_lines (invoice_id, product_id, variant_id, description, quantity, unit_price, tax_rate, tax_amount, line_total)
            VALUES (?, ?, ?, 'Cloud ERP Core (Standard Edition)', 15, 15.0, 10.0, 22.5, 247.5)
        """, (inv4_id, erp_id, variant_std_id))
        cursor.execute("""
            INSERT INTO payments (invoice_id, amount, payment_method, payment_date, reference_note, recorded_by)
            VALUES (?, 247.5, 'Credit Card', ?, 'Auto-card payment #CC-4412', ?)
        """, (inv4_id, (today - timedelta(days=19)).strftime("%Y-%m-%d"), staff_id))

        # Activity Logs
        cursor.execute("""
            INSERT INTO activity_logs (user_id, action, entity_type, entity_id, details)
            VALUES
            (?, 'SEED_DATA_INITIALIZED', 'system', 1, 'Brightloop database initialized with realistic multi-tiered subscriptions'),
            (?, 'QUOTE_CREATED', 'subscription', ?, 'Sales quote SUB-2026-0003 sent to GrowthLab Digital'),
            (?, 'PAYMENT_RECORDED', 'payment', 1, 'Payment of $440 recorded for INV-2026-0001'),
            (?, 'PAYMENT_RECORDED', 'payment', 2, 'Partial wire payment of $5,000 recorded for INV-2026-0003')
        """, (admin_id, staff_id, sub3_id, staff_id, staff_id))

    print("Database successfully seeded with Brightloop data!")


if __name__ == "__main__":
    seed_all()
