"""Bounded cross-language R2 retrieval for the production request path."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from model_gateway.base import ChatProvider


PERSIAN_RE = re.compile(r"[\u0600-\u06ff]")
MAX_REWRITE_TOKENS = 160
REWRITE_SYSTEM_PROMPT = """You rewrite one search query for cross-language document retrieval.
Return JSON only: {"rewritten_query": "..."}.
Translate or reformulate the query into the requested document language.
Generate exactly one query. Preserve names, numbers, quoted phrases, technical
terms, and negation. Do not answer the question, add facts, explain, or emit
multiple alternatives. Keep the query concise and retrieval-focused."""


@dataclass(frozen=True)
class RewriteResult:
    used: bool
    original_query: str
    rewritten_query: str | None
    status: str
    latency_ms: int = 0
    error_category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "used": self.used,
            "original_query": self.original_query,
            "rewritten_query": self.rewritten_query,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "error_category": self.error_category,
        }


@dataclass(frozen=True)
class R2Result:
    chunks: list[dict[str, Any]]
    rewrite: RewriteResult
    search_count: int
    reranker_count: int

    @property
    def telemetry(self) -> dict[str, Any]:
        return {
            "retrieval_mode": "r2",
            "rewrite_used": self.rewrite.used and self.rewrite.status == "success",
            "rewrite_status": self.rewrite.status,
            "search_count": self.search_count,
            "reranker_count": self.reranker_count,
        }


def text_language(text: str) -> str:
    return "fa" if PERSIAN_RE.search(text or "") else "en"


def has_language_mismatch(query: str, document_language: str | None) -> bool:
    return document_language in {"fa", "en"} and text_language(query) != document_language


def rewrite_query(
    query: str,
    document_language: str | None,
    provider: ChatProvider | None,
    *,
    enabled: bool = True,
) -> RewriteResult:
    original = (query or "").strip()
    if not enabled or not has_language_mismatch(original, document_language):
        return RewriteResult(False, original, None, "not_needed")
    if provider is None:
        return RewriteResult(True, original, original, "fallback", error_category="provider_missing")

    started = time.perf_counter()
    try:
        raw = provider.chat(
            messages=[
                {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Target document language: {document_language}\n"
                        f"Original query: {original}"
                    ),
                },
            ],
            options={
                "temperature": 0.0,
                "max_tokens": MAX_REWRITE_TOKENS,
                "reasoning": {"effort": "none", "exclude": True},
                "seed": 17,
            },
            response_format="json",
        )
        payload = json.loads(raw)
        rewritten = str(payload.get("rewritten_query") or "").strip()
        if not rewritten or rewritten == original:
            raise ValueError("rewrite_empty_or_unchanged")
        if text_language(rewritten) != document_language:
            raise ValueError("rewrite_language_mismatch")
        return RewriteResult(
            True,
            original,
            rewritten,
            "success",
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # A failed rewrite must not break retrieval.
        return RewriteResult(
            True,
            original,
            original,
            "fallback",
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_category=exc.__class__.__name__,
        )


def _chunk_key(chunk: dict[str, Any]) -> tuple[str, str]:
    return str(chunk.get("document_id") or ""), str(chunk.get("chunk") or "")


def fuse_candidate_lists(
    rankings: list[list[dict[str, Any]]],
    *,
    top_k: int,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    scores: dict[tuple[str, str], float] = {}
    chunks: dict[tuple[str, str], dict[str, Any]] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, 1):
            key = _chunk_key(chunk)
            chunks[key] = chunk
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
    ordered = sorted(scores, key=scores.get, reverse=True)[:top_k]
    output = []
    for key in ordered:
        chunk = dict(chunks[key])
        chunk["rewrite_fusion_score"] = scores[key]
        output.append(chunk)
    return output


def retrieve_r2(
    *,
    query: str,
    document_language: str | None,
    search: Callable[[str], list[dict[str, Any]]],
    rerank: Callable[[str, list[dict[str, Any]]], list[dict[str, Any]]],
    finalize: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    rewrite_provider: ChatProvider | None,
    candidate_k: int,
    cross_language_rewrite_enabled: bool = True,
    stage_recorder: Callable[[str, list[dict[str, Any]]], None] | None = None,
) -> R2Result:
    rewrite = rewrite_query(
        query,
        document_language,
        rewrite_provider,
        enabled=cross_language_rewrite_enabled,
    )
    original_candidates = search(query)
    rankings = [original_candidates]
    rerank_query = query
    if rewrite.status == "success" and rewrite.rewritten_query:
        rankings.append(search(rewrite.rewritten_query))
        rerank_query = f"{query}\n{rewrite.rewritten_query}"
    candidates = (
        fuse_candidate_lists(rankings, top_k=candidate_k)
        if len(rankings) > 1 else original_candidates
    )
    if stage_recorder:
        stage_recorder("production_fused_pre_rerank", candidates)
    reranked = rerank(rerank_query, candidates)
    if stage_recorder:
        stage_recorder("production_reranked", reranked)
    final_chunks = finalize(reranked)
    if stage_recorder:
        stage_recorder("production_r2_final", final_chunks)
    return R2Result(
        chunks=final_chunks,
        rewrite=rewrite,
        search_count=len(rankings),
        reranker_count=1 if candidates else 0,
    )
