#!/usr/bin/env python3
"""
Brightloop Software - System Runner & Startup Script.
"""

import sys
import os

# Add local directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import init_db
from seed import seed_all
from app import start_server

if __name__ == "__main__":
    port = 8000
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])

    if "--seed" in sys.argv or not os.path.exists(os.path.join(os.path.dirname(__file__), "brightloop.db")):
        seed_all()

    print(f"\n========================================================")
    print(f"  Brightloop Software Subscription & Billing Platform   ")
    print(f"========================================================")
    print(f"Web Interface: http://localhost:{port}")
    print(f"Demo Logins:")
    print(f"  • Admin:    admin@brightloop.com        (Password: Admin@1234#)")
    print(f"  • Staff:    sarah.staff@brightloop.com  (Password: Staff@1234#)")
    print(f"  • Customer: acme@shops.com              (Password: Customer@1234#)")
    print(f"  • Customer: techcorp@enterprise.com     (Password: Customer@1234#)")
    print(f"========================================================\n")

    start_server(port)

