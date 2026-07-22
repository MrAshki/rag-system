"""add document unit summary cache

Revision ID: 20260721_0007
Revises: 20260721_0006
Create Date: 2026-07-21
"""
from alembic import op


revision = "20260721_0007"
down_revision = "20260721_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_unit_summaries (
            asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
            unit_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            summary_text TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (asset_id, unit_id, content_hash, provider, model)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_document_unit_summaries_asset "
        "ON document_unit_summaries (asset_id, updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_unit_summaries")
