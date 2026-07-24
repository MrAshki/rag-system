import os
import threading
import time
from math import sqrt

import requests

from backend.app.core.config import settings
from backend.app.services.usage_tracking import record_compute_usage_event

_model = None
_model_lock = threading.Lock()
OPENROUTER_EMBED_BATCH_SIZE = max(1, int(os.getenv("OPENROUTER_EMBED_BATCH_SIZE", "64")))
OPENROUTER_EMBED_RETRY_ATTEMPTS = max(1, int(os.getenv("OPENROUTER_EMBED_RETRY_ATTEMPTS", "5")))


def embedding_device() -> str:
    if settings.embedding_provider != "local":
        return "api"
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def get_embedding_model():
    global _model
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(settings.embedding_model_path, device=embedding_device())
    return _model


def _normalize(vector: list[float]) -> list[float]:
    norm = sqrt(sum(float(v) * float(v) for v in vector))
    if not norm:
        return [float(v) for v in vector]
    return [float(v) / norm for v in vector]


def _openrouter_headers() -> dict[str, str]:
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set. Add it to .env before using OpenRouter embeddings.")
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if settings.openrouter_site_url:
        headers["HTTP-Referer"] = settings.openrouter_site_url
    if settings.openrouter_app_name:
        headers["X-Title"] = settings.openrouter_app_name
    return headers


def _raise_openrouter_error(response: requests.Response) -> None:
    if response.ok:
        return
    detail = ""
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "")
        elif error:
            detail = str(error)
    except ValueError:
        detail = (response.text or "").strip()
    suffix = f": {detail[:300]}" if detail else ""
    raise RuntimeError(f"OpenRouter embedding request failed ({response.status_code}){suffix}")


def _embed_texts_openrouter(texts: list[str], input_type: str) -> list[list[float]]:
    if not texts:
        return []
    start = time.perf_counter()
    input_chars = sum(len(text or "") for text in texts)
    payload = {
        "model": settings.embedding_model,
        "input": texts,
        "input_type": input_type,
        "encoding_format": "float",
    }
    try:
        response = None
        for attempt in range(OPENROUTER_EMBED_RETRY_ATTEMPTS):
            try:
                response = requests.post(
                    f"{settings.openrouter_base_url}/embeddings",
                    headers=_openrouter_headers(),
                    json=payload,
                    timeout=(10, 180),
                )
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if attempt == OPENROUTER_EMBED_RETRY_ATTEMPTS - 1:
                        _raise_openrouter_error(response)
                    try:
                        delay = float(retry_after) if retry_after else 1.5 * (attempt + 1)
                    except ValueError:
                        delay = 1.5 * (attempt + 1)
                    time.sleep(min(max(delay, 0.5), 15.0))
                    continue
                if response.status_code not in {500, 502, 503, 504}:
                    _raise_openrouter_error(response)
                    break
            except (requests.ConnectionError, requests.Timeout):
                if attempt == OPENROUTER_EMBED_RETRY_ATTEMPTS - 1:
                    raise
            if attempt == OPENROUTER_EMBED_RETRY_ATTEMPTS - 1:
                _raise_openrouter_error(response)
            time.sleep(0.5 * (attempt + 1))
        if response is None:
            raise RuntimeError("OpenRouter embedding request returned no response.")
        data = response.json()
        if data.get("error"):
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(f"OpenRouter embedding API error: {message}")
        items = sorted(data.get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [_normalize(item.get("embedding") or []) for item in items]
        if len(vectors) != len(texts):
            raise RuntimeError(f"OpenRouter returned {len(vectors)} embeddings for {len(texts)} inputs.")
        latency_ms = round((time.perf_counter() - start) * 1000)
        record_compute_usage_event(
            operation_type="embedding",
            provider="openrouter",
            model=settings.embedding_model,
            device="api",
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
        return vectors
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000)
        record_compute_usage_event(
            operation_type="embedding",
            provider="openrouter",
            model=settings.embedding_model,
            device="api",
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


def _embed_texts_local(texts: list[str]) -> list[list[float]]:
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


def embed_texts(texts: list[str], input_type: str = "passage") -> list[list[float]]:
    if settings.embedding_provider == "openrouter":
        vectors: list[list[float]] = []
        for start in range(0, len(texts), OPENROUTER_EMBED_BATCH_SIZE):
            vectors.extend(
                _embed_texts_openrouter(
                    texts[start:start + OPENROUTER_EMBED_BATCH_SIZE],
                    input_type=input_type,
                )
            )
        return vectors
    if settings.embedding_provider != "local":
        raise RuntimeError(f"Unsupported EMBEDDING_PROVIDER={settings.embedding_provider!r}. Use 'local' or 'openrouter'.")
    return _embed_texts_local(texts)


def embed_text(text: str) -> list[float]:
    return embed_texts([text], input_type="query")[0]
