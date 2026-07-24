from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from document_pipeline import ingest  # noqa: E402
from evaluation.metrics.citations import evaluate_citations  # noqa: E402
from evaluation.metrics.conversations import evaluate_conversations  # noqa: E402
from evaluation.metrics.generation import aggregate_generation, score_generation  # noqa: E402
from evaluation.metrics.grounded_task_success import aggregate_grounded_task_success  # noqa: E402
from evaluation.metrics.retrieval import evaluate_rankings  # noqa: E402
from evaluation.metrics.routing import evaluate_routing  # noqa: E402
from evaluation.metrics.summaries import score_summary  # noqa: E402
from evaluation.metrics.proportions import proportion_result  # noqa: E402
from evaluation.runners.evaluate_ingestion import load_jsonl  # noqa: E402


ENDPOINT = "http://127.0.0.1:5000/api/ask/stream"
BASE_URL = "http://127.0.0.1:5000"
HARD_CAP_USD = 0.35
TARGET_USD = 0.20
FILES = [
    "doh-16-381.pdf",
    "doh-16-395.pdf",
    "doh-16-345.pdf",
    "fixture-001-conflicting-retention-policy.pdf",
    "fixture-003-mixed-persian-english.pdf",
    "fixture-004-intentional-no-answer.pdf",
    "fixture-005-ambiguous-followup.pdf",
]
SINGLE_CASE_IDS = [
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
]
INTERNAL_MESSAGE_RE = re.compile(r"برنامه پاسخ انتخاب شد|agent_plan|agent_execute|context_hash|fallback_generation", re.I)
PAGE_RE = re.compile(r"(?:صفحه|صفحات|page|pages)\s*([0-9۰-۹]+)(?:\s*(?:تا|-|–)\s*([0-9۰-۹]+))?", re.I)
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _load_tasks() -> dict[str, dict]:
    return {
        row["query_id"]: row
        for row in load_jsonl(ROOT / "evaluation" / "dev_goldset" / "tasks.jsonl")
    }


def _session(storage_state: Path) -> requests.Session:
    payload = json.loads(storage_state.read_text(encoding="utf-8"))
    session = requests.Session()
    for cookie in payload.get("cookies", []):
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path") or "/",
        )
    response = session.get(f"{BASE_URL}/api/auth/me", timeout=10)
    response.raise_for_status()
    if not response.json().get("logged_in"):
        raise RuntimeError("E2E storage state is not authenticated")
    return session


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _state_path(run_dir: Path) -> Path:
    return run_dir / "state.json"


