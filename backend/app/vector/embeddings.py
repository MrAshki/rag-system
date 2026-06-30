import os
import threading
import time

import torch
from sentence_transformers import SentenceTransformer

from backend.app.core.config import settings
from backend.app.services.usage_tracking import record_compute_usage_event

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

_model = None
_model_lock = threading.Lock()


def embedding_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def get_embedding_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer(settings.embedding_model_path, device=embedding_device())
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    start = time.perf_counter()
    device = embedding_device()
    input_chars = sum(len(text or "") for text in texts)
    model = get_embedding_model()
    try:
        with _model_lock:
            vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        latency_ms = round((time.perf_counter() - start) * 1000)
        record_compute_usage_event(
            operation_type="embedding",
            provider="local_cpu" if device == "cpu" else "local_gpu",
            model=settings.embedding_model_path,
            device=device,
            latency_ms=latency_ms,
            input_count=len(texts),
            input_chars=input_chars,
            batch_size=len(texts),
            status="success",
            metadata={
                "text_count": len(texts),
                "embedding_dim": settings.embedding_dim,
            },
        )
        return vectors.astype("float32").tolist()
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000)
        record_compute_usage_event(
            operation_type="embedding",
            provider="local_cpu" if device == "cpu" else "local_gpu",
            model=settings.embedding_model_path,
            device=device,
            latency_ms=latency_ms,
            input_count=len(texts),
            input_chars=input_chars,
            batch_size=len(texts),
            status="error",
            error_type=exc.__class__.__name__,
            metadata={
                "text_count": len(texts),
                "embedding_dim": settings.embedding_dim,
            },
        )
        raise


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
