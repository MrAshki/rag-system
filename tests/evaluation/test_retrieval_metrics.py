import math

from evaluation.metrics.retrieval import (
    average_precision,
    evaluate_rankings,
    hit_rate_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_known_ranking_metrics():
    qrels = {"a": 3, "b": 2, "c": 1}
    run = ["x", "a", "c", "y", "b"]
    assert recall_at_k(run, qrels, 1) == 0
    assert recall_at_k(run, qrels, 5) == 1
    assert precision_at_k(run, qrels, 5) == 3 / 5
    assert hit_rate_at_k(run, qrels, 2) == 1
    assert reciprocal_rank(run, qrels) == 1 / 2
    assert average_precision(run, qrels) == ((1 / 2) + (2 / 3) + (3 / 5)) / 3
    assert 0 < ndcg_at_k(run, qrels, 5) < 1


def test_evaluate_rankings_reports_per_task_and_mean():
    result = evaluate_rankings(
        {"q1": {"a": 1}, "q2": {"b": 1}},
        {"q1": ["a"], "q2": ["x", "b"]},
        ks=(1, 5),
    )
    assert result["query_count"] == 2
    assert result["means"]["mrr"] == 0.75
    assert set(result["per_task"]) == {"q1", "q2"}
    assert math.isclose(result["means"]["recall@5"], 1.0)
