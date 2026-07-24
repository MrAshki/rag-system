import math

from evaluation.metrics.retrieval import evaluate_rankings
from evaluation.metrics.standard_ir import evaluate_with_pytrec, parity_differences


def test_pytrec_parity_on_manually_verified_toy_ranking():
    qrels = {"q": {"a": 3, "b": 2, "c": 1}}
    run = {"q": ["x", "a", "c", "y", "b"]}
    local = evaluate_rankings(qrels, run, ks=(1, 5))
    standard = evaluate_with_pytrec(qrels, run, ks=(1, 5))

    assert local["per_task"]["q"]["recall@5"] == 1.0
    assert local["per_task"]["q"]["precision@5"] == 3 / 5
    assert local["per_task"]["q"]["hit_rate@5"] == 1.0
    assert local["per_task"]["q"]["mrr"] == 1 / 2
    assert math.isclose(
        local["per_task"]["q"]["ap"],
        ((1 / 2) + (2 / 3) + (3 / 5)) / 3,
    )
    assert parity_differences(local, standard) == []


def test_pytrec_parity_is_per_query_and_reproducible():
    qrels = {"q1": {"a": 1}, "q2": {"b": 1, "c": 1}}
    run = {"q1": ["a"], "q2": ["x", "c", "b"]}
    first = evaluate_with_pytrec(qrels, run, ks=(1, 5, 10))
    second = evaluate_with_pytrec(qrels, run, ks=(1, 5, 10))
    local = evaluate_rankings(qrels, run)

    assert first == second
    assert set(first["per_task"]) == {"q1", "q2"}
    assert parity_differences(local, first) == []
