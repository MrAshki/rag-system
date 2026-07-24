from evaluation.runners import evaluate_goal3_expanded as expanded


def test_goal3_expanded_subset_has_required_coverage() -> None:
    expanded._assert_selection()
    cases = expanded._cases()
    coverage = expanded._coverage(cases)

    assert 25 <= len(cases) <= 30
    assert coverage["documents"] >= 8
    assert coverage["local_factual"] >= 6
    assert coverage["table_or_numerical"] >= 4
    assert coverage["summary_or_analytical"] >= 4
    assert coverage["cross_language"] >= 3
    assert coverage["no_answer_or_conflict"] >= 3
    assert coverage["conversation_turns"] >= 4
    assert coverage["quoted_document_explanation"] >= 2


def test_goal3_expanded_subset_preserves_gold_task_expectations() -> None:
    source = expanded.baseline._load_tasks()
    selected = expanded._selection()["single_task_ids"]
    cases = {case["query_id"]: case for case in expanded._cases()}

    for query_id in selected:
        assert cases[query_id] == source[query_id]


def test_goal3_expanded_conversation_turns_follow_gold_annotations() -> None:
    conversations = {
        row["conversation_id"]: row
        for row in expanded._load_jsonl(
            expanded.ROOT / "evaluation" / "dev_goldset" / "conversations.jsonl"
        )
    }
    cases = {case["query_id"]: case for case in expanded._cases()}

    for spec in expanded._selection()["conversation_turns"]:
        conversation = conversations[spec["conversation_id"]]
        turn = next(
            item for item in conversation["turns"]
            if item["turn_id"] == spec["turn_id"]
        )
        case = cases[f"{spec['conversation_id']}:{spec['turn_id']}"]
        assert case["query"] == turn["query"]
        assert case["expected_route"] == turn["expected_route"]
        assert case["retrieval_policy"] == turn["retrieval_policy"]
        assert case["acceptable_answers"] == [
            turn["acceptable_response_behavior"]
        ]
