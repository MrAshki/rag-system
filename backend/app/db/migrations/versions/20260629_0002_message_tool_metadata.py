"""add message tool metadata

Revision ID: 20260629_0002
Revises: 20260628_0001
Create Date: 2026-06-29
"""

from alembic import op


revision = "20260629_0002"
down_revision = "20260628_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS mode TEXT")
    op.execute("ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS tool_id TEXT")
    op.execute("ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS tool_title TEXT")
    op.execute("ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS tool_params_json TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE conversation_messages DROP COLUMN IF EXISTS tool_params_json")
    op.execute("ALTER TABLE conversation_messages DROP COLUMN IF EXISTS tool_title")
    op.execute("ALTER TABLE conversation_messages DROP COLUMN IF EXISTS tool_id")
    op.execute("ALTER TABLE conversation_messages DROP COLUMN IF EXISTS mode")
