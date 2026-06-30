"""add compute usage events

Revision ID: 20260629_0005
Revises: 20260629_0004
Create Date: 2026-06-29
"""

from alembic import op


revision = "20260629_0005"
down_revision = "20260629_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_compute_usage_events_created ON compute_usage_events (created_at DESC)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compute_usage_events_user_created "
        "ON compute_usage_events (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compute_usage_events_feature_created "
        "ON compute_usage_events (feature, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compute_usage_events_operation_created "
        "ON compute_usage_events (operation_type, created_at DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_compute_usage_events_request ON compute_usage_events (request_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_compute_usage_events_conversation ON compute_usage_events (conversation_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compute_usage_events_metadata_gin "
        "ON compute_usage_events USING gin (metadata_json)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_compute_usage_events_metadata_gin")
    op.execute("DROP INDEX IF EXISTS idx_compute_usage_events_conversation")
    op.execute("DROP INDEX IF EXISTS idx_compute_usage_events_request")
    op.execute("DROP INDEX IF EXISTS idx_compute_usage_events_operation_created")
    op.execute("DROP INDEX IF EXISTS idx_compute_usage_events_feature_created")
    op.execute("DROP INDEX IF EXISTS idx_compute_usage_events_user_created")
    op.execute("DROP INDEX IF EXISTS idx_compute_usage_events_created")
    op.execute("DROP TABLE IF EXISTS compute_usage_events")
