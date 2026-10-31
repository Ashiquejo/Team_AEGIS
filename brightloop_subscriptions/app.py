"""
Brightloop Software - Main Web Server & Application.
Unified Subscription, Plan, Invoicing, Payment, and Revenue Management System.
"""

import os
import json
import re
import urllib.parse
from datetime import datetime, date, timedelta
from wsgiref.simple_server import make_server
from jinja2 import Environment, FileSystemLoader

from database import get_db, rows_to_dicts, init_db
import auth
from billing_engine import (
    run_billing_day,
    preview_billing_day,
    record_payment,
    get_finance_summary,
    generate_subscription_number,
    calculate_due_date,
    add_billing_interval
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Setup Jinja2 Template Engine
jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)


class Request:
    """Encapsulates WSGI environ into a clean request object."""
    def __init__(self, environ):
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = environ.get("PATH_INFO", "/")
        self.query_string = environ.get("QUERY_STRING", "")
        self.query_params = urllib.parse.parse_qs(self.query_string)
        self.headers = {
            k[5:].replace("_", "-").title(): v
            for k, v in environ.items()
            if k.startswith("HTTP_")
        }
        self.cookies = self._parse_cookies(environ.get("HTTP_COOKIE", ""))
        self._body = None
        self._json = None
        self.user = self._resolve_user()

    def _parse_cookies(self, cookie_str):
        cookies = {}
        if not cookie_str:
            return cookies
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies

    def _resolve_user(self):
        token = self.cookies.get("session_token")
        if not token:
            auth_header = self.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
        if not token:
            return None
        payload = auth.decode_access_token(token)
        if not payload:
            return None
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, role, name, company_name FROM users WHERE id = ?", (payload["user_id"],))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_query(self, key, default=None):
        vals = self.query_params.get(key)
        return vals[0] if vals else default

    def read_body(self):
        if self._body is None:
            try:
                content_len = int(self.environ.get("CONTENT_LENGTH", 0) or 0)
            except (ValueError, TypeError):
                content_len = 0
            if content_len > 0:
                self._body = self.environ["wsgi.input"].read(content_len)
            else:
                self._body = b""
        return self._body

    def json(self):
        if self._json is None:
            body = self.read_body()
            if not body:
                self._json = {}
            else:
                try:
                    self._json = json.loads(body.decode("utf-8"))
                except Exception:
                    self._json = {}
        return self._json


class Response:
    """Helper to formulate WSGI response with headers and cookies."""
    def __init__(self, body="", status=200, content_type="text/html; charset=utf-8", headers=None):
        self.status = status
        self.content_type = content_type
        self.headers = headers or []
        self.cookies_to_set = []
        if isinstance(body, str):
            self.body = body.encode("utf-8")
        elif isinstance(body, (bytes, bytearray)):
            self.body = body
        else:
            self.body = json.dumps(body).encode("utf-8")
            self.content_type = "application/json; charset=utf-8"

    def set_cookie(self, key, value, max_age=86400, path="/", http_only=True):
        cookie = f"{key}={value}; Path={path}; Max-Age={max_age}"
        if http_only:
            cookie += "; HttpOnly; SameSite=Lax"
        self.cookies_to_set.append(cookie)

    def delete_cookie(self, key, path="/"):
        self.cookies_to_set.append(f"{key}=; Path={path}; Max-Age=0; HttpOnly")

    def to_wsgi(self, start_response):
        status_line = f"{self.status} {self._get_status_text(self.status)}"
        resp_headers = [("Content-Type", self.content_type), ("Content-Length", str(len(self.body)))]
        resp_headers.extend(self.headers)
        for c in self.cookies_to_set:
            resp_headers.append(("Set-Cookie", c))
        start_response(status_line, resp_headers)
        return [self.body]

    def _get_status_text(self, code):
        codes = {
            200: "OK", 201: "Created", 302: "Found", 400: "Bad Request",
            401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
            500: "Internal Server Error"
        }
        return codes.get(code, "OK")


def redirect(location, cookies=None):
    resp = Response(status=302, headers=[("Location", location)])
    if cookies:
        for c in cookies:
            resp.set_cookie(*c)
    return resp


def render(template_name, context, req=None):
    """Renders a Jinja2 template with common global variables."""
    ctx = dict(context)
    ctx["current_user"] = req.user if req else None
    ctx["today_date"] = date.today().strftime("%Y-%m-%d")
    template = jinja_env.get_template(template_name)
    html = template.render(**ctx)
    return Response(html, content_type="text/html; charset=utf-8")


def json_response(data, status=200):
    return Response(data, status=status, content_type="application/json; charset=utf-8")


# -------------------------------------------------------------
# Route Handlers
# -------------------------------------------------------------

def handle_static(req):
    """Serves static assets safely from STATIC_DIR."""
    filename = req.path[len("/static/"):].lstrip("/")
    safe_path = os.path.abspath(os.path.join(STATIC_DIR, filename))
    if not safe_path.startswith(STATIC_DIR) or not os.path.isfile(safe_path):
        return Response("Not Found", status=404)

    ext = os.path.splitext(safe_path)[1].lower()
    mimes = {
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon"
    }
    content_type = mimes.get(ext, "application/octet-stream")
    with open(safe_path, "rb") as f:
        data = f.read()
    return Response(data, content_type=content_type)


