from fastapi import APIRouter, Depends

import rag
from backend.app.dependencies import require_login

router = APIRouter()


@router.get("/api/health")
def health():
    return {
        "status": "ok",
        "answer_prompt_version": rag.ANSWER_PROMPT_VERSION,
        "chat_provider": rag.CHAT_PROVIDER.name,
        "chat_model": rag.CHAT_PROVIDER.model,
        "ollama_model": rag.OLLAMA_MODEL,
        "ollama_num_ctx": rag.OLLAMA_NUM_CTX,
        "embedding_model": rag.EMBEDDING_MODEL,
        "reranker_enabled": rag.ENABLE_RERANKER,
        "reranker_model": rag.RERANKER_MODEL,
        "retrieve_k": rag.RETRIEVE_K,
        "rerank_top_k": rag.RERANK_TOP_K,
        "vector_backend": "pgvector",
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
