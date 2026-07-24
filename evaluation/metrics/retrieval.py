from __future__ import annotations

import math
from statistics import fmean
from typing import Hashable, Iterable, Mapping, Sequence


def _relevant(qrels: Mapping[Hashable, int | float]) -> set[Hashable]:
    return {item for item, grade in qrels.items() if grade > 0}


def recall_at_k(retrieved: Sequence[Hashable], qrels: Mapping[Hashable, int | float], k: int) -> float:
    relevant = _relevant(qrels)
    return len(relevant.intersection(retrieved[:k])) / len(relevant) if relevant else 0.0


def precision_at_k(retrieved: Sequence[Hashable], qrels: Mapping[Hashable, int | float], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    relevant = _relevant(qrels)
    return sum(item in relevant for item in retrieved[:k]) / k


def hit_rate_at_k(retrieved: Sequence[Hashable], qrels: Mapping[Hashable, int | float], k: int) -> float:
    relevant = _relevant(qrels)
    return float(any(item in relevant for item in retrieved[:k]))


def reciprocal_rank(retrieved: Sequence[Hashable], qrels: Mapping[Hashable, int | float]) -> float:
    relevant = _relevant(qrels)
    return next((1 / rank for rank, item in enumerate(retrieved, start=1) if item in relevant), 0.0)


def average_precision(retrieved: Sequence[Hashable], qrels: Mapping[Hashable, int | float]) -> float:
    relevant = _relevant(qrels)
    if not relevant:
        return 0.0
    hits = 0
    total = 0.0
    seen: set[Hashable] = set()
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant and item not in seen:
            seen.add(item)
            hits += 1
            total += hits / rank
    return total / len(relevant)


def ndcg_at_k(retrieved: Sequence[Hashable], qrels: Mapping[Hashable, int | float], k: int) -> float:
    def gain(grade: float, rank: int) -> float:
        # TREC's ndcg_cut uses the judgment grade as the gain. Keeping the
        # local implementation identical makes independent parity meaningful.
        return grade / math.log2(rank + 1)

    actual = sum(gain(float(qrels.get(item, 0)), rank) for rank, item in enumerate(retrieved[:k], start=1))
    ideal_grades = sorted((float(value) for value in qrels.values() if value > 0), reverse=True)[:k]
    ideal = sum(gain(grade, rank) for rank, grade in enumerate(ideal_grades, start=1))
    return actual / ideal if ideal else 0.0


def expected_page_recall(expected_pages: Iterable[int], retrieved: Sequence[Mapping]) -> float:
    expected = set(expected_pages)
    found = {int(item["page"]) for item in retrieved if item.get("page") is not None}
    return len(expected & found) / len(expected) if expected else 0.0


def expected_document_recall(expected_documents: Iterable[str], retrieved: Sequence[Mapping]) -> float:
    expected = set(expected_documents)
    found = {str(item["document_sha256"]) for item in retrieved if item.get("document_sha256")}
    return len(expected & found) / len(expected) if expected else 0.0


def evidence_set_recall(expected_evidence: Iterable[str], retrieved: Sequence[Mapping]) -> float:
    expected = set(expected_evidence)
    found = {str(item["evidence_id"]) for item in retrieved if item.get("evidence_id")}
    return len(expected & found) / len(expected) if expected else 0.0


def evaluate_rankings(qrels: Mapping[str, Mapping[str, int]], run: Mapping[str, Sequence[str]], ks=(1, 5, 10)) -> dict:
    per_task: dict[str, dict] = {}
    for query_id, judgments in qrels.items():
        retrieved = list(run.get(query_id, []))
        scores = {
            "mrr": reciprocal_rank(retrieved, judgments),
            "ap": average_precision(retrieved, judgments),
        }
        for k in ks:
            scores.update({
                f"recall@{k}": recall_at_k(retrieved, judgments, k),
                f"precision@{k}": precision_at_k(retrieved, judgments, k),
                f"hit_rate@{k}": hit_rate_at_k(retrieved, judgments, k),
                f"ndcg@{k}": ndcg_at_k(retrieved, judgments, k),
            })
        per_task[query_id] = scores
    metric_names = sorted({name for item in per_task.values() for name in item})
    return {
        "query_count": len(per_task),
        "means": {
            name: fmean(item[name] for item in per_task.values()) if per_task else 0.0
            for name in metric_names
        },
        "per_task": per_task,
    }