def handle_root(req):
    if not req.user:
        return redirect("/login")
    if req.user["role"] == "customer":
        return redirect("/portal")
    return redirect("/dashboard")


def handle_login_page(req):
    if req.user:
        return redirect("/portal" if req.user["role"] == "customer" else "/dashboard")
    return render("login.html", {}, req)


def handle_signup_page(req):
    if req.user:
        return redirect("/portal" if req.user["role"] == "customer" else "/dashboard")
    return render("signup.html", {}, req)


def handle_reset_password_page(req):
    token = req.get_query("token", "")
    return render("reset_password.html", {"token": token}, req)


# Auth API Handlers
def api_login(req):
    data = req.json()
    email = data.get("email", "")
    password = data.get("password", "")
    ok, msg, user = auth.authenticate_user(email, password)
    if not ok:
        return json_response({"success": False, "message": msg}, status=401)

    token = auth.create_access_token(user["id"], user["email"], user["role"], user["name"])
    resp = json_response({"success": True, "message": msg, "user": user, "token": token})
    resp.set_cookie("session_token", token)
    return resp


def api_signup(req):
    data = req.json()
    email = data.get("email", "")
    password = data.get("password", "")
    name = data.get("name", "")
    company_name = data.get("company_name", "")
    phone = data.get("phone", "")

    ok, msg, user = auth.register_user(
        email=email, password=password, name=name,
        company_name=company_name, phone=phone,
        role="customer", actor_role="public"
    )
    if not ok:
        return json_response({"success": False, "message": msg}, status=400)

    token = auth.create_access_token(user["id"], user["email"], user["role"], user["name"])
    resp = json_response({"success": True, "message": msg, "user": user, "token": token}, status=201)
    resp.set_cookie("session_token", token)
    return resp


def api_logout(req):
    resp = json_response({"success": True, "message": "Logged out."})
    resp.delete_cookie("session_token")
    return resp


def api_forgot_password(req):
    data = req.json()
    email = data.get("email", "")
    ok, msg, token = auth.create_password_reset_token(email)
    if not ok:
        return json_response({"success": False, "message": msg}, status=400)
    reset_url = f"/reset-password?token={token}"
    return json_response({
        "success": True,
        "message": msg,
        "reset_token": token,
        "reset_url": reset_url
    })


def api_reset_password(req):
    data = req.json()
    token = data.get("token", "")
    new_password = data.get("new_password", "")
    ok, msg = auth.reset_password_with_token(token, new_password)
    if not ok:
        return json_response({"success": False, "message": msg}, status=400)
    return json_response({"success": True, "message": msg})


def api_create_staff(req):
    """Admin-only endpoint: Only the admin can add a new member of staff."""
    if not req.user or req.user["role"] != "admin":
        return json_response({"success": False, "message": "Only administrators can add staff members."}, status=403)

    data = req.json()
    email = data.get("email", "")
    password = data.get("password", "")
    name = data.get("name", "")
    company_name = data.get("company_name", "Brightloop Operations")

    ok, msg, user = auth.register_user(
        email=email, password=password, name=name,
        company_name=company_name, role="staff", actor_role=req.user["role"]
    )
    if not ok:
        return json_response({"success": False, "message": msg}, status=400)
    return json_response({"success": True, "message": "Staff member created successfully.", "user": user}, status=201)


# Dashboard / Finance Lead View
def handle_dashboard(req):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return redirect("/login")

    plan_id = req.get_query("plan_id")
    customer_id = req.get_query("customer_id")
    plan_filter = int(plan_id) if plan_id and plan_id.isdigit() else None
    cust_filter = int(customer_id) if customer_id and customer_id.isdigit() else None

    summary = get_finance_summary(filter_plan=plan_filter, filter_customer=cust_filter)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, billing_frequency FROM plans WHERE is_active = 1")
        plans = rows_to_dicts(cursor.fetchall())
        cursor.execute("SELECT id, name, company_name, email FROM users WHERE role = 'customer' ORDER BY name ASC")
        customers = rows_to_dicts(cursor.fetchall())

    return render("dashboard.html", {
        "active_page": "dashboard",
        "summary": summary,
        "plans": plans,
        "customers": customers,
        "selected_plan": plan_id,
        "selected_customer": customer_id
    }, req)


