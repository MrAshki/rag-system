"""Independent TREC metric adapter used to audit the local IR implementation."""
from __future__ import annotations

from statistics import fmean
from typing import Mapping, Sequence


def _scored_run(retrieved: Sequence[str]) -> dict[str, float]:
    # pytrec_eval consumes scores, not ordered lists. Strictly descending
    # synthetic scores preserve the supplied ranking without provider data.
    size = len(retrieved)
    return {
        str(document_id): float(size - rank)
        for rank, document_id in enumerate(dict.fromkeys(retrieved))
    }


def evaluate_with_pytrec(
    qrels: Mapping[str, Mapping[str, int | float]],
    run: Mapping[str, Sequence[str]],
    *,
    ks: Sequence[int] = (1, 5, 10),
) -> dict:
    """Return standard TREC metrics with names matching the local evaluator."""
    try:
        import pytrec_eval
    except ImportError as exc:  # pragma: no cover - explicit dependency error
        raise RuntimeError(
            "Install requirements-eval.txt to run the independent IR audit"
        ) from exc

    metric_names = {"map", "recip_rank"}
    for k in ks:
        metric_names.update({f"recall_{k}", f"P_{k}", f"success_{k}", f"ndcg_cut_{k}"})
    evaluator = pytrec_eval.RelevanceEvaluator(
        {
            str(query_id): {
                str(document_id): int(grade)
                for document_id, grade in judgments.items()
            }
            for query_id, judgments in qrels.items()
        },
        metric_names,
    )
    raw = evaluator.evaluate(
        {
            str(query_id): _scored_run(run.get(query_id, ()))
            for query_id in qrels
        }
    )
    per_task: dict[str, dict[str, float]] = {}
    for query_id in qrels:
        scores = raw.get(str(query_id), {})
        normalized = {
            "mrr": float(scores.get("recip_rank", 0.0)),
            "ap": float(scores.get("map", 0.0)),
        }
        for k in ks:
            normalized.update({
                f"recall@{k}": float(scores.get(f"recall_{k}", 0.0)),
                f"precision@{k}": float(scores.get(f"P_{k}", 0.0)),
                f"hit_rate@{k}": float(scores.get(f"success_{k}", 0.0)),
                f"ndcg@{k}": float(scores.get(f"ndcg_cut_{k}", 0.0)),
            })
        per_task[str(query_id)] = normalized
    names = sorted({name for scores in per_task.values() for name in scores})
    return {
        "tool": "pytrec-eval-terrier",
        "version": getattr(pytrec_eval, "__version__", "0.5.10"),
        "query_count": len(per_task),
        "means": {
            name: fmean(scores[name] for scores in per_task.values())
            if per_task else 0.0
            for name in names
        },
        "per_task": per_task,
    }


def parity_differences(local: dict, standard: dict, tolerance: float = 1e-12) -> list[dict]:
    differences = []
    for query_id, local_scores in local.get("per_task", {}).items():
        standard_scores = standard.get("per_task", {}).get(query_id, {})
        for name, local_value in local_scores.items():
            if name not in standard_scores:
                continue
            delta = abs(float(local_value) - float(standard_scores[name]))
            if delta > tolerance:
                differences.append({
                    "query_id": query_id,
                    "metric": name,
                    "local": float(local_value),
                    "standard": float(standard_scores[name]),
                    "absolute_difference": delta,
                })
    return differences
