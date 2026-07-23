from evaluation.metrics.proportions import proportion_result
from evaluation.runners.generate_report import render_report


def test_report_generation_is_deterministic():
    prop = proportion_result(1, 2)
    production = {
        "endpoint": "http://127.0.0.1:5000/api/ask/stream",
        "endpoint_request_count": 1,
        "core_subset": ["q1"],
        "retrieval": {"means": {"recall@1": 1, "recall@5": 1, "recall@10": 1, "precision@5": 0.2, "hit_rate@5": 1, "mrr": 1, "ap": 1, "ndcg@10": 1}},
        "routing": {"route_selection_accuracy": prop},
        "generation": {"acceptable_answer_match": prop, "required_concept_coverage_mean": 0.5},
        "summary": {
            "task_count": 0,
            "substantive_section_coverage_mean": 0,
            "key_claim_recall_mean": 0,
            "conclusion_coverage": proportion_result(0, 0),
            "contamination_rate_mean": 0,
            "page_range_diversity_mean": 0,
            "comprehensive_summary_pass": proportion_result(0, 0),
        },
        "citations": {"citation_validity": prop},
        "conversations": {"history_use_accuracy": prop},
        "grounded_task_success": {"per_route": {"focused_rag": prop}, "overall": prop},
        "latency_ms": {"p50": 10, "p95": 20},
        "usage": {"provider_request_count": 1, "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001},
        "hard_cap_respected": True,
        "results": [],
    }
    data = {
        "goldset": {"documents": 20, "pages": 223, "tasks": 65, "conversations": 10, "conversation_turns": 25, "categories": {"local_factual": 18}},
        "production": production,
        "isolated_retrieval": {"query_count": 1, "means": production["retrieval"]["means"] | {"expected_page_recall": 1, "expected_document_recall": 1, "evidence_set_recall": 1}},
        "validation": {},
    }
    first = render_report(data)
    second = render_report(data)
    assert first == second
    assert "Development Set" in first
    assert "Wilson 95%" in first