# Subscriptions Views
def handle_subscriptions(req):
    if not req.user:
        return redirect("/login")
    if req.user["role"] == "customer":
        return redirect("/portal")

    status_filter = req.get_query("status")

    with get_db() as conn:
        cursor = conn.cursor()
        query = """
            SELECT s.*, u.name as customer_name, u.company_name, u.email as customer_email,
                   p.name as plan_name, p.billing_frequency,
                   (SELECT COALESCE(SUM(subtotal), 0) FROM subscription_lines WHERE subscription_id = s.id) as total_subtotal
            FROM subscriptions s
            JOIN users u ON s.customer_id = u.id
            JOIN plans p ON s.plan_id = p.id
        """
        params = []
        if status_filter:
            query += " WHERE s.status = ?"
            params.append(status_filter)
        query += " ORDER BY s.id DESC"

        cursor.execute(query, params)
        subs = rows_to_dicts(cursor.fetchall())

        # Counts
        cursor.execute("SELECT status, count(*) as count FROM subscriptions GROUP BY status")
        counts_dict = {row["status"]: row["count"] for row in cursor.fetchall()}
        counts = {
            "all": sum(counts_dict.values()),
            "active": counts_dict.get("active", 0),
            "quotation": counts_dict.get("quotation", 0),
            "confirmed": counts_dict.get("confirmed", 0),
            "draft": counts_dict.get("draft", 0),
            "closed": counts_dict.get("closed", 0)
        }

    return render("subscriptions.html", {
        "active_page": "subscriptions",
        "subscriptions": subs,
        "current_status": status_filter,
        "counts": counts
    }, req)


def handle_subscription_detail(req, sub_id):
    if not req.user:
        return redirect("/login")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*, u.name as customer_name, u.company_name, u.email as customer_email,
                   p.name as plan_name, p.billing_frequency, p.auto_close_on_end,
                   p.can_close_early, p.can_pause, p.can_renew,
                   d.code as discount_code, d.description as discount_desc
            FROM subscriptions s
            JOIN users u ON s.customer_id = u.id
            JOIN plans p ON s.plan_id = p.id
            LEFT JOIN discounts d ON s.discount_id = d.id
            WHERE s.id = ?
        """, (sub_id,))
        row = cursor.fetchone()
        if not row:
            return Response("Subscription not found", status=404)
        sub = dict(row)

        # Isolation check for customers
        if req.user["role"] == "customer" and sub["customer_id"] != req.user["id"]:
            return Response("Forbidden", status=403)

        # Fetch lines
        cursor.execute("""
            SELECT sl.*, p.name as product_name, pv.variant_name, pv.price_adjustment,
                   t.name as tax_name
            FROM subscription_lines sl
            JOIN products p ON sl.product_id = p.id
            LEFT JOIN product_variants pv ON sl.variant_id = pv.id
            LEFT JOIN taxes t ON sl.tax_id = t.id
            WHERE sl.subscription_id = ?
        """, (sub_id,))
        lines = rows_to_dicts(cursor.fetchall())
        total_subtotal = sum(l["subtotal"] for l in lines)

        # Invoices under this subscription
        cursor.execute("""
            SELECT * FROM invoices WHERE subscription_id = ? ORDER BY id DESC
        """, (sub_id,))
        invoices = rows_to_dicts(cursor.fetchall())

    return render("subscription_detail.html", {
        "active_page": "subscriptions",
        "sub": sub,
        "lines": lines,
        "total_subtotal": total_subtotal,
        "invoices": invoices
    }, req)


# Invoices Views
def handle_invoices(req):
    if not req.user:
        return redirect("/login")
    if req.user["role"] == "customer":
        return redirect("/portal")

    status_filter = req.get_query("status")
    today_str = date.today().strftime("%Y-%m-%d")

    with get_db() as conn:
        cursor = conn.cursor()
        query = """
            SELECT i.*, u.name as customer_name, u.company_name, u.email as customer_email,
                   s.subscription_number
            FROM invoices i
            JOIN users u ON i.customer_id = u.id
            LEFT JOIN subscriptions s ON i.subscription_id = s.id
        """
        params = []
        if status_filter == "overdue":
            query += " WHERE i.status IN ('draft', 'confirmed') AND i.due_date < ? AND i.balance_due > 0"
            params.append(today_str)
        elif status_filter:
            query += " WHERE i.status = ?"
            params.append(status_filter)
        query += " ORDER BY i.id DESC"

        cursor.execute(query, params)
        invs = rows_to_dicts(cursor.fetchall())
        for inv in invs:
            inv["is_overdue"] = inv["status"] in ("draft", "confirmed") and inv["due_date"] < today_str and inv["balance_due"] > 0

    return render("invoices.html", {
        "active_page": "invoices",
        "invoices": invs,
        "current_status": status_filter
    }, req)


def handle_invoice_detail(req, inv_id):
    if not req.user:
        return redirect("/login")

    today_str = date.today().strftime("%Y-%m-%d")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT i.*, u.name as customer_name, u.company_name, u.email as customer_email, u.phone,
                   s.subscription_number
            FROM invoices i
            JOIN users u ON i.customer_id = u.id
            LEFT JOIN subscriptions s ON i.subscription_id = s.id
            WHERE i.id = ?
        """, (inv_id,))
        row = cursor.fetchone()
        if not row:
            return Response("Invoice not found", status=404)
        inv = dict(row)

        if req.user["role"] == "customer" and inv["customer_id"] != req.user["id"]:
            return Response("Forbidden", status=403)

        inv["is_overdue"] = inv["status"] in ("draft", "confirmed") and inv["due_date"] < today_str and inv["balance_due"] > 0

        # Lines
        cursor.execute("SELECT * FROM invoice_lines WHERE invoice_id = ?", (inv_id,))
        lines = rows_to_dicts(cursor.fetchall())

        # Payments
        cursor.execute("SELECT * FROM payments WHERE invoice_id = ? ORDER BY id DESC", (inv_id,))
        payments = rows_to_dicts(cursor.fetchall())

    return render("invoice_detail.html", {
        "active_page": "invoices",
        "inv": inv,
        "lines": lines,
        "payments": payments
    }, req)


