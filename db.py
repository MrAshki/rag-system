import json
import os
import uuid
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

-- Registration profile fields, added after the initial phone-only schema.
-- All nullable so pre-existing phone-only accounts keep working untouched; they
-- get populated when a user completes the full register form. `password_hash` is
-- set only for accounts that registered with an email+password (the alternate
-- login path); phone+OTP-only accounts leave it NULL. `email` is unique among
-- non-NULL values (Postgres lets multiple NULLs coexist under a UNIQUE index).
ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name    TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name     TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email         TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS birth_date    DATE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (email);

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

-- Per-user uploaded files (the gallery). Single source of truth for a user's
-- assets and their scan lifecycle; Chroma still holds the chunk vectors for
-- retrieval, but file ownership/status lives here. `id` is the asset_id (uuid
-- hex), which for text assets is also the Chroma document_id.
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    category TEXT NOT NULL,              -- text | image | audio | video
    original_filename TEXT NOT NULL,
    file_ext TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
        -- text:  uploaded -> scanning -> scanned | failed
        -- media: uploaded -> stored   (no processing pipeline yet)
    scan_error TEXT,
    chunk_count INTEGER,
    original_path TEXT NOT NULL,
    normalized_md_path TEXT,
    extraction_warning TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    scanned_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_assets_user   ON assets (user_id, category, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assets_status ON assets (status);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    chat_provider TEXT,
    chat_model TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
    ON conversations (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    sources_json TEXT,
    status TEXT NOT NULL DEFAULT 'complete',
    stream_status TEXT,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_created
    ON conversation_messages (conversation_id, created_at);
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


def get_user_by_email(email: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()


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


def complete_user_registration(phone, first_name, last_name, email, birth_date, password_hash):
    """Fill in a user's profile after their phone is OTP-verified during the full
    register flow. The phone row already exists (get_or_create_user makes a stub on
    OTP verify), so this just patches in the collected fields and marks it verified.
    Returns the refreshed user row."""
    user = get_or_create_user(phone)
    with get_db() as conn:
        conn.execute(
            """UPDATE users
                   SET first_name = %s, last_name = %s, email = %s,
                       birth_date = %s, password_hash = %s, is_verified = TRUE
                 WHERE id = %s""",
            (first_name, last_name, email, birth_date, password_hash, user["id"]),
        )
    return get_user_by_id(user["id"])


def update_user_profile(user_id: int, first_name, last_name, email, birth_date):
    """Edit the user-facing profile fields from the profile page. Phone is the
    verified identity and is intentionally not editable here."""
    with get_db() as conn:
        conn.execute(
            """UPDATE users SET first_name = %s, last_name = %s, email = %s, birth_date = %s
                 WHERE id = %s""",
            (first_name, last_name, email, birth_date, user_id),
        )


def set_user_password(user_id: int, password_hash: str):
    with get_db() as conn:
        conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))


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


def list_payments_for_user(user_id: int):
    """A single user's own payment history, for their profile page."""
    with get_db() as conn:
        return conn.execute(
            """SELECT payments.*, plans.name AS plan_name
                 FROM payments
                 JOIN plans ON plans.id = payments.plan_id
                WHERE payments.user_id = %s
                ORDER BY payments.created_at DESC""",
            (user_id,),
        ).fetchall()


def list_payments_for_admin():
    with get_db() as conn:
        return conn.execute(
            """SELECT payments.*, users.phone AS phone, plans.name AS plan_name
               FROM payments
               JOIN users ON users.id = payments.user_id
               JOIN plans ON plans.id = payments.plan_id
               ORDER BY payments.created_at DESC"""
        ).fetchall()


# ---- assets (gallery / per-user files) ----

def create_asset(asset_id: str, user_id: int, category: str, original_filename: str,
                 file_ext: str, size_bytes: int, original_path: str, status: str = "uploaded"):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO assets
                   (id, user_id, category, original_filename, file_ext, size_bytes,
                    original_path, status, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (asset_id, user_id, category, original_filename, file_ext, size_bytes,
             original_path, status, now()),
        )


def get_asset(asset_id: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM assets WHERE id = %s", (asset_id,)).fetchone()


def list_assets(user_id: int, category: str = None, status: str = None):
    clauses = ["user_id = %s"]
    params = [user_id]
    if category:
        clauses.append("category = %s")
        params.append(category)
    if status:
        clauses.append("status = %s")
        params.append(status)
    with get_db() as conn:
        return conn.execute(
            f"SELECT * FROM assets WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
            tuple(params),
        ).fetchall()


def list_assets_by_ids(user_id: int, asset_ids):
    asset_ids = [asset_id for asset_id in (asset_ids or []) if asset_id]
    if not asset_ids:
        return []
    with get_db() as conn:
        return conn.execute(
            """SELECT * FROM assets
                WHERE user_id = %s AND id = ANY(%s)
                ORDER BY created_at DESC""",
            (user_id, asset_ids),
        ).fetchall()


# ---- conversations ----

def _encode_sources(sources) -> str:
    return json.dumps(sources or [], ensure_ascii=False)


def create_conversation(user_id: int, title: str = "گفتگوی جدید",
                        chat_provider: str = None, chat_model: str = None):
    conversation_id = uuid.uuid4().hex
    ts = now()
    with get_db() as conn:
        return conn.execute(
            """INSERT INTO conversations
                   (id, user_id, title, chat_provider, chat_model, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING *""",
            (conversation_id, user_id, title or "گفتگوی جدید", chat_provider, chat_model, ts, ts),
        ).fetchone()


def list_conversations(user_id: int):
    with get_db() as conn:
        return conn.execute(
            """SELECT * FROM conversations
                WHERE user_id = %s
                ORDER BY updated_at DESC, created_at DESC""",
            (user_id,),
        ).fetchall()


def get_conversation(user_id: int, conversation_id: str):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        ).fetchone()


def update_conversation(user_id: int, conversation_id: str, title=None,
                        chat_provider=None, chat_model=None, touch: bool = True):
    sets = []
    params = []
    if title is not None:
        sets.append("title = %s")
        params.append((title or "گفتگوی جدید").strip()[:160])
    if chat_provider is not None:
        sets.append("chat_provider = %s")
        params.append(chat_provider)
    if chat_model is not None:
        sets.append("chat_model = %s")
        params.append(chat_model)
    if touch:
        sets.append("updated_at = %s")
        params.append(now())
    if not sets:
        return get_conversation(user_id, conversation_id)
    params.extend([conversation_id, user_id])
    with get_db() as conn:
        return conn.execute(
            f"""UPDATE conversations
                   SET {', '.join(sets)}
                 WHERE id = %s AND user_id = %s
                 RETURNING *""",
            tuple(params),
        ).fetchone()


def delete_conversation(user_id: int, conversation_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "DELETE FROM conversations WHERE id = %s AND user_id = %s RETURNING id",
            (conversation_id, user_id),
        ).fetchone()
        return bool(row)


def list_conversation_messages(user_id: int, conversation_id: str):
    with get_db() as conn:
        return conn.execute(
            """SELECT conversation_messages.*
                 FROM conversation_messages
                 JOIN conversations ON conversations.id = conversation_messages.conversation_id
                WHERE conversation_messages.conversation_id = %s
                  AND conversations.user_id = %s
                ORDER BY conversation_messages.created_at ASC""",
            (conversation_id, user_id),
        ).fetchall()


def create_conversation_message(conversation_id: str, role: str, content: str = "",
                                sources=None, status: str = "complete",
                                stream_status: str = None):
    message_id = uuid.uuid4().hex
    ts = now()
    with get_db() as conn:
        row = conn.execute(
            """INSERT INTO conversation_messages
                   (id, conversation_id, role, content, sources_json, status, stream_status, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING *""",
            (message_id, conversation_id, role, content or "", _encode_sources(sources),
             status, stream_status, ts),
        ).fetchone()
        conn.execute("UPDATE conversations SET updated_at = %s WHERE id = %s", (ts, conversation_id))
        return row


def update_conversation_message(conversation_id: str, message_id: str, content=None,
                                sources=None, status=None, stream_status=None):
    sets = []
    params = []
    if content is not None:
        sets.append("content = %s")
        params.append(content)
    if sources is not None:
        sets.append("sources_json = %s")
        params.append(_encode_sources(sources))
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if stream_status is not None:
        sets.append("stream_status = %s")
        params.append(stream_status)
    if not sets:
        return None
    params.extend([message_id, conversation_id])
    with get_db() as conn:
        row = conn.execute(
            f"""UPDATE conversation_messages
                   SET {', '.join(sets)}
                 WHERE id = %s AND conversation_id = %s
                 RETURNING *""",
            tuple(params),
        ).fetchone()
        conn.execute("UPDATE conversations SET updated_at = %s WHERE id = %s", (now(), conversation_id))
        return row


def update_asset_status(asset_id: str, status: str, scan_error: str = None,
                        chunk_count: int = None, normalized_md_path: str = None,
                        extraction_warning: str = None, set_scanned_at: bool = False):
    """Patch an asset's scan state. Only non-None fields are written, so callers
    can update just status, or status plus the post-scan result fields."""
    sets = ["status = %s"]
    params = [status]
    if scan_error is not None:
        sets.append("scan_error = %s")
        params.append(scan_error)
    if chunk_count is not None:
        sets.append("chunk_count = %s")
        params.append(chunk_count)
    if normalized_md_path is not None:
        sets.append("normalized_md_path = %s")
        params.append(normalized_md_path)
    if extraction_warning is not None:
        sets.append("extraction_warning = %s")
        params.append(extraction_warning)
    if set_scanned_at:
        sets.append("scanned_at = %s")
        params.append(now())
    params.append(asset_id)
    with get_db() as conn:
        conn.execute(f"UPDATE assets SET {', '.join(sets)} WHERE id = %s", tuple(params))


def claim_next_uploaded_asset():
    """Atomically pick the oldest 'uploaded' asset and flip it to 'scanning',
    returning the claimed row (or None if the queue is empty). FOR UPDATE SKIP
    LOCKED makes this safe even if several workers/processes poll concurrently --
    no two claim the same asset."""
    with get_db() as conn:
        return conn.execute(
            """UPDATE assets SET status = 'scanning'
               WHERE id = (
                   SELECT id FROM assets WHERE status = 'uploaded'
                   ORDER BY created_at
                   FOR UPDATE SKIP LOCKED
                   LIMIT 1
               )
               RETURNING *"""
        ).fetchone()


def requeue_stuck_scanning() -> int:
    """On startup, return any asset stranded in 'scanning' (e.g. a crash/restart
    mid-scan) back to 'uploaded' so the worker reprocesses it. Index upserts are
    idempotent (deterministic chunk ids), so re-running a scan is safe. Returns
    how many were requeued."""
    with get_db() as conn:
        rows = conn.execute(
            "UPDATE assets SET status = 'uploaded' WHERE status = 'scanning' RETURNING id"
        ).fetchall()
        return len(rows)
