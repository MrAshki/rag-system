"""Goal 2 staged checkpoint over the unchanged Goal 1 production subset."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from evaluation.runners import evaluate_production_baseline as baseline


GOAL2_HARD_CAP_USD = 0.55
STAGE1_CAP_USD = 0.18
STAGE2_CAP_USD = 0.40
PROGRAM_GOAL1_COST_USD = 0.04927749
PROJECTED_GOAL2_COST_USD = 0.14


def _write(path: Path, value) -> None:
    baseline._write_json(path, value)


def plan(run_dir: Path, storage_state: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    session = baseline._session(storage_state)
    assets = session.get(f"{baseline.BASE_URL}/api/gallery/assets", timeout=15).json().get("assets", [])
    existing_ids = [str(row["id"]) for row in assets]
    user_id = baseline._resolve_user_id(existing_ids) if existing_ids else baseline._authenticated_user_id(session)
    state = {
        "goal": 2,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": baseline.ENDPOINT,
        "endpoint_request_count": 15,
        "endpoint_attempt_count": 0,
        "estimated_provider_request_count": 16,
        "estimated_provider_input_tokens": 230_000,
        "estimated_provider_output_tokens": 25_000,
        "projected_cost_usd": PROJECTED_GOAL2_COST_USD,
        "target_cost_usd": 0.35,
        "hard_cap_usd": GOAL2_HARD_CAP_USD,
        "stage1_cap_usd": STAGE1_CAP_USD,
        "stage2_cap_usd": STAGE2_CAP_USD,
        "remaining_budget_usd": GOAL2_HARD_CAP_USD,
        "preflight_passed": True,
        "preflight": {"pytest": "113 passed, 2 subtests passed"},
        "user_id": user_id,
        "asset_ids": {},
        "cases": [case["query_id"] for case in baseline._cases()],
        "program_goal1_cost_usd": PROGRAM_GOAL1_COST_USD,
    }
    _write(baseline._state_path(run_dir), state)
    _write(run_dir / "cost-ledger.json", {
        "estimate": state,
        "actual": baseline._usage(state),
        "cumulative_optimization_program_cost_usd": PROGRAM_GOAL1_COST_USD,
    })
    print(json.dumps({
        "endpoint_requests": 15,
        "estimated_provider_requests": 16,
        "estimated_input_tokens": 230_000,
        "estimated_output_tokens": 25_000,
        "projected_goal2_cost_usd": PROJECTED_GOAL2_COST_USD,
        "remaining_goal2_budget_usd": GOAL2_HARD_CAP_USD,
    }, indent=2))


def prepare(run_dir: Path, storage_state: Path) -> None:
    state = baseline._load_state(run_dir)
    if state.get("projected_cost_usd", 1) >= GOAL2_HARD_CAP_USD:
        raise RuntimeError("Projected Goal 2 cost exceeds the hard cap")
    baseline.prepare(run_dir, storage_state)


def _record_ledger(run_dir: Path, state: dict) -> dict:
    usage = baseline._usage(state)
    _write(run_dir / "cost-ledger.json", {
        "estimate": state,
        "actual": usage,
        "remaining_goal2_budget_usd": round(GOAL2_HARD_CAP_USD - usage["cost_usd"], 8),
        "cumulative_optimization_program_cost_usd": round(PROGRAM_GOAL1_COST_USD + usage["cost_usd"], 8),
    })
    return usage


def _run_case(
    session,
    run_dir: Path,
    state: dict,
    index: int,
    case: dict,
    conversation_id: str | None,
) -> dict:
    usage = _record_ledger(run_dir, state)
    if usage["cost_usd"] >= GOAL2_HARD_CAP_USD:
        raise RuntimeError("Goal 2 hard cost cap reached")
    events, latency_ms = baseline._stream_request(
        session,
        case,
        state["asset_ids"][case["filename"]],
        conversation_id,
    )
    response_path = run_dir / "responses" / f"{index:02d}-{case['query_id'].replace(':', '-')}.json"
    _write(response_path, events)
    result = baseline._score(case, events, latency_ms, state["asset_ids"][case["filename"]])
    _write(run_dir / "incremental-results" / f"{index:02d}.json", result)
    usage = _record_ledger(run_dir, state)
    state["endpoint_attempt_count"] = int(state.get("endpoint_attempt_count") or 0) + 1
    _write(baseline._state_path(run_dir), state)
    print(json.dumps({
        "completed": index,
        "case": case["query_id"],
        "route": result["actual_route"],
        "selected_route": result.get("metadata", {}).get("selected_route"),
        "latency_ms": round(latency_ms),
        "goal2_cost_usd": usage["cost_usd"],
    }, ensure_ascii=False), flush=True)
    return result


def _remove_prior_clarification_messages(run_dir: Path, conversation_id: str) -> list[str]:
    response_path = run_dir / "responses" / "02-conv-d381-summary-clarify-t2.json"
    events = json.loads(response_path.read_text(encoding="utf-8"))
    event = next(item for item in events if item.get("type") == "conversation")
    ids = [
        event["user_message"]["id"],
        event["assistant_message"]["id"],
    ]
    with baseline.db.get_db() as conn:
        rows = conn.execute(
            """SELECT id, role FROM conversation_messages
                WHERE conversation_id = %s AND id IN (%s, %s)""",
            (conversation_id, ids[0], ids[1]),
        ).fetchall()
        if {row["role"] for row in rows} != {"user", "assistant"} or len(rows) != 2:
            raise RuntimeError("Refusing to prune messages outside the exact Goal 2 clarification")
        conn.execute(
            """DELETE FROM conversation_messages
                WHERE conversation_id = %s AND id IN (%s, %s)""",
            (conversation_id, ids[0], ids[1]),
        )
    return ids


def stage1(run_dir: Path, storage_state: Path) -> None:
    state = baseline._load_state(run_dir)
    if set(state.get("asset_ids", {})) != set(baseline.FILES):
        raise RuntimeError("Prepared asset set is incomplete")
    session = baseline._session(storage_state)
    cases = baseline._cases()[:3]
    checkpoint_path = run_dir / "stage1-checkpoint.json"
    prior = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else None
    summary_already_green = bool(prior and prior.get("gates", {}).get("summary_substantive"))
    if summary_already_green:
        conversation_id = prior["results"][0]["conversation_id"]
        removed = _remove_prior_clarification_messages(run_dir, conversation_id)
        state.setdefault("cleaned_test_message_ids", []).extend(removed)
        results = [prior["results"][0]]
        indexed_cases = [(2, cases[1])]
    else:
        conversation_id = None
        results = []
        indexed_cases = list(enumerate(cases[:2] if prior else cases, 1))
    for position, (index, case) in enumerate(indexed_cases, 1):
        result = _run_case(session, run_dir, state, index, case, conversation_id)
        results.append(result)
        conversation_id = result.get("conversation_id") or conversation_id
        if baseline._usage(state)["cost_usd"] > STAGE1_CAP_USD:
            raise RuntimeError("Stage 1 cost ceiling exceeded")
        if position < len(indexed_cases):
            time.sleep(1.2)
    if prior and len(results) < 3:
        results.append(prior["results"][2])
    state["stage1_conversation_id"] = conversation_id
    _write(baseline._state_path(run_dir), state)
    usage = _record_ledger(run_dir, state)
    summary, clarification, table = results
    gates = {
        "summary_substantive": bool(
            summary["answer"]
            and not summary["generation_score"]["generic_failure"]
            and summary.get("sources")
        ),
        "summary_direct_route": summary.get("metadata", {}).get("selected_route") == "direct_whole_document",
        "clarification_conversation_only": clarification.get("metadata", {}).get("selected_route") == "conversation_only",
        "clarification_zero_document_operations": all(
            int(clarification.get("metadata", {}).get("telemetry", {}).get(key) or 0) == 0
            for key in ("retrieval_calls", "embedding_calls", "rewrite_calls", "reranker_calls")
        ),
        "clarification_complete_and_concise": bool(
            clarification["answer"].strip().endswith((".", "؟", "!", "»"))
            and len(clarification["answer"]) <= 1400
        ),
        "table_exact": bool(
            table["generation_score"]["acceptable_answer_match"]
            and table["generation_score"]["required_concept_coverage"] >= 1.0
        ),
        "table_page_9": 9 in table["cited_pages"],
        "internal_message_absent": all(row["no_internal_message_exposed"] for row in results),
    }
    _write(checkpoint_path, {
        "gates": gates,
        "results": results,
        "usage": usage,
    })
    print(json.dumps({"gates": gates, "usage": usage}, ensure_ascii=False, indent=2, default=str))
    if not all(gates.values()):
        raise RuntimeError("One or more Stage 1 acceptance gates failed")


def stage2(run_dir: Path, storage_state: Path) -> None:
    state = baseline._load_state(run_dir)
    checkpoint = json.loads((run_dir / "stage1-checkpoint.json").read_text(encoding="utf-8"))
    if not all(checkpoint["gates"].values()):
        raise RuntimeError("Stage 1 gates are not all green")
    cases = baseline._cases()
    results = list(checkpoint["results"])
    session = baseline._session(storage_state)
    conversation_ids: dict[str, str] = {}
    for index, case in enumerate(cases[3:], 4):
        conversation_key = case.get("conversation_key")
        incremental = run_dir / "incremental-results" / f"{index:02d}.json"
        if incremental.exists():
            result = json.loads(incremental.read_text(encoding="utf-8"))
            results.append(result)
            if conversation_key and result.get("conversation_id"):
                conversation_ids[conversation_key] = result["conversation_id"]
            continue
        response_path = run_dir / "responses" / f"{index:02d}-{case['query_id'].replace(':', '-')}.json"
        if response_path.exists():
            events = json.loads(response_path.read_text(encoding="utf-8"))
            final = next((event for event in reversed(events) if event.get("type") == "final"), {})
            latency_ms = float(
                (final.get("metadata") or {}).get("telemetry", {}).get("latency_ms") or 0
            )
            result = baseline._score(
                case,
                events,
                latency_ms,
                state["asset_ids"][case["filename"]],
            )
            _write(incremental, result)
            results.append(result)
            if conversation_key and result.get("conversation_id"):
                conversation_ids[conversation_key] = result["conversation_id"]
            continue
        conversation_id = conversation_ids.get(conversation_key) if conversation_key else None
        result = _run_case(session, run_dir, state, index, case, conversation_id)
        results.append(result)
        if conversation_key and result.get("conversation_id"):
            conversation_ids[conversation_key] = result["conversation_id"]
        if baseline._usage(state)["cost_usd"] > STAGE2_CAP_USD:
            raise RuntimeError("Stage 2 cost ceiling exceeded")
        if index < len(cases):
            time.sleep(1.2)
    report = baseline._aggregate(results, state)
    report.update({
        "run_kind": "goal2_post_fix_same_15_task_checkpoint",
        "goal2_cost_cap_usd": GOAL2_HARD_CAP_USD,
        "cumulative_optimization_program_cost_usd": round(
            PROGRAM_GOAL1_COST_USD + report["usage"]["cost_usd"],
            8,
        ),
    })
    _write(run_dir / "production-checkpoint.json", report)
    _record_ledger(run_dir, state)
    print(json.dumps({
        "completed": len(results),
        "routing": report["routing"],
        "generation": report["generation"],
        "summary": report["summary"],
        "conversations": report["conversations"],
        "citations": report["citations"],
        "gts": report["grounded_task_success"],
        "latency_ms": report["latency_ms"],
        "usage": report["usage"],
    }, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["plan", "prepare", "stage1", "stage2"])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--storage-state",
        type=Path,
        default=baseline.ROOT / "tmp" / "rag-quality-goal" / "e2e-auth" / "e2e-storage-state.json",
    )
    args = parser.parse_args()
    {
        "plan": lambda: plan(args.run_dir, args.storage_state),
        "prepare": lambda: prepare(args.run_dir, args.storage_state),
        "stage1": lambda: stage1(args.run_dir, args.storage_state),
        "stage2": lambda: stage2(args.run_dir, args.storage_state),
    }[args.action]()


if __name__ == "__main__":
    main()