# Billing Day Operations
def handle_billing_day(req):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return redirect("/login")

    due_subs = preview_billing_day()
    return render("billing_day.html", {
        "active_page": "billing-day",
        "due_subscriptions": due_subs
    }, req)


# Products & Variants
def handle_products(req):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return redirect("/login")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products ORDER BY id ASC")
        products = rows_to_dicts(cursor.fetchall())
        for p in products:
            cursor.execute("SELECT * FROM product_variants WHERE product_id = ? ORDER BY id ASC", (p["id"],))
            p["variants"] = rows_to_dicts(cursor.fetchall())

    return render("products.html", {
        "active_page": "products",
        "products": products
    }, req)


# Plans
def handle_plans(req):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return redirect("/login")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM plans ORDER BY id ASC")
        plans = rows_to_dicts(cursor.fetchall())

    return render("plans.html", {
        "active_page": "plans",
        "plans": plans
    }, req)


# Discounts (Admin Only)
def handle_discounts(req):
    if not req.user or req.user["role"] != "admin":
        return redirect("/dashboard")

    today_str = date.today().strftime("%Y-%m-%d")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.*, p.name as applicable_product_name
            FROM discounts d
            LEFT JOIN products p ON d.applicable_product_id = p.id
            ORDER BY d.id DESC
        """)
        discounts = rows_to_dicts(cursor.fetchall())
        for d in discounts:
            d["is_expired"] = bool(d["end_date"] and d["end_date"] < today_str)

        cursor.execute("SELECT id, name FROM products WHERE is_active = 1")
        products = rows_to_dicts(cursor.fetchall())

    return render("discounts.html", {
        "active_page": "discounts",
        "discounts": discounts,
        "products": products
    }, req)


# Taxes (Admin Only)
def handle_taxes(req):
    if not req.user or req.user["role"] != "admin":
        return redirect("/dashboard")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM taxes ORDER BY id ASC")
        taxes = rows_to_dicts(cursor.fetchall())

    return render("taxes.html", {
        "active_page": "taxes",
        "taxes": taxes
    }, req)


# Quotation Templates & Quotes
def handle_quotes(req):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return redirect("/login")

    with get_db() as conn:
        cursor = conn.cursor()
        # Templates
        cursor.execute("""
            SELECT qt.*, p.name as plan_name, p.billing_frequency
            FROM quotation_templates qt
            JOIN plans p ON qt.plan_id = p.id
            ORDER BY qt.id ASC
        """)
        templates = rows_to_dicts(cursor.fetchall())
        for t in templates:
            cursor.execute("""
                SELECT qtl.*, p.name as product_name, pv.variant_name
                FROM quotation_template_lines qtl
                JOIN products p ON qtl.product_id = p.id
                LEFT JOIN product_variants pv ON qtl.variant_id = pv.id
                WHERE qtl.template_id = ?
            """, (t["id"],))
            t["lines"] = rows_to_dicts(cursor.fetchall())

        # Active quotations
        cursor.execute("""
            SELECT s.*, u.name as customer_name, u.company_name, u.email as customer_email,
                   p.name as plan_name, p.billing_frequency,
                   (SELECT COALESCE(SUM(subtotal), 0) FROM subscription_lines WHERE subscription_id = s.id) as total_subtotal
            FROM subscriptions s
            JOIN users u ON s.customer_id = u.id
            JOIN plans p ON s.plan_id = p.id
            WHERE s.status IN ('draft', 'quotation')
            ORDER BY s.id DESC
        """)
        quotations = rows_to_dicts(cursor.fetchall())

        # Customer list for new quote modal
        cursor.execute("SELECT id, name, company_name, email FROM users WHERE role = 'customer' ORDER BY name ASC")
        customers = rows_to_dicts(cursor.fetchall())

        # Plans
        cursor.execute("SELECT id, name, billing_frequency, base_price FROM plans WHERE is_active = 1")
        plans = rows_to_dicts(cursor.fetchall())

        # Products with variants for dynamic JS
        cursor.execute("SELECT * FROM products WHERE is_active = 1")
        products = rows_to_dicts(cursor.fetchall())
        for p in products:
            cursor.execute("SELECT * FROM product_variants WHERE product_id = ?", (p["id"],))
            p["variants"] = rows_to_dicts(cursor.fetchall())

        # Taxes
        cursor.execute("SELECT id, name, rate FROM taxes WHERE is_active = 1")
        taxes = rows_to_dicts(cursor.fetchall())

        # Discounts
        cursor.execute("SELECT id, code, description FROM discounts WHERE is_active = 1")
        discounts = rows_to_dicts(cursor.fetchall())

    return render("quotes.html", {
        "active_page": "quotes",
        "templates": templates,
        "quotations": quotations,
        "customers": customers,
        "plans": plans,
        "discounts": discounts,
        "products_json": json.dumps(products),
        "templates_json": json.dumps(templates),
        "taxes_json": json.dumps(taxes)
    }, req)


# Customer Self-Service Portal
def handle_customer_portal(req):
    if not req.user:
        return redirect("/login")
    if req.user["role"] != "customer":
        return redirect("/dashboard")

    cust_id = req.user["id"]
    today_str = date.today().strftime("%Y-%m-%d")

    with get_db() as conn:
        cursor = conn.cursor()
        # My Subscriptions
        cursor.execute("""
            SELECT s.*, p.name as plan_name, p.billing_frequency,
                   (SELECT COALESCE(SUM(subtotal), 0) FROM subscription_lines WHERE subscription_id = s.id) as total_subtotal
            FROM subscriptions s
            JOIN plans p ON s.plan_id = p.id
            WHERE s.customer_id = ?
            ORDER BY s.id DESC
        """, (cust_id,))
        subs = rows_to_dicts(cursor.fetchall())
        active_subs = [s for s in subs if s["status"] == "active"]
        pending_quotes = [s for s in subs if s["status"] == "quotation"]

        # My Invoices
        cursor.execute("""
            SELECT * FROM invoices
            WHERE customer_id = ?
            ORDER BY id DESC
        """, (cust_id,))
        invoices = rows_to_dicts(cursor.fetchall())
        total_due = 0.0
        for inv in invoices:
            inv["is_overdue"] = inv["status"] in ("draft", "confirmed") and inv["due_date"] < today_str and inv["balance_due"] > 0
            if inv["status"] in ("draft", "confirmed"):
                total_due += inv["balance_due"]

    return render("customer_portal.html", {
        "active_page": "portal",
        "my_subscriptions": subs,
        "active_subscriptions": active_subs,
        "pending_quotes": pending_quotes,
        "my_invoices": invoices,
        "total_due": round(total_due, 2)
    }, req)


# Activity & Audit Trail
def handle_activity(req):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return redirect("/login")

    action_filter = req.get_query("action")
    entity_filter = req.get_query("entity_type")

    with get_db() as conn:
        cursor = conn.cursor()
        query = """
            SELECT l.*, u.name as user_name, u.email as user_email, u.role as user_role
            FROM activity_logs l
            LEFT JOIN users u ON l.user_id = u.id
            WHERE 1=1
        """
        params = []
        if action_filter:
            query += " AND l.action = ?"
            params.append(action_filter)
        if entity_filter:
            query += " AND l.entity_type = ?"
            params.append(entity_filter)
        query += " ORDER BY l.id DESC LIMIT 150"

        cursor.execute(query, params)
        logs = rows_to_dicts(cursor.fetchall())

        cursor.execute("SELECT DISTINCT action FROM activity_logs ORDER BY action ASC")
        actions = [r["action"] for r in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT entity_type FROM activity_logs ORDER BY entity_type ASC")
        entities = [r["entity_type"] for r in cursor.fetchall()]

    return render("activity.html", {
        "active_page": "activity",
        "logs": logs,
        "actions": actions,
        "entities": entities,
        "selected_action": action_filter,
        "selected_entity": entity_filter
    }, req)


# -------------------------------------------------------------
# REST API Endpoints
# -------------------------------------------------------------

def api_subscription_status(req, sub_id):
    if not req.user:
        return json_response({"success": False, "message": "Unauthorized"}, status=401)

    data = req.json()
    new_status = data.get("status")
    allowed_statuses = ["draft", "quotation", "confirmed", "active", "paused", "closed"]
    if new_status not in allowed_statuses:
        return json_response({"success": False, "message": "Invalid status transition"}, status=400)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,))
        sub = cursor.fetchone()
        if not sub:
            return json_response({"success": False, "message": "Subscription not found"}, status=404)

        # Plan lifecycle restrictions
        cursor.execute("SELECT * FROM plans WHERE id = ?", (sub["plan_id"],))
        plan = cursor.fetchone()

        if new_status == "paused" and not plan["can_pause"]:
            return json_response({"success": False, "message": "This plan does not permit pausing."}, status=400)
        if new_status == "closed" and sub["status"] == "active" and not plan["can_close_early"]:
            return json_response({"success": False, "message": "This plan does not permit early closure."}, status=400)

        # If activating from confirmed or draft, setup next_billing_date if null
        next_billing = sub["next_billing_date"]
        if new_status == "active" and not next_billing:
            next_billing = sub["start_date"] or date.today().strftime("%Y-%m-%d")

        cursor.execute("""
            UPDATE subscriptions
            SET status = ?, next_billing_date = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_status, next_billing, sub_id))

        cursor.execute("""
            INSERT INTO activity_logs (user_id, action, entity_type, entity_id, details)
            VALUES (?, 'STATUS_UPDATED', 'subscription', ?, ?)
        """, (req.user["id"], sub_id, f"Subscription {sub['subscription_number']} transitioned to {new_status}"))

        return json_response({"success": True, "message": f"Status updated to {new_status}"})


