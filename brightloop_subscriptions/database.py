"""
Database configuration, schema definition, and connection helpers for Brightloop Software.
"""

import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brightloop.db")


def get_db_connection():
    """Returns a SQLite connection configured with Row factory and foreign keys."""
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


@contextmanager
def get_db():
    """Context manager for safe database transactions."""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initializes the database schema and indexes."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Users table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'staff', 'customer')),
            name TEXT NOT NULL,
            company_name TEXT,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Password Reset Tokens table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Products table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL, -- e.g. software, addon, service
            sales_price REAL NOT NULL,
            cost_price REAL DEFAULT 0.0,
            notes TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Product Variants table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            variant_name TEXT NOT NULL,
            price_adjustment REAL DEFAULT 0.0,
            sku TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Plans table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            description TEXT,
            billing_frequency TEXT NOT NULL CHECK(billing_frequency IN ('daily', 'weekly', 'monthly', 'yearly')),
            base_price REAL NOT NULL,
            min_quantity INTEGER DEFAULT 1,
            available_from DATE,
            available_to DATE,
            auto_close_on_end INTEGER DEFAULT 1,
            can_close_early INTEGER DEFAULT 1,
            can_pause INTEGER DEFAULT 1,
            can_renew INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Taxes table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS taxes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            rate REAL NOT NULL, -- e.g. 10.0 for 10%
            is_fixed INTEGER DEFAULT 0, -- 0 = percentage, 1 = fixed amount
            is_default INTEGER DEFAULT 0,
            description TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Discounts table (admin only managed)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS discounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL COLLATE NOCASE,
            description TEXT,
            discount_type TEXT NOT NULL CHECK(discount_type IN ('percentage', 'fixed')),
            value REAL NOT NULL,
            min_purchase_amount REAL DEFAULT 0.0,
            min_quantity INTEGER DEFAULT 0,
            start_date DATE,
            end_date DATE,
            max_uses INTEGER, -- NULL = unlimited
            used_count INTEGER DEFAULT 0,
            scope TEXT NOT NULL CHECK(scope IN ('whole_subscription', 'specific_product')),
            applicable_product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
            is_active INTEGER DEFAULT 1,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Quotation Templates table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS quotation_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL,
            validity_days INTEGER DEFAULT 30,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Quotation Template Lines table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS quotation_template_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL REFERENCES quotation_templates(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            variant_id INTEGER REFERENCES product_variants(id) ON DELETE SET NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL,
            tax_id INTEGER REFERENCES taxes(id) ON DELETE SET NULL
        );
        """)

        # Subscriptions table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subscription_number TEXT UNIQUE NOT NULL,
            customer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE RESTRICT,
            status TEXT NOT NULL CHECK(status IN ('draft', 'quotation', 'confirmed', 'active', 'paused', 'closed', 'expired')),
            start_date DATE NOT NULL,
            expiry_date DATE,
            next_billing_date DATE,
            last_billing_date DATE,
            payment_terms TEXT DEFAULT 'Net 30',
            discount_id INTEGER REFERENCES discounts(id) ON DELETE SET NULL,
            notes TEXT,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Subscription Line Items table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscription_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            variant_id INTEGER REFERENCES product_variants(id) ON DELETE SET NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL,
            tax_id INTEGER REFERENCES taxes(id) ON DELETE SET NULL,
            subtotal REAL NOT NULL
        );
        """)

        # Invoices table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE NOT NULL,
            subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE SET NULL,
            customer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            issue_date DATE NOT NULL,
            due_date DATE NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('draft', 'confirmed', 'paid', 'cancelled')),
            subtotal REAL NOT NULL DEFAULT 0.0,
            discount_amount REAL NOT NULL DEFAULT 0.0,
            tax_amount REAL NOT NULL DEFAULT 0.0,
            total_amount REAL NOT NULL DEFAULT 0.0,
            amount_paid REAL NOT NULL DEFAULT 0.0,
            balance_due REAL NOT NULL DEFAULT 0.0,
            billing_period_start DATE,
            billing_period_end DATE,
            sent_at TIMESTAMP,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Invoice Line Items table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoice_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            variant_id INTEGER REFERENCES product_variants(id) ON DELETE SET NULL,
            description TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL,
            tax_rate REAL DEFAULT 0.0,
            tax_amount REAL DEFAULT 0.0,
            line_total REAL NOT NULL
        );
        """)

        # Payments table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL,
            payment_date DATE NOT NULL,
            reference_note TEXT,
            recorded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Activity & Audit Logs table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # System indexes for lightning-fast lookups (<2s requirement even with 10k+ rows)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_customer ON subscriptions(customer_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_next_billing ON subscriptions(next_billing_date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_plan ON subscriptions(plan_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_due_date ON invoices(due_date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_subscription ON invoices(subscription_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);")


def rows_to_dicts(cursor_rows):
    """Utility to convert sqlite3.Row list to list of Python dicts."""
    return [dict(row) for row in cursor_rows]

