import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.db.session import engine

load_dotenv(override=True, encoding="utf-8-sig")

DATABASE_URL = settings.database_url

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
    document_profile_json JSONB,
    document_map_path TEXT,
    processing_version TEXT,
    content_hash TEXT,
    quality_status TEXT,
    quality_score DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL,
    scanned_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_assets_user   ON assets (user_id, category, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assets_status ON assets (status);
ALTER TABLE assets ADD COLUMN IF NOT EXISTS document_profile_json JSONB;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS document_map_path TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS processing_version TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS quality_status TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS quality_score DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS document_unit_summaries (
    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    unit_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (asset_id, unit_id, content_hash, provider, model)
);
CREATE INDEX IF NOT EXISTS idx_document_unit_summaries_asset
    ON document_unit_summaries (asset_id, updated_at DESC);

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
    mode TEXT,
    tool_id TEXT,
    tool_title TEXT,
    tool_params_json TEXT,
    generated_output_id TEXT,
    created_at TIMESTAMPTZ NOT NULL
);
ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS mode TEXT;
ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS tool_id TEXT;
ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS tool_title TEXT;
ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS tool_params_json TEXT;
ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS generated_output_id TEXT;
CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_created
    ON conversation_messages (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS generated_outputs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content_json TEXT,
    content_markdown TEXT NOT NULL DEFAULT '',
    source_asset_ids_json TEXT,
    template_id TEXT,
    template_params_json TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_generated_outputs_user_updated
    ON generated_outputs (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_generated_outputs_conversation
    ON generated_outputs (conversation_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS usage_events (
    id TEXT PRIMARY KEY,
    request_id TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    message_id TEXT REFERENCES conversation_messages(id) ON DELETE SET NULL,
    tool_run_id TEXT,
    output_id TEXT REFERENCES generated_outputs(id) ON DELETE SET NULL,
    feature TEXT NOT NULL,
    operation_type TEXT NOT NULL DEFAULT 'chat_completion',
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd NUMERIC(18, 8) NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'success',
    error_type TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_usage_events_created
    ON usage_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_user_created
    ON usage_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_feature_created
    ON usage_events (feature, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_provider_model_created
    ON usage_events (provider, model, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_request
    ON usage_events (request_id);
CREATE INDEX IF NOT EXISTS idx_usage_events_conversation
    ON usage_events (conversation_id);
CREATE INDEX IF NOT EXISTS idx_usage_events_metadata_gin
    ON usage_events USING gin (metadata_json);

CREATE TABLE IF NOT EXISTS compute_usage_events (
    id TEXT PRIMARY KEY,
    request_id TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    message_id TEXT REFERENCES conversation_messages(id) ON DELETE SET NULL,
    output_id TEXT REFERENCES generated_outputs(id) ON DELETE SET NULL,
    feature TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    device TEXT,
    latency_ms INTEGER,
    input_count INTEGER NOT NULL DEFAULT 0,
    input_chars INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    pair_count INTEGER NOT NULL DEFAULT 0,
    query_count INTEGER NOT NULL DEFAULT 0,
    batch_size INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'success',
    error_type TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_compute_usage_events_created
    ON compute_usage_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_compute_usage_events_user_created
    ON compute_usage_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_compute_usage_events_feature_created
    ON compute_usage_events (feature, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_compute_usage_events_operation_created
    ON compute_usage_events (operation_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_compute_usage_events_request
    ON compute_usage_events (request_id);
CREATE INDEX IF NOT EXISTS idx_compute_usage_events_conversation
    ON compute_usage_events (conversation_id);
CREATE INDEX IF NOT EXISTS idx_compute_usage_events_metadata_gin
    ON compute_usage_events USING gin (metadata_json);
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def get_db():
    with engine.begin() as conn:
        yield _CompatConnection(conn)


def init_db():
    with engine.begin() as conn:
        if conn.execute(text("SELECT to_regclass('public.plans')")).scalar_one() is None:
            raise RuntimeError(
                "Database schema is not initialized. Run "
                "`python -m alembic upgrade head` or `python scripts/reset_postgres_schema.py` first."
            )
        existing = conn.execute(text("SELECT COUNT(*) AS c FROM plans")).mappings().fetchone()["c"]
        if existing == 0:
            conn.execute(
                text("INSERT INTO plans (name, price_toman, duration_days, active) VALUES (:name, :price, :days, TRUE)"),
                {"name": "اشتراک یک ماهه", "price": 150000, "days": 30},
            )


class _CompatResult:
    def __init__(self, result):
        self._result = result
        self.rowcount = result.rowcount

    def fetchone(self):
        return self._result.mappings().fetchone()

    def fetchall(self):
        return self._result.mappings().fetchall()


class _CompatConnection:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=None):
        converted_sql, converted_params = _convert_psycopg_params(sql, params)
        return _CompatResult(self._conn.execute(text(converted_sql), converted_params))


def _convert_psycopg_params(sql: str, params=None):
    if params is None:
        return sql, {}
    if not isinstance(params, (list, tuple)):
        return sql, params
    converted = sql
    values = {}
    for index, value in enumerate(params):
        name = f"p{index}"
        converted = converted.replace("%s", f":{name}", 1)
        values[name] = value
    return converted, values


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


def list_scanned_text_assets():
    with get_db() as conn:
        return conn.execute(
            """SELECT * FROM assets
                WHERE category = 'text' AND status = 'scanned'
                ORDER BY created_at"""
        ).fetchall()


def get_document_unit_summary(asset_id: str, unit_id: str, content_hash: str, provider: str, model: str):
    with get_db() as conn:
        return conn.execute(
            """SELECT * FROM document_unit_summaries
                WHERE asset_id = %s AND unit_id = %s AND content_hash = %s
                  AND provider = %s AND model = %s""",
            (asset_id, unit_id, content_hash, provider, model),
        ).fetchone()


def upsert_document_unit_summary(asset_id: str, unit_id: str, content_hash: str,
                                 provider: str, model: str, summary_text: str):
    ts = now()
    with get_db() as conn:
        return conn.execute(
            """INSERT INTO document_unit_summaries
                   (asset_id, unit_id, content_hash, provider, model, summary_text, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (asset_id, unit_id, content_hash, provider, model)
               DO UPDATE SET summary_text = EXCLUDED.summary_text, updated_at = EXCLUDED.updated_at
               RETURNING *""",
            (asset_id, unit_id, content_hash, provider, model, summary_text, ts, ts),
        ).fetchone()


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
                                stream_status: str = None, mode: str = None,
                                tool_id: str = None, tool_title: str = None,
                                tool_params=None, generated_output_id: str = None):
    message_id = uuid.uuid4().hex
    ts = now()
    with get_db() as conn:
        row = conn.execute(
            """INSERT INTO conversation_messages
                   (id, conversation_id, role, content, sources_json, status, stream_status,
                    mode, tool_id, tool_title, tool_params_json, generated_output_id, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING *""",
            (message_id, conversation_id, role, content or "", _encode_sources(sources),
             status, stream_status, mode, tool_id, tool_title,
             json.dumps(tool_params or {}, ensure_ascii=False) if tool_params is not None else None,
             generated_output_id, ts),
        ).fetchone()
        conn.execute("UPDATE conversations SET updated_at = %s WHERE id = %s", (ts, conversation_id))
        return row


def update_conversation_message(conversation_id: str, message_id: str, content=None,
                                sources=None, status=None, stream_status=None,
                                generated_output_id=None):
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
    if generated_output_id is not None:
        sets.append("generated_output_id = %s")
        params.append(generated_output_id)
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


def create_generated_output(user_id: int, conversation_id: str, output_type: str,
                            title: str, content_markdown: str,
                            content_json=None, source_asset_ids=None,
                            template_id: str = None, template_params=None):
    output_id = uuid.uuid4().hex
    ts = now()
    with get_db() as conn:
        return conn.execute(
            """INSERT INTO generated_outputs
                   (id, user_id, conversation_id, type, title, content_json,
                    content_markdown, source_asset_ids_json, template_id,
                    template_params_json, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING *""",
            (
                output_id,
                user_id,
                conversation_id,
                output_type,
                (title or "خروجی")[:180],
                json.dumps(content_json or {}, ensure_ascii=False) if content_json is not None else None,
                content_markdown or "",
                json.dumps(source_asset_ids or [], ensure_ascii=False),
                template_id,
                json.dumps(template_params or {}, ensure_ascii=False) if template_params is not None else None,
                ts,
                ts,
            ),
        ).fetchone()


def get_generated_output(user_id: int, output_id: str):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM generated_outputs WHERE id = %s AND user_id = %s",
            (output_id, user_id),
        ).fetchone()


def get_message_for_generated_output(output_id: str):
    with get_db() as conn:
        return conn.execute(
            """SELECT *
                 FROM conversation_messages
                WHERE generated_output_id = %s
                ORDER BY created_at DESC
                LIMIT 1""",
            (output_id,),
        ).fetchone()


# ---- usage events ----

def create_usage_event(
    *,
    request_id: str = None,
    user_id: int = None,
    conversation_id: str = None,
    message_id: str = None,
    tool_run_id: str = None,
    output_id: str = None,
    feature: str,
    operation_type: str = "chat_completion",
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    estimated_cost_usd=0,
    latency_ms: int = None,
    status: str = "success",
    error_type: str = None,
    metadata=None,
):
    usage_event_id = uuid.uuid4().hex
    ts = now()
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
    with get_db() as conn:
        return conn.execute(
            """INSERT INTO usage_events
                   (id, request_id, user_id, conversation_id, message_id, tool_run_id,
                    output_id, feature, operation_type, provider, model, input_tokens,
                    output_tokens, total_tokens, estimated_cost_usd, latency_ms, status,
                    error_type, metadata_json, created_at)
               VALUES
                   (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, CAST(%s AS jsonb), %s)
               RETURNING *""",
            (
                usage_event_id,
                request_id,
                user_id,
                conversation_id,
                message_id,
                tool_run_id,
                output_id,
                feature,
                operation_type,
                provider,
                model,
                int(input_tokens or 0),
                int(output_tokens or 0),
                int(total_tokens or 0),
                estimated_cost_usd or 0,
                latency_ms,
                status,
                error_type,
                metadata_json,
                ts,
            ),
        ).fetchone()


def update_usage_events_context(
    request_id: str,
    message_id: str = None,
    output_id: str = None,
    conversation_id: str = None,
    user_id: int = None,
):
    sets = []
    params = []
    if user_id is not None:
        sets.append("user_id = COALESCE(user_id, %s)")
        params.append(user_id)
    if conversation_id is not None:
        sets.append("conversation_id = COALESCE(conversation_id, %s)")
        params.append(conversation_id)
    if message_id is not None:
        sets.append("message_id = COALESCE(message_id, %s)")
        params.append(message_id)
    if output_id is not None:
        sets.append("output_id = COALESCE(output_id, %s)")
        params.append(output_id)
    if not request_id or not sets:
        return 0
    params.append(request_id)
    with get_db() as conn:
        result = conn.execute(
            f"""UPDATE usage_events
                   SET {', '.join(sets)}
                 WHERE request_id = %s""",
            tuple(params),
        )
        return result.rowcount or 0


def create_compute_usage_event(
    *,
    request_id: str = None,
    user_id: int = None,
    conversation_id: str = None,
    message_id: str = None,
    output_id: str = None,
    feature: str,
    operation_type: str,
    provider: str,
    model: str = None,
    device: str = None,
    latency_ms: int = None,
    input_count: int = 0,
    input_chars: int = 0,
    chunk_count: int = 0,
    pair_count: int = 0,
    query_count: int = 0,
    batch_size: int = 0,
    status: str = "success",
    error_type: str = None,
    metadata=None,
):
    compute_event_id = uuid.uuid4().hex
    ts = now()
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
    with get_db() as conn:
        return conn.execute(
            """INSERT INTO compute_usage_events
                   (id, request_id, user_id, conversation_id, message_id, output_id,
                    feature, operation_type, provider, model, device, latency_ms,
                    input_count, input_chars, chunk_count, pair_count, query_count,
                    batch_size, status, error_type, metadata_json, created_at)
               VALUES
                   (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb), %s)
               RETURNING *""",
            (
                compute_event_id,
                request_id,
                user_id,
                conversation_id,
                message_id,
                output_id,
                feature,
                operation_type,
                provider,
                model,
                device,
                latency_ms,
                int(input_count or 0),
                int(input_chars or 0),
                int(chunk_count or 0),
                int(pair_count or 0),
                int(query_count or 0),
                int(batch_size or 0),
                status,
                error_type,
                metadata_json,
                ts,
            ),
        ).fetchone()


def update_compute_usage_events_context(
    request_id: str,
    message_id: str = None,
    output_id: str = None,
    conversation_id: str = None,
    user_id: int = None,
):
    sets = []
    params = []
    if user_id is not None:
        sets.append("user_id = COALESCE(user_id, %s)")
        params.append(user_id)
    if conversation_id is not None:
        sets.append("conversation_id = COALESCE(conversation_id, %s)")
        params.append(conversation_id)
    if message_id is not None:
        sets.append("message_id = COALESCE(message_id, %s)")
        params.append(message_id)
    if output_id is not None:
        sets.append("output_id = COALESCE(output_id, %s)")
        params.append(output_id)
    if not request_id or not sets:
        return 0
    params.append(request_id)
    with get_db() as conn:
        result = conn.execute(
            f"""UPDATE compute_usage_events
                   SET {', '.join(sets)}
                 WHERE request_id = %s""",
            tuple(params),
        )
        return result.rowcount or 0


def update_asset_status(asset_id: str, status: str, scan_error: str = None,
                        chunk_count: int = None, normalized_md_path: str = None,
                        extraction_warning: str = None, document_profile=None,
                        document_map_path: str = None, processing_version: str = None,
                        content_hash: str = None, quality_status: str = None,
                        quality_score: float = None, set_scanned_at: bool = False):
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
    if document_profile is not None:
        sets.append("document_profile_json = CAST(%s AS jsonb)")
        params.append(json.dumps(document_profile, ensure_ascii=False))
    if document_map_path is not None:
        sets.append("document_map_path = %s")
        params.append(document_map_path)
    if processing_version is not None:
        sets.append("processing_version = %s")
        params.append(processing_version)
    if content_hash is not None:
        sets.append("content_hash = %s")
        params.append(content_hash)
    if quality_status is not None:
        sets.append("quality_status = %s")
        params.append(quality_status)
    if quality_score is not None:
        sets.append("quality_score = %s")
        params.append(float(quality_score))
    if set_scanned_at:
        sets.append("scanned_at = %s")
        params.append(now())
    params.append(asset_id)
    with get_db() as conn:
        conn.execute(f"UPDATE assets SET {', '.join(sets)} WHERE id = %s", tuple(params))


def prepare_asset_for_rescan(asset_id: str):
    with get_db() as conn:
        return conn.execute(
            """UPDATE assets
                  SET status = 'scanning',
                      scan_error = NULL,
                      chunk_count = NULL,
                      normalized_md_path = NULL,
                      extraction_warning = NULL,
                      document_profile_json = NULL,
                      document_map_path = NULL,
                      processing_version = NULL,
                      content_hash = NULL,
                      quality_status = NULL,
                      quality_score = NULL,
                      scanned_at = NULL
                WHERE id = %s
                RETURNING *""",
            (asset_id,),
        ).fetchone()


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