def api_create_quote(req):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return json_response({"success": False, "message": "Unauthorized"}, status=401)

    data = req.json()
    customer_id = data.get("customer_id")
    plan_id = data.get("plan_id")
    payment_terms = data.get("payment_terms", "Net 30")
    start_date = data.get("start_date") or date.today().strftime("%Y-%m-%d")
    validity_days = int(data.get("validity_days", 30))
    discount_id = data.get("discount_id")
    lines = data.get("lines", [])

    if not customer_id or not plan_id or not lines:
        return json_response({"success": False, "message": "Missing customer, plan, or line items."}, status=400)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    expiry_dt = start_dt + timedelta(days=validity_days)

    with get_db() as conn:
        cursor = conn.cursor()
        sub_number = generate_subscription_number(conn)

        cursor.execute("""
            INSERT INTO subscriptions (
                subscription_number, customer_id, plan_id, status, start_date, expiry_date,
                next_billing_date, payment_terms, discount_id, created_by
            ) VALUES (?, ?, ?, 'quotation', ?, ?, ?, ?, ?, ?)
        """, (
            sub_number, customer_id, plan_id,
            start_dt.strftime("%Y-%m-%d"),
            expiry_dt.strftime("%Y-%m-%d"),
            start_dt.strftime("%Y-%m-%d"),
            payment_terms, discount_id, req.user["id"]
        ))
        sub_id = cursor.lastrowid

        for l in lines:
            prod_id = l["product_id"]
            var_id = l.get("variant_id")
            qty = int(l.get("quantity", 1))
            unit_price = float(l.get("unit_price", 0.0))
            tax_id = l.get("tax_id")
            subtotal = round(qty * unit_price, 2)

            cursor.execute("""
                INSERT INTO subscription_lines (
                    subscription_id, product_id, variant_id, quantity, unit_price, tax_id, subtotal
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (sub_id, prod_id, var_id, qty, unit_price, tax_id, subtotal))

        cursor.execute("""
            INSERT INTO activity_logs (user_id, action, entity_type, entity_id, details)
            VALUES (?, 'QUOTE_CREATED', 'subscription', ?, ?)
        """, (req.user["id"], sub_id, f"Quotation {sub_number} generated"))

        return json_response({
            "success": True,
            "subscription": {
                "id": sub_id,
                "subscription_number": sub_number
            }
        }, status=201)


def api_confirm_quote(req, sub_id):
    """Allows staff or customer via portal to confirm a quote into an active/confirmed subscription."""
    if not req.user:
        return json_response({"success": False, "message": "Unauthorized"}, status=401)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,))
        sub = cursor.fetchone()
        if not sub:
            return json_response({"success": False, "message": "Subscription not found"}, status=404)

        if req.user["role"] == "customer" and sub["customer_id"] != req.user["id"]:
            return json_response({"success": False, "message": "Forbidden"}, status=403)

        cursor.execute("""
            UPDATE subscriptions
            SET status = 'active', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (sub_id,))

        cursor.execute("""
            INSERT INTO activity_logs (user_id, action, entity_type, entity_id, details)
            VALUES (?, 'QUOTE_ACCEPTED', 'subscription', ?, ?)
        """, (req.user["id"], sub_id, f"Quotation {sub['subscription_number']} confirmed and activated"))

        return json_response({"success": True, "message": "Quotation accepted and activated!"})


