from evaluation.runners.evaluate_judge_calibration import (
    LABELS,
    classification_stats,
    cohens_kappa,
    load_cases,
)
from pathlib import Path


def test_calibration_set_has_required_human_labels_and_adversarial_coverage():
    path = Path(__file__).resolve().parents[2] / "evaluation" / "judge_calibration" / "cases.jsonl"
    cases = load_cases(path)
    assert len(cases) >= 12
    assert all(set(case["human_labels"]) == set(LABELS) for case in cases)
    assert any(not case["human_labels"]["answer_correctness"] for case in cases)
    assert any(not case["human_labels"]["citation_support"] for case in cases)
    assert any(not case["human_labels"]["refusal_correctness"] for case in cases)
    assert any(case["query"].isascii() for case in cases)
    assert any(not case["query"].isascii() for case in cases)


def test_classification_statistics_and_kappa_are_reproducible():
    expected = [True, True, False, False]
    predicted = [True, False, True, False]
    assert classification_stats(expected, predicted) == {
        "accuracy": 0.5,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
        "confusion_matrix": {"tp": 1, "tn": 1, "fp": 1, "fn": 1},
    }
    assert cohens_kappa(expected, predicted) == 0.0
