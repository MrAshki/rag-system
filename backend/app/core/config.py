import os
from dataclasses import dataclass

from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy.engine import URL

load_dotenv(override=True, encoding="utf-8-sig")

MAX_UPLOAD_MB = 25


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _database_url_for_sqlalchemy(raw_url: str) -> str:
    raw_url = (raw_url or "").strip()
    if raw_url.startswith("DATABASE_URL="):
        raw_url = raw_url.removeprefix("DATABASE_URL=").strip()
    if not raw_url:
        return "postgresql+psycopg://postgres:123@127.0.0.1:5432/rag_system"
    if raw_url.startswith("postgresql+psycopg://"):
        return raw_url
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+psycopg://", 1)

    parts = conninfo_to_dict(raw_url)
    return str(URL.create(
        "postgresql+psycopg",
        username=parts.get("user"),
        password=parts.get("password"),
        host=parts.get("host", "127.0.0.1"),
        port=int(parts["port"]) if parts.get("port") else None,
        database=parts.get("dbname"),
    ))


class Settings:
    secret_key: str
    public_base_url: str
    frontend_url: str
    host: str
    port: int
    debug: bool
    database_url: str
    vector_backend: str
    embedding_model_path: str
    embedding_dim: int

    def __init__(self):
        self.secret_key = os.getenv("SESSION_SECRET_KEY") or os.getenv("FLASK_SECRET_KEY", "")
        if not self.secret_key:
            raise RuntimeError(
                "SESSION_SECRET_KEY is not set. Add a long random value to .env before running "
                "(e.g. python -c \"import secrets; print(secrets.token_hex(32))\")."
            )
        self.public_base_url = os.getenv("PUBLIC_BASE_URL", "")
        self.frontend_url = os.getenv("FRONTEND_URL", "http://127.0.0.1:3000")
        self.host = os.getenv("HOST", "127.0.0.1")
        self.port = int(os.getenv("PORT", "5000"))
        self.debug = os.getenv("FASTAPI_DEBUG", os.getenv("FLASK_DEBUG", "false")).lower() == "true"
        self.database_url = _database_url_for_sqlalchemy(os.getenv("DATABASE_URL", ""))
        self.vector_backend = os.getenv("VECTOR_BACKEND", "qdrant").strip().lower()
        self.qdrant_url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333").strip()
        self.qdrant_api_key = os.getenv("QDRANT_API_KEY", "").strip() or None
        self.qdrant_collection = os.getenv("QDRANT_COLLECTION", "rag_documents").strip()
        self.embedding_provider = os.getenv("EMBEDDING_PROVIDER", "openrouter").strip().lower()
        default_embedding_model = (
            "nvidia/nemotron-3-embed-1b:free"
            if self.embedding_provider == "openrouter"
            else "./models/bge-m3"
        )
        self.embedding_model = os.getenv(
            "RAG_EMBEDDING_MODEL",
            os.getenv("EMBEDDING_MODEL", default_embedding_model),
        ).strip()
        self.embedding_model_path = os.getenv("EMBEDDING_MODEL_PATH") or self.embedding_model
        self.embedding_dim = int(os.getenv("EMBEDDING_DIM", "2048"))
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.openrouter_base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        self.openrouter_site_url = os.getenv("OPENROUTER_SITE_URL", self.public_base_url).strip()
        self.openrouter_app_name = os.getenv("OPENROUTER_APP_NAME", "rag-system").strip()
        self.rag_retrieval_mode = os.getenv("RAG_RETRIEVAL_MODE", "r2").strip().lower()
        if self.rag_retrieval_mode not in {"r1", "r2"}:
            raise RuntimeError("RAG_RETRIEVAL_MODE must be 'r1' or 'r2'.")
        self.rag_cross_language_rewrite_enabled = _bool_env(
            "RAG_CROSS_LANGUAGE_REWRITE_ENABLED", True,
        )
        self.rag_primary_generator_model = os.getenv(
            "RAG_PRIMARY_GENERATOR_MODEL", "google/gemini-2.5-flash",
        ).strip()
        self.rag_fallback_generator_model = os.getenv(
            "RAG_FALLBACK_GENERATOR_MODEL", "z-ai/glm-5.2",
        ).strip()
        self.rag_generator_fallback_enabled = _bool_env(
            "RAG_GENERATOR_FALLBACK_ENABLED", True,
        )
        self.rag_max_generator_attempts = int(os.getenv("RAG_MAX_GENERATOR_ATTEMPTS", "2"))
        if self.rag_max_generator_attempts not in {1, 2}:
            raise RuntimeError("RAG_MAX_GENERATOR_ATTEMPTS must be 1 or 2.")
        if self.rag_generator_fallback_enabled and self.rag_max_generator_attempts != 2:
            raise RuntimeError("Fallback requires RAG_MAX_GENERATOR_ATTEMPTS=2.")
        self.rag_max_output_tokens = int(os.getenv("RAG_MAX_OUTPUT_TOKENS", "900"))

    @property
    def secure_cookies(self) -> bool:
        return self.public_base_url.startswith("https://")


settings = Settings()
