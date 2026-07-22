"""Dense + deterministic lexical retrieval with reciprocal-rank fusion."""
from __future__ import annotations

import math
import re
from collections import Counter

from backend.app.vector.base import SearchResult, VectorStore


TOKEN_RE = re.compile(r"[0-9A-Za-z\u0600-\u06ff]{2,}")
CHAR_TRANS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه"})
RRF_K = 60


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall((text or "").translate(CHAR_TRANS))]


def lexical_rank(query: str, chunks: list[SearchResult], top_k: int) -> list[SearchResult]:
    query_terms = list(dict.fromkeys(tokenize(query)))
    if not query_terms or not chunks:
        return []
    documents = [tokenize(chunk.text) for chunk in chunks]
    document_frequency = Counter(term for tokens in documents for term in set(tokens) if term in query_terms)
    average_length = sum(len(tokens) for tokens in documents) / max(len(documents), 1)
    scored = []
    for chunk, tokens in zip(chunks, documents):
        frequencies = Counter(tokens)
        score = 0.0
        for term in query_terms:
            tf = frequencies.get(term, 0)
            if not tf:
                continue
            df = document_frequency.get(term, 0)
            idf = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
            denominator = tf + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / max(average_length, 1))
            score += idf * (tf * 2.5) / denominator
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _score, chunk in scored[:top_k]]


def _key(chunk: SearchResult) -> tuple[str, int]:
    return chunk.document_id, int(chunk.chunk)


def reciprocal_rank_fusion(
    dense: list[SearchResult],
    lexical: list[SearchResult],
    top_k: int,
) -> list[SearchResult]:
    scores: dict[tuple[str, int], float] = {}
    chunks: dict[tuple[str, int], SearchResult] = {}
    for ranking in (dense, lexical):
        for rank, chunk in enumerate(ranking, 1):
            key = _key(chunk)
            chunks[key] = chunk
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    ordered = sorted(scores, key=scores.get, reverse=True)[:top_k]
    return [
        SearchResult(
            text=chunks[key].text,
            source=chunks[key].source,
            chunk=chunks[key].chunk,
            document_id=chunks[key].document_id,
            score=scores[key],
            metadata={**(chunks[key].metadata or {}), "retrieval": "hybrid_rrf"},
        )
        for key in ordered
    ]


def hybrid_search(
    store: VectorStore,
    *,
    query: str,
    query_embedding: list[float],
    filters: dict | None,
    top_k: int,
    lexical_scan_limit: int,
) -> list[SearchResult]:
    dense = store.search(query_embedding, filters=filters, top_k=top_k)
    lexical_pool = store.list_chunks(filters=filters, limit=lexical_scan_limit)
    lexical = lexical_rank(query, lexical_pool, top_k=top_k)
    return reciprocal_rank_fusion(dense, lexical, top_k=top_k)
