from __future__ import annotations

from evaluation.runners.evaluate_production_retrieval import (
    _page_run,
    _stage_metrics,
    tuning_cases,
)


def test_chunk_results_are_projected_to_unique_physical_page_qrel_units():
    sha = "a" * 64
    rows = [
        {"page": 4, "parent_page_start": 4, "parent_page_end": 8},
        {"page": 4, "parent_page_start": 4, "parent_page_end": 8},
        {"page": 7, "parent_page_start": 4, "parent_page_end": 8},
    ]
    assert _page_run(sha, rows) == [f"{sha}#page=4", f"{sha}#page=7"]


def test_parent_range_never_replaces_matched_child_page():
    sha = "b" * 64
    rows = [{"page": 6, "parent_page_start": 3, "parent_page_end": 9}]
    assert _page_run(sha, rows) == [f"{sha}#page=6"]


def test_per_stage_metrics_keep_denominators_stage_specific():
    sha = "c" * 64
    evidence = f"{sha}#page=2"
    qrels = {"q1": {evidence: 2}, "q2": {f"{sha}#page=3": 1}}
    results = [
        {
            "query_id": "q1",
            "page_rankings": {
                "production_dense": [evidence],
                "production_r2_final": [evidence],
            },
        },
        {
            "query_id": "q2",
            "page_rankings": {"production_dense": [f"{sha}#page=1"]},
        },
    ]
    metrics = _stage_metrics(results, qrels)
    assert metrics["production_dense"]["query_count"] == 2
    assert metrics["production_r2_final"]["query_count"] == 1
    assert metrics["production_r2_final"]["means"]["recall@5"] == 1.0


def test_history_aware_case_carries_real_previous_user_query():
    case = next(
        row
        for row in tuning_cases()
        if row["query_id"] == "conv-d1366-history-and-evidence:t2"
    )
    assert case["previous_user_query"] == "نتیجه غربالگری مرحله دوم چه بود؟"