def api_confirm_invoice(req, inv_id):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return json_response({"success": False, "message": "Unauthorized"}, status=401)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE invoices SET status = 'confirmed' WHERE id = ? AND status = 'draft'", (inv_id,))
        return json_response({"success": True, "message": "Invoice confirmed"})


def api_cancel_invoice(req, inv_id):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return json_response({"success": False, "message": "Unauthorized"}, status=401)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE invoices SET status = 'cancelled' WHERE id = ?", (inv_id,))
        return json_response({"success": True, "message": "Invoice cancelled"})


def api_send_invoice(req, inv_id):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return json_response({"success": False, "message": "Unauthorized"}, status=401)

    with get_db() as conn:
        cursor = conn.cursor()
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE invoices SET sent_at = ? WHERE id = ?", (now_str, inv_id))
        cursor.execute("""
            INSERT INTO activity_logs (user_id, action, entity_type, entity_id, details)
            VALUES (?, 'INVOICE_SENT', 'invoice', ?, 'Sent invoice notification to customer registered email')
        """, (req.user["id"], inv_id))
        return json_response({"success": True, "message": "Invoice sent to customer."})


def api_chase_invoice(req, inv_id):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return json_response({"success": False, "message": "Unauthorized"}, status=401)

    data = req.json()
    note = data.get("note", "Payment reminder notice sent to customer.")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO activity_logs (user_id, action, entity_type, entity_id, details)
            VALUES (?, 'OVERDUE_CHASE', 'invoice', ?, ?)
        """, (req.user["id"], inv_id, note))
        return json_response({"success": True, "message": "Overdue chase recorded and reminder dispatched."})


def api_record_payment(req):
    if not req.user:
        return json_response({"success": False, "message": "Unauthorized"}, status=401)

    data = req.json()
    inv_id = int(data.get("invoice_id"))
    amount = float(data.get("amount", 0.0))
    method = data.get("payment_method", "Credit Card")
    pay_date_str = data.get("payment_date") or date.today().strftime("%Y-%m-%d")
    note = data.get("reference_note", "")

    pay_date = datetime.strptime(pay_date_str, "%Y-%m-%d").date()
    ok, msg, res = record_payment(
        invoice_id=inv_id, amount=amount, payment_method=method,
        payment_date=pay_date, reference_note=note, recorded_by=req.user["id"]
    )
    if not ok:
        return json_response({"success": False, "message": msg}, status=400)
    return json_response({"success": True, "message": msg, "payment": res})


def api_run_billing_day(req):
    if not req.user or req.user["role"] not in ("admin", "staff"):
        return json_response({"success": False, "message": "Unauthorized"}, status=401)

    data = req.json()
    b_date_str = data.get("billing_date")
    as_of = datetime.strptime(b_date_str, "%Y-%m-%d").date() if b_date_str else date.today()

    res = run_billing_day(as_of)
    return json_response({"success": True, "result": res})


def api_create_product(req):
    if not req.user or req.user["role"] != "admin":
        return json_response({"success": False, "message": "Unauthorized"}, status=403)

    data = req.json()
    name = data.get("name", "").strip()
    p_type = data.get("type", "software")
    sales_price = float(data.get("sales_price", 0.0))
    cost_price = float(data.get("cost_price", 0.0))
    notes = data.get("notes", "")

    if not name:
        return json_response({"success": False, "message": "Product name is required"}, status=400)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO products (name, type, sales_price, cost_price, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (name, p_type, sales_price, cost_price, notes))
        pid = cursor.lastrowid
        return json_response({"success": True, "product_id": pid}, status=201)


def api_create_variant(req, prod_id):
    if not req.user or req.user["role"] != "admin":
        return json_response({"success": False, "message": "Unauthorized"}, status=403)

    data = req.json()
    var_name = data.get("variant_name", "").strip()
    price_adj = float(data.get("price_adjustment", 0.0))
    sku = data.get("sku", "").strip()

    if not var_name:
        return json_response({"success": False, "message": "Variant name is required"}, status=400)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO product_variants (product_id, variant_name, price_adjustment, sku)
            VALUES (?, ?, ?, ?)
        """, (prod_id, var_name, price_adj, sku))
        vid = cursor.lastrowid
        return json_response({"success": True, "variant_id": vid}, status=201)


