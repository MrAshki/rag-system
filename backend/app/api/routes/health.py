from fastapi import APIRouter, Depends

import rag
from backend.app.core.config import settings
from backend.app.dependencies import require_login

router = APIRouter()


@router.get("/api/health")
def health():
    return {
        "status": "ok",
        "embedding_model": rag.EMBEDDING_MODEL,
        "retrieval_mode": rag.RETRIEVAL_MODE,
        "cross_language_rewrite_enabled": rag.CROSS_LANGUAGE_REWRITE_ENABLED,
        "primary_generator": rag.PRIMARY_GENERATOR_MODEL,
        "fallback_generator": rag.FALLBACK_GENERATOR_MODEL,
        "fallback_enabled": rag.GENERATOR_FALLBACK_ENABLED,
        "vector_backend": settings.vector_backend,
        "qdrant_collection": settings.qdrant_collection if settings.vector_backend == "qdrant" else None,
        "indexed_chunks": rag.indexed_chunk_count(),
    }


@router.get("/api/chat/models")
def chat_models(_user=Depends(require_login)):
    return {"models": rag.chat_model_options()}


@router.get("/")
def root():
    from backend.app.core.config import settings

    return {
        "status": "api_only",
        "message": "FastAPI is the API server. Use the Next.js frontend.",
        "frontend": settings.frontend_url,
    }
