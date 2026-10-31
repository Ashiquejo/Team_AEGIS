"""
Unit tests for Authentication, Password Policies, Password Reset, and RBAC.
"""

import unittest
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth import (
    validate_password_strength,
    hash_password,
    verify_password,
    register_user,
    authenticate_user,
    create_password_reset_token,
    reset_password_with_token
)
from database import init_db, get_db


class TestAuthAndSecurity(unittest.TestCase):
    def setUp(self):
        # Clean up test user records before each test
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE email LIKE '%@testshop.com' OR email LIKE '%@brightloop.com' AND role = 'staff' AND email != 'sarah.staff@brightloop.com' AND email != 'mark.staff@brightloop.com'")

    def test_password_strength_rules(self):
        """Tests Brightloop password rule: >8 chars, uppercase, lowercase, special char."""
        # Too short (<= 8 chars)
        ok, msg = validate_password_strength("Ab1!cde") # 7 chars
        self.assertFalse(ok)
        self.assertIn("more than 8 characters", msg)

        ok, msg = validate_password_strength("Ab1!cdef") # exactly 8 chars
        self.assertFalse(ok)
        self.assertIn("more than 8 characters", msg)

        # Missing uppercase
        ok, msg = validate_password_strength("weakpass!123")
        self.assertFalse(ok)
        self.assertIn("uppercase", msg)

        # Missing lowercase
        ok, msg = validate_password_strength("STRONGPASS!123")
        self.assertFalse(ok)
        self.assertIn("lowercase", msg)

        # Missing special character
        ok, msg = validate_password_strength("StrongPass123")
        self.assertFalse(ok)
        self.assertIn("special character", msg)

        # Valid password (> 8 chars, Upper, Lower, Special)
        ok, msg = validate_password_strength("StrongPass@123")
        self.assertTrue(ok)

    def test_unique_email_constraint(self):
        """Tests: 'Each email can belong to only one account'."""
        email = "unique.customer@testshop.com"
        pwd = "Customer@Secure2026#"

        # First registration
        ok1, msg1, user1 = register_user(email, pwd, "First User", "Acme Test")
        self.assertTrue(ok1)
        self.assertIsNotNone(user1)

        # Duplicate registration attempt
        ok2, msg2, user2 = register_user(email, pwd, "Second User", "Duplicate Test")
        self.assertFalse(ok2)
        self.assertIn("already exists", msg2)
        self.assertIsNone(user2)

    def test_only_admin_can_add_staff(self):
        """Tests: 'Only the admin can add a new member of staff'."""
        staff_email = "new.staff@brightloop.com"
        pwd = "Staff@Secret123#"

        # Attempt by non-admin (e.g. public/customer)
        ok, msg, user = register_user(staff_email, pwd, "Staff Candidate", role="staff", actor_role="customer")
        self.assertFalse(ok)
        self.assertIn("Only an administrator can create staff", msg)

        # Attempt by admin
        ok_admin, msg_admin, user_admin = register_user(staff_email, pwd, "Staff Candidate", role="staff", actor_role="admin")
        self.assertTrue(ok_admin)
        self.assertEqual(user_admin["role"], "staff")

    def test_forgot_password_reset_flow(self):
        """Tests: 'If they forget it later, a reset link should arrive at their registered email.'"""
        email = "forgotten.user@testshop.com"
        pwd = "OldPassword@123"
        new_pwd = "NewPassword@2026!"

        register_user(email, pwd, "Reset User", "Reset Shop")

        # Generate reset token
        ok, msg, token = create_password_reset_token(email)
        self.assertTrue(ok)
        self.assertIsNotNone(token)

        # Reset password using token
        ok_reset, msg_reset = reset_password_with_token(token, new_pwd)
        self.assertTrue(ok_reset)

        # Verify old password fails and new password authenticates
        auth_old, _, _ = authenticate_user(email, pwd)
        self.assertFalse(auth_old)

        auth_new, _, new_user = authenticate_user(email, new_pwd)
        self.assertTrue(auth_new)
        self.assertEqual(new_user["email"], email)


if __name__ == "__main__":
    unittest.main()
