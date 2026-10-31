"""
Tests for Products, Variants (e.g. Odoo brand +560), and Plan Lifecycle Rules.
"""

import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import init_db, get_db


class TestProductsAndPlans(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_product_variants_pricing_odoo_rule(self):
        """
        Tests: 'The admin adds it with its name, type, sales price, cost price and notes,
        and offers it in variants, for example by brand, where choosing the Odoo brand
        adds 560 to the price.'
        """
        with get_db() as conn:
            cursor = conn.cursor()
            # Insert product
            cursor.execute("""
                INSERT INTO products (name, type, sales_price, cost_price, notes)
                VALUES ('Cloud Suite X', 'software', 400.0, 120.0, 'Enterprise ERP solution')
            """)
            prod_id = cursor.lastrowid

            # Insert standard variant (+0) and Odoo variant (+560)
            cursor.execute("""
                INSERT INTO product_variants (product_id, variant_name, price_adjustment, sku)
                VALUES 
                (?, 'Standard Brand', 0.0, 'PROD-STD'),
                (?, 'Odoo Brand', 560.0, 'PROD-ODOO-560')
            """, (prod_id, prod_id))

            # Query product with variants
            cursor.execute("SELECT * FROM products WHERE id = ?", (prod_id,))
            prod = dict(cursor.fetchone())
            self.assertEqual(prod["sales_price"], 400.0)
            self.assertEqual(prod["cost_price"], 120.0)
            self.assertEqual(prod["notes"], 'Enterprise ERP solution')

            cursor.execute("SELECT * FROM product_variants WHERE product_id = ?", (prod_id,))
            variants = {v["variant_name"]: v["price_adjustment"] for v in cursor.fetchall()}

            self.assertEqual(variants["Standard Brand"], 0.0)
            self.assertEqual(variants["Odoo Brand"], 560.0)

            # Effective price with Odoo variant: 400 + 560 = 960
            effective_price = prod["sales_price"] + variants["Odoo Brand"]
            self.assertEqual(effective_price, 960.0)

    def test_plans_cadences_and_lifecycle_policies(self):
        """
        Tests: 'how often it bills (daily, weekly, monthly or yearly), the minimum quantity,
        and the dates it is available. Some plans should close on their own when they end,
        and others can be closed early, paused or renewed. The admin decides which, plan by plan.'
        """
        with get_db() as conn:
            cursor = conn.cursor()
            plans_to_insert = [
                ("Daily Micro", "PLAN-D-TEST", "daily", 10.0, 1, 1, 0, 0, 0),
                ("Weekly Growth", "PLAN-W-TEST", "weekly", 80.0, 2, 1, 1, 1, 1),
                ("Monthly Pro", "PLAN-M-TEST", "monthly", 300.0, 5, 0, 1, 1, 1),
                ("Yearly Enterprise", "PLAN-Y-TEST", "yearly", 3200.0, 10, 1, 1, 0, 1),
            ]

            for name, code, freq, price, min_q, auto_close, close_early, pause, renew in plans_to_insert:
                cursor.execute("""
                    INSERT INTO plans (
                        name, code, billing_frequency, base_price, min_quantity,
                        auto_close_on_end, can_close_early, can_pause, can_renew
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, code, freq, price, min_q, auto_close, close_early, pause, renew))

            # Verify cadence constraints
            cursor.execute("SELECT code, billing_frequency, min_quantity, auto_close_on_end, can_pause FROM plans WHERE code LIKE 'PLAN-%-TEST'")
            rows = {r["code"]: dict(r) for r in cursor.fetchall()}

            self.assertEqual(rows["PLAN-D-TEST"]["billing_frequency"], "daily")
            self.assertEqual(rows["PLAN-D-TEST"]["auto_close_on_end"], 1)
            self.assertEqual(rows["PLAN-D-TEST"]["can_pause"], 0)

            self.assertEqual(rows["PLAN-M-TEST"]["billing_frequency"], "monthly")
            self.assertEqual(rows["PLAN-M-TEST"]["min_quantity"], 5)
            self.assertEqual(rows["PLAN-M-TEST"]["auto_close_on_end"], 0)
            self.assertEqual(rows["PLAN-M-TEST"]["can_pause"], 1)


if __name__ == "__main__":
    unittest.main()

