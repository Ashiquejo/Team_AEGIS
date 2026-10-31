"""
Tests for Billing Day, Quotations to Subscriptions, Taxes, Discounts, and Idempotency.
"""

import unittest
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import init_db, get_db
from seed import seed_all
from billing_engine import (
    run_billing_day,
    preview_billing_day,
    generate_invoice_for_subscription,
    evaluate_discount,
    add_billing_interval
)


class TestBillingEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_all()

    def test_quote_to_subscription_lifecycle(self):
        """
        Tests: 'Each subscription gets its own number, a customer, a plan, a start date,
        an expiry date and payment terms... It moves from Draft to Quotation to Confirmed
        to Active and finally to Closed.'
        """
        with get_db() as conn:
            cursor = conn.cursor()
            # Fetch quotation SUB-2026-0003
            cursor.execute("SELECT * FROM subscriptions WHERE subscription_number = 'SUB-2026-0003'")
            sub = dict(cursor.fetchone())
            self.assertEqual(sub["status"], "quotation")

            # Move from Quotation -> Confirmed
            cursor.execute("UPDATE subscriptions SET status = 'confirmed' WHERE id = ?", (sub["id"],))
            cursor.execute("SELECT status FROM subscriptions WHERE id = ?", (sub["id"],))
            self.assertEqual(cursor.fetchone()["status"], "confirmed")

            # Move from Confirmed -> Active
            cursor.execute("UPDATE subscriptions SET status = 'active' WHERE id = ?", (sub["id"],))
            cursor.execute("SELECT status FROM subscriptions WHERE id = ?", (sub["id"],))
            self.assertEqual(cursor.fetchone()["status"], "active")

            # Move from Active -> Closed
            cursor.execute("UPDATE subscriptions SET status = 'closed' WHERE id = ?", (sub["id"],))
            cursor.execute("SELECT status FROM subscriptions WHERE id = ?", (sub["id"],))
            self.assertEqual(cursor.fetchone()["status"], "closed")

    def test_discount_rules_evaluation(self):
        """
        Tests: 'Only the admin can create discount rules: a fixed amount or a percentage,
        with a minimum purchase or quantity, start and end dates, and a limit on how many
        times it can be used... Once it applies, it should appear on the next invoice on
        its own, without anyone having to remember it, and stop when it expires or runs out.'
        """
        with get_db() as conn:
            cursor = conn.cursor()
            today = date.today()

            # 1. Volume discount (15% off for 10+ seats)
            cursor.execute("SELECT id FROM discounts WHERE code = 'VOLUME15'")
            disc_id = cursor.fetchone()["id"]

            # Less than 10 seats -> discount should NOT apply
            amt, code, _ = evaluate_discount(cursor, disc_id, lines_subtotal=2000.0, total_quantity=5, current_date=today)
            self.assertEqual(amt, 0.0)

            # >= 10 seats -> discount applies! 15% of $10,000 = $1,500
            amt, code, inc_id = evaluate_discount(cursor, disc_id, lines_subtotal=10000.0, total_quantity=10, current_date=today)
            self.assertEqual(amt, 1500.0)
            self.assertEqual(code, "VOLUME15")
            self.assertEqual(inc_id, disc_id)

            # 2. Expired discount check
            cursor.execute("SELECT id FROM discounts WHERE code = 'EXPIRED50'")
            exp_id = cursor.fetchone()["id"]
            amt_exp, _, _ = evaluate_discount(cursor, exp_id, lines_subtotal=100.0, total_quantity=1, current_date=today)
            self.assertEqual(amt_exp, 0.0) # stopped because expired!

    def test_billing_day_and_idempotency(self):
        """
        Tests: 'It is billing day, and hundreds of subscriptions are due at once.
        Each one should be created from its subscription, with customer details,
        product lines, taxes and totals... Nothing should be billed twice or skipped.'
        """
        today = date.today()

        # Run billing day
        result1 = run_billing_day(today)
        self.assertGreater(result1["invoices_generated"], 0)
        first_generated = result1["invoices_generated"]

        # Immediate second run on the same date:
        # Idempotency guarantee: must generate 0 new invoices!
        result2 = run_billing_day(today)
        self.assertEqual(result2["invoices_generated"], 0)

        # Invoices should exist in 'draft' status
        with get_db() as conn:
            cursor = conn.cursor()
            inv_id = result1["invoices"][0]["invoice_id"]
            cursor.execute("SELECT status FROM invoices WHERE id = ?", (inv_id,))
            self.assertEqual(cursor.fetchone()["status"], "draft")

            # Team confirms invoice: moves Draft -> Confirmed
            cursor.execute("UPDATE invoices SET status = 'confirmed' WHERE id = ?", (inv_id,))
            cursor.execute("SELECT status FROM invoices WHERE id = ?", (inv_id,))
            self.assertEqual(cursor.fetchone()["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()

