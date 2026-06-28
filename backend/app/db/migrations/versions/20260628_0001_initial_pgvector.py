"""initial postgres and pgvector schema

Revision ID: 20260628_0001
Revises:
Create Date: 2026-06-28
"""
import os

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "20260628_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    embedding_dim = int(os.getenv("EMBEDDING_DIM", "1024"))
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.Text(), nullable=False, unique=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_name", sa.Text()),
        sa.Column("last_name", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("birth_date", sa.Date()),
        sa.Column("password_hash", sa.Text()),
    )
    op.create_index("idx_users_email", "users", ["email"], unique=True)

    op.create_table(
        "otp_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_otp_phone", "otp_codes", ["phone", "created_at"])

    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("price_toman", sa.BigInteger(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_sub_user", "subscriptions", ["user_id", "status", "expires_at"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("amount_toman", sa.BigInteger(), nullable=False),
        sa.Column("authority", sa.Text()),
        sa.Column("ref_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_pay_authority", "payments", ["authority"])

    op.create_table(
        "assets",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("file_ext", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="uploaded"),
        sa.Column("scan_error", sa.Text()),
        sa.Column("chunk_count", sa.Integer()),
        sa.Column("original_path", sa.Text(), nullable=False),
        sa.Column("normalized_md_path", sa.Text()),
        sa.Column("extraction_warning", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_assets_user", "assets", ["user_id", "category", "created_at"])
    op.create_index("idx_assets_status", "assets", ["status"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("chat_provider", sa.Text()),
        sa.Column("chat_model", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_conversations_user_updated", "conversations", ["user_id", "updated_at"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("conversation_id", sa.Text(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("sources_json", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="complete"),
        sa.Column("stream_status", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_conversation_messages_conversation_created",
        "conversation_messages",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chunk_id", sa.Text(), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Text(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(embedding_dim), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_document_chunk_index"),
    )
    op.create_index("idx_document_chunks_user_document", "document_chunks", ["user_id", "document_id"])
    op.create_index("idx_document_chunks_metadata_gin", "document_chunks", ["metadata"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_cosine "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )

    op.execute(
        "INSERT INTO plans (name, price_toman, duration_days, active) "
        "VALUES ('اشتراک یک ماهه', 150000, 30, TRUE)"
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
    op.drop_table("assets")
    op.drop_table("payments")
    op.drop_table("subscriptions")
    op.drop_table("plans")
    op.drop_table("otp_codes")
    op.drop_table("users")
