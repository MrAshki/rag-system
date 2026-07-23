from evaluation.metrics.routing import evaluate_routing


def test_routing_and_retrieval_necessity_metrics():
    records = [
        {
            "expected_intent": "exact_answer", "actual_intent": "exact_answer",
            "expected_route": "focused_rag", "actual_route": "focused_rag",
            "retrieval_policy": "required", "retrieval_called": True,
            "rewrite_expected": False, "rewrite_correct": True,
            "reranker_expected": True, "reranker_called": True,
        },
        {
            "expected_intent": "conversational_followup", "actual_intent": "exact_answer",
            "expected_route": "conversational_followup", "actual_route": "focused_rag",
            "retrieval_policy": "forbidden", "retrieval_called": True,
            "rewrite_expected": False, "rewrite_correct": True,
            "reranker_expected": False, "reranker_called": True,
        },
    ]
    result = evaluate_routing(records)
    assert result["route_selection_accuracy"]["numerator"] == 1
    assert result["route_selection_accuracy"]["denominator"] == 2
    assert result["unnecessary_retrieval_rate"]["percentage"] == 100
    assert result["missing_retrieval_rate"]["percentage"] == 0
    assert result["reranker_call_correctness"]["numerator"] == 1