def api_create_plan(req):
    if not req.user or req.user["role"] != "admin":
        return json_response({"success": False, "message": "Unauthorized"}, status=403)

    data = req.json()
    name = data.get("name", "").strip()
    code = data.get("code", "").strip().upper()
    billing_frequency = data.get("billing_frequency", "monthly")
    base_price = float(data.get("base_price", 0.0))
    min_quantity = int(data.get("min_quantity", 1))
    available_from = data.get("available_from")
    available_to = data.get("available_to")
    desc = data.get("description", "")
    auto_close = int(data.get("auto_close_on_end", 1))
    close_early = int(data.get("can_close_early", 1))
    can_pause = int(data.get("can_pause", 1))
    can_renew = int(data.get("can_renew", 1))

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO plans (
                name, code, description, billing_frequency, base_price, min_quantity,
                available_from, available_to, auto_close_on_end, can_close_early, can_pause, can_renew
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, code, desc, billing_frequency, base_price, min_quantity, available_from, available_to, auto_close, close_early, can_pause, can_renew))
        plan_id = cursor.lastrowid
        return json_response({"success": True, "plan_id": plan_id}, status=201)


def api_create_discount(req):
    if not req.user or req.user["role"] != "admin":
        return json_response({"success": False, "message": "Unauthorized"}, status=403)

    data = req.json()
    code = data.get("code", "").strip().upper()
    desc = data.get("description", "")
    d_type = data.get("discount_type", "percentage")
    val = float(data.get("value", 0.0))
    min_qty = int(data.get("min_quantity", 0))
    min_amount = float(data.get("min_purchase_amount", 0.0))
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    max_uses = data.get("max_uses")
    scope = data.get("scope", "whole_subscription")
    applicable_product_id = data.get("applicable_product_id")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO discounts (
                code, description, discount_type, value, min_purchase_amount, min_quantity,
                start_date, end_date, max_uses, scope, applicable_product_id, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (code, desc, d_type, val, min_amount, min_qty, start_date, end_date, max_uses, scope, applicable_product_id, req.user["id"]))
        disc_id = cursor.lastrowid
        return json_response({"success": True, "discount_id": disc_id}, status=201)


