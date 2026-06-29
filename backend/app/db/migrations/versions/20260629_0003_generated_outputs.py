"""add generated outputs

Revision ID: 20260629_0003
Revises: 20260629_0002
Create Date: 2026-06-29
"""

from alembic import op


revision = "20260629_0003"
down_revision = "20260629_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS generated_output_id TEXT")
    op.execute(
        """
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
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_generated_outputs_user_updated "
        "ON generated_outputs (user_id, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_generated_outputs_conversation "
        "ON generated_outputs (conversation_id, updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_generated_outputs_conversation")
    op.execute("DROP INDEX IF EXISTS idx_generated_outputs_user_updated")
    op.execute("DROP TABLE IF EXISTS generated_outputs")
    op.execute("ALTER TABLE conversation_messages DROP COLUMN IF EXISTS generated_output_id")