def _load_state(run_dir: Path) -> dict:
    path = _state_path(run_dir)
    if not path.exists():
        raise RuntimeError(f"Missing plan state: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_user_id(asset_ids: list[str]) -> int:
    for asset_id in asset_ids:
        asset = db.get_asset(asset_id)
        if asset:
            return int(asset["user_id"])
    raise RuntimeError("Could not resolve authenticated E2E user from assets")


def _authenticated_user_id(session: requests.Session) -> int:
    response = session.get(f"{BASE_URL}/api/auth/me", timeout=10)
    response.raise_for_status()
    phone = response.json().get("phone")
    user = db.get_user_by_phone(phone) if phone else None
    if not user:
        raise RuntimeError("Could not resolve authenticated E2E user")
    return int(user["id"])


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _asset_matches_source(asset_id: str, *, user_id: int, source: Path) -> bool:
    """Verify an evaluation asset against owner, filename, size and raw bytes."""
    asset = db.get_asset(asset_id)
    if not asset:
        return False
    if int(asset["user_id"]) != int(user_id):
        return False
    if asset["original_filename"] != source.name or int(asset["size_bytes"] or 0) != source.stat().st_size:
        return False
    original_path = Path(str(asset["original_path"] or ""))
    source_matches = (
        original_path.is_file()
        and _source_sha256(original_path) == _source_sha256(source)
    )
    if not source_matches:
        return False
    if asset["status"] == "scanned":
        return str(asset["processing_version"] or "").startswith(f"{ingest.NORMALIZATION_VERSION}:")
    return asset["status"] in {"uploaded", "scanning"}


def _usage(state: dict) -> dict:
    user_id = state.get("user_id")
    if not user_id:
        return {"rows": [], "provider_request_count": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    with db.get_db() as conn:
        rows = conn.execute(
            """SELECT request_id, conversation_id, feature, operation_type, provider, model,
                      input_tokens, output_tokens, total_tokens, estimated_cost_usd,
                      latency_ms, status, error_type, created_at
                 FROM usage_events
                WHERE user_id = %s AND created_at >= %s
                ORDER BY created_at""",
            (user_id, state["started_at"]),
        ).fetchall()
        compute = conn.execute(
            """SELECT request_id, operation_type, provider, model, latency_ms, input_count,
                      input_chars, chunk_count, pair_count, query_count, status, error_type, created_at
                 FROM compute_usage_events
                WHERE user_id = %s AND created_at >= %s
                ORDER BY created_at""",
            (user_id, state["started_at"]),
        ).fetchall()
    serial = [dict(row) for row in rows]
    provider_rows = [row for row in serial if row.get("operation_type") == "chat_completion"]
    return {
        "rows": serial,
        "compute_rows": [dict(row) for row in compute],
        "provider_request_count": len(provider_rows),
        "input_tokens": sum(int(row.get("input_tokens") or 0) for row in serial),
        "output_tokens": sum(int(row.get("output_tokens") or 0) for row in serial),
        "cost_usd": round(sum(float(row.get("estimated_cost_usd") or 0) for row in serial), 8),
    }


def _cases() -> list[dict]:
    tasks = _load_tasks()
    ordered = [tasks["d16381-summary"]]
    ordered.append({
        "query_id": "conv-d381-summary-clarify:t2",
        "filename": "doh-16-381.pdf",
        "query": "یعنی چی؟",
        "task_type": "conversation_followup",
        "expected_intent": "conversational_followup",
        "expected_route": "conversational_followup",
        "answerability": "answerable",
        "acceptable_answers": ["توضیح ساده همان خلاصه قبلی"],
        "required_concepts": ["بازیافت آب", "بیمارستان"],
        "forbidden_claims": ["funding"],
        "relevant_pages": [1, 5, 7, 8, 9, 11, 12],
        "retrieval_policy": "forbidden",
        "citation_expectation": {"required": True, "expected_pages": [1, 5, 7, 8, 9, 11, 12]},
        "conversation_key": "summary",
        "followup": True,
    })
    ordered.extend(tasks[item] for item in SINGLE_CASE_IDS[1:])
    ordered.append({
        "query_id": "conv-fx005-ambiguous:t1",
        "filename": "fixture-005-ambiguous-followup.pdf",
        "query": "موعد و بررسی امنیتی آلفا و بتا را مقایسه کن.",
        "task_type": "conversation_initial",
        "expected_intent": "compare",
        "expected_route": "analytical",
        "answerability": "answerable",
        "acceptable_answers": ["آلفا ۱۵ مهر و ده روز؛ بتا ۳۰ مهر و چهارده روز"],
        "required_concepts": ["آلفا", "بتا", "۱۵ مهر", "۳۰ مهر", "ده روز", "چهارده روز"],
        "forbidden_claims": [],
        "relevant_pages": [1, 2],
        "retrieval_policy": "required",
        "citation_expectation": {"required": True, "expected_pages": [1, 2]},
        "conversation_key": "ambiguous",
    })
    ordered.append({
        "query_id": "conv-fx005-ambiguous:t2",
        "filename": "fixture-005-ambiguous-followup.pdf",
        "query": "آن را زودتر تحویل بدهند؟",
        "task_type": "conversation_followup",
        "expected_intent": "conversational_followup",
        "expected_route": "conversational_followup",
        "answerability": "ambiguous",
        "acceptable_answers": ["منظور پروژه آلفاست یا بتا؟"],
        "required_concepts": ["آلفا", "بتا", "منظور"],
        "forbidden_claims": ["انتخاب قطعی آلفا", "انتخاب قطعی بتا"],
        "relevant_pages": [1, 2, 3],
        "retrieval_policy": "forbidden",
        "citation_expectation": {"required": False, "expected_pages": [1, 2, 3]},
        "conversation_key": "ambiguous",
        "followup": True,
    })
    if len(ordered) != 15:
        raise AssertionError(f"core subset must contain 15 endpoint requests, got {len(ordered)}")
    return ordered


def plan(run_dir: Path, storage_state: Path, preflight_passed: bool) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    session = _session(storage_state)
    assets = session.get(f"{BASE_URL}/api/gallery/assets", timeout=15).json().get("assets", [])
    existing_ids = [str(row["id"]) for row in assets]
    user_id = _resolve_user_id(existing_ids) if existing_ids else _authenticated_user_id(session)
    projected_input = 225_000
    projected_output = 24_000
    projected_cost = projected_input * 0.30 / 1_000_000 + projected_output * 2.50 / 1_000_000
    state = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": ENDPOINT,
        "endpoint_request_count": 15,
        "endpoint_attempt_count": 0,
        "estimated_provider_input_tokens": projected_input,
        "estimated_provider_output_tokens": projected_output,
        "projected_cost_usd": round(projected_cost, 6),
        "target_cost_usd": TARGET_USD,
        "hard_cap_usd": HARD_CAP_USD,
        "preflight_passed": preflight_passed,
        "user_id": user_id,
        "asset_ids": {},
        "cases": [case["query_id"] for case in _cases()],
    }
    if not preflight_passed:
        raise RuntimeError("Refusing to create paid-run plan until deterministic tests pass")
    _write_json(_state_path(run_dir), state)
    _write_json(run_dir / "cost-ledger.json", {"estimate": state, "actual": _usage(state)})
    print(json.dumps({key: state[key] for key in ("endpoint_request_count", "estimated_provider_input_tokens", "estimated_provider_output_tokens", "projected_cost_usd", "hard_cap_usd")}, indent=2))


def prepare(run_dir: Path, storage_state: Path) -> None:
    state = _load_state(run_dir)
    if not state.get("preflight_passed"):
        raise RuntimeError("Preflight is not recorded as passed")
    if state["projected_cost_usd"] >= HARD_CAP_USD:
        raise RuntimeError("Projected cost exceeds hard cap")
    session = _session(storage_state)
    user_id = _authenticated_user_id(session)
    assets = session.get(f"{BASE_URL}/api/gallery/assets", timeout=15).json().get("assets", [])
    by_filename = {}
    for item in assets:
        by_filename.setdefault(item["filename"], []).append(item)
    missing = []
    asset_ids = {}
    for filename in FILES:
        source = ROOT / "composite_goldset_pdfs" / filename
        size = source.stat().st_size
        match = next(
            (
                row
                for row in by_filename.get(filename, [])
                if int(row.get("size_bytes") or 0) == size
                and row.get("status") in {"uploaded", "scanning", "scanned"}
                and _asset_matches_source(str(row["id"]), user_id=user_id, source=source)
            ),
            None,
        )
        if match:
            asset_ids[filename] = str(match["id"])
        else:
            missing.append(filename)
    if missing:
        handles = []
        try:
            files = []
            for filename in missing:
                handle = (ROOT / "composite_goldset_pdfs" / filename).open("rb")
                handles.append(handle)
                files.append(("files", (filename, handle, "application/pdf")))
            response = session.post(f"{BASE_URL}/api/gallery/upload", files=files, timeout=120)
            response.raise_for_status()
            for item in response.json().get("created", []):
                asset_ids[item["filename"]] = str(item["id"])
        finally:
            for handle in handles:
                handle.close()
    state["asset_ids"] = asset_ids
    state["user_id"] = user_id
    state["asset_source_mapping"] = {
        filename: {
            "asset_id": asset_id,
            "user_id": user_id,
            "source_sha256": _source_sha256(ROOT / "composite_goldset_pdfs" / filename),
        }
        for filename, asset_id in asset_ids.items()
    }
    state["prepared_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(_state_path(run_dir), state)
    ledger = _usage(state)
    _write_json(run_dir / "cost-ledger.json", {"estimate": state, "actual": ledger})
    print(json.dumps({"assets": len(asset_ids), "uploaded_now": len(missing), "statuses": "scan asynchronously", "cost_usd": ledger["cost_usd"]}, indent=2))


def status(run_dir: Path, storage_state: Path) -> None:
    state = _load_state(run_dir)
    session = _session(storage_state)
    assets = session.get(f"{BASE_URL}/api/gallery/assets", timeout=15).json().get("assets", [])
    by_id = {str(row["id"]): row for row in assets}
    statuses = {
        filename: {
            "id": asset_id,
            "status": by_id.get(asset_id, {}).get("status", "missing"),
            "chunk_count": by_id.get(asset_id, {}).get("chunk_count", 0),
            "warning": by_id.get(asset_id, {}).get("warning"),
        }
        for filename, asset_id in state.get("asset_ids", {}).items()
    }
    ledger = _usage(state)
    _write_json(run_dir / "asset-status.json", statuses)
    _write_json(run_dir / "cost-ledger.json", {"estimate": state, "actual": ledger})
    print(json.dumps({"ready": all(row["status"] == "scanned" for row in statuses.values()), "assets": statuses, "cost_usd": ledger["cost_usd"]}, ensure_ascii=False, indent=2))


def _stream_request(session: requests.Session, case: dict, asset_id: str, conversation_id: str | None) -> tuple[list[dict], float]:
    body = {"question": case["query"], "scope": "selected", "asset_ids": [asset_id]}
    if conversation_id:
        body["conversation_id"] = conversation_id
    started = time.perf_counter()
    response = session.post(ENDPOINT, json=body, timeout=(10, 420), stream=True)
    if not response.ok:
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": "non-JSON HTTP error"}
        return [{
            "type": "http_error",
            "status_code": response.status_code,
            "error": payload.get("error") if isinstance(payload, dict) else "HTTP error",
        }], (time.perf_counter() - started) * 1000
    events = []
    for line in response.iter_lines(decode_unicode=True):
        if line and line.strip():
            events.append(json.loads(line))
    return events, (time.perf_counter() - started) * 1000


def _pages(sources: list[str]) -> list[int]:
    pages = set()
    for source in sources:
        for match in PAGE_RE.finditer(source):
            start = int(match.group(1).translate(DIGITS))
            end = int((match.group(2) or match.group(1)).translate(DIGITS))
            pages.update(range(min(start, end), max(start, end) + 1))
    return sorted(pages)


def _score(case: dict, events: list[dict], latency_ms: float, asset_id: str) -> dict:
    final = next((event for event in reversed(events) if event.get("type") == "final"), {})
    plan_event = next((event for event in events if event.get("type") == "trace" and event.get("stage") == "agent_plan"), {})
    conversation_event = next((event for event in events if event.get("type") == "conversation"), {})
    answer = final.get("answer") or ""
    sources = final.get("sources") or []
    metadata = final.get("metadata") or {}
    request_plan = metadata.get("request_plan") or {}
    actual_intent = plan_event.get("intent") or request_plan.get("intent") or metadata.get("intent")
    actual_route = (
        plan_event.get("route")
        or metadata.get("telemetry", {}).get("evaluation_route")
        or request_plan.get("route")
    )
    generation = score_generation(case, answer)
    cited_pages = _pages(sources)
    expected_pages = set(case.get("relevant_pages", []))
    expected_filename = case["filename"]
    citation_required = bool(case.get("citation_expectation", {}).get("required"))
    citation_valid = all(isinstance(item, str) and PAGE_RE.search(item) for item in sources) if sources else not citation_required
    citation_document_correct = all(expected_filename in item for item in sources) if sources else not citation_required
    cited_page_set = set(cited_pages)
    citation_page_correct = (
        bool(cited_page_set)
        and cited_page_set.issubset(expected_pages)
        if citation_required else True
    )
    retrieval = metadata.get("retrieval") or {}
    strategy = metadata.get("strategy")
    retrieval_called = bool(metadata.get("retrieved_chunks") or metadata.get("evidence_items"))
    if strategy in {"previous_answer_citation_reuse", "previous_answer_only"}:
        retrieval_called = False
    concept_threshold = 1.0
    concepts_covered = generation["required_concept_coverage"] >= concept_threshold
    answer_correct = generation["acceptable_answer_match"] and not generation["forbidden_claim"]
    minimum_citations = int(case.get("citation_expectation", {}).get("minimum_citations") or 1)
    all_required_claims_cited = (
        len(sources) >= minimum_citations
        and citation_page_correct
        if citation_required else True
    )
    telemetry = metadata.get("telemetry") or {}
    record = {
        "query_id": case["query_id"],
        "filename": expected_filename,
        "asset_id": asset_id,
        "expected_intent": case.get("expected_intent"),
        "actual_intent": actual_intent,
        "expected_route": case["expected_route"],
        "actual_route": actual_route,
        "retrieval_policy": case["retrieval_policy"],
        "retrieval_called": retrieval_called,
        "document_operations": {
            key: int(telemetry.get(key) or 0)
            for key in ("retrieval_calls", "embedding_calls", "rewrite_calls", "reranker_calls")
        },
        "rewrite_expected": case.get("task_type") == "cross_language",
        "rewrite_correct": bool(retrieval.get("rewrite_used")) == (case.get("task_type") == "cross_language"),
        "reranker_expected": case["expected_route"] in {"focused_rag", "analytical"} and case["retrieval_policy"] == "required",
        "reranker_called": int(retrieval.get("reranker_count") or 0) > 0,
        "answer": answer,
        "sources": sources,
        "cited_pages": cited_pages,
        "metadata": metadata,
        "latency_ms": latency_ms,
        "conversation_id": (conversation_event.get("conversation") or {}).get("id"),
        "generation_score": generation,
        "citation_required": citation_required,
        "citation_valid": citation_valid,
        "citation_document_correct": citation_document_correct,
        "citation_page_correct": citation_page_correct,
        "all_required_claims_cited": all_required_claims_cited,
        "contains_numeric_claim": case.get("task_type") in {"table_or_numerical", "local_factual"},
        "unsupported_numeric_citation_failure": bool(case.get("task_type") in {"table_or_numerical", "local_factual"} and answer_correct and not sources),
        "metadata_only_citation_failure": bool(sources and not cited_pages),
        "route_correct": actual_route == case["expected_route"],
        "evidence_available": bool(
            sources
            or metadata.get("retrieved_chunks")
            or metadata.get("evidence_items")
            or metadata.get("history_resolved")
        ),
        "answer_correct": bool(answer_correct),
        "required_concepts_covered": bool(concepts_covered),
        "grounded": bool((not citation_required or sources) and not generation["forbidden_claim"]),
        "citations_correct": bool(
            citation_valid
            and citation_document_correct
            and citation_page_correct
            and all_required_claims_cited
        ),
        "output_complete": bool(answer.strip() and not generation["generic_failure"] and not generation["truncation"]),
        "no_internal_message_exposed": not bool(INTERNAL_MESSAGE_RE.search(answer)),
    }
    if case.get("task_type") == "comprehensive_summary":
        record["summary_score"] = score_summary(case, answer, cited_pages)
    return record


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _aggregate(results: list[dict], state: dict) -> dict:
    task_by_id = {case["query_id"]: case for case in _cases()}
    ranking_qrels = {}
    ranking_run = {}
    for result in results:
        case = task_by_id[result["query_id"]]
        if not case.get("relevant_pages"):
            continue
        judgments = {
            f"{case.get('document_sha256', case['filename'])}#page={page}": 3 if index == 0 else 2
            for index, page in enumerate(case["relevant_pages"])
        }
        ranking_qrels[result["query_id"]] = judgments
        ranking_run[result["query_id"]] = [
            f"{case.get('document_sha256', case['filename'])}#page={page}"
            for page in result["cited_pages"]
        ]
    conversation_results = []
    for result in results:
        case = task_by_id[result["query_id"]]
        if case.get("task_type") != "conversation_followup":
            continue
        conversation_results.append({
            "followup_resolved": result["actual_route"] == "conversational_followup" and result["answer_correct"],
            "history_used_correctly": bool(result["metadata"].get("history_resolved")),
            "retrieval_policy": case["retrieval_policy"],
            "retrieval_called": result["retrieval_called"],
            "selected_asset_persisted": True,
            "conversation_id_persisted": bool(result["conversation_id"]),
        })
    summaries = [row["summary_score"] for row in results if row.get("summary_score")]
    latency = [row["latency_ms"] for row in results]
    usage = _usage(state)
    report = {
        "run_kind": "production_path_core_subset",
        "endpoint": ENDPOINT,
        "endpoint_request_count": len(results),
        "endpoint_attempt_count": int(state.get("endpoint_attempt_count") or len(results)),
        "core_subset": [row["query_id"] for row in results],
        "retrieval": evaluate_rankings(ranking_qrels, ranking_run),
        "routing": evaluate_routing(results),
        "generation": aggregate_generation([row["generation_score"] for row in results]),
        "summary": {
            "task_count": len(summaries),
            "substantive_section_coverage_mean": statistics.fmean(row["substantive_section_coverage"] for row in summaries) if summaries else 0,
            "key_claim_recall_mean": statistics.fmean(row["key_claim_recall"] for row in summaries) if summaries else 0,
            "conclusion_coverage": proportion_result(sum(row["conclusion_coverage"] for row in summaries), len(summaries)),
            "contamination_rate_mean": statistics.fmean(row["contamination_rate"] for row in summaries) if summaries else 0,
            "page_range_diversity_mean": statistics.fmean(row["page_range_diversity"] for row in summaries) if summaries else 0,
            "comprehensive_summary_pass": proportion_result(sum(row["comprehensive_summary_pass"] for row in summaries), len(summaries)),
        },
        "citations": evaluate_citations(results),
        "conversations": evaluate_conversations(conversation_results),
        "grounded_task_success": aggregate_grounded_task_success(results),
        "latency_ms": {
            "p50": _percentile(latency, 0.50),
            "p95": _percentile(latency, 0.95),
            "count": len(latency),
        },
        "usage": usage,
        "hard_cap_respected": usage["cost_usd"] <= HARD_CAP_USD,
        "results": results,
    }
    return report


def run(run_dir: Path, storage_state: Path) -> None:
    state = _load_state(run_dir)
    if set(state.get("asset_ids", {})) != set(FILES):
        raise RuntimeError("Prepared asset set is incomplete")
    for filename, asset_id in state["asset_ids"].items():
        asset = db.get_asset(asset_id)
        mapping = (state.get("asset_source_mapping") or {}).get(filename) or {}
        source = ROOT / "composite_goldset_pdfs" / filename
        if (
            not asset
            or asset["status"] != "scanned"
            or not _asset_matches_source(asset_id, user_id=int(state["user_id"]), source=source)
            or mapping.get("source_sha256") != _source_sha256(source)
        ):
            raise RuntimeError(f"Asset not ready: {filename}")
    initial_usage = _usage(state)
    if initial_usage["cost_usd"] >= HARD_CAP_USD:
        raise RuntimeError("Hard cost cap already reached")
    session = _session(storage_state)
    results = []
    conversation_ids: dict[str, str] = {}
    for index, case in enumerate(_cases(), start=1):
        usage_before = _usage(state)
        if usage_before["cost_usd"] >= HARD_CAP_USD:
            break
        conversation_key = case.get("conversation_key")
        if case["query_id"] == "d16381-summary":
            conversation_key = "summary"
        conversation_id = conversation_ids.get(conversation_key) if conversation_key else None
        events, latency_ms = _stream_request(
            session,
            case,
            state["asset_ids"][case["filename"]],
            conversation_id,
        )
        _write_json(run_dir / "responses" / f"{index:02d}-{case['query_id'].replace(':', '-')}.json", events)
        scored = _score(case, events, latency_ms, state["asset_ids"][case["filename"]])
        results.append(scored)
        if conversation_key and scored.get("conversation_id"):
            conversation_ids[conversation_key] = scored["conversation_id"]
        usage_after = _usage(state)
        _write_json(run_dir / "cost-ledger.json", {"estimate": state, "actual": usage_after})
        print(json.dumps({"completed": index, "case": case["query_id"], "route": scored["actual_route"], "latency_ms": round(latency_ms), "cost_usd": usage_after["cost_usd"]}, ensure_ascii=False), flush=True)
    report = _aggregate(results, state)
    state["endpoint_attempt_count"] = int(state.get("endpoint_attempt_count") or 0) + len(results)
    _write_json(_state_path(run_dir), state)
    report["endpoint_attempt_count"] = state["endpoint_attempt_count"]
    _write_json(run_dir / "production-baseline.json", report)
    _write_json(run_dir / "cost-ledger.json", {"estimate": state, "actual": report["usage"]})
    print(json.dumps({
        "completed": len(results),
        "cost_usd": report["usage"]["cost_usd"],
        "input_tokens": report["usage"]["input_tokens"],
        "output_tokens": report["usage"]["output_tokens"],
        "gts": report["grounded_task_success"]["overall"],
        "latency_ms": report["latency_ms"],
    }, ensure_ascii=False, indent=2))


def resume_rate_limited(run_dir: Path, storage_state: Path) -> None:
    """Run each locally rate-limited core case once, preserving earlier outcomes."""
    state = _load_state(run_dir)
    prior_report_path = run_dir / "production-baseline.json"
    if not prior_report_path.exists():
        raise RuntimeError("No prior production run exists")
    prior_report = json.loads(prior_report_path.read_text(encoding="utf-8"))
    by_query = {row["query_id"]: row for row in prior_report.get("results", [])}
    cases = _cases()
    retry_cases = []
    for index, case in enumerate(cases, start=1):
        response_path = run_dir / "responses" / f"{index:02d}-{case['query_id'].replace(':', '-')}.json"
        events = json.loads(response_path.read_text(encoding="utf-8"))
        if any(event.get("type") == "http_error" and event.get("status_code") == 429 for event in events):
            retry_cases.append((index, case))
    if not retry_cases:
        raise RuntimeError("No locally rate-limited cases remain")
    session = _session(storage_state)
    conversation_ids: dict[str, str] = {}
    attempts = 0
    for index, case in retry_cases:
        if _usage(state)["cost_usd"] >= HARD_CAP_USD:
            break
        time.sleep(1.2)
        conversation_key = case.get("conversation_key")
        events, latency_ms = _stream_request(
            session,
            case,
            state["asset_ids"][case["filename"]],
            conversation_ids.get(conversation_key) if conversation_key else None,
        )
        attempts += 1
        _write_json(run_dir / "responses" / f"resume-{index:02d}-{case['query_id'].replace(':', '-')}.json", events)
        if any(event.get("type") == "http_error" and event.get("status_code") == 429 for event in events):
            raise RuntimeError(f"Case remained rate-limited; no further retry: {case['query_id']}")
        scored = _score(case, events, latency_ms, state["asset_ids"][case["filename"]])
        by_query[case["query_id"]] = scored
        if conversation_key and scored.get("conversation_id"):
            conversation_ids[conversation_key] = scored["conversation_id"]
        usage_after = _usage(state)
        _write_json(run_dir / "cost-ledger.json", {"estimate": state, "actual": usage_after})
        print(json.dumps({"resumed": index, "case": case["query_id"], "route": scored["actual_route"], "latency_ms": round(latency_ms), "cost_usd": usage_after["cost_usd"]}, ensure_ascii=False), flush=True)
    state["endpoint_attempt_count"] = int(state.get("endpoint_attempt_count") or 0) + attempts
    _write_json(_state_path(run_dir), state)
    results = [by_query[case["query_id"]] for case in cases]
    report = _aggregate(results, state)
    report["rate_limited_attempts_excluded_from_core_outcomes"] = len(retry_cases)
    _write_json(run_dir / "production-baseline.json", report)
    _write_json(run_dir / "cost-ledger.json", {"estimate": state, "actual": report["usage"]})
    print(json.dumps({
        "core_outcomes": len(results),
        "endpoint_attempts": state["endpoint_attempt_count"],
        "rate_limited_attempts": len(retry_cases),
        "cost_usd": report["usage"]["cost_usd"],
        "gts": report["grounded_task_success"]["overall"],
    }, ensure_ascii=False, indent=2))


def rescore(run_dir: Path) -> None:
    """Recompute deterministic metrics from stored endpoint responses, without calls."""
    state = _load_state(run_dir)
    prior = json.loads((run_dir / "production-baseline.json").read_text(encoding="utf-8"))
    prior_by_query = {row["query_id"]: row for row in prior.get("results", [])}
    response_files = list((run_dir / "responses").glob("*.json"))
    state["endpoint_attempt_count"] = len(response_files)
    results = []
    rate_limited = 0
    for index, case in enumerate(_cases(), start=1):
        stem = f"{index:02d}-{case['query_id'].replace(':', '-')}.json"
        original = run_dir / "responses" / stem
        resumed = run_dir / "responses" / f"resume-{stem}"
        original_events = json.loads(original.read_text(encoding="utf-8"))
        rate_limited += int(any(
            event.get("type") == "http_error" and event.get("status_code") == 429
            for event in original_events
        ))
        events = json.loads((resumed if resumed.exists() else original).read_text(encoding="utf-8"))
        latency_ms = float(prior_by_query.get(case["query_id"], {}).get("latency_ms") or 0)
        results.append(_score(case, events, latency_ms, state["asset_ids"][case["filename"]]))
    _write_json(_state_path(run_dir), state)
    report = _aggregate(results, state)
    report["rate_limited_attempts_excluded_from_core_outcomes"] = rate_limited
    _write_json(run_dir / "production-baseline.json", report)
    _write_json(run_dir / "cost-ledger.json", {"estimate": state, "actual": report["usage"]})
    print(json.dumps({
        "core_outcomes": len(results),
        "endpoint_attempts": state["endpoint_attempt_count"],
        "provider_requests": report["usage"]["provider_request_count"],
        "cost_usd": report["usage"]["cost_usd"],
        "gts": report["grounded_task_success"]["overall"],
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=["plan", "prepare", "status", "run", "resume-rate-limited", "rescore"],
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--storage-state",
        type=Path,
        default=ROOT / "tmp" / "rag-quality-goal" / "e2e-auth" / "e2e-storage-state.json",
    )
    parser.add_argument("--preflight-passed", action="store_true")
    args = parser.parse_args()
    {
        "plan": lambda: plan(args.run_dir, args.storage_state, args.preflight_passed),
        "prepare": lambda: prepare(args.run_dir, args.storage_state),
        "status": lambda: status(args.run_dir, args.storage_state),
        "run": lambda: run(args.run_dir, args.storage_state),
        "resume-rate-limited": lambda: resume_rate_limited(args.run_dir, args.storage_state),
        "rescore": lambda: rescore(args.run_dir),
    }[args.action]()


if __name__ == "__main__":
    main()