def api_create_tax(req):
    if not req.user or req.user["role"] != "admin":
        return json_response({"success": False, "message": "Unauthorized"}, status=403)

    data = req.json()
    name = data.get("name", "").strip()
    rate = float(data.get("rate", 0.0))
    is_fixed = int(data.get("is_fixed", 0))
    is_default = int(data.get("is_default", 0))
    desc = data.get("description", "")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO taxes (name, rate, is_fixed, is_default, description)
            VALUES (?, ?, ?, ?, ?)
        """, (name, rate, is_fixed, is_default, desc))
        tax_id = cursor.lastrowid
        return json_response({"success": True, "tax_id": tax_id}, status=201)


# -------------------------------------------------------------
# Router & Main Dispatcher
# -------------------------------------------------------------

def dispatch(req):
    path = req.path.rstrip("/")
    if not path:
        path = "/"
    method = req.method

    # Static assets
    if path.startswith("/static/"):
        return handle_static(req)

    # Pages
    if path == "/" and method == "GET":
        return handle_root(req)
    if path == "/login" and method == "GET":
        return handle_login_page(req)
    if path == "/signup" and method == "GET":
        return handle_signup_page(req)
    if path == "/reset-password" and method == "GET":
        return handle_reset_password_page(req)
    if path == "/dashboard" and method == "GET":
        return handle_dashboard(req)
    if path == "/subscriptions" and method == "GET":
        return handle_subscriptions(req)
    if path == "/invoices" and method == "GET":
        return handle_invoices(req)
    if path == "/billing-day" and method == "GET":
        return handle_billing_day(req)
    if path == "/products" and method == "GET":
        return handle_products(req)
    if path == "/plans" and method == "GET":
        return handle_plans(req)
    if path == "/discounts" and method == "GET":
        return handle_discounts(req)
    if path == "/taxes" and method == "GET":
        return handle_taxes(req)
    if path == "/quotes" and method == "GET":
        return handle_quotes(req)
    if path == "/activity" and method == "GET":
        return handle_activity(req)
    if path == "/portal" and method == "GET":
        return handle_customer_portal(req)

    # Dynamic item pages
    sub_match = re.match(r"^/subscriptions/(\d+)$", path)
    if sub_match and method == "GET":
        return handle_subscription_detail(req, int(sub_match.group(1)))

    inv_match = re.match(r"^/invoices/(\d+)$", path)
    if inv_match and method == "GET":
        return handle_invoice_detail(req, int(inv_match.group(1)))

    # API Auth Endpoints
    if path == "/api/auth/login" and method == "POST":
        return api_login(req)
    if path == "/api/auth/signup" and method == "POST":
        return api_signup(req)
    if path == "/api/auth/logout" and method == "POST":
        return api_logout(req)
    if path == "/api/auth/forgot-password" and method == "POST":
        return api_forgot_password(req)
    if path == "/api/auth/reset-password" and method == "POST":
        return api_reset_password(req)
    if path == "/api/staff" and method == "POST":
        return api_create_staff(req)

    # API Subscriptions & Quotes
    if path == "/api/quotes" and method == "POST":
        return api_create_quote(req)
    quote_confirm_match = re.match(r"^/api/quotes/(\d+)/confirm$", path)
    if quote_confirm_match and method == "POST":
        return api_confirm_quote(req, int(quote_confirm_match.group(1)))

    sub_status_match = re.match(r"^/api/subscriptions/(\d+)/status$", path)
    if sub_status_match and method == "POST":
        return api_subscription_status(req, int(sub_status_match.group(1)))

    # API Invoices & Payments
    inv_confirm_match = re.match(r"^/api/invoices/(\d+)/confirm$", path)
    if inv_confirm_match and method == "POST":
        return api_confirm_invoice(req, int(inv_confirm_match.group(1)))

    inv_cancel_match = re.match(r"^/api/invoices/(\d+)/cancel$", path)
    if inv_cancel_match and method == "POST":
        return api_cancel_invoice(req, int(inv_cancel_match.group(1)))

    inv_send_match = re.match(r"^/api/invoices/(\d+)/send$", path)
    if inv_send_match and method == "POST":
        return api_send_invoice(req, int(inv_send_match.group(1)))

    inv_chase_match = re.match(r"^/api/invoices/(\d+)/chase$", path)
    if inv_chase_match and method == "POST":
        return api_chase_invoice(req, int(inv_chase_match.group(1)))

    if path == "/api/payments" and method == "POST":
        return api_record_payment(req)

    # API Billing Day
    if path == "/api/billing-day/run" and method == "POST":
        return api_run_billing_day(req)

    # API Admin Catalog
    if path == "/api/products" and method == "POST":
        return api_create_product(req)
    prod_var_match = re.match(r"^/api/products/(\d+)/variants$", path)
    if prod_var_match and method == "POST":
        return api_create_variant(req, int(prod_var_match.group(1)))
    if path == "/api/plans" and method == "POST":
        return api_create_plan(req)
    if path == "/api/discounts" and method == "POST":
        return api_create_discount(req)
    if path == "/api/taxes" and method == "POST":
        return api_create_tax(req)

    return Response("Not Found", status=404)


def application(environ, start_response):
    req = Request(environ)
    try:
        resp = dispatch(req)
    except Exception as e:
        import traceback
        traceback.print_exc()
        resp = Response(f"Internal Server Error: {str(e)}", status=500)
    return resp.to_wsgi(start_response)


def start_server(port=8000):
    init_db()
    server = make_server("0.0.0.0", port, application)
    print(f"Brightloop Subscription Platform running on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    start_server(8000)

