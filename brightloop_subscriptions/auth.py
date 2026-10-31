"""
Authentication, Password Validation, RBAC, and Token Management for Brightloop Software.
"""

import re
import secrets
from datetime import datetime, timedelta, timezone
import bcrypt
import jwt
from database import get_db

JWT_SECRET = "brightloop-secret-key-production-grade-2026"
JWT_ALGORITHM = "HS256"
SESSION_DURATION_HOURS = 24


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validates password against Brightloop requirements:
    - More than 8 characters (> 8 chars, i.e., length >= 9)
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one special character
    """
    if not password or len(password) <= 8:
        return False, "Password must be more than 8 characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"[^A-Za-z0-9]", password):
        return False, "Password must contain at least one special character (e.g. !@#$%^&*)."
    return True, "Password meets all security criteria."


def hash_password(password: str) -> str:
    """Hashes a password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: int, email: str, role: str, name: str) -> str:
    """Creates a signed JWT access token for user sessions."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "email": email,
        "role": role,
        "name": name,
        "exp": now + timedelta(hours=SESSION_DURATION_HOURS),
        "iat": now
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Decodes and validates a JWT access token."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def register_user(email: str, password: str, name: str, company_name: str = "", phone: str = "", role: str = "customer", actor_role: str = "public") -> tuple[bool, str, dict | None]:
    """
    Registers a new user in the system.
    Rules:
    - Only an admin can register a user with role 'staff' or 'admin'.
    - Email must be unique.
    - Password must satisfy security requirements.
    """
    email = email.strip().lower()
    if not email:
        return False, "Email address is required.", None

    if role in ("staff", "admin") and actor_role != "admin":
        return False, "Only an administrator can create staff or admin accounts.", None

    is_valid, msg = validate_password_strength(password)
    if not is_valid:
        return False, msg, None

    pwd_hash = hash_password(password)

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cursor.fetchone():
                return False, "An account with this email already exists.", None

            cursor.execute("""
                INSERT INTO users (email, password_hash, role, name, company_name, phone)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (email, pwd_hash, role, name.strip(), company_name.strip() if company_name else None, phone.strip() if phone else None))
            new_id = cursor.lastrowid

            cursor.execute("SELECT id, email, role, name, company_name FROM users WHERE id = ?", (new_id,))
            user = dict(cursor.fetchone())
            return True, "Registration successful.", user
    except Exception as e:
        return False, f"Database error during registration: {str(e)}", None


def authenticate_user(email: str, password: str) -> tuple[bool, str, dict | None]:
    """Authenticates a user with email and password."""
    email = email.strip().lower()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, password_hash, role, name, company_name FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        if not row:
            return False, "Invalid email or password.", None

        user = dict(row)
        if verify_password(password, user["password_hash"]):
            # Remove hash before returning
            del user["password_hash"]
            return True, "Authentication successful.", user
        return False, "Invalid email or password.", None


def create_password_reset_token(email: str) -> tuple[bool, str, str | None]:
    """
    Generates a secure password reset token for the given email.
    Returns (success, message, token).
    """
    email = email.strip().lower()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        if not row:
            return False, "No account found with this email address.", None

        user_id = row["id"]
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO password_resets (user_id, token, expires_at)
            VALUES (?, ?, ?)
        """, (user_id, token, expires_at))

        return True, "Password reset link generated.", token


def reset_password_with_token(token: str, new_password: str) -> tuple[bool, str]:
    """Validates the reset token and updates the user's password."""
    is_valid, msg = validate_password_strength(new_password)
    if not is_valid:
        return False, msg

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id, expires_at, used
            FROM password_resets
            WHERE token = ? AND used = 0
        """, (token,))
        row = cursor.fetchone()
        if not row:
            return False, "Invalid or expired password reset link."

        expires_at = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            return False, "This password reset link has expired."

        # Update password
        new_hash = hash_password(new_password)
        cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, row["user_id"]))
        cursor.execute("UPDATE password_resets SET used = 1 WHERE id = ?", (row["id"],))

        return True, "Password has been successfully updated. You can now log in."
