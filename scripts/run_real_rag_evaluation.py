"""Staged, budgeted E2E evaluation over the two private quality PDFs.

The runner creates a uniquely named user/assets, records every test identifier,
and can remove only those exact rows and Qdrant points. Originals are copied and
never modified. Evaluation artifacts live under the git-ignored quality folder.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
import rag  # noqa: E402
import scan_worker  # noqa: E402
import storage  # noqa: E402
from backend.app.agents import rag_graph  # noqa: E402
from backend.app.services.usage_tracking import usage_context  # noqa: E402


SOURCE_DIR = Path(r"C:\Users\ashkriz\Downloads\New folder")
ARTIFACT_DIR = ROOT / "tmp" / "rag-quality-goal" / "20260722-2015"
STATE_PATH = ARTIFACT_DIR / "real-e2e-state.json"
HARD_CAP_USD = 1.00
TARGET_CAP_USD = 0.50
PHASE_CEILINGS = {"stage1": 0.065, "stage2": 0.20}

FILES = {
    "epr": "einsteinetal1935.pdf",
    "fa": "بررس ی انتقادی رو یکرد فلسفی د یوی د بوهم.pdf",
}


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _load_state() -> dict:
    if not STATE_PATH.exists():
        raise RuntimeError("No E2E state exists. Run setup first.")
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _db_counts() -> dict:
    with db.get_db() as conn:
        return {
            "users": int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]),
            "assets": int(conn.execute("SELECT COUNT(*) AS n FROM assets").fetchone()["n"]),
            "usage_events": int(conn.execute("SELECT COUNT(*) AS n FROM usage_events").fetchone()["n"]),
            "compute_usage_events": int(conn.execute("SELECT COUNT(*) AS n FROM compute_usage_events").fetchone()["n"]),
        }


def _test_point_count(state: dict) -> int:
    return sum(
        len(rag.vector_store.list_chunks({"document_id": asset_id, "user_id": state["user_id"]}, limit=200))
        for asset_id in state["assets"].values()
    )


def setup() -> None:
    if STATE_PATH.exists():
        state = _load_state()
        if all(db.get_asset(asset_id) for asset_id in state["assets"].values()):
            print(json.dumps({"status": "already_setup", "state": state}, ensure_ascii=False, indent=2))
            return

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = "rqg-" + uuid.uuid4().hex[:12]
    phone = "+9899" + str(int(uuid.uuid4().hex[:9], 16))[:9]
    before = {"db": _db_counts(), "qdrant_points": rag.indexed_chunk_count()}
    user = db.get_or_create_user(phone)
    user_id = int(user["id"])
    state = {
        "run_id": run_id,
        "phone": phone,
        "user_id": user_id,
        "assets": {key: f"{run_id}-{key}" for key in FILES},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "before": before,
    }
    _write_json(STATE_PATH, state)

    isolated_root = (ARTIFACT_DIR / "isolated-runtime" / run_id).resolve()
    storage.STORAGE_ROOT = str(isolated_root / "storage")
    copies = isolated_root / "originals"
    copies.mkdir(parents=True, exist_ok=True)
    try:
        for key, filename in FILES.items():
            source = SOURCE_DIR / filename
            target = copies / filename
            shutil.copy2(source, target)
            asset_id = state["assets"][key]
            db.create_asset(
                asset_id, user_id, "text", filename, ".pdf", target.stat().st_size,
                str(target), status="scanning",
            )
            with usage_context(
                request_id=f"{run_id}-ingest-{key}", user_id=user_id,
                feature="quality_evaluation", metadata={"quality_run": run_id, "asset_key": key},
            ):
                scan_worker._process_text_asset(db.get_asset(asset_id))
            asset = db.get_asset(asset_id)
            if not asset or asset["status"] != "scanned":
                raise RuntimeError(f"Asset {key} did not scan successfully: {dict(asset or {})}")
        state["isolated_root"] = str(isolated_root)
        state["after_setup"] = {
            "db": _db_counts(),
            "qdrant_points": rag.indexed_chunk_count(),
            "test_points": _test_point_count(state),
            "assets": {
                key: {
                    "id": asset_id,
                    "status": db.get_asset(asset_id)["status"],
                    "chunks": db.get_asset(asset_id)["chunk_count"],
                    "processing_version": db.get_asset(asset_id)["processing_version"],
                    "quality_status": db.get_asset(asset_id)["quality_status"],
                }
                for key, asset_id in state["assets"].items()
            },
        }
        _write_json(STATE_PATH, state)
        print(json.dumps(state["after_setup"], ensure_ascii=False, indent=2))
    except Exception:
        _write_json(STATE_PATH, state)
        raise


def _usage_rows(run_id: str) -> list[dict]:
    with db.get_db() as conn:
        rows = conn.execute(
            """SELECT request_id, operation_type, provider, model, input_tokens,
                      output_tokens, estimated_cost_usd, status, error_type
                 FROM usage_events WHERE request_id LIKE %s ORDER BY created_at""",
            (run_id + "-%",),
        ).fetchall()
    return [dict(row) for row in rows]


def _conservative_cost(rows: list[dict]) -> float:
    total = 0.0
    for row in rows:
        if row.get("operation_type") != "chat_completion" or row.get("status") != "success":
            continue
        reported = float(row.get("estimated_cost_usd") or 0)
        model = str(row.get("model") or "")
        if "gemini-2.5-flash" in model:
            calculated = int(row.get("input_tokens") or 0) * 0.30 / 1_000_000 + int(row.get("output_tokens") or 0) * 2.50 / 1_000_000
        elif "glm-5.2" in model:
            calculated = int(row.get("input_tokens") or 0) * 0.93 / 1_000_000 + int(row.get("output_tokens") or 0) * 3.00 / 1_000_000
        else:
            calculated = 0.0
        total += max(reported, calculated)
    return round(total, 8)


def _pages(sources: list[str]) -> list[int]:
    pages: set[int] = set()
    for source in sources or []:
        match = re.search(r"(?:صفحه|صفحات)\s*(\d+)(?:\s*تا\s*(\d+))?", source)
        if not match:
            continue
        start, end = int(match.group(1)), int(match.group(2) or match.group(1))
        pages.update(range(min(start, end), max(start, end) + 1))
    return sorted(pages)


def _run_case(state: dict, stage: str, case: dict, history=None) -> dict:
    asset_ids = [state["assets"][key] for key in case["assets"]]
    request_id = f"{state['run_id']}-{stage}-{case['id']}"
    with usage_context(
        request_id=request_id, user_id=state["user_id"], feature="quality_evaluation",
        metadata={"quality_run": state["run_id"], "case_id": case["id"], "stage": stage},
    ):
        result = rag_graph.answer_request(
            case["question"], scope="selected", asset_ids=asset_ids,
            user_id=state["user_id"], conversation_history=history or [],
        )
    answer = result.get("answer") or ""
    sources = result.get("sources") or []
    pages = _pages(sources)
    expected_pages = case.get("expected_pages") or []
    concepts = case.get("concepts") or []
    return {
        **case,
        "request_id": request_id,
        "answer": answer,
        "sources": sources,
        "pages": pages,
        "metadata": result.get("metadata") or {},
        "checks": {
            "has_answer": bool(answer.strip()),
            "has_citation_or_safe_no_answer": bool(re.search(r"\[S\d+\]", answer)) or not sources,
            "expected_page_hit": not expected_pages or bool(set(pages) & set(expected_pages)),
            "concept_hits": [concept for concept in concepts if concept.casefold() in answer.casefold()],
            "no_internal_error_text": not re.search(r"traceback|provider|api error|fallback_generation|context_hash", answer, re.IGNORECASE),
        },
    }


def run_stage(stage: str) -> None:
    state = _load_state()
    current_rows = _usage_rows(state["run_id"])
    current_cost = _conservative_cost(current_rows)
    if current_cost >= HARD_CAP_USD:
        raise RuntimeError(f"Hard budget cap reached before {stage}: ${current_cost:.6f}")

    if stage == "stage1":
        cases = [
            {"id": "epr_fact", "assets": ["epr"], "question": "What criterion of physical reality do the authors propose?", "expected_pages": [1], "concepts": ["certainty", "disturbing"]},
            {"id": "fa_conclusion", "assets": ["fa"], "question": "نتیجه‌گیری مقاله چیست؟", "expected_pages": [15, 16, 17], "concepts": ["علیت", "جهل", "متغیرهای پنهان"]},
            {"id": "epr_global", "assets": ["epr"], "question": "Summarize the complete argument section by section.", "expected_pages": [1, 2, 3, 4], "concepts": ["reality", "complete", "particle"]},
        ]
    else:
        cases = [
            {"id": "fa_numeric", "assets": ["fa"], "question": "بوهم در چه سالی صورت‌بندی علی نظریه کوانتوم را ارائه داد؟", "expected_pages": [7], "concepts": ["1952"]},
            {"id": "fa_compare", "assets": ["fa"], "question": "دیدگاه بوهم درباره علیت را با فلسفه ملاصدرا مقایسه کن.", "expected_pages": [7, 11, 13, 16, 17], "concepts": ["متغیرهای پنهان", "اصالت وجود", "علیت"]},
            {"id": "fa_global", "assets": ["fa"], "question": "خلاصه جامع و بخش‌به‌بخش کل مقاله را بده.", "expected_pages": [1, 3, 7, 11, 13, 17], "concepts": ["مقدمه", "بوهم", "ملاصدرا", "نتیجه"]},
            {"id": "epr_cross_language", "assets": ["epr"], "question": "معیار واقعیت فیزیکی در این مقاله چیست؟", "expected_pages": [1], "concepts": ["یقین", "اختلال"]},
            {"id": "epr_unanswerable", "assets": ["epr"], "question": "What conclusion do the authors draw about Bell's inequality?", "expected_pages": [], "concepts": []},
            {"id": "fa_quoted", "assets": ["fa"], "question": "در جمله «اصل علیت بدیهی است» یعنی چی؟", "expected_pages": [15, 16], "concepts": ["علیت"]},
        ]

    results = []
    for case in cases:
        results.append(_run_case(state, stage, case))
        cost = _conservative_cost(_usage_rows(state["run_id"]))
        if cost >= HARD_CAP_USD:
            raise RuntimeError(f"Hard budget cap reached during {stage}: ${cost:.6f}")

    if stage == "stage1":
        previous = results[1]
        followup = {
            "id": "fa_followup", "assets": ["fa"], "question": "یعنی چی؟",
            "expected_pages": previous["pages"], "concepts": ["علیت"],
        }
        history = [{"role": "assistant", "content": previous["answer"], "sources": previous["sources"]}]
        results.append(_run_case(state, stage, followup, history=history))

    rows = _usage_rows(state["run_id"])
    actual = _conservative_cost(rows)
    report = {
        "stage": stage,
        "phase_ceiling_usd": PHASE_CEILINGS[stage],
        "target_cap_usd": TARGET_CAP_USD,
        "hard_cap_usd": HARD_CAP_USD,
        "cumulative_conservative_cost_usd": actual,
        "within_phase_ceiling": actual <= PHASE_CEILINGS[stage],
        "fallback_calls": sum(
            1 for item in results
            if ((item.get("metadata") or {}).get("generation") or {}).get("fallback_used")
        ),
        "results": results,
        "usage_rows": rows,
    }
    _write_json(ARTIFACT_DIR / f"real-{stage}-results.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


def recheck_global() -> None:
    state = _load_state()
    case = {
        "id": "epr_global_recheck", "assets": ["epr"],
        "question": "Summarize the complete argument section by section.",
        "expected_pages": [1, 2, 3, 4], "concepts": ["reality", "complete", "particle"],
    }
    result = _run_case(state, "stage1", case)
    report = {
        "cumulative_conservative_cost_usd": _conservative_cost(_usage_rows(state["run_id"])),
        "result": result,
    }
    _write_json(ARTIFACT_DIR / "real-stage1-global-recheck.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


def recheck_fa_global() -> None:
    state = _load_state()
    case = {
        "id": "fa_global_recheck", "assets": ["fa"],
        "question": "خلاصه جامع و بخش‌به‌بخش کل مقاله را بده.",
        "expected_pages": [1, 3, 7, 11, 13, 17],
        "concepts": ["مقدمه", "بوهم", "ملاصدرا", "نتیجه"],
    }
    result = _run_case(state, "stage2", case)
    report = {
        "cumulative_conservative_cost_usd": _conservative_cost(_usage_rows(state["run_id"])),
        "result": result,
    }
    _write_json(ARTIFACT_DIR / "real-stage2-fa-global-recheck.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


def cleanup() -> None:
    state = _load_state()
    deleted_points = {
        key: rag.delete_document_index(asset_id, user_id=state["user_id"])
        for key, asset_id in state["assets"].items()
    }
    with db.get_db() as conn:
        for asset_id in state["assets"].values():
            conn.execute("DELETE FROM document_unit_summaries WHERE asset_id = %s", (asset_id,))
            conn.execute("DELETE FROM assets WHERE id = %s AND user_id = %s", (asset_id, state["user_id"]))
        conn.execute("DELETE FROM usage_events WHERE request_id LIKE %s", (state["run_id"] + "-%",))
        conn.execute("DELETE FROM compute_usage_events WHERE request_id LIKE %s", (state["run_id"] + "-%",))
        conn.execute("DELETE FROM users WHERE id = %s AND phone = %s", (state["user_id"], state["phone"]))
    isolated_root = Path(state.get("isolated_root") or "").resolve()
    allowed_root = ARTIFACT_DIR.resolve()
    if isolated_root != allowed_root and allowed_root in isolated_root.parents and isolated_root.exists():
        shutil.rmtree(isolated_root)
    verification = {
        "deleted_points": deleted_points,
        "remaining_test_points": _test_point_count(state),
        "remaining_assets": [asset_id for asset_id in state["assets"].values() if db.get_asset(asset_id)],
        "remaining_user": bool(db.get_user_by_id(state["user_id"])),
        "final_db": _db_counts(),
        "final_qdrant_points": rag.indexed_chunk_count(),
    }
    _write_json(ARTIFACT_DIR / "real-cleanup-verification.json", verification)
    print(json.dumps(verification, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["setup", "stage1", "recheck-global", "stage2", "recheck-fa-global", "cleanup"])
    args = parser.parse_args()
    {"setup": setup, "stage1": lambda: run_stage("stage1"), "recheck-global": recheck_global, "stage2": lambda: run_stage("stage2"), "recheck-fa-global": recheck_fa_global, "cleanup": cleanup}[args.action]()


if __name__ == "__main__":
    main()
