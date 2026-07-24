from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_PYTHON = [
    ROOT / "rag.py",
    *sorted((ROOT / "backend").rglob("*.py")),
    *sorted((ROOT / "document_pipeline").rglob("*.py")),
]
FORBIDDEN_LITERAL_PATTERNS = {
    "gold query/task id": re.compile(
        r"\b(?:d\d{3,5}-(?:fact|num|cross|page|summary|analysis|quote|noanswer|table)"
        r"|fx00[1-5]-(?:fact|cross|page|quote|conflict|noanswer|ambiguous))[\w:-]*\b",
        re.IGNORECASE,
    ),
    "gold source filename": re.compile(
        r"\b(?:doh-\d{2}-\d+|fixture-00[1-5][-\w]*)\.pdf\b",
        re.IGNORECASE,
    ),
    "known source hash": re.compile(
        r"\bfe90e8354efdd2333840c25d7b0210a89bd550cf736ba83f54d747ee30b3375e\b",
        re.IGNORECASE,
    ),
}


def _production_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in PRODUCTION_PYTHON)


def test_production_has_no_gold_query_id_filename_or_hash_literals():
    text = _production_text()
    matches = {
        name: sorted(set(pattern.findall(text)))
        for name, pattern in FORBIDDEN_LITERAL_PATTERNS.items()
        if pattern.search(text)
    }
    assert not matches, matches


def test_production_does_not_import_evaluation_modules():
    violations = []
    for path in PRODUCTION_PYTHON:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (
                node.module == "evaluation"
                or str(node.module or "").startswith("evaluation.")
            ):
                violations.append((str(path.relative_to(ROOT)), node.lineno))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "evaluation" or alias.name.startswith("evaluation."):
                        violations.append((str(path.relative_to(ROOT)), node.lineno))
    assert not violations, violations


def test_production_does_not_read_goldset_annotations_or_expected_answers():
    text = _production_text().lower()
    forbidden = (
        "evaluation/dev_goldset",
        "evaluation\\dev_goldset",
        "tasks.jsonl",
        "qrels.json",
        "expected_answer",
        "acceptable_answers",
        "expected_pages",
    )
    assert not {value for value in forbidden if value in text}
