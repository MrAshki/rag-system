from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GOLD_DIR = ROOT / "evaluation" / "dev_goldset"
EXPANDED_SELECTION = ROOT / "evaluation" / "goal3_expanded_subset.json"
DEFAULT_OUTPUT = ROOT / "tmp" / "rag-quality-goal" / "goal3b" / "heldout-selection.json"
DEFAULT_SEED = 20260723

CORE_SINGLE_IDS = {
    "d16381-summary",
    "d16381-table4",
    "d16381-fact-economic",
    "fx004-fact-leave",
    "fx003-fact-rollback",
    "fx005-fact-alpha",
    "d16395-num-method",
    "d16345-summary",
    "fx004-noanswer-overtime",
    "fx001-conflict",
    "fx003-cross-threshold",
    "fx004-cross",
}
CORE_CONVERSATION_IDS = {
    "conv-d381-summary-clarify:t2",
    "conv-fx005-ambiguous:t1",
    "conv-fx005-ambiguous:t2",
}
FINAL_UI_CONVERSATIONS = {
    "conv-d381-summary-clarify",
    "conv-fx005-ambiguous",
}
EXCLUDED_FILENAMES = {"doh-16-381.pdf", "einsteinetal1935.pdf"}
STRATUM_QUOTAS = {
    "factual": 3,
    "numeric": 2,
    "summary_analytical": 2,
    "cross_language": 1,
    "no_answer_conflict": 1,
    "quoted_explanation": 1,
    "page_specific": 1,
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _stable_score(seed: int, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def _stratum(task: dict[str, Any]) -> str:
    task_type = task["task_type"]
    if task_type == "local_factual":
        return "factual"
    if task_type == "table_or_numerical":
        return "numeric"
    if task_type in {"comprehensive_summary", "analytical"}:
        return "summary_analytical"
    if task_type == "cross_language":
        return "cross_language"
    if task_type == "no_answer_or_conflict":
        return "no_answer_conflict"
    if task_type == "quoted_document_explanation":
        return "quoted_explanation"
    if task_type == "page_specific":
        return "page_specific"
    raise ValueError(f"Unmapped task type: {task_type}")


def _is_fixture(filename: str) -> bool:
    return filename.startswith("fixture-")


def _select_stratified(
    candidates: list[dict[str, Any]], seed: int
) -> list[dict[str, Any]]:
    """Select seeded strata while preferring document diversity.

    Stable hash order supplies the seeded randomization. Within each stratum,
    a candidate from a new document is preferred; fixture tasks are admitted
    only while the global two-fixture cap permits them.
    """
    selected: list[dict[str, Any]] = []
    selected_documents: set[str] = set()
    fixture_count = 0
    for stratum, quota in STRATUM_QUOTAS.items():
        pool = sorted(
            (row for row in candidates if _stratum(row) == stratum),
            key=lambda row: _stable_score(seed, row["query_id"]),
        )
        for _ in range(quota):
            available = [
                row
                for row in pool
                if row not in selected
                and (not _is_fixture(row["filename"]) or fixture_count < 2)
            ]
            if not available:
                raise RuntimeError(f"Cannot satisfy held-out stratum {stratum}")
            available.sort(
                key=lambda row: (
                    row["filename"] in selected_documents,
                    _is_fixture(row["filename"]),
                    _stable_score(seed, row["query_id"]),
                )
            )
            chosen = available[0]
            selected.append(chosen)
            selected_documents.add(chosen["filename"])
            fixture_count += int(_is_fixture(chosen["filename"]))
    return selected


def build_selection(seed: int = DEFAULT_SEED) -> dict[str, Any]:
    tasks = _load_jsonl(GOLD_DIR / "tasks.jsonl")
    conversations = _load_jsonl(GOLD_DIR / "conversations.jsonl")
    expanded = json.loads(EXPANDED_SELECTION.read_text(encoding="utf-8"))
    expanded_ids = set(expanded["single_task_ids"])
    expanded_conversation_ids = {
        f"{row['conversation_id']}:{row['turn_id']}"
        for row in expanded["conversation_turns"]
    }
    excluded_ids = CORE_SINGLE_IDS | CORE_CONVERSATION_IDS | expanded_ids

    candidates = [
        row
        for row in tasks
        if row["query_id"] not in excluded_ids
        and row["filename"] not in EXCLUDED_FILENAMES
    ]
    selected = _select_stratified(candidates, seed)

    selected_fixture_count = sum(_is_fixture(row["filename"]) for row in selected)
    conversation_candidates: list[dict[str, Any]] = []
    for conversation in conversations:
        if (
            conversation["conversation_id"] in FINAL_UI_CONVERSATIONS
            or conversation["filename"] in EXCLUDED_FILENAMES
        ):
            continue
        for turn in conversation["turns"]:
            query_id = f"{conversation['conversation_id']}:{turn['turn_id']}"
            if (
                query_id in expanded_conversation_ids
                or query_id in CORE_CONVERSATION_IDS
                or not turn.get("must_use_history")
            ):
                continue
            conversation_candidates.append(
                {
                    "query_id": query_id,
                    "conversation_id": conversation["conversation_id"],
                    "turn_id": turn["turn_id"],
                    "filename": conversation["filename"],
                    "query": turn["query"],
                    "expected_route": turn["expected_route"],
                    "task_type": "conversation_turn",
                    "must_use_history": True,
                    "prerequisite_turn_ids": [
                        previous["turn_id"]
                        for previous in conversation["turns"]
                        if previous["turn_id"] < turn["turn_id"]
                    ],
                }
            )
    conversation_candidates.sort(
        key=lambda row: (
            row["filename"] in {item["filename"] for item in selected},
            _is_fixture(row["filename"]),
            _stable_score(seed, row["query_id"]),
        )
    )
    conversation = next(
        row
        for row in conversation_candidates
        if selected_fixture_count + int(_is_fixture(row["filename"])) <= 2
    )

    final_rows = [
        {
            "query_id": row["query_id"],
            "filename": row["filename"],
            "task_type": row["task_type"],
            "expected_route": row["expected_route"],
        }
        for row in selected
    ] + [conversation]
    documents = Counter(row["filename"] for row in final_rows)
    routes = Counter(row["expected_route"] for row in final_rows)
    types = Counter(row["task_type"] for row in final_rows)
    if len(final_rows) != 12:
        raise AssertionError("Held-out subset must contain exactly 12 scored tasks")
    if len(documents) < 8:
        raise AssertionError("Held-out subset must span at least eight documents")
    if sum(_is_fixture(row["filename"]) for row in final_rows) > 2:
        raise AssertionError("Held-out subset exceeded the two-fixture cap")

    return {
        "version": 1,
        "kind": "goal3b_preregistered_heldout",
        "selection_algorithm": (
            "SHA-256(seed:query_id) ordering within fixed task-type strata; "
            "greedy preference for a new document, then real documents, with "
            "a global two-fixture cap"
        ),
        "seed": seed,
        "candidate_task_ids": sorted(row["query_id"] for row in candidates),
        "excluded_task_ids": {
            "unchanged_15": sorted(CORE_SINGLE_IDS | CORE_CONVERSATION_IDS),
            "expanded_26": sorted(expanded_ids | expanded_conversation_ids),
            "final_ui_conversations": sorted(FINAL_UI_CONVERSATIONS),
        },
        "excluded_filenames": sorted(EXCLUDED_FILENAMES),
        "stratum_quotas": STRATUM_QUOTAS,
        "selected": final_rows,
        "selected_ids": [row["query_id"] for row in final_rows],
        "document_distribution": dict(sorted(documents.items())),
        "route_distribution": dict(sorted(routes.items())),
        "task_type_distribution": dict(sorted(types.items())),
        "distinct_documents": len(documents),
        "fixture_task_count": sum(
            _is_fixture(row["filename"]) for row in final_rows
        ),
        "provider_execution_count": 0,
        "tuning_visibility": "selection_only; no held-out answer was executed",
    }


def write_selection(output: Path, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    selection = build_selection(seed)
    serialized = json.dumps(selection, ensure_ascii=False, indent=2) + "\n"
    if output.exists():
        if output.read_text(encoding="utf-8") != serialized:
            raise RuntimeError(
                f"Refusing to replace an existing held-out selection: {output}"
            )
        return selection
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")
    return selection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    selection = write_selection(args.output, args.seed)
    print(json.dumps(selection, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
