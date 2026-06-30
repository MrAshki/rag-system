"""add usage events

Revision ID: 20260629_0004
Revises: 20260629_0003
Create Date: 2026-06-29
"""

from alembic import op


revision = "20260629_0004"
down_revision = "20260629_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_created ON usage_events (created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_user_created ON usage_events (user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_feature_created ON usage_events (feature, created_at DESC)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_provider_model_created "
        "ON usage_events (provider, model, created_at DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_request ON usage_events (request_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_conversation ON usage_events (conversation_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_metadata_gin "
        "ON usage_events USING gin (metadata_json)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_usage_events_metadata_gin")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_conversation")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_request")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_provider_model_created")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_feature_created")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_user_created")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_created")
    op.execute("DROP TABLE IF EXISTS usage_events")
