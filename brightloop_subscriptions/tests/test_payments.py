"""
Tests for Payment Recording, Partial & Full Settlement, and Overdue Chase Tracking.
"""

import unittest
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import init_db, get_db
from seed import seed_all
from billing_engine import record_payment, get_finance_summary


class TestPaymentsAndOverdue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_all()

    def test_payment_recording_partial_and_full(self):
        """
        Tests: 'Payments arrive by different methods and on different days.
        Each one needs to be recorded with its method, amount, date and a note,
        against the right invoice... see which invoices are paid and which are still outstanding.'
        """
        with get_db() as conn:
            cursor = conn.cursor()
            # Find an outstanding confirmed invoice
            cursor.execute("SELECT id, invoice_number, total_amount, balance_due FROM invoices WHERE status = 'confirmed' LIMIT 1")
            inv = dict(cursor.fetchone())
            inv_id = inv["id"]
            orig_balance = inv["balance_due"]

            # 1. Record partial payment
            partial_amount = round(orig_balance / 2.0, 2)
            today = date.today()
            ok, msg, res = record_payment(
                invoice_id=inv_id,
                amount=partial_amount,
                payment_method="Bank Transfer",
                payment_date=today,
                reference_note="First 50% installment"
            )
            self.assertTrue(ok)
            self.assertEqual(res["status"], "confirmed") # Still outstanding!
            expected_bal = round(orig_balance - partial_amount, 2)
            self.assertAlmostEqual(res["balance_due"], expected_bal, places=2)

            # 2. Record remaining payment (Full settlement)
            ok2, msg2, res2 = record_payment(
                invoice_id=inv_id,
                amount=expected_bal,
                payment_method="Credit Card",
                payment_date=today,
                reference_note="Settlement in full"
            )
            self.assertTrue(ok2)
            self.assertEqual(res2["status"], "paid") # Now marked as Paid!
            self.assertEqual(res2["balance_due"], 0.0)

    def test_overdue_detection_and_aging(self):
        """
        Tests: 'At any moment, the team should be able to see which invoices are paid
        and which are still outstanding, so overdue ones can be chased before they turn
        into lost revenue.'
        """
        summary = get_finance_summary()
        self.assertGreater(summary["overdue_count"], 0)
        self.assertGreater(summary["overdue_total"], 0.0)

        # Aging buckets
        aging = summary["aging"]
        total_aging = aging["1_15_days"] + aging["16_30_days"] + aging["31_60_days"] + aging["60_plus_days"]
        self.assertAlmostEqual(total_aging, summary["overdue_total"], places=2)


if __name__ == "__main__":
    unittest.main()

