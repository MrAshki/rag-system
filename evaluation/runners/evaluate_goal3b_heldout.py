"""Execute the pre-registered Goal 3B held-out set exactly once."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from evaluation.metrics.standard_ir import evaluate_with_pytrec
from evaluation.runners import evaluate_goal3_expanded as expanded
from evaluation.runners import evaluate_production_baseline as baseline
from evaluation.tuning_freeze import verify_manifest


ROOT = Path(__file__).resolve().parents[2]
SELECTION = ROOT / "tmp/rag-quality-goal/goal3b/heldout-selection.json"
FREEZE = ROOT / "tmp/rag-quality-goal/goal3b/frozen-manifest.json"
AUTH = ROOT / "tmp/rag-quality-goal/e2e-auth/e2e-storage-state.json"


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def cases() -> list[dict]:
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    tasks = {
        row["query_id"]: row
        for row in _jsonl(ROOT / "evaluation/dev_goldset/tasks.jsonl")
    }
    conversations = {
        row["conversation_id"]: row
        for row in _jsonl(ROOT / "evaluation/dev_goldset/conversations.jsonl")
    }
    output = []
    for selected in selection["selected"]:
        query_id = selected["query_id"]
        if query_id in tasks:
            output.append(dict(tasks[query_id]))
            continue
        conversation = conversations[selected["conversation_id"]]
        turn = next(
            row for row in conversation["turns"]
            if row["turn_id"] == selected["turn_id"]
        )
        base = dict(tasks["d14148-quote-explain"])
        base.update({
            "query_id": query_id,
            "query": turn["query"],
            "task_type": "conversation_turn",
            "expected_intent": "conversational_followup",
            "expected_route": turn["expected_route"],
            "retrieval_policy": turn["retrieval_policy"],
            "acceptable_answers": [turn["acceptable_response_behavior"]],
            "required_concepts": ["ادغام", "رسالت", "چشم‌انداز", "راهبرد", "فرایند"],
            "forbidden_claims": [turn["unacceptable_response_behavior"]],
            "conversation_key": conversation["conversation_id"],
            "conversation_turn_id": turn["turn_id"],
            "must_use_history": True,
        })
        output.append(base)
    return output


def _state(run_dir: Path) -> dict:
    return baseline._load_state(run_dir)


def plan(run_dir: Path) -> None:
    if run_dir.exists():
        raise RuntimeError("Refusing to reuse a held-out run directory")
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    if selection.get("provider_execution_count") != 0:
        raise RuntimeError("Held-out selection is not pristine")
    mismatches = verify_manifest(
        ROOT, json.loads(FREEZE.read_text(encoding="utf-8"))
    )
    if mismatches:
        raise RuntimeError(f"Tuning freeze mismatch: {mismatches}")
    session = baseline._session(AUTH)
    user_id = baseline._authenticated_user_id(session)
    rows = cases()
    state = {
        "run_kind": "goal3b_single_heldout",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "preflight_passed": True,
        "tuning_frozen": True,
        "user_id": user_id,
        "asset_ids": {},
        "cases": [row["query_id"] for row in rows],
        "endpoint_request_count": len(rows) + 1,
        "projected_provider_cost_usd": 0.20,
    }
    baseline._write_json(baseline._state_path(run_dir), state)
    print(json.dumps(state, ensure_ascii=False, indent=2))


def prepare(run_dir: Path) -> None:
    original_cases, original_files = expanded._cases, expanded._files
    expanded._cases = cases
    expanded._files = lambda _cases=None: sorted(
        {row["filename"] for row in (_cases or cases())}
    )
    try:
        expanded.prepare(run_dir, AUTH)
    finally:
        expanded._cases, expanded._files = original_cases, original_files


def _prerequisite() -> dict:
    conversation = next(
        row for row in _jsonl(ROOT / "evaluation/dev_goldset/conversations.jsonl")
        if row["conversation_id"] == "conv-d14148-quoted"
    )
    turn = conversation["turns"][0]
    return {
        "query_id": "conv-d14148-quoted:t1-prerequisite",
        "filename": conversation["filename"],
        "query": turn["query"],
    }


def _ir_metrics(rows: list[dict], case_map: dict[str, dict]) -> dict:
    qrels, run = {}, {}
    for row in rows:
        case = case_map[row["query_id"]]
        pages = case.get("relevant_pages") or []
        if not pages:
            continue
        prefix = case.get("document_sha256") or case["filename"]
        qrels[row["query_id"]] = {
            f"{prefix}#page={page}": int(
                (case.get("graded_relevance") or {}).get(str(page), 1)
            )
            for page in pages
        }
        considered = (
            row.get("metadata", {}).get("pages_considered")
            or row.get("cited_pages")
            or []
        )
        run[row["query_id"]] = [
            f"{prefix}#page={int(page)}" for page in considered
        ]
    return evaluate_with_pytrec(qrels, run)


def run(run_dir: Path) -> None:
    state = _state(run_dir)
    report_path = run_dir / "heldout-report.json"
    if report_path.exists() or state.get("heldout_started"):
        raise RuntimeError("Held-out execution may run only once")
    if verify_manifest(ROOT, json.loads(FREEZE.read_text(encoding="utf-8"))):
        raise RuntimeError("Tuning changed after freeze")
    state["heldout_started"] = datetime.now(timezone.utc).isoformat()
    baseline._write_json(baseline._state_path(run_dir), state)
    session = baseline._session(AUTH)
    rows = cases()
    results = []
    conversation_id = None
    for index, case in enumerate(rows, 1):
        if case["query_id"] == "conv-d14148-quoted:t2":
            prerequisite = _prerequisite()
            events, _latency = baseline._stream_request(
                session,
                prerequisite,
                state["asset_ids"][prerequisite["filename"]],
                None,
            )
            baseline._write_json(
                run_dir / "responses/12-prerequisite.json", events
            )
            conversation = next(
                (event for event in events if event.get("type") == "conversation"),
                {},
            )
            conversation_id = (
                conversation.get("conversation") or {}
            ).get("id")
            if not conversation_id:
                raise RuntimeError("Conversation prerequisite failed")
            time.sleep(1.2)
        events, latency = baseline._stream_request(
            session,
            case,
            state["asset_ids"][case["filename"]],
            conversation_id if case.get("conversation_key") else None,
        )
        if any(event.get("type") == "http_error" for event in events):
            raise RuntimeError(
                f"Held-out execution failed at {case['query_id']}: {events}"
            )
        baseline._write_json(
            run_dir / f"responses/{index:02d}-{case['query_id'].replace(':', '-')}.json",
            events,
        )
        scored = baseline._score(
            case, events, latency, state["asset_ids"][case["filename"]]
        )
        if case["task_type"] == "comprehensive_summary":
            scored["summary_score"] = expanded.score_summary(
                case, scored["answer"], scored["cited_pages"]
            )
        results.append(scored)
        time.sleep(1.2)
    original_cases, original_selection = expanded._cases, expanded._selection
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    expanded._cases = cases
    expanded._selection = lambda: selection
    try:
        report = expanded._aggregate(results, state)
    finally:
        expanded._cases, expanded._selection = original_cases, original_selection
    report["run_kind"] = "goal3b_single_heldout"
    report["production_answer_evidence_ir"] = _ir_metrics(
        results, {row["query_id"]: row for row in rows}
    )
    report["heldout_execution_count"] = 1
    report["prerequisite_request_count"] = 1
    baseline._write_json(report_path, report)
    print(json.dumps({
        "results": len(results),
        "route": report["routing"]["route_selection_accuracy"],
        "answer": report["generation"]["acceptable_answer_match"],
        "citations": report["citations"]["citation_page_accuracy"],
        "gts": report["grounded_task_success"]["overall"],
        "ir": report["production_answer_evidence_ir"]["means"],
        "usage": report["usage"],
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["plan", "prepare", "run"])
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    {"plan": plan, "prepare": prepare, "run": run}[args.action](args.run_dir)


if __name__ == "__main__":
    main()
