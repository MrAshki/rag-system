from evaluation.metrics.conversations import evaluate_conversations


def test_conversation_metrics_measure_forbidden_retrieval_and_persistence():
    result = evaluate_conversations([
        {
            "followup_resolved": True,
            "history_used_correctly": True,
            "retrieval_policy": "forbidden",
            "retrieval_called": False,
            "selected_asset_persisted": True,
            "conversation_id_persisted": True,
        },
        {
            "followup_resolved": False,
            "history_used_correctly": False,
            "retrieval_policy": "forbidden",
            "retrieval_called": True,
            "selected_asset_persisted": True,
            "conversation_id_persisted": True,
        },
    ])
    assert result["followup_resolution_accuracy"]["percentage"] == 50
    assert result["unnecessary_retrieval_rate"]["percentage"] == 50
    assert result["selected_asset_persistence"]["percentage"] == 100
