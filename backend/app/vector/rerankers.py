import os
import time
from typing import Any

import requests

from backend.app.core.config import settings
from backend.app.services.usage_tracking import estimate_tokens_from_text, record_compute_usage_event


def reranker_provider() -> str:
    return os.getenv("RERANKER_PROVIDER", "local").strip().lower()


def openrouter_rerank(query: str, chunks: list[dict[str, Any]], model: str, top_k: int) -> list[dict[str, Any]]:
    if not chunks:
        return []
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set. Add it to .env before using OpenRouter reranking.")

    start = time.perf_counter()
    documents = [chunk.get("text") or "" for chunk in chunks]
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if settings.openrouter_site_url:
        headers["HTTP-Referer"] = settings.openrouter_site_url
    if settings.openrouter_app_name:
        headers["X-Title"] = settings.openrouter_app_name

    input_chars = len(query or "") * len(chunks) + sum(len(doc) for doc in documents)
    input_tokens = estimate_tokens_from_text(query) * len(chunks) + sum(estimate_tokens_from_text(doc) for doc in documents)
    try:
        response = requests.post(
            f"{settings.openrouter_base_url}/rerank",
            headers=headers,
            json={
                "model": model,
                "query": query,
                "documents": documents,
                "top_n": int(top_k),
            },
            timeout=(10, 180),
        )
        response.raise_for_status()
        data = response.json()
        ranked = []
        for item in data.get("results") or []:
            index = item.get("index")
            if index is None or index < 0 or index >= len(chunks):
                continue
            chunk = dict(chunks[index])
            score = item.get("relevance_score", item.get("score"))
            if score is not None:
                chunk["rerank_score"] = float(score)
            ranked.append(chunk)

        record_compute_usage_event(
            operation_type="reranking",
            provider="openrouter",
            model=model,
            device="api",
            latency_ms=round((time.perf_counter() - start) * 1000),
            input_count=len(chunks),
            input_chars=input_chars,
            chunk_count=len(chunks),
            pair_count=len(chunks),
            query_count=1,
            batch_size=len(chunks),
            status="success",
            metadata={
                "estimated_input_tokens": input_tokens,
                "top_k": top_k,
                "returned": len(ranked),
            },
        )
        return ranked or chunks[:top_k]
    except Exception as exc:
        record_compute_usage_event(
            operation_type="reranking",
            provider="openrouter",
            model=model,
            device="api",
            latency_ms=round((time.perf_counter() - start) * 1000),
            input_count=len(chunks),
            input_chars=input_chars,
            chunk_count=len(chunks),
            pair_count=len(chunks),
            query_count=1,
            batch_size=len(chunks),
            status="error",
            error_type=exc.__class__.__name__,
            metadata={
                "estimated_input_tokens": input_tokens,
                "top_k": top_k,
            },
        )
        raise
