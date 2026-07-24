"""Generation-free audit of the authoritative production retrieval path.

The runner invokes the same router, selected-asset filters, hybrid search,
cross-language rewrite, RRF, reranker, diversification, structural
augmentation and parent expansion used by `/api/ask/stream`. It never calls
the answer generator. Raw retrieval units are chunks; standard IR metrics are
computed after deterministic projection to physical-page qrel IDs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
import rag  # noqa: E402
from backend.app.agents import rag_graph  # noqa: E402
from backend.app.retrieval.r2 import fuse_candidate_lists  # noqa: E402
from backend.app.services.usage_tracking import usage_context  # noqa: E402
from evaluation.metrics.standard_ir import evaluate_with_pytrec  # noqa: E402
from evaluation.runners import evaluate_goal3_expanded as expanded  # noqa: E402
from evaluation.runners import evaluate_production_baseline as baseline  # noqa: E402
from evaluation.runners.evaluate_retrieval import run_isolated_index  # noqa: E402


DEFAULT_OUTPUT = (
    ROOT
    / "tmp"
    / "rag-quality-goal"
    / "goal3b"
    / "production-retrieval-baseline.json"
)
CORE_STATE = (
    ROOT
    / "tmp"
    / "rag-quality-goal"
    / "goal3"
    / "checkpoints"
    / "checkpoint-e-production15"
    / "state.json"
)
EXPANDED_STATE = (
    ROOT
    / "tmp"
    / "rag-quality-goal"
    / "goal3"
    / "checkpoints"
    / "checkpoint-f-expanded"
    / "state.json"
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def tuning_cases() -> list[dict[str, Any]]:
    ordered: dict[str, dict[str, Any]] = {}
    for subset, cases in (
        ("unchanged_15", baseline._cases()),
        ("expanded_26", expanded._cases()),
    ):
        for case in cases:
            query_id = case["query_id"]
            if query_id not in ordered:
                ordered[query_id] = {**case, "tuning_subsets": [subset]}
            elif subset not in ordered[query_id]["tuning_subsets"]:
                ordered[query_id]["tuning_subsets"].append(subset)
    conversations = {
        row["conversation_id"]: row
        for row in _load_jsonl(
            ROOT / "evaluation" / "dev_goldset" / "conversations.jsonl"
        )
    }
    for case in ordered.values():
        conversation_id = case.get("conversation_key")
        turn_id = case.get("conversation_turn_id")
        conversation = conversations.get(str(conversation_id))
        if not conversation or not turn_id:
            continue
        turns = conversation.get("turns") or []
        index = next(
            (i for i, turn in enumerate(turns) if turn.get("turn_id") == turn_id),
            None,
        )
        if index is not None and index > 0:
            case["previous_user_query"] = turns[index - 1].get("query")
    return list(ordered.values())


def _asset_mapping() -> tuple[int, dict[str, str]]:
    user_ids = set()
    mapping: dict[str, str] = {}
    for path in (CORE_STATE, EXPANDED_STATE):
        state = json.loads(path.read_text(encoding="utf-8"))
        user_ids.add(int(state["user_id"]))
        for filename, asset_id in (state.get("asset_ids") or {}).items():
            existing = mapping.get(filename)
            if existing and existing != asset_id:
                # The expanded state is newer and uses normalization v5. Shared
                # filenames must nevertheless resolve to the same exact asset.
                raise RuntimeError(
                    f"Conflicting retained asset mapping for {filename}: "
                    f"{existing} vs {asset_id}"
                )
            mapping[filename] = str(asset_id)
    if len(user_ids) != 1:
        raise RuntimeError(f"Expected one evaluation owner, got {sorted(user_ids)}")
    return user_ids.pop(), mapping


def _safe_chunk(row: dict[str, Any], rank: int) -> dict[str, Any]:
    text = str(row.get("text") or "")
    return {
        "rank": rank,
        "chunk_id": row.get("chunk_id"),
        "document_id": row.get("document_id"),
        "source": row.get("source"),
        "chunk_index": row.get("chunk"),
        "physical_page": row.get("page"),
        "parent_id": row.get("parent_id"),
        "parent_title": row.get("parent_title"),
        "parent_page_start": row.get("parent_page_start"),
        "parent_page_end": row.get("parent_page_end"),
        "score": row.get("score"),
        "rerank_score": row.get("rerank_score"),
        "rewrite_fusion_score": row.get("rewrite_fusion_score"),
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def _page_evidence_id(document_sha256: str, row: dict[str, Any]) -> str | None:
    page = row.get("page")
    try:
        page = int(page)
    except (TypeError, ValueError):
        return None
    return f"{document_sha256}#page={page}"


def _page_run(document_sha256: str, rows: list[dict[str, Any]]) -> list[str]:
    seen = set()
    ranked = []
    for row in rows:
        evidence_id = _page_evidence_id(document_sha256, row)
        if evidence_id and evidence_id not in seen:
            seen.add(evidence_id)
            ranked.append(evidence_id)
    return ranked


def _combine_rewrite_stage(
    raw_stages: dict[str, list[dict[str, Any]]],
    prefix: str,
    candidate_k: int,
) -> list[dict[str, Any]]:
    rankings = [
        raw_stages[name]
        for name in (f"{prefix}:original", f"{prefix}:rewrite")
        if raw_stages.get(name)
    ]
    if len(rankings) > 1:
        return fuse_candidate_lists(rankings, top_k=candidate_k)
    return rankings[0] if rankings else []


def _usage_for_request(request_id: str) -> dict[str, Any]:
    with db.get_db() as conn:
        paid = [
            dict(row)
            for row in conn.execute(
                """SELECT operation_type, provider, model, input_tokens,
                          output_tokens, estimated_cost_usd, latency_ms, status
                     FROM usage_events
                    WHERE request_id = %s
                    ORDER BY created_at""",
                (request_id,),
            ).fetchall()
        ]
        compute = [
            dict(row)
            for row in conn.execute(
                """SELECT operation_type, provider, model, input_count,
                          chunk_count, pair_count, latency_ms, status
                     FROM compute_usage_events
                    WHERE request_id = %s
                    ORDER BY created_at""",
                (request_id,),
            ).fetchall()
        ]
    return {
        "provider_events": paid,
        "compute_events": compute,
        "provider_request_count": len(paid),
        "input_tokens": sum(int(row.get("input_tokens") or 0) for row in paid),
        "output_tokens": sum(int(row.get("output_tokens") or 0) for row in paid),
        "cost_usd": round(
            sum(float(row.get("estimated_cost_usd") or 0) for row in paid), 8
        ),
    }


def _normalized_page_evidence(
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence = []
    for asset in rag_graph._selected_assets(state):
        for page in rag_graph._normalized_pages(asset):
            if page["text"]:
                evidence.append(
                    {
                        "text": page["text"],
                        "source": asset["original_filename"],
                        "document_id": asset["id"],
                        "page": page["page"],
                        "parent_id": f"{asset['id']}#page={page['page']}",
                        "parent_title": f"page {page['page']}",
                    }
                )
    return evidence


def _run_case(
    case: dict[str, Any],
    *,
    user_id: int,
    asset_id: str,
    document_sha256: str,
) -> dict[str, Any]:
    history = []
    if case.get("followup") or case.get("must_use_history"):
        history = [
            {
                "role": "user",
                "content": case.get("previous_user_query") or "previous question",
            },
            {"role": "assistant", "content": "previous grounded answer"},
        ]
    state: dict[str, Any] = {
        "question": case["query"],
        "generation_question": case["query"],
        "scope": "selected",
        "document_id": asset_id,
        "document_ids": [],
        "user_id": user_id,
        "conversation_history": history,
    }
    state.update(rag_graph._planner_node(state))
    plan = state["request_plan"]
    route = state["route"]
    implementation = plan["route_implementation"]
    budget = plan["budget"]
    raw_stages: dict[str, list[dict[str, Any]]] = {}

    def record(name: str, rows: list[dict[str, Any]]) -> None:
        raw_stages[name] = [dict(row) for row in rows]

    request_id = f"goal3b-r2-{uuid.uuid4().hex}"
    started = time.perf_counter()
    operations = {
        "retrieval_calls": 0,
        "embedding_calls": 0,
        "rewrite_calls": 0,
        "reranker_calls": 0,
    }
    final_evidence: list[dict[str, Any]] = []
    retrieval_metadata: dict[str, Any] = {}
    token_estimate = int(plan.get("document_token_estimate") or 0)

    with usage_context(
        request_id=request_id,
        user_id=user_id,
        feature="goal3b_production_retrieval",
        metadata={"query_id": case["query_id"], "generation_skipped": True},
    ):
        if implementation == "history_aware_retrieval":
            previous_question = str(case.get("previous_user_query") or "").strip()
            retrieval_question = " ".join(
                value for value in (previous_question, case["query"]) if value
            )
            focused_plan = rag_graph.plan_request(
                retrieval_question,
                has_document_scope=True,
            ).to_dict()
            focused_budget = focused_plan["budget"]
            chunks, retrieval_metadata = rag.retrieve_with_metadata(
                retrieval_question,
                document_id=asset_id,
                user_id=user_id,
                top_k=int(
                    focused_budget.get("evidence_k") or rag.RERANK_TOP_K
                ),
                retrieve_k=int(
                    focused_budget.get("candidate_k") or rag.RETRIEVE_K
                ),
                stage_recorder=record,
            )
            operations.update(
                {
                    "retrieval_calls": 1,
                    "embedding_calls": int(
                        retrieval_metadata.get("search_count") or 0
                    ),
                    "rewrite_calls": int(
                        retrieval_metadata.get("rewrite_status")
                        not in {None, "not_needed", "disabled"}
                    ),
                    "reranker_calls": int(
                        retrieval_metadata.get("reranker_count") or 0
                    ),
                }
            )
            final_evidence = chunks
        elif route in {"conversational_followup", "retry_previous", "free_chat"}:
            final_evidence = []
        elif implementation == "direct_whole_document":
            final_evidence = _normalized_page_evidence(state)
        elif implementation == "table_or_structured_document":
            final_evidence = rag_graph._table_evidence(state)
            operations["retrieval_calls"] = 1
        elif route == "specific_section":
            final_evidence = rag_graph._section_chunks(state)
            operations["retrieval_calls"] = 1
        elif token_estimate and token_estimate <= 2_000:
            # This is the same complete-small-document evidence used before
            # generation in both focused and analytical graph nodes.
            final_evidence = _normalized_page_evidence(state)
            operations["retrieval_calls"] = 1
        elif route in {"focused_rag", "analytical"}:
            top_k = (
                max(6, int(budget.get("evidence_k") or 12) // 2)
                if route == "analytical"
                else int(budget.get("evidence_k") or rag.RERANK_TOP_K)
            )
            chunks, retrieval_metadata = rag.retrieve_with_metadata(
                case["query"],
                document_id=asset_id,
                user_id=user_id,
                top_k=top_k,
                retrieve_k=int(budget.get("candidate_k") or rag.RETRIEVE_K),
                stage_recorder=record,
            )
            operations.update(
                {
                    "retrieval_calls": 1,
                    "embedding_calls": int(
                        retrieval_metadata.get("search_count") or 0
                    ),
                    "rewrite_calls": int(
                        retrieval_metadata.get("rewrite_status")
                        not in {None, "not_needed", "disabled"}
                    ),
                    "reranker_calls": int(
                        retrieval_metadata.get("reranker_count") or 0
                    ),
                }
            )
            document_chunks = rag_graph._all_selected_chunks(state)
            if route == "analytical":
                parent_keys = {
                    (
                        chunk.get("document_id"),
                        chunk.get("parent_id") or chunk.get("parent_title"),
                    )
                    for chunk in chunks
                }
                expanded_chunks = [
                    chunk
                    for chunk in document_chunks
                    if (
                        chunk.get("document_id"),
                        chunk.get("parent_id") or chunk.get("parent_title"),
                    )
                    in parent_keys
                ]
                final_evidence = rag_graph._cap_chunks_evenly(
                    expanded_chunks or chunks,
                    int(budget.get("evidence_k") or 12),
                )
            else:
                final_evidence = rag_graph._augment_numeric_abstract_evidence(
                    case["query"], chunks, document_chunks
                )
                final_evidence = rag_graph._augment_method_evidence(
                    case["query"], final_evidence, document_chunks
                )
                final_evidence = rag_graph._augment_metric_abstract_evidence(
                    case["query"], final_evidence, document_chunks
                )
                if implementation == "quoted_document_explanation":
                    final_evidence = rag_graph._augment_quoted_evidence(
                        case["query"], final_evidence, document_chunks
                    )
        else:
            final_evidence = []

    candidate_k = int(budget.get("candidate_k") or rag.RETRIEVE_K)
    raw_stages["production_dense"] = _combine_rewrite_stage(
        raw_stages, "production_dense", candidate_k
    )
    raw_stages["production_sparse"] = _combine_rewrite_stage(
        raw_stages, "production_sparse", candidate_k
    )
    raw_stages["production_fused_pre_rerank"] = raw_stages.get(
        "production_fused_pre_rerank", []
    )
    raw_stages["production_reranked"] = raw_stages.get(
        "production_reranked", []
    )
    raw_stages["production_r2_final"] = raw_stages.get(
        "production_r2_final", []
    )
    raw_stages["production_answer_evidence"] = final_evidence
    output_stages = {
        name: [_safe_chunk(row, index) for index, row in enumerate(rows, 1)]
        for name, rows in raw_stages.items()
        if ":" not in name
    }
    page_rankings = {
        name: _page_run(document_sha256, rows)
        for name, rows in raw_stages.items()
        if ":" not in name
    }
    usage = _usage_for_request(request_id)
    return {
        "query_id": case["query_id"],
        "filename": case["filename"],
        "document_sha256": document_sha256,
        "expected_route": case.get("expected_route"),
        "actual_route": route,
        "route_implementation": implementation,
        "retrieval_mode": retrieval_metadata.get("retrieval_mode")
        or (
            "complete_small_document"
            if token_estimate and token_estimate <= 2_000
            else implementation
        ),
        "result_unit": "chunk_with_physical_page_projection",
        "qrel_unit": "physical_page",
        "operations": operations,
        "retrieval_metadata": retrieval_metadata,
        "stages": output_stages,
        "page_rankings": page_rankings,
        "usage": usage,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "tuning_subsets": case["tuning_subsets"],
    }


def _stage_metrics(
    results: list[dict[str, Any]], qrels: dict[str, dict[str, int]]
) -> dict[str, Any]:
    names = sorted(
        {
            stage
            for result in results
            for stage, ranking in result["page_rankings"].items()
            if ranking and result["query_id"] in qrels
        }
    )
    output = {}
    for stage in names:
        eligible = {
            result["query_id"]: result["page_rankings"].get(stage, [])
            for result in results
            if result["query_id"] in qrels
            and result["page_rankings"].get(stage)
        }
        stage_qrels = {query_id: qrels[query_id] for query_id in eligible}
        output[stage] = evaluate_with_pytrec(stage_qrels, eligible)
    return output


def run(output: Path, case_ids: set[str] | None = None) -> dict[str, Any]:
    user_id, asset_mapping = _asset_mapping()
    manifest = {
        row["filename"]: row
        for row in _load_jsonl(
            ROOT / "evaluation" / "dev_goldset" / "manifest.jsonl"
        )
    }
    qrel_rows = json.loads(
        (ROOT / "evaluation" / "dev_goldset" / "qrels.json").read_text(
            encoding="utf-8"
        )
    )["queries"]
    qrels = {
        query_id: {
            row["evidence_id"]: int(row["relevance"]) for row in rows
        }
        for query_id, rows in qrel_rows.items()
        if rows
    }
    cases = [
        case
        for case in tuning_cases()
        if not case_ids or case["query_id"] in case_ids
    ]
    for case in cases:
        query_id = case["query_id"]
        if query_id in qrels or not case.get("relevant_pages"):
            continue
        document_sha256 = str(
            case.get("document_sha256")
            or manifest[case["filename"]]["sha256"]
        )
        graded = {
            int(page): int(grade)
            for page, grade in (case.get("graded_relevance") or {}).items()
        }
        qrels[query_id] = {
            f"{document_sha256}#page={int(page)}": graded.get(int(page), 1)
            for page in case["relevant_pages"]
        }
    missing_assets = sorted(
        {case["filename"] for case in cases if case["filename"] not in asset_mapping}
    )
    if missing_assets:
        raise RuntimeError(f"Missing retained tuning assets: {missing_assets}")

    results = []
    for case in cases:
        document_sha256 = str(
            case.get("document_sha256")
            or manifest[case["filename"]]["sha256"]
        )
        result = _run_case(
            case,
            user_id=user_id,
            asset_id=asset_mapping[case["filename"]],
            document_sha256=document_sha256,
        )
        results.append(result)
        print(
            f"{result['query_id']}: {result['route_implementation']} "
            f"R/E/W/RR={list(result['operations'].values())}",
            flush=True,
        )

    isolated = run_isolated_index(
        ROOT / "evaluation" / "dev_goldset",
        ROOT / "composite_goldset_pdfs",
    )
    metrics = _stage_metrics(results, qrels)
    cross_ids = {
        case["query_id"]
        for case in cases
        if case.get("task_type") == "cross_language"
    }
    cross_results = [
        result for result in results if result["query_id"] in cross_ids
    ]
    usage = {
        "provider_request_count": sum(
            result["usage"]["provider_request_count"] for result in results
        ),
        "input_tokens": sum(result["usage"]["input_tokens"] for result in results),
        "output_tokens": sum(result["usage"]["output_tokens"] for result in results),
        "cost_usd": round(
            sum(result["usage"]["cost_usd"] for result in results), 8
        ),
    }
    report = {
        "kind": "goal3b_generation_free_authoritative_production_retrieval",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(results),
        "query_preparation": "production request router and bounded R2 rewrite policy",
        "selected_asset_filter": "exact PostgreSQL owner + asset/document id",
        "production_path": (
            "planner -> complete-small/table/section bypass OR "
            "Nemotron embedding -> Qdrant dense + bounded lexical BM25 -> RRF -> "
            "optional one rewrite fusion -> one production reranker -> diversity -> "
            "route-specific augmentation/parent expansion"
        ),
        "result_unit": "chunk; metrics use ordered unique physical-page projection",
        "qrel_unit": "physical page evidence id",
        "isolated_sparse": {
            "label": "isolated_sparse",
            "means": isolated["means"],
            "query_count": isolated["query_count"],
            "exactly_matches_production": False,
        },
        "stage_metrics": metrics,
        "cross_language_final_metrics": _stage_metrics(cross_results, qrels),
        "usage": usage,
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-id", action="append", default=[])
    args = parser.parse_args()
    report = run(args.output, set(args.case_id) or None)
    print(
        json.dumps(
            {
                "case_count": report["case_count"],
                "stage_metrics": {
                    name: {
                        "query_count": value["query_count"],
                        "means": value["means"],
                    }
                    for name, value in report["stage_metrics"].items()
                },
                "usage": report["usage"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
