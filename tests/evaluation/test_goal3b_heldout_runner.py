from evaluation.runners.evaluate_goal3b_heldout import cases


def test_heldout_runner_uses_exact_preregistered_order():
    rows = cases()
    assert len(rows) == 12
    assert rows[-1]["query_id"] == "conv-d14148-quoted:t2"
    assert rows[-1]["must_use_history"]
    assert len({row["filename"] for row in rows}) >= 8
