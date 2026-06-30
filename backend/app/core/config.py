import os
from dataclasses import dataclass

from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy.engine import URL

load_dotenv(override=True)

MAX_UPLOAD_MB = 25


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
        self.vector_backend = os.getenv("VECTOR_BACKEND", "pgvector").strip().lower()
        self.embedding_model_path = os.getenv("EMBEDDING_MODEL_PATH") or os.getenv("EMBEDDING_MODEL", "./models/bge-m3")
        self.embedding_dim = int(os.getenv("EMBEDDING_DIM", "1024"))

    @property
    def secure_cookies(self) -> bool:
        return self.public_base_url.startswith("https://")


settings = Settings()
