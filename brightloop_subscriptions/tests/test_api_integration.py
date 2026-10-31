"""
End-to-End Integration and HTTP Testing for Brightloop Web Server & Endpoints.
"""

import unittest
import os
import sys
import json
from io import BytesIO
import urllib.parse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import application
from database import init_db
from seed import seed_all
import auth


class TestWebIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_all()

    def make_request(self, method="GET", path="/", query="", body=None, headers=None, cookies=None):
        """Simulates WSGI request and returns (status_code, headers_dict, body_str, json_dict)."""
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "wsgi.url_scheme": "http",
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "8000"
        }

        body_bytes = b""
        if body is not None:
            if isinstance(body, dict):
                body_bytes = json.dumps(body).encode("utf-8")
                environ["CONTENT_TYPE"] = "application/json"
            elif isinstance(body, str):
                body_bytes = body.encode("utf-8")
            environ["CONTENT_LENGTH"] = str(len(body_bytes))
        environ["wsgi.input"] = BytesIO(body_bytes)

        if headers:
            for k, v in headers.items():
                environ[f"HTTP_{k.upper().replace('-', '_')}"] = v

        if cookies:
            environ["HTTP_COOKIE"] = "; ".join(f"{k}={v}" for k, v in cookies.items())

        response_status = []
        response_headers = []

        def start_response(status, resp_headers):
            response_status.append(status)
            response_headers.extend(resp_headers)

        res_iter = application(environ, start_response)
        res_body = b"".join(res_iter).decode("utf-8")
        status_code = int(response_status[0].split()[0])
        headers_dict = dict(response_headers)

        json_data = None
        if "application/json" in headers_dict.get("Content-Type", ""):
            try:
                json_data = json.loads(res_body)
            except Exception:
                json_data = None

        return status_code, headers_dict, res_body, json_data

    def test_pages_render(self):
        """Test public and static asset rendering."""
        # Static CSS
        status, headers, body, _ = self.make_request("GET", "/static/style.css")
        self.assertEqual(status, 200)
        self.assertIn("Brightloop Software", body)

        # Login page
        status, headers, body, _ = self.make_request("GET", "/login")
        self.assertEqual(status, 200)
        self.assertIn("Sign in to Brightloop", body)

        # Signup page
        status, headers, body, _ = self.make_request("GET", "/signup")
        self.assertEqual(status, 200)
        self.assertIn("Join Brightloop Software", body)

    def test_authenticated_workflows(self):
        """Test Admin, Staff, and Customer user sessions and isolation."""
        # 1. Login as Admin
        status, headers, _, data = self.make_request("POST", "/api/auth/login", body={
            "email": "admin@brightloop.com",
            "password": "Admin@1234#"
        })
        self.assertEqual(status, 200)
        admin_token = data["token"]
        admin_cookie = {"session_token": admin_token}

        # Admin access to /dashboard
        status, _, body, _ = self.make_request("GET", "/dashboard", cookies=admin_cookie)
        self.assertEqual(status, 200)
        self.assertIn("Finance & Revenue Hub", body)

        # Admin access to /discounts
        status, _, body, _ = self.make_request("GET", "/discounts", cookies=admin_cookie)
        self.assertEqual(status, 200)
        self.assertIn("Discount Rules", body)

        # 2. Login as Customer
        status, _, _, cust_data = self.make_request("POST", "/api/auth/login", body={
            "email": "acme@shops.com",
            "password": "Customer@1234#"
        })
        self.assertEqual(status, 200)
        cust_token = cust_data["token"]
        cust_cookie = {"session_token": cust_token}

        # Customer access to /portal
        status, _, body, _ = self.make_request("GET", "/portal", cookies=cust_cookie)
        self.assertEqual(status, 200)
        self.assertIn("Customer Portal", body)

        # Customer attempts to access admin discounts -> redirected
        status, _, _, _ = self.make_request("GET", "/discounts", cookies=cust_cookie)
        self.assertEqual(status, 302) # forbidden redirect!

    def test_end_to_end_billing_and_payment_flow(self):
        """End-to-end integration test of Billing Day and payment logging."""
        # Login as Staff
        _, _, _, staff_data = self.make_request("POST", "/api/auth/login", body={
            "email": "sarah.staff@brightloop.com",
            "password": "Staff@1234#"
        })
        staff_cookie = {"session_token": staff_data["token"]}

        # Run Billing Day via API
        status, _, _, run_res = self.make_request("POST", "/api/billing-day/run", body={}, cookies=staff_cookie)
        self.assertEqual(status, 200)
        self.assertTrue(run_res["success"])

        # Check Invoices list
        status, _, body, _ = self.make_request("GET", "/invoices", cookies=staff_cookie)
        self.assertEqual(status, 200)
        self.assertIn("Invoices & Accounts Receivable", body)


if __name__ == "__main__":
    unittest.main()
