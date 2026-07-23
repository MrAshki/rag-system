from evaluation.metrics.grounded_task_success import (
    REQUIRED_GTS_CONDITIONS,
    aggregate_grounded_task_success,
    grounded_task_success,
)


def test_grounded_task_success_is_strict_conjunction():
    record = {name: True for name in REQUIRED_GTS_CONDITIONS}
    assert grounded_task_success(record) == 1
    for condition in REQUIRED_GTS_CONDITIONS:
        failed = dict(record)
        failed[condition] = False
        assert grounded_task_success(failed) == 0
    missing = dict(record)
    missing.pop("grounded")
    assert grounded_task_success(missing) == 0


def test_grounded_task_success_reports_route_slices():
    passed = {name: True for name in REQUIRED_GTS_CONDITIONS} | {"expected_route": "focused_rag"}
    failed = dict(passed, answer_correct=False)
    result = aggregate_grounded_task_success([passed, failed])
    assert result["overall"]["numerator"] == 1
    assert result["overall"]["denominator"] == 2
    assert result["per_route"]["focused_rag"]["percentage"] == 50
