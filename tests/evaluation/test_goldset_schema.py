from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from evaluation.runners.evaluate_ingestion import GoldSetValidationError, load_jsonl, validate_goldset


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "evaluation" / "dev_goldset"
PDFS = ROOT / "composite_goldset_pdfs"


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "goldset"
    shutil.copytree(SOURCE, target)
    return target


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_real_goldset_validates_and_has_required_size():
    result = validate_goldset(SOURCE, PDFS)
    assert result == {
        "documents": 20,
        "pages": 223,
        "tasks": 65,
        "conversations": 10,
        "conversation_turns": 25,
        "source_hashes_verified": True,
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate", "duplicate query IDs"),
        ("missing_hash", "missing or mismatched document hash"),
        ("invalid_page", "invalid page"),
        ("invalid_route", "invalid route"),
        ("contradictory", "answerable task has no evidence page"),
    ],
)
def test_invalid_task_annotations_are_rejected(tmp_path, mutation, message):
    base = _copy(tmp_path)
    tasks = load_jsonl(base / "tasks.jsonl")
    if mutation == "duplicate":
        tasks[1]["query_id"] = tasks[0]["query_id"]
    elif mutation == "missing_hash":
        tasks[0]["document_sha256"] = ""
    elif mutation == "invalid_page":
        tasks[0]["relevant_pages"] = [999]
        tasks[0]["evidence_descriptions"] = [{"page": 999, "description": "bad"}]
    elif mutation == "invalid_route":
        tasks[0]["expected_route"] = "magic_route"
    elif mutation == "contradictory":
        tasks[0]["relevant_pages"] = []
        tasks[0]["evidence_descriptions"] = []
    _write_jsonl(base / "tasks.jsonl", tasks)
    with pytest.raises(GoldSetValidationError, match=message):
        validate_goldset(base, PDFS, verify_source_hashes=False)


def test_malformed_conversation_ordering_is_rejected(tmp_path):
    base = _copy(tmp_path)
    conversations = load_jsonl(base / "conversations.jsonl")
    conversations[0]["turns"][1]["turn_id"] = "t9"
    _write_jsonl(base / "conversations.jsonl", conversations)
    with pytest.raises(GoldSetValidationError, match="malformed turn ordering"):
        validate_goldset(base, PDFS, verify_source_hashes=False)
