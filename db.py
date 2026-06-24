import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

# Connection string. Override via DATABASE_URL in .env for production.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "host=127.0.0.1 port=5432 user=postgres password=123 dbname=rag_system",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    phone TEXT UNIQUE NOT NULL,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id SERIAL PRIMARY KEY,
    phone TEXT NOT NULL,
    code TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_otp_phone ON otp_codes (phone, created_at DESC);

CREATE TABLE IF NOT EXISTS plans (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    price_toman BIGINT NOT NULL,
    duration_days INTEGER NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    plan_id INTEGER NOT NULL REFERENCES plans(id),
    starts_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions (user_id, status, expires_at);

CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    plan_id INTEGER NOT NULL REFERENCES plans(id),
    amount_toman BIGINT NOT NULL,
    authority TEXT,
    ref_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL,
    paid_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_pay_authority ON payments (authority);
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def get_db():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute(SCHEMA)
        existing = conn.execute("SELECT COUNT(*) AS c FROM plans").fetchone()["c"]
        if existing == 0:
            conn.execute(
                "INSERT INTO plans (name, price_toman, duration_days, active) VALUES (%s, %s, %s, TRUE)",
                ("اشتراک یک ماهه", 150000, 30),
            )


# ---- users ----

def get_user_by_phone(phone: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE phone = %s", (phone,)).fetchone()


def get_user_by_id(user_id: int):
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()


def get_or_create_user(phone: str):
    user = get_user_by_phone(phone)
    if user:
        return user
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (phone, is_verified, is_admin, created_at) VALUES (%s, FALSE, FALSE, %s)",
            (phone, now()),
        )
    return get_user_by_phone(phone)


def mark_user_verified(phone: str):
    with get_db() as conn:
        conn.execute("UPDATE users SET is_verified = TRUE WHERE phone = %s", (phone,))


def list_users():
    with get_db() as conn:
        return conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()


def set_admin(phone: str, is_admin: bool):
    with get_db() as conn:
        conn.execute("UPDATE users SET is_admin = %s WHERE phone = %s", (is_admin, phone))


# ---- otp ----

def create_otp(phone: str, code: str, ttl_seconds: int = 120):
    expires_at = now() + timedelta(seconds=ttl_seconds)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO otp_codes (phone, code, expires_at, consumed, created_at) VALUES (%s, %s, %s, FALSE, %s)",
            (phone, code, expires_at, now()),
        )


def recent_otp_count(phone: str, window_seconds: int) -> int:
    since = now() - timedelta(seconds=window_seconds)
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM otp_codes WHERE phone = %s AND created_at >= %s",
            (phone, since),
        ).fetchone()
        return row["c"]


def verify_and_consume_otp(phone: str, code: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM otp_codes WHERE phone = %s AND code = %s AND consumed = FALSE
               ORDER BY created_at DESC LIMIT 1""",
            (phone, code),
        ).fetchone()
        if not row:
            return False
        if row["expires_at"] < now():
            return False
        conn.execute("UPDATE otp_codes SET consumed = TRUE WHERE id = %s", (row["id"],))
        return True


# ---- plans ----

def list_active_plans():
    with get_db() as conn:
        return conn.execute("SELECT * FROM plans WHERE active = TRUE ORDER BY price_toman").fetchall()


def get_plan(plan_id: int):
    with get_db() as conn:
        return conn.execute("SELECT * FROM plans WHERE id = %s", (plan_id,)).fetchone()


# ---- subscriptions ----

def get_active_subscription(user_id: int):
    with get_db() as conn:
        return conn.execute(
            """SELECT * FROM subscriptions WHERE user_id = %s AND status = 'active'
               AND expires_at > %s ORDER BY expires_at DESC LIMIT 1""",
            (user_id, now()),
        ).fetchone()


def create_subscription(user_id: int, plan_id: int, duration_days: int):
    starts_at = now()
    expires_at = starts_at + timedelta(days=duration_days)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO subscriptions (user_id, plan_id, starts_at, expires_at, status, created_at)
               VALUES (%s, %s, %s, %s, 'active', %s)""",
            (user_id, plan_id, starts_at, expires_at, now()),
        )


def list_subscriptions_for_admin():
    with get_db() as conn:
        return conn.execute(
            """SELECT subscriptions.*, users.phone AS phone, plans.name AS plan_name
               FROM subscriptions
               JOIN users ON users.id = subscriptions.user_id
               JOIN plans ON plans.id = subscriptions.plan_id
               ORDER BY subscriptions.created_at DESC"""
        ).fetchall()


def revoke_subscription(subscription_id: int):
    with get_db() as conn:
        conn.execute("UPDATE subscriptions SET status = 'cancelled' WHERE id = %s", (subscription_id,))


# ---- payments ----

def create_payment(user_id: int, plan_id: int, amount_toman: int) -> int:
    with get_db() as conn:
        row = conn.execute(
            """INSERT INTO payments (user_id, plan_id, amount_toman, status, created_at)
               VALUES (%s, %s, %s, 'pending', %s) RETURNING id""",
            (user_id, plan_id, amount_toman, now()),
        ).fetchone()
        return row["id"]


def set_payment_authority(payment_id: int, authority: str):
    with get_db() as conn:
        conn.execute("UPDATE payments SET authority = %s WHERE id = %s", (authority, payment_id))


def get_payment_by_authority(authority: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM payments WHERE authority = %s", (authority,)).fetchone()


def mark_payment_paid(payment_id: int, ref_id: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE payments SET status = 'paid', ref_id = %s, paid_at = %s WHERE id = %s",
            (ref_id, now(), payment_id),
        )


def mark_payment_failed(payment_id: int):
    with get_db() as conn:
        conn.execute("UPDATE payments SET status = 'failed' WHERE id = %s", (payment_id,))


def list_payments_for_admin():
    with get_db() as conn:
        return conn.execute(
            """SELECT payments.*, users.phone AS phone, plans.name AS plan_name
               FROM payments
               JOIN users ON users.id = payments.user_id
               JOIN plans ON plans.id = payments.plan_id
               ORDER BY payments.created_at DESC"""
        ).fetchall()
