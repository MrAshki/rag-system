"""Run the fixed Goal 3 representative subset through the production endpoint.

The selection references only existing Development Gold Set annotations. It
does not alter source tasks, expected answers, pages, or route labels.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.metrics.citations import evaluate_citations
from evaluation.metrics.conversations import evaluate_conversations
from evaluation.metrics.generation import aggregate_generation
from evaluation.metrics.grounded_task_success import aggregate_grounded_task_success
from evaluation.metrics.proportions import proportion_result
from evaluation.metrics.retrieval import evaluate_rankings
from evaluation.metrics.routing import evaluate_routing
from evaluation.metrics.summaries import score_summary
from evaluation.runners import evaluate_production_baseline as baseline

SELECTION_PATH = ROOT / "evaluation" / "goal3_expanded_subset.json"
GOAL3_HARD_CAP_USD = 1.60
STAGE_E_CUMULATIVE_CAP_USD = 1.25
GOAL3_COST_BEFORE_EXPANDED_USD = 0.17431924
PROGRAM_COST_BEFORE_GOAL3_USD = 0.33339131
PROJECTED_EXPANDED_COST_USD = 0.40


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _selection() -> dict:
    return json.loads(SELECTION_PATH.read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    selected = _selection()
    tasks = {
        row["query_id"]: row
        for row in _load_jsonl(ROOT / "evaluation" / "dev_goldset" / "tasks.jsonl")
    }
    conversations = {
        row["conversation_id"]: row
        for row in _load_jsonl(ROOT / "evaluation" / "dev_goldset" / "conversations.jsonl")
    }
    cases = [dict(tasks[query_id]) for query_id in selected["single_task_ids"]]
    for spec in selected["conversation_turns"]:
        conversation = conversations[spec["conversation_id"]]
        turn = next(
            item for item in conversation["turns"]
            if item["turn_id"] == spec["turn_id"]
        )
        base = dict(tasks[spec["base_task_id"]])
        base.update({
            "query_id": f"{conversation['conversation_id']}:{turn['turn_id']}",
            "filename": conversation["filename"],
            "document_sha256": conversation["document_sha256"],
            "query": turn["query"],
            "task_type": "conversation_turn",
            "expected_intent": (
                "conversational_followup"
                if turn["expected_route"] == "conversational_followup"
                else base.get("expected_intent")
            ),
            "expected_route": turn["expected_route"],
            "retrieval_policy": turn["retrieval_policy"],
            "acceptable_answers": [turn["acceptable_response_behavior"]],
            "required_concepts": spec.get(
                "required_concepts",
                base.get("required_concepts", []),
            ),
            "forbidden_claims": [turn["unacceptable_response_behavior"]],
            "conversation_key": conversation["conversation_id"],
            "conversation_turn_id": turn["turn_id"],
            "must_use_history": bool(turn["must_use_history"]),
            "selected_document_persistence_required": bool(
                turn["selected_document_persistence_required"]
            ),
        })
        cases.append(base)
    return cases


def _files(cases: list[dict] | None = None) -> list[str]:
    return sorted({case["filename"] for case in (cases or _cases())})


def _coverage(cases: list[dict]) -> dict:
    categories = Counter(case["task_type"] for case in cases)
    return {
        "total": len(cases),
        "documents": len({case["filename"] for case in cases}),
        "local_factual": categories["local_factual"],
        "table_or_numerical": categories["table_or_numerical"],
        "summary_or_analytical": (
            categories["comprehensive_summary"] + categories["analytical"]
        ),
        "cross_language": categories["cross_language"],
        "no_answer_or_conflict": categories["no_answer_or_conflict"],
        "conversation_turns": categories["conversation_turn"],
        "quoted_document_explanation": categories["quoted_document_explanation"],
        "per_document": dict(Counter(case["filename"] for case in cases)),
    }


def _assert_selection() -> None:
    cases = _cases()
    expected = _selection()["coverage"]
    actual = _coverage(cases)
    if len(cases) < 25 or len(cases) > 30:
        raise AssertionError("Expanded subset must contain between 25 and 30 requests")
    for key, minimum in expected.items():
        if actual[key] < minimum:
            raise AssertionError(
                f"Expanded subset coverage for {key} is {actual[key]}, expected {minimum}"
            )
    if actual["documents"] < 8:
        raise AssertionError("Expanded subset must span at least eight documents")
    if actual["per_document"].get("doh-16-381.pdf", 0) > 3:
        raise AssertionError("Expanded subset is over-concentrated on doh-16-381.pdf")
    if sum(
        count for name, count in actual["per_document"].items()
        if name.startswith("fixture-")
    ) > len(cases) // 3:
        raise AssertionError("Expanded subset is over-concentrated on fixtures")


def plan(run_dir: Path, storage_state: Path, preflight_passed: bool) -> None:
    _assert_selection()
    if not preflight_passed:
        raise RuntimeError("Refusing paid-run planning until zero-cost preflight passes")
    run_dir.mkdir(parents=True, exist_ok=True)
    cases = _cases()
    session = baseline._session(storage_state)
    assets = session.get(
        f"{baseline.BASE_URL}/api/gallery/assets", timeout=15
    ).json().get("assets", [])
    existing_ids = [str(row["id"]) for row in assets]
    user_id = (
        baseline._resolve_user_id(existing_ids)
        if existing_ids
        else baseline._authenticated_user_id(session)
    )
    projected_goal3 = GOAL3_COST_BEFORE_EXPANDED_USD + PROJECTED_EXPANDED_COST_USD
    if projected_goal3 >= STAGE_E_CUMULATIVE_CAP_USD:
        raise RuntimeError("Projected expanded run exceeds the Stage E ceiling")
    state = {
        "goal": 3,
        "run_kind": "goal3_expanded_representative_subset",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": baseline.ENDPOINT,
        "endpoint_request_count": len(cases),
        "endpoint_attempt_count": 0,
        "estimated_chat_request_count": 32,
        "estimated_input_tokens": 300_000,
        "estimated_output_tokens": 30_000,
        "projected_incremental_cost_usd": PROJECTED_EXPANDED_COST_USD,
        "goal3_cost_before_run_usd": GOAL3_COST_BEFORE_EXPANDED_USD,
        "projected_goal3_cumulative_cost_usd": projected_goal3,
        "goal3_hard_cap_usd": GOAL3_HARD_CAP_USD,
        "stage_e_cumulative_cap_usd": STAGE_E_CUMULATIVE_CAP_USD,
        "preflight_passed": True,
        "user_id": user_id,
        "asset_ids": {},
        "cases": [case["query_id"] for case in cases],
        "coverage": _coverage(cases),
    }
    baseline._write_json(baseline._state_path(run_dir), state)
    baseline._write_json(
        run_dir / "cost-ledger.json",
        {"estimate": state, "actual": baseline._usage(state)},
    )
    print(json.dumps({
        "requests": len(cases),
        "documents": len(_files(cases)),
        "coverage": state["coverage"],
        "projected_incremental_cost_usd": PROJECTED_EXPANDED_COST_USD,
        "projected_goal3_cumulative_cost_usd": projected_goal3,
        "remaining_goal3_hard_budget_usd": round(
            GOAL3_HARD_CAP_USD - GOAL3_COST_BEFORE_EXPANDED_USD, 8
        ),
    }, ensure_ascii=False, indent=2))


def prepare(run_dir: Path, storage_state: Path) -> None:
    state = baseline._load_state(run_dir)
    if not state.get("preflight_passed"):
        raise RuntimeError("Preflight is not recorded as passed")
    session = baseline._session(storage_state)
    user_id = baseline._authenticated_user_id(session)
    assets = session.get(
        f"{baseline.BASE_URL}/api/gallery/assets", timeout=15
    ).json().get("assets", [])
    by_filename: dict[str, list[dict]] = defaultdict(list)
    for item in assets:
        by_filename[item["filename"]].append(item)
    asset_ids: dict[str, str] = {}
    missing: list[str] = []
    for filename in _files():
        source = ROOT / "composite_goldset_pdfs" / filename
        match = next((
            row for row in by_filename.get(filename, [])
            if int(row.get("size_bytes") or 0) == source.stat().st_size
            and row.get("status") in {"uploaded", "scanning", "scanned"}
            and baseline._asset_matches_source(
                str(row["id"]), user_id=user_id, source=source
            )
        ), None)
        if match:
            asset_ids[filename] = str(match["id"])
        else:
            missing.append(filename)
    handles = []
    try:
        files = []
        for filename in missing:
            handle = (ROOT / "composite_goldset_pdfs" / filename).open("rb")
            handles.append(handle)
            files.append(("files", (filename, handle, "application/pdf")))
        if files:
            response = session.post(
                f"{baseline.BASE_URL}/api/gallery/upload",
                files=files,
                timeout=180,
            )
            response.raise_for_status()
            for item in response.json().get("created", []):
                asset_ids[item["filename"]] = str(item["id"])
    finally:
        for handle in handles:
            handle.close()
    if set(asset_ids) != set(_files()):
        missing_mapping = sorted(set(_files()) - set(asset_ids))
        raise RuntimeError(f"Asset mapping incomplete: {missing_mapping}")
    state.update({
        "asset_ids": asset_ids,
        "uploaded_now": missing,
        "user_id": user_id,
        "asset_source_mapping": {
            filename: {
                "asset_id": asset_id,
                "user_id": user_id,
                "source_sha256": baseline._source_sha256(
                    ROOT / "composite_goldset_pdfs" / filename
                ),
            }
            for filename, asset_id in asset_ids.items()
        },
        "prepared_at": datetime.now(timezone.utc).isoformat(),
    })
    baseline._write_json(baseline._state_path(run_dir), state)
    baseline._write_json(
        run_dir / "cost-ledger.json",
        {"estimate": state, "actual": baseline._usage(state)},
    )
    print(json.dumps({
        "assets": len(asset_ids),
        "uploaded_now": len(missing),
        "asset_ids": asset_ids,
    }, ensure_ascii=False, indent=2))


def status(run_dir: Path, storage_state: Path) -> None:
    state = baseline._load_state(run_dir)
    session = baseline._session(storage_state)
    assets = session.get(
        f"{baseline.BASE_URL}/api/gallery/assets", timeout=15
    ).json().get("assets", [])
    by_id = {str(row["id"]): row for row in assets}
    statuses = {}
    for filename, asset_id in state.get("asset_ids", {}).items():
        asset = baseline.db.get_asset(asset_id)
        api = by_id.get(asset_id, {})
        statuses[filename] = {
            "id": asset_id,
            "status": api.get("status", "missing"),
            "chunk_count": api.get("chunk_count", 0),
            "processing_version": asset["processing_version"] if asset else None,
            "warning": api.get("warning"),
        }
    ready = bool(statuses) and all(
        row["status"] == "scanned"
        and str(row["processing_version"] or "").startswith(
            f"{baseline.ingest.NORMALIZATION_VERSION}:"
        )
        for row in statuses.values()
    )
    baseline._write_json(run_dir / "asset-status.json", statuses)
    print(json.dumps({"ready": ready, "assets": statuses}, ensure_ascii=False, indent=2))


def _retrieval_policy_correct(result: dict) -> bool:
    policy = result["retrieval_policy"]
    called = bool(result["retrieval_called"])
    return (
        (policy == "required" and called)
        or (policy == "forbidden" and not called)
        or policy == "allowed"
    )


def _group_metrics(results: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        groups[str(result[key])].append(result)
    return {
        name: {
            "count": len(rows),
            "route_accuracy": proportion_result(
                sum(row["route_correct"] for row in rows), len(rows)
            ),
            "retrieval_necessity_accuracy": proportion_result(
                sum(_retrieval_policy_correct(row) for row in rows), len(rows)
            ),
            "acceptable_answer_match": proportion_result(
                sum(row["answer_correct"] for row in rows), len(rows)
            ),
            "citation_page_accuracy": proportion_result(
                sum(row["citation_page_correct"] for row in rows), len(rows)
            ),
            "strict_gts": aggregate_grounded_task_success(rows)["overall"],
            "latency_p50_ms": baseline._percentile(
                [row["latency_ms"] for row in rows], 0.50
            ),
            "latency_p95_ms": baseline._percentile(
                [row["latency_ms"] for row in rows], 0.95
            ),
        }
        for name, rows in sorted(groups.items())
    }


def _aggregate(results: list[dict], state: dict) -> dict:
    cases = {case["query_id"]: case for case in _cases()}
    ranking_qrels = {}
    ranking_run = {}
    for result in results:
        case = cases[result["query_id"]]
        if not case.get("relevant_pages"):
            continue
        prefix = case.get("document_sha256", case["filename"])
        ranking_qrels[result["query_id"]] = {
            f"{prefix}#page={page}": int(
                (case.get("graded_relevance") or {}).get(str(page), 3)
            )
            for page in case["relevant_pages"]
        }
        ranking_run[result["query_id"]] = [
            f"{prefix}#page={page}" for page in result["cited_pages"]
        ]
    summaries = [
        result["summary_score"]
        for result in results
        if result.get("summary_score")
    ]
    conversation_rows = []
    for result in results:
        case = cases[result["query_id"]]
        if case.get("task_type") != "conversation_turn" or not case.get("must_use_history"):
            continue
        conversation_rows.append({
            "followup_resolved": bool(
                result["actual_route"] == "conversational_followup"
                and result["answer_correct"]
            ),
            "history_used_correctly": bool(result["metadata"].get("history_resolved")),
            "retrieval_policy": case["retrieval_policy"],
            "retrieval_called": result["retrieval_called"],
            "selected_asset_persisted": True,
            "conversation_id_persisted": bool(result["conversation_id"]),
        })
    latency = [result["latency_ms"] for result in results]
    usage = baseline._usage(state)
    goal3_total = round(
        GOAL3_COST_BEFORE_EXPANDED_USD + usage["cost_usd"], 8
    )
    return {
        "run_kind": "goal3_expanded_representative_subset",
        "selection": _selection(),
        "coverage": _coverage(list(cases.values())),
        "endpoint_request_count": len(results),
        "routing": evaluate_routing(results),
        "retrieval_necessity_accuracy": proportion_result(
            sum(_retrieval_policy_correct(row) for row in results), len(results)
        ),
        "citation_page_ranking_proxy": evaluate_rankings(
            ranking_qrels, ranking_run
        ),
        "generation": aggregate_generation(
            [row["generation_score"] for row in results]
        ),
        "summaries": {
            "count": len(summaries),
            "section_coverage_mean": (
                statistics.fmean(
                    row["substantive_section_coverage"] for row in summaries
                ) if summaries else 0.0
            ),
            "key_claim_recall_mean": (
                statistics.fmean(row["key_claim_recall"] for row in summaries)
                if summaries else 0.0
            ),
            "conclusion_coverage": proportion_result(
                sum(row["conclusion_coverage"] for row in summaries),
                len(summaries),
            ),
        },
        "citations": evaluate_citations(results),
        "conversations": evaluate_conversations(conversation_rows),
        "grounded_task_success": aggregate_grounded_task_success(results),
        "per_route": _group_metrics(results, "expected_route"),
        "per_document": _group_metrics(results, "filename"),
        "latency_ms": {
            "p50": baseline._percentile(latency, 0.50),
            "p95": baseline._percentile(latency, 0.95),
            "count": len(latency),
        },
        "usage": usage,
        "goal3_cumulative_cost_usd": goal3_total,
        "program_cumulative_cost_usd": round(
            PROGRAM_COST_BEFORE_GOAL3_USD + goal3_total, 8
        ),
        "stage_e_cap_respected": goal3_total <= STAGE_E_CUMULATIVE_CAP_USD,
        "goal3_hard_cap_respected": goal3_total <= GOAL3_HARD_CAP_USD,
        "results": results,
    }


def _saved_response_path(
    run_dir: Path,
    state: dict,
    index: int,
    case: dict,
) -> Path:
    override = (state.get("response_overrides") or {}).get(case["query_id"])
    if override:
        path = run_dir / override
        if path.exists():
            return path
    return (
        run_dir / "responses"
        / f"{index:02d}-{case['query_id'].replace(':', '-')}.json"
    )


def _score_saved_results(run_dir: Path, state: dict) -> list[dict]:
    results = []
    for index, case in enumerate(_cases(), start=1):
        response_path = _saved_response_path(run_dir, state, index, case)
        events = json.loads(response_path.read_text(encoding="utf-8"))
        final = next(
            (event for event in reversed(events) if event.get("type") == "final"),
            {},
        )
        latency_ms = float(
            (final.get("metadata") or {})
            .get("telemetry", {})
            .get("latency_ms")
            or 0
        )
        result = baseline._score(
            case,
            events,
            latency_ms,
            state["asset_ids"][case["filename"]],
        )
        if case.get("task_type") == "comprehensive_summary":
            result["summary_score"] = score_summary(
                case, result["answer"], result["cited_pages"]
            )
        results.append(result)
    return results


def run(run_dir: Path, storage_state: Path) -> None:
    state = baseline._load_state(run_dir)
    cases = _cases()
    if set(state.get("asset_ids", {})) != set(_files(cases)):
        raise RuntimeError("Prepared expanded asset set is incomplete")
    for filename, asset_id in state["asset_ids"].items():
        source = ROOT / "composite_goldset_pdfs" / filename
        asset = baseline.db.get_asset(asset_id)
        mapping = (state.get("asset_source_mapping") or {}).get(filename) or {}
        if (
            not asset
            or asset["status"] != "scanned"
            or not str(asset["processing_version"] or "").startswith(
                f"{baseline.ingest.NORMALIZATION_VERSION}:"
            )
            or not baseline._asset_matches_source(
                asset_id, user_id=int(state["user_id"]), source=source
            )
            or mapping.get("source_sha256") != baseline._source_sha256(source)
        ):
            raise RuntimeError(f"Asset is not ready and exact: {filename}")
    session = baseline._session(storage_state)
    results = []
    conversation_ids: dict[str, str] = {}
    for index, case in enumerate(cases, start=1):
        response_path = (
            run_dir / "responses"
            / f"{index:02d}-{case['query_id'].replace(':', '-')}.json"
        )
        conversation_key = case.get("conversation_key")
        if response_path.exists():
            events = json.loads(response_path.read_text(encoding="utf-8"))
            final = next(
                (
                    event for event in reversed(events)
                    if event.get("type") == "final"
                ),
                {},
            )
            latency_ms = float(
                (final.get("metadata") or {})
                .get("telemetry", {})
                .get("latency_ms")
                or 0
            )
            result = baseline._score(
                case,
                events,
                latency_ms,
                state["asset_ids"][case["filename"]],
            )
            if case.get("task_type") == "comprehensive_summary":
                result["summary_score"] = score_summary(
                    case, result["answer"], result["cited_pages"]
                )
            results.append(result)
            if conversation_key and result.get("conversation_id"):
                conversation_ids[conversation_key] = result["conversation_id"]
            print(json.dumps({
                "resumed_from_saved_response": index,
                "case": case["query_id"],
            }, ensure_ascii=False), flush=True)
            continue
        usage_before = baseline._usage(state)
        projected_goal3 = (
            GOAL3_COST_BEFORE_EXPANDED_USD + usage_before["cost_usd"]
        )
        if projected_goal3 >= STAGE_E_CUMULATIVE_CAP_USD:
            raise RuntimeError("Stage E cumulative cost ceiling reached")
        events, latency_ms = baseline._stream_request(
            session,
            case,
            state["asset_ids"][case["filename"]],
            conversation_ids.get(conversation_key) if conversation_key else None,
        )
        baseline._write_json(response_path, events)
        result = baseline._score(
            case,
            events,
            latency_ms,
            state["asset_ids"][case["filename"]],
        )
        if case.get("task_type") == "comprehensive_summary":
            result["summary_score"] = score_summary(
                case, result["answer"], result["cited_pages"]
            )
        results.append(result)
        if conversation_key and result.get("conversation_id"):
            conversation_ids[conversation_key] = result["conversation_id"]
        state["endpoint_attempt_count"] = index
        baseline._write_json(baseline._state_path(run_dir), state)
        usage_after = baseline._usage(state)
        baseline._write_json(
            run_dir / "cost-ledger.json",
            {"estimate": state, "actual": usage_after},
        )
        print(json.dumps({
            "completed": index,
            "case": case["query_id"],
            "route": result["actual_route"],
            "answer_correct": result["answer_correct"],
            "citation_page_correct": result["citation_page_correct"],
            "latency_ms": round(latency_ms),
            "incremental_cost_usd": usage_after["cost_usd"],
            "goal3_cumulative_cost_usd": round(
                GOAL3_COST_BEFORE_EXPANDED_USD + usage_after["cost_usd"], 8
            ),
        }, ensure_ascii=False), flush=True)
        if index < len(cases):
            time.sleep(1.2)
    report = _aggregate(results, state)
    baseline._write_json(run_dir / "expanded-production-report.json", report)
    baseline._write_json(
        run_dir / "cost-ledger.json",
        {"estimate": state, "actual": report["usage"]},
    )
    print(json.dumps({
        "completed": len(results),
        "routing": report["routing"],
        "retrieval_necessity": report["retrieval_necessity_accuracy"],
        "generation": report["generation"],
        "citations": report["citations"],
        "gts": report["grounded_task_success"],
        "latency_ms": report["latency_ms"],
        "usage": report["usage"],
        "goal3_cumulative_cost_usd": report["goal3_cumulative_cost_usd"],
    }, ensure_ascii=False, indent=2, default=str))


def rerun(
    run_dir: Path,
    storage_state: Path,
    case_ids: list[str],
) -> None:
    state = baseline._load_state(run_dir)
    cases = _cases()
    known = {case["query_id"] for case in cases}
    selected = list(dict.fromkeys(case_ids))
    unknown = sorted(set(selected) - known)
    if unknown:
        raise RuntimeError(f"Unknown expanded case IDs: {unknown}")
    if not selected:
        raise RuntimeError("At least one --case-id is required")
    session = baseline._session(storage_state)
    conversation_ids: dict[str, str] = {}
    selected_set = set(selected)
    attempts = 0
    for index, case in enumerate(cases, start=1):
        conversation_key = case.get("conversation_key")
        if case["query_id"] not in selected_set:
            if conversation_key:
                path = _saved_response_path(run_dir, state, index, case)
                if path.exists():
                    events = json.loads(path.read_text(encoding="utf-8"))
                    event = next(
                        (
                            row for row in events
                            if row.get("type") == "conversation"
                        ),
                        {},
                    )
                    conversation_id = (
                        event.get("conversation") or {}
                    ).get("id")
                    if conversation_id:
                        conversation_ids[conversation_key] = conversation_id
            continue
        usage_before = baseline._usage(state)
        if (
            GOAL3_COST_BEFORE_EXPANDED_USD + usage_before["cost_usd"]
            >= STAGE_E_CUMULATIVE_CAP_USD
        ):
            raise RuntimeError("Stage E cumulative cost ceiling reached")
        events, latency_ms = baseline._stream_request(
            session,
            case,
            state["asset_ids"][case["filename"]],
            conversation_ids.get(conversation_key) if conversation_key else None,
        )
        attempts += 1
        relative = (
            Path("responses")
            / "retained-fixes"
            / f"{int(state.get('endpoint_attempt_count') or 0) + attempts:03d}-"
              f"{case['query_id'].replace(':', '-')}.json"
        )
        baseline._write_json(run_dir / relative, events)
        state.setdefault("response_overrides", {})[case["query_id"]] = str(
            relative
        ).replace("\\", "/")
        result = baseline._score(
            case,
            events,
            latency_ms,
            state["asset_ids"][case["filename"]],
        )
        if conversation_key and result.get("conversation_id"):
            conversation_ids[conversation_key] = result["conversation_id"]
        usage_after = baseline._usage(state)
        print(json.dumps({
            "rerun": attempts,
            "case": case["query_id"],
            "route": result["actual_route"],
            "answer_correct": result["answer_correct"],
            "citation_page_correct": result["citation_page_correct"],
            "latency_ms": round(latency_ms),
            "incremental_cost_usd": usage_after["cost_usd"],
            "goal3_cumulative_cost_usd": round(
                GOAL3_COST_BEFORE_EXPANDED_USD + usage_after["cost_usd"], 8
            ),
        }, ensure_ascii=False), flush=True)
        if attempts < len(selected):
            time.sleep(1.2)
    state["endpoint_attempt_count"] = (
        int(state.get("endpoint_attempt_count") or 0) + attempts
    )
    baseline._write_json(baseline._state_path(run_dir), state)
    results = _score_saved_results(run_dir, state)
    report = _aggregate(results, state)
    report["retained_rerun_case_ids"] = selected
    report["endpoint_attempt_count"] = state["endpoint_attempt_count"]
    baseline._write_json(run_dir / "expanded-production-report.json", report)
    baseline._write_json(
        run_dir / "cost-ledger.json",
        {"estimate": state, "actual": report["usage"]},
    )
    print(json.dumps({
        "rerun_completed": attempts,
        "retained_outcomes": len(results),
        "routing": report["routing"],
        "generation": report["generation"],
        "citations": report["citations"],
        "gts": report["grounded_task_success"],
        "latency_ms": report["latency_ms"],
        "usage": report["usage"],
        "goal3_cumulative_cost_usd": report["goal3_cumulative_cost_usd"],
    }, ensure_ascii=False, indent=2, default=str))


def rescore(run_dir: Path) -> None:
    state = baseline._load_state(run_dir)
    results = _score_saved_results(run_dir, state)
    report = _aggregate(results, state)
    baseline._write_json(run_dir / "expanded-production-report.json", report)
    print(json.dumps({
        "rescored": len(results),
        "gts": report["grounded_task_success"],
        "cost_usd": report["usage"]["cost_usd"],
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=["plan", "prepare", "status", "run", "rerun", "rescore"],
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--storage-state",
        type=Path,
        default=(
            ROOT / "tmp" / "rag-quality-goal"
            / "e2e-auth" / "e2e-storage-state.json"
        ),
    )
    parser.add_argument("--preflight-passed", action="store_true")
    parser.add_argument("--case-id", action="append", default=[])
    args = parser.parse_args()
    {
        "plan": lambda: plan(
            args.run_dir, args.storage_state, args.preflight_passed
        ),
        "prepare": lambda: prepare(args.run_dir, args.storage_state),
        "status": lambda: status(args.run_dir, args.storage_state),
        "run": lambda: run(args.run_dir, args.storage_state),
        "rerun": lambda: rerun(
            args.run_dir, args.storage_state, args.case_id
        ),
        "rescore": lambda: rescore(args.run_dir),
    }[args.action]()


if __name__ == "__main__":
    main()
