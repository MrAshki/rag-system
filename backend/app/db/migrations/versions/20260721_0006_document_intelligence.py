"""add deterministic document profile and map metadata

Revision ID: 20260721_0006
Revises: 20260629_0005
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260721_0006"
down_revision = "20260629_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("document_profile_json", postgresql.JSONB(), nullable=True))
    op.add_column("assets", sa.Column("document_map_path", sa.Text(), nullable=True))
    op.add_column("assets", sa.Column("processing_version", sa.Text(), nullable=True))
    op.add_column("assets", sa.Column("content_hash", sa.Text(), nullable=True))
    op.add_column("assets", sa.Column("quality_status", sa.Text(), nullable=True))
    op.add_column("assets", sa.Column("quality_score", sa.Float(), nullable=True))
    op.create_index("idx_assets_quality_status", "assets", ["quality_status"])
    op.create_index("idx_assets_content_hash", "assets", ["content_hash"])


def downgrade() -> None:
    op.drop_index("idx_assets_content_hash", table_name="assets")
    op.drop_index("idx_assets_quality_status", table_name="assets")
    op.drop_column("assets", "quality_score")
    op.drop_column("assets", "quality_status")
    op.drop_column("assets", "content_hash")
    op.drop_column("assets", "processing_version")
    op.drop_column("assets", "document_map_path")
    op.drop_column("assets", "document_profile_json")
