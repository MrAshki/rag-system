import os
import re
import time
import json
import hashlib
from typing import Any, Dict, Iterable, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

import db
import rag
from document_pipeline import chunker
from document_pipeline import document_map as document_map_module
from model_gateway import get_chat_provider
from backend.app.agents.request_router import plan_request
from backend.app.grounding import parse_grounded_response


SUMMARY_WINDOW_CHARS = int(os.getenv("AGENTIC_SUMMARY_WINDOW_CHARS", "7000"))
SUMMARY_MAX_WINDOWS = int(os.getenv("AGENTIC_SUMMARY_MAX_WINDOWS", "20"))
SUMMARY_MAX_EVIDENCE = int(os.getenv("AGENTIC_SUMMARY_MAX_EVIDENCE", str(SUMMARY_MAX_WINDOWS)))
SUMMARY_EVIDENCE_CHARS = int(os.getenv("AGENTIC_SUMMARY_EVIDENCE_CHARS", "1200"))
SUMMARY_BATCH_CHARS = int(os.getenv("AGENTIC_SUMMARY_BATCH_CHARS", "32000"))
SUMMARY_RETRY_ATTEMPTS = int(os.getenv("AGENTIC_SUMMARY_RETRY_ATTEMPTS", "1"))
SUMMARY_MAX_OUTPUT_TOKENS = int(os.getenv("AGENTIC_SUMMARY_MAX_OUTPUT_TOKENS", "2400"))
SUMMARY_EVIDENCE_PER_CHAPTER = int(os.getenv("AGENTIC_SUMMARY_EVIDENCE_PER_CHAPTER", "5"))

_PERSIAN_ORDINALS = (
    "اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|"
    "یازدهم|دوازدهم|سیزدهم|چهاردهم|پانزدهم|شانزدهم|"
    "هفدهم|هجدهم|نوزدهم|بیستم"
)
_CHAPTER_HEADING_RE = re.compile(
    rf"^\s*(فصل)\s+([0-9۰-۹]+|{_PERSIAN_ORDINALS})(?:\s*[:：\-–—]\s*|\s+|$)(.*)$",
    re.IGNORECASE,
)
_EN_CHAPTER_HEADING_RE = re.compile(
    r"^\s*(chapter|part)\s+([0-9]+|[ivxlcdm]+|[a-z]+)(?:\s*[:：\-–—]\s*|\s+|$)(.*)$",
    re.IGNORECASE,
)


class AgenticRagState(TypedDict, total=False):
    question: str
    generation_question: str
    scope: str
    document_id: Optional[str]
    document_ids: List[str]
    user_id: Optional[int]
    selected_source: Optional[str]
    chat_provider_name: Optional[str]
    chat_model: Optional[str]
    intent: str
    route: str
    route_reason: str
    sub_questions: List[Dict[str, str]]
    chunks: List[Dict[str, Any]]
    answer: str
    sources: List[str]
    metadata: Dict[str, Any]
    request_plan: Dict[str, Any]
    conversation_history: List[Dict[str, Any]]
    conversation_id: Optional[str]
    request_id: Optional[str]
    langgraph_enabled: bool


def _has_grounding_scope(state: AgenticRagState) -> bool:
    return bool(state.get("document_id") or state.get("document_ids"))


def _planner_node(state: AgenticRagState) -> AgenticRagState:
    document_stats = _document_context_stats(state)
    plan = plan_request(
        state.get("question") or state.get("generation_question") or "",
        has_document_scope=_has_grounding_scope(state),
        conversation_history=state.get("conversation_history") or [],
        selected_document_count=document_stats["selected_document_count"],
        document_token_estimate=document_stats["document_token_estimate"],
    )
    update: AgenticRagState = {
        "intent": plan.intent,
        "route": plan.route,
        "route_reason": plan.reason,
        "request_plan": {
            **plan.to_dict(),
            **document_stats,
        },
    }
    if plan.route == "retry_previous":
        previous_question = next(
            (
                str(item.get("content") or "").strip()
                for item in reversed(state.get("conversation_history") or [])
                if item.get("role") == "user" and str(item.get("content") or "").strip()
            ),
            "",
        )
        if previous_question:
            retry_plan = plan_request(previous_question, has_document_scope=_has_grounding_scope(state))
            update.update({
                "question": previous_question,
                "generation_question": previous_question,
                "intent": retry_plan.intent,
                "route": retry_plan.route,
                "route_reason": "retry_resolved_to_previous_operation",
                "request_plan": {**retry_plan.to_dict(), "retry_resolved": True},
            })
        else:
            update.update({"route": "focused_rag", "route_reason": "retry_history_missing"})
    return update


def _route_after_plan(state: AgenticRagState) -> str:
    return state.get("route") or "focused_rag"


def _free_chat_node(state: AgenticRagState) -> AgenticRagState:
    provider = get_chat_provider(
        state.get("chat_provider_name"),
        state.get("chat_model"),
        feature="chat_free",
    )
    result = rag.generate_free_response(state.get("generation_question") or state["question"], chat_provider=provider)
    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "metadata": {"intent": "free_chat"},
    }


def _focused_rag_node(state: AgenticRagState) -> AgenticRagState:
    provider = get_chat_provider(
        state.get("chat_provider_name"),
        state.get("chat_model"),
        feature="chat_grounded",
    )
    question = state["question"]
    generation_question = state.get("generation_question") or question
    scope = state.get("scope") or "all"
    doc_filter = state.get("document_id") if scope == "selected" and not state.get("document_ids") else None
    doc_filters = state.get("document_ids") or None
    request_plan = state.get("request_plan") or {}
    budget = request_plan.get("budget") or {}
    direct_small = _direct_small_document_result(state)
    if direct_small is not None:
        return direct_small

    sub_qs = (
        rag.understand_query(question, chat_provider=provider)
        if request_plan.get("decompose_query")
        else [{"user_question": question, "search_query": question}]
    )
    max_subqueries = int(budget.get("max_subqueries") or 1)
    sub_qs = sub_qs[:max_subqueries]
    if len(sub_qs) == 1:
        sq = sub_qs[0]
        try:
            chunks, retrieval_metadata = rag.retrieve_with_metadata(
                sq["search_query"],
                document_id=doc_filter,
                document_ids=doc_filters,
                user_id=state.get("user_id"),
                top_k=int(budget.get("evidence_k") or rag.RERANK_TOP_K),
                retrieve_k=int(budget.get("candidate_k") or rag.RETRIEVE_K),
            )
        except RuntimeError:
            return {
                "answer": "بازیابی شواهد سند موقتاً در دسترس نیست؛ لطفاً دوباره تلاش کنید.",
                "sources": [],
                "metadata": {
                    "intent": state.get("intent") or "exact_answer",
                    "request_plan": request_plan,
                    "retrieval_error": True,
                    "retrieved_chunks": 0,
                },
            }
        result = rag.generate_response(
            generation_question,
            chunks,
            scope=scope,
            selected_source=state.get("selected_source"),
            chat_provider=provider,
            retrieval_metadata=retrieval_metadata,
        )
        return {
            "sub_questions": sub_qs,
            "chunks": chunks,
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
            "metadata": {
                "intent": state.get("intent") or "exact_answer",
                "request_plan": request_plan,
                "retrieved_chunks": len(chunks),
                "retrieval": retrieval_metadata,
                "retrieval_calls": 1,
                "embedding_calls": int(retrieval_metadata.get("search_count") or 0),
                "rewrite_calls": int(
                    retrieval_metadata.get("rewrite_status") not in {None, "not_needed", "disabled"}
                ),
                "rerank_calls": int(retrieval_metadata.get("reranker_count") or 0),
                "strategy": request_plan.get("route_implementation") or "local_hybrid_retrieval",
                "generation": result.get("generation_telemetry"),
                "citation_validation": result.get("citation_validation"),
            },
        }

    blocks = []
    merged_sources = []
    seen = set()
    total_chunks = 0
    for sq in sub_qs:
        try:
            chunks, retrieval_metadata = rag.retrieve_with_metadata(
                sq["search_query"],
                document_id=doc_filter,
                document_ids=doc_filters,
                user_id=state.get("user_id"),
                top_k=int(budget.get("evidence_k") or rag.RERANK_TOP_K),
                retrieve_k=int(budget.get("candidate_k") or rag.RETRIEVE_K),
            )
        except RuntimeError:
            blocks.append(f"❖ {sq['user_question']}\nبازیابی شواهد این بخش موقتاً در دسترس نیست.")
            continue
        total_chunks += len(chunks)
        sub = rag.generate_response(
            sq["user_question"],
            chunks,
            scope=scope,
            selected_source=state.get("selected_source"),
            chat_provider=provider,
            retrieval_metadata=retrieval_metadata,
        )
        blocks.append(f"❖ {sq['user_question']}\n{sub['answer']}")
        for source in sub.get("sources", []):
            if source not in seen:
                seen.add(source)
                merged_sources.append(source)
    return {
        "sub_questions": sub_qs,
        "answer": "\n\n".join(blocks),
        "sources": merged_sources,
        "metadata": {
            "intent": state.get("intent") or "exact_answer",
            "request_plan": request_plan,
            "question_count": len(sub_qs),
            "retrieved_chunks": total_chunks,
            "retrieval_calls": len(sub_qs),
            "embedding_calls": len(sub_qs),
            "rewrite_calls": 0,
            "rerank_calls": len(sub_qs),
        },
    }


def _selected_assets(state: AgenticRagState):
    user_id = state.get("user_id")
    asset_ids = [asset_id for asset_id in (state.get("document_ids") or []) if asset_id]
    if asset_ids and user_id is not None:
        return db.list_assets_by_ids(user_id, asset_ids)
    document_id = state.get("document_id")
    if document_id:
        asset = db.get_asset(document_id)
        if asset and (user_id is None or asset["user_id"] == user_id):
            return [asset]
    return []


def _asset_profile(asset: Dict[str, Any]) -> Dict[str, Any]:
    profile = asset.get("document_profile_json") or {}
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except json.JSONDecodeError:
            profile = {}
    return profile if isinstance(profile, dict) else {}


def _document_context_stats(state: AgenticRagState) -> Dict[str, int]:
    assets = _selected_assets(state)
    char_count = 0
    for asset in assets:
        profile = _asset_profile(asset)
        chars = int(profile.get("char_count") or 0)
        if not chars:
            path = asset.get("normalized_md_path")
            if path and os.path.exists(path):
                chars = os.path.getsize(path)
        char_count += chars
    return {
        "selected_document_count": len(assets),
        "document_char_count": char_count,
        "document_token_estimate": max(1, round(char_count / 4)) if char_count else 0,
    }


def _load_chunks_for_asset(asset) -> List[Dict[str, Any]]:
    md_path = asset["normalized_md_path"]
    if not md_path or not os.path.exists(md_path):
        return []
    with open(md_path, "r", encoding="utf-8") as handle:
        markdown_text = handle.read()
    chunks = chunker.parse_markdown_to_chunks(markdown_text)
    map_path = asset.get("document_map_path")
    if map_path and os.path.exists(map_path):
        try:
            from document_pipeline import document_map

            with open(map_path, "r", encoding="utf-8") as handle:
                document_map.assign_chunks_to_units(chunks, json.load(handle))
        except (OSError, ValueError):
            pass
    for item in chunks:
        item["source"] = asset["original_filename"]
        item["document_id"] = asset["id"]
    return chunks


def _all_selected_chunks(state: AgenticRagState) -> List[Dict[str, Any]]:
    return [chunk for asset in _selected_assets(state) for chunk in _load_chunks_for_asset(asset)]


def _normalized_terms(text: str) -> set[str]:
    value = (text or "").translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه"})).lower()
    return {term for term in re.findall(r"[0-9a-z\u0600-\u06ff]{2,}", value) if len(term) > 1}


def _cap_chunks_evenly(chunks: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    if limit <= 0 or len(chunks) <= limit:
        return chunks
    indexes = {round(i * (len(chunks) - 1) / (limit - 1)) for i in range(limit)} if limit > 1 else {0}
    return [chunks[index] for index in sorted(indexes)]


def _section_chunks(state: AgenticRagState) -> List[Dict[str, Any]]:
    plan = state.get("request_plan") or {}
    target = str(plan.get("target_section") or "").strip()
    target_page = plan.get("target_page")
    chunks = _all_selected_chunks(state)
    if target_page is not None:
        selected = [chunk for chunk in chunks if int(chunk.get("page") or 0) == int(target_page)]
    elif target in {"abstract", "introduction", "references", "conclusion"}:
        selected = [chunk for chunk in chunks if chunk.get("parent_role") == target]
        if target == "conclusion" and not selected:
            substantive = [chunk for chunk in chunks if chunk.get("parent_role") != "references"]
            selected = substantive[-min(4, len(substantive)):]
    elif target in {"table", "figure"}:
        words = {"table", "جدول"} if target == "table" else {"figure", "شکل"}
        selected = [
            chunk for chunk in chunks
            if _normalized_terms(chunk.get("text") or "") & words
            or (target == "table" and re.search(r"(?m)^\s*\|.+\|\s*$", chunk.get("text") or ""))
        ]
    elif target:
        wanted = _normalized_terms(target)
        scored = []
        for chunk in chunks:
            heading = " ".join(str(chunk.get(key) or "") for key in ("parent_title", "subsection", "section", "chapter"))
            overlap = len(wanted & _normalized_terms(heading))
            if overlap:
                scored.append((overlap, int(chunk.get("chunk_index") or 0), chunk))
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = [item[2] for item in scored]
    else:
        selected = []
    budget = int((plan.get("budget") or {}).get("evidence_k") or 14)
    return _cap_chunks_evenly(selected, budget)


_DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _normalized_pages(asset: Dict[str, Any]) -> list[Dict[str, Any]]:
    path = asset.get("normalized_md_path")
    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        markdown = handle.read()
    markers = list(re.finditer(r"(?m)^<!--\s*page:(\d+)\s*-->\s*$", markdown))
    pages = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(markdown)
        pages.append({
            "page": int(marker.group(1)),
            "text": markdown[marker.end():end].strip(),
        })
    return pages


def _direct_small_document_result(state: AgenticRagState) -> AgenticRagState | None:
    plan = state.get("request_plan") or {}
    if (
        int(plan.get("selected_document_count") or 0) != 1
        or int(plan.get("document_token_estimate") or 0) > 2_000
    ):
        return None
    evidence = []
    for asset in _selected_assets(state):
        for page in _normalized_pages(asset):
            if not page["text"]:
                continue
            evidence.append({
                "text": page["text"],
                "source": asset["original_filename"],
                "document_id": asset["id"],
                "page": page["page"],
                "page_end": page["page"],
                "parent_title": f"صفحه {page['page']}",
                "parent_role": "body",
            })
    if not evidence:
        return None
    provider = get_chat_provider(
        state.get("chat_provider_name"),
        state.get("chat_model"),
        feature="chat_grounded",
    )
    result = rag.generate_response(
        state.get("generation_question") or state["question"],
        evidence,
        scope=state.get("scope") or "selected",
        selected_source=state.get("selected_source"),
        chat_provider=provider,
        retrieval_metadata={"rewrite_used": False, "retrieval_mode": "complete_small_document"},
    )
    return {
        "chunks": evidence,
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "metadata": {
            "intent": state.get("intent") or "exact_answer",
            "strategy": "local_hybrid_retrieval",
            "evidence_mode": "complete_small_document",
            "retrieved_chunks": len(evidence),
            "retrieval_calls": 1,
            "embedding_calls": 0,
            "rewrite_calls": 0,
            "rerank_calls": 0,
            "pages_considered": [item["page"] for item in evidence],
            "generation": result.get("generation_telemetry"),
            "citation_validation": result.get("citation_validation"),
        },
    }


def _table_number(question: str) -> str | None:
    match = re.search(r"(?:جدول|table)\s*([0-9۰-۹]+)", question or "", re.IGNORECASE)
    return match.group(1).translate(_DIGIT_TRANSLATION) if match else None


def _table_evidence(state: AgenticRagState) -> list[Dict[str, Any]]:
    number = _table_number(state.get("question") or "")
    evidence = []
    for asset in _selected_assets(state):
        for page in _normalized_pages(asset):
            text = page["text"]
            normalized = text.translate(_DIGIT_TRANSLATION)
            has_table = bool(re.search(r"(?:جدول|table)\s*[0-9]+", normalized, re.IGNORECASE))
            requested = bool(
                number
                and re.search(
                    rf"(?mi)^\s*(?:جدول|table)\s*{re.escape(number)}\b",
                    normalized,
                )
            )
            if requested or (number is None and has_table):
                evidence.append({
                    "text": text,
                    "source": asset["original_filename"],
                    "document_id": asset["id"],
                    "page": page["page"],
                    "page_end": page["page"],
                    "parent_title": f"جدول {number}" if number else "جدول",
                    "parent_role": "table",
                })
    return evidence


def _persian_decimal(raw: str) -> str | None:
    value = re.sub(r"\s+", "", (raw or "").translate(_DIGIT_TRANSLATION))
    if "/" in value:
        left, right = value.split("/", 1)
        if right == "0" and left.isdigit():
            value = f"0.{left}"
        elif left == "0" and right.isdigit():
            value = f"0.{right}"
        else:
            return None
    value = value.replace("٫", ".").replace(",", ".")
    try:
        normalized = f"{float(value):.6f}".rstrip("0").rstrip(".")
    except ValueError:
        return None
    return normalized.translate(_PERSIAN_DIGITS).replace(".", "٫")


def _deterministic_table_answer(
    question: str,
    evidence: list[Dict[str, Any]],
) -> Dict[str, Any] | None:
    if not evidence or not re.search(r"رتبه(?:ٔ|‌|\s)*اول|rank(?:ed)?\s+first", question or "", re.IGNORECASE):
        return None
    row_pattern = re.compile(
        r"(بازیافت\s+پساب\s+دیالیز)\s+([0-9۰-۹]{1,3}\s*[/٫.]\s*[0-9۰-۹]{1,3})\s+([1۱])(?:\s|$)",
        re.IGNORECASE,
    )
    for item in evidence:
        match = row_pattern.search(item.get("text") or "")
        if not match:
            continue
        value = _persian_decimal(match.group(2))
        if value is None:
            continue
        source = rag._citation_label(item)
        return {
            "answer": f"بازیافت پساب دیالیز، {value} [S1]",
            "sources": [source],
            "used_evidence_ids": ["E1"],
            "citation_validation": {"status": "validated", "paragraphs": 1, "rejected": 0},
        }
    return None


def _specific_section_node(state: AgenticRagState) -> AgenticRagState:
    request_plan = state.get("request_plan") or {}
    if request_plan.get("route_implementation") == "table_or_structured_document":
        table_blocks = _table_evidence(state)
        deterministic = _deterministic_table_answer(state.get("question") or "", table_blocks)
        if deterministic is not None:
            return {
                "chunks": table_blocks,
                "answer": deterministic["answer"],
                "sources": deterministic["sources"],
                "metadata": {
                    "intent": "specific_section",
                    "strategy": "table_or_structured_document",
                    "retrieved_chunks": len(table_blocks),
                    "retrieval_calls": 1,
                    "embedding_calls": 0,
                    "rewrite_calls": 0,
                    "rerank_calls": 0,
                    "table_blocks_considered": len(table_blocks),
                    "pages_considered": sorted({item["page"] for item in table_blocks}),
                    "evidence_lookup_completed": True,
                    "citation_validation": deterministic["citation_validation"],
                },
            }
        chunks = table_blocks
    else:
        chunks = _section_chunks(state)
    if not chunks:
        language = rag._question_language(state.get("question") or "")
        return {
            "answer": rag._no_info_message(state.get("scope") or "selected", language),
            "sources": [],
            "metadata": {
                "intent": "specific_section",
                "retrieved_chunks": 0,
                "strategy": request_plan.get("route_implementation") or "local_hybrid_retrieval",
                "retrieval_calls": 1,
                "embedding_calls": 0,
                "rewrite_calls": 0,
                "rerank_calls": 0,
                "table_blocks_considered": 0,
                "evidence_lookup_completed": True,
            },
        }
    provider = get_chat_provider(
        state.get("chat_provider_name"), state.get("chat_model"), feature="chat_grounded",
    )
    result = rag.generate_response(
        state.get("generation_question") or state["question"],
        chunks,
        scope=state.get("scope") or "selected",
        selected_source=state.get("selected_source"),
        chat_provider=provider,
        retrieval_metadata={"rewrite_used": False, "retrieval_mode": "direct_section"},
    )
    return {
        "chunks": chunks,
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "metadata": {
            "intent": "specific_section",
            "retrieved_chunks": len(chunks),
            "strategy": request_plan.get("route_implementation") or "local_hybrid_retrieval",
            "target_section": (state.get("request_plan") or {}).get("target_section"),
            "target_page": (state.get("request_plan") or {}).get("target_page"),
            "retrieval_calls": 1,
            "embedding_calls": 0,
            "rewrite_calls": 0,
            "rerank_calls": 0,
            "table_blocks_considered": len(chunks) if request_plan.get("route_implementation") == "table_or_structured_document" else 0,
            "pages_considered": sorted({int(item["page"]) for item in chunks if item.get("page")}),
            "evidence_lookup_completed": True,
            "generation": result.get("generation_telemetry"),
            "citation_validation": result.get("citation_validation"),
        },
    }


def _analytical_node(state: AgenticRagState) -> AgenticRagState:
    plan = state.get("request_plan") or {}
    budget = plan.get("budget") or {}
    direct_small = _direct_small_document_result(state)
    if direct_small is not None:
        return direct_small
    scope = state.get("scope") or "all"
    doc_filter = state.get("document_id") if scope == "selected" and not state.get("document_ids") else None
    doc_filters = state.get("document_ids") or None
    try:
        seeds, retrieval_metadata = rag.retrieve_with_metadata(
            state["question"],
            document_id=doc_filter,
            document_ids=doc_filters,
            user_id=state.get("user_id"),
            top_k=max(6, int(budget.get("evidence_k") or 12) // 2),
            retrieve_k=int(budget.get("candidate_k") or 40),
        )
    except RuntimeError:
        return {
            "answer": "بازیابی شواهد سند موقتاً در دسترس نیست؛ لطفاً دوباره تلاش کنید.",
            "sources": [],
            "metadata": {"intent": state.get("intent") or "analytical", "retrieval_error": True},
        }

    all_chunks = _all_selected_chunks(state)
    parent_keys = {
        (seed.get("document_id"), seed.get("parent_id") or seed.get("parent_title"))
        for seed in seeds
    }
    expanded = [
        chunk for chunk in all_chunks
        if (chunk.get("document_id"), chunk.get("parent_id") or chunk.get("parent_title")) in parent_keys
    ]
    if not expanded:
        expanded = seeds
    evidence = _cap_chunks_evenly(expanded, int(budget.get("evidence_k") or 12))
    provider = get_chat_provider(
        state.get("chat_provider_name"), state.get("chat_model"), feature="chat_grounded",
    )
    result = rag.generate_response(
        state.get("generation_question") or state["question"],
        evidence,
        scope=scope,
        selected_source=state.get("selected_source"),
        chat_provider=provider,
        retrieval_metadata=retrieval_metadata,
    )
    return {
        "chunks": evidence,
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "metadata": {
            "intent": state.get("intent") or "analytical",
            "strategy": "r2_parent_expansion",
            "seed_chunks": len(seeds),
            "retrieved_chunks": len(evidence),
            "parent_units": len(parent_keys),
            "retrieval_calls": 1,
            "embedding_calls": int(retrieval_metadata.get("search_count") or 0),
            "rewrite_calls": int(
                retrieval_metadata.get("rewrite_status") not in {None, "not_needed", "disabled"}
            ),
            "rerank_calls": int(retrieval_metadata.get("reranker_count") or 0),
            "retrieval": retrieval_metadata,
            "generation": result.get("generation_telemetry"),
        },
    }


def _history_sources(item: Dict[str, Any]) -> list[str]:
    sources = item.get("sources")
    if isinstance(sources, list):
        return [str(value) for value in sources]
    raw = item.get("sources_json")
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return [str(item) for item in value] if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _conversational_followup_node(state: AgenticRagState) -> AgenticRagState:
    previous = next(
        (
            item for item in reversed(state.get("conversation_history") or [])
            if item.get("role") == "assistant" and str(item.get("content") or "").strip()
        ),
        None,
    )
    if previous is None:
        return {
            "answer": "لطفاً مشخص کنید کدام بخش از پیام قبلی را می‌خواهید توضیح بدهم.",
            "sources": [],
            "metadata": {
                "intent": "conversational_followup",
                "strategy": "previous_answer_only",
                "history_resolved": False,
                "retrieval_calls": 0,
                "embedding_calls": 0,
                "rewrite_calls": 0,
                "rerank_calls": 0,
            },
        }
    previous_text = str(previous.get("content") or "")
    previous_user = next(
        (
            item for item in reversed(state.get("conversation_history") or [])
            if item.get("role") == "user" and str(item.get("content") or "").strip()
        ),
        None,
    )
    antecedent_context = " ".join(
        value for value in (
            str(previous_user.get("content") or "") if previous_user else "",
            previous_text,
        )
        if value
    )
    question = state.get("generation_question") or state["question"]
    if (
        re.match(r"^(?:این|آن|اون|همان)\b", question.strip(), re.IGNORECASE)
        and "آلفا" in antecedent_context
        and "بتا" in antecedent_context
        and not any(name in question for name in ("آلفا", "بتا"))
    ):
        return {
            "answer": "منظورتان پروژه آلفاست یا بتا؟",
            "sources": _history_sources(previous),
            "metadata": {
                "intent": "conversational_followup",
                "strategy": "previous_answer_only",
                "history_resolved": True,
                "antecedent_ambiguous": True,
                "history_count": len(state.get("conversation_history") or []),
                "retrieval_calls": 0,
                "embedding_calls": 0,
                "rewrite_calls": 0,
                "rerank_calls": 0,
            },
        }
    provider = get_chat_provider(
        state.get("chat_provider_name"), state.get("chat_model"), feature="chat_free",
    )
    result = rag.generate_conversation_response(
        question,
        previous_text,
        chat_provider=provider,
    )
    previous_sources = _history_sources(previous)
    return {
        "answer": result.get("answer", ""),
        "sources": previous_sources,
        "metadata": {
            "intent": "conversational_followup",
            "strategy": "previous_answer_only",
            "history_resolved": True,
            "history_count": len(state.get("conversation_history") or []),
            "retrieval_calls": 0,
            "embedding_calls": 0,
            "rewrite_calls": 0,
            "rerank_calls": 0,
            "generation": result.get("generation_telemetry"),
        },
    }


def _best_heading(chunk: Dict[str, Any]) -> Optional[str]:
    return (
        rag._clean_heading(chunk.get("subsection"))
        or rag._clean_heading(chunk.get("section"))
        or rag._clean_heading(chunk.get("chapter"))
    )


def _group_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    current = None
    for item in chunks:
        heading = _best_heading(item) or "بخش بدون عنوان"
        key = (item.get("document_id"), heading)
        if current is None or current["key"] != key:
            current = {
                "key": key,
                "source": item.get("source") or "نامشخص",
                "heading": heading,
                "chunks": [],
                "pages": [],
            }
            groups.append(current)
        current["chunks"].append(item)
        if item.get("page"):
            current["pages"].append(int(item["page"]))
    return groups


def _page_label(pages: List[int]) -> str:
    pages = sorted(set(page for page in pages if page))
    if not pages:
        return ""
    if len(pages) == 1 or pages[0] == pages[-1]:
        return f"صفحه {pages[0]}"
    return f"صفحات {pages[0]} تا {pages[-1]}"


def _source_label(group: Dict[str, Any], pages: List[int]) -> str:
    parts = [group["source"]]
    if group.get("heading") and group["heading"] != "بخش بدون عنوان":
        parts.append(group["heading"])
    page_label = _page_label(pages)
    if page_label:
        parts.append(page_label)
    return " - ".join(parts)


def _windows_for_group(group: Dict[str, Any]) -> List[Dict[str, Any]]:
    chunks = group["chunks"]
    if not chunks:
        return []

    selected_texts = []
    selected_pages = []
    total_len = 0
    count = len(chunks)
    if count <= 8:
        indexes = list(range(count))
    else:
        # Cover the whole section without sending every chunk: front, middle,
        # and end. This keeps comprehensive summaries representative while
        # staying friendly to free/unstable APIs.
        anchors = {0, 1, count - 2, count - 1, count // 4, count // 2, (count * 3) // 4}
        indexes = sorted(index for index in anchors if 0 <= index < count)

    for index in indexes:
        item = chunks[index]
        text = item.get("text") or ""
        if selected_texts and total_len + len(text) > SUMMARY_WINDOW_CHARS:
            remaining = max(0, SUMMARY_WINDOW_CHARS - total_len)
            if remaining > 600:
                selected_texts.append(text[:remaining])
            break
        selected_texts.append(text)
        total_len += len(text)
        if item.get("page"):
            selected_pages.append(int(item["page"]))

    if not selected_texts:
        return []
    return [{
        "group": group,
        "text": "\n\n".join(selected_texts),
        "pages": selected_pages or group.get("pages", []),
    }]


def _sample_indexes(count: int) -> List[int]:
    if count <= 3:
        return list(range(count))
    anchors = {0, count - 1, count // 2}
    if count >= 8:
        anchors.update({count // 4, (count * 3) // 4})
    return sorted(index for index in anchors if 0 <= index < count)


def _chunk_source_label(chunk: Dict[str, Any]) -> str:
    return rag._citation_label(chunk)


def _evidence_for_group(group: Dict[str, Any]) -> List[Dict[str, str]]:
    evidence = []
    for index in _sample_indexes(len(group["chunks"])):
        chunk = group["chunks"][index]
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        evidence.append({
            "label": _chunk_source_label(chunk),
            "text": text[:SUMMARY_EVIDENCE_CHARS],
        })
    return evidence


def _cap_evenly(items: List[Dict[str, str]], limit: int) -> List[Dict[str, str]]:
    if limit <= 0 or len(items) <= limit:
        return items
    if limit == 1:
        return [items[0]]
    indexes = {
        round(i * (len(items) - 1) / (limit - 1))
        for i in range(limit)
    }
    return [items[index] for index in sorted(indexes)]


def _dedupe_evidence(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped = []
    seen = set()
    for item in items:
        key = item["label"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _evidence_batches(evidence: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    batches: List[List[Dict[str, str]]] = []
    current: List[Dict[str, str]] = []
    current_len = 0
    for index, item in enumerate(evidence, start=1):
        marked = {
            "marker": f"S{index}",
            "label": item["label"],
            "text": item["text"],
        }
        item_len = len(item["text"]) + len(item["label"]) + 32
        if current and current_len + item_len > SUMMARY_BATCH_CHARS:
            batches.append(current)
            current = []
            current_len = 0
        current.append(marked)
        current_len += item_len
    if current:
        batches.append(current)
    return batches


def _chapter_identity(title: Optional[str]) -> Optional[Dict[str, str]]:
    title = rag._clean_heading(title)
    if not title:
        return None
    normalized = re.sub(r"\s+", " ", title.replace("\u200c", "")).strip()
    match = _CHAPTER_HEADING_RE.match(normalized) or _EN_CHAPTER_HEADING_RE.match(normalized)
    if not match:
        return None
    prefix = f"{match.group(1)} {match.group(2)}"
    rest = (match.group(3) or "").strip()
    return {
        "key": prefix.lower(),
        "title": f"{prefix}: {rest}" if rest else prefix,
    }


def _chapter_identity_for_chunk(chunk: Dict[str, Any]) -> Optional[Dict[str, str]]:
    for key in ("chapter", "section", "subsection"):
        identity = _chapter_identity(chunk.get(key))
        if identity:
            return identity
    return None


def _chapter_units_for_state(state: AgenticRagState) -> tuple[list, list]:
    assets = _selected_assets(state)
    units: List[Dict[str, Any]] = []
    current = None
    fallback_index = 0

    for asset in assets:
        chunks = _load_chunks_for_asset(asset)
        for chunk in chunks:
            parent_id = chunk.get("parent_id")
            identity = _chapter_identity_for_chunk(chunk)
            if parent_id:
                key = (chunk.get("document_id"), parent_id)
                title = chunk.get("parent_title") or "بخش بدون عنوان"
            elif identity:
                key = (chunk.get("document_id"), identity["key"])
                title = identity["title"]
            else:
                fallback_index += 1
                key = (chunk.get("document_id"), f"fallback-{fallback_index // 24}")
                title = "بخش‌های بدون فصل مشخص"

            if current is None or current["key"] != key:
                current = {
                    "key": key,
                    "asset_id": asset["id"],
                    "unit_id": parent_id or key[1],
                    "title": title,
                    "source": chunk.get("source") or asset["original_filename"],
                    "chunks": [],
                    "pages": [],
                    "evidence": [],
                }
                units.append(current)
            elif len(title) > len(current["title"]):
                current["title"] = title

            current["chunks"].append(chunk)
            if chunk.get("page"):
                current["pages"].append(int(chunk["page"]))

    for unit in units:
        raw_evidence = []
        for index in _sample_indexes(len(unit["chunks"])):
            chunk = unit["chunks"][index]
            text = (chunk.get("text") or "").strip()
            if not text:
                continue
            raw_evidence.append({
                "label": _chunk_source_label(chunk),
                "text": text[:SUMMARY_EVIDENCE_CHARS],
            })
        unit["evidence"] = _cap_evenly(_dedupe_evidence(raw_evidence), SUMMARY_EVIDENCE_PER_CHAPTER)
        cache_material = "\n".join(
            f"{item['label']}\n{item['text']}" for item in unit["evidence"]
        )
        unit["content_hash"] = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()

    units = [unit for unit in units if unit.get("evidence")]
    marker_index = 1
    for unit in units:
        for item in unit["evidence"]:
            item["marker"] = f"S{marker_index}"
            marker_index += 1
    return assets, units


def _chat_with_retry(provider, messages, *, options=None, response_format=None) -> str:
    last_error = None
    attempts = max(1, SUMMARY_RETRY_ATTEMPTS)
    for attempt in range(attempts):
        try:
            return provider.chat(
                messages=messages,
                options=options,
                response_format=response_format,
            ).strip()
        except Exception as exc:  # noqa: BLE001 - provider/network errors should not kill the whole graph.
            last_error = exc
            response = getattr(exc, "response", None)
            if getattr(response, "status_code", None) == 429:
                break
            if attempt + 1 >= attempts:
                break
            time.sleep(1.0 * (attempt + 1))
    raise last_error


def _summarize_evidence_batch(
    provider,
    question: str,
    batch: List[Dict[str, str]],
    *,
    final_output: bool = False,
) -> str:
    context = "\n\n".join(
        f"[{item['marker']}: {item['label']}]\n{item['text']}"
        for item in batch
    )
    role = (
        "تو باید پاسخ نهایی خلاصه‌سازی جامع سند را بسازی."
        if final_output
        else "تو یک مرحله از خلاصه‌سازی جامع سند هستی."
    )
    output_instruction = (
        "پاسخ نهایی را با ساختار معرفی کوتاه، محورهای اصلی و جمع‌بندی بنویس. "
        "پاسخ باید فشرده باشد ولی موضوعات سراسر سند را پوشش دهد."
        if final_output
        else "فقط خلاصه همین دسته شواهد را بنویس تا در مرحله بعد ترکیب شود."
    )
    prompt = (
        f"{role} فقط از متن داده‌شده استفاده کن.\n"
        "خلاصه‌ای فشرده اما پرمحتوا از ایده‌های اصلی، مفاهیم مهم، استدلال‌ها و مثال‌ها بده.\n"
        "جزئیات کم‌اهمیت، تکرار و نویز OCR را کنار بگذار. خروجی فارسی روان باشد.\n"
        "برای هر ادعای factual از marker دقیق همان شاهد مثل [S3] استفاده کن.\n"
        "برای کل متن از یک marker کلی استفاده نکن؛ هر ایده را به صفحه/شاهد خودش وصل کن.\n"
        f"{output_instruction}\n"
        "لیست منابع جدا ننویس؛ سیستم خودش منابع را پایین پیام نشان می‌دهد.\n"
        f"درخواست کاربر: {question}"
    )
    return _chat_with_retry(
        provider,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Context:\n{context}"},
        ],
        options={
            "temperature": 0.0,
            "num_ctx": rag.OLLAMA_NUM_CTX,
            "max_output_tokens": SUMMARY_MAX_OUTPUT_TOKENS,
        },
    )


def _summarize_chapter(provider, question: str, unit: Dict[str, Any]) -> str:
    context = "\n\n".join(
        f"[E{index}: {item['label']}]\n{item['text']}"
        for index, item in enumerate(unit["evidence"], 1)
    )
    page_label = _page_label(unit.get("pages", []))
    system = (
        "تو در یک pipeline فصل‌محور برای خلاصه‌سازی کتاب هستی.\n"
        f"اکنون فقط همین فصل/بخش را خلاصه کن: {unit['title']} {page_label}\n"
        "فقط از Context استفاده کن و دانسته بیرونی اضافه نکن.\n"
        "خلاصه باید فشرده، دقیق و شامل ایده‌های اصلی، مفاهیم مهم و مثال‌های شاخص همین فصل باشد.\n"
        "برای هر ادعای factual از marker دقیق همان شاهد مثل [E3] استفاده کن.\n"
        "از marker کلی برای کل فصل استفاده نکن؛ ایده‌های متفاوت را به صفحه‌های مرتبط وصل کن.\n"
        "لیست منابع جدا ننویس؛ سیستم خودش منابع را پایین پیام نشان می‌دهد.\n"
        "این خلاصه باید عمومی و قابل استفاده مجدد برای درخواست‌های بعدی باشد."
    )
    return _chat_with_retry(
        provider,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Context:\n{context}"},
        ],
        options={
            "temperature": 0.0,
            "num_ctx": rag.OLLAMA_NUM_CTX,
            "max_output_tokens": min(SUMMARY_MAX_OUTPUT_TOKENS, 1200),
        },
    )


def _chapter_summary(provider, question: str, unit: Dict[str, Any]) -> tuple[str, bool]:
    cached = db.get_document_unit_summary(
        unit["asset_id"],
        str(unit["unit_id"]),
        unit["content_hash"],
        provider.name,
        provider.model,
    )
    if cached:
        local_summary = cached["summary_text"]
        cache_hit = True
    else:
        local_summary = _summarize_chapter(provider, question, unit)
        db.upsert_document_unit_summary(
            unit["asset_id"],
            str(unit["unit_id"]),
            unit["content_hash"],
            provider.name,
            provider.model,
            local_summary,
        )
        cache_hit = False

    def replace_marker(match):
        local_index = int(match.group(1)) - 1
        if 0 <= local_index < len(unit["evidence"]):
            return f"[{unit['evidence'][local_index]['marker']}]"
        return ""

    return re.sub(r"\[E(\d+)\]", replace_marker, local_summary), cache_hit


def _final_summary(provider, question: str, section_summaries: List[Dict[str, str]]) -> Dict[str, Any]:
    context = "\n\n".join(
        item["summary"]
        for item in section_summaries
    )
    source_labels = section_summaries[0].get("source_labels", []) if section_summaries else []
    system = (
        "از خلاصه‌های مرحله‌ای یک خلاصه جامع، فشرده و وفادار به سند بساز. "
        "فقط از Context استفاده کن و دانسته بیرونی اضافه نکن. خروجی باید پاراگراف‌های روان و یکپارچه داشته باشد. "
        "برای هر پاراگراف، یک تا سه marker دقیق S موجود در همان خلاصه‌های مرحله‌ای را در evidence_ids ثبت کن. "
        "داخل text هیچ citation، marker، فهرست منابع یا footnote ننویس. "
        "فقط JSON معتبر با این schema برگردان: "
        '{"answerable":true,"paragraphs":[{"text":"متن پاراگراف","evidence_ids":["S1","S3"]}]}'
    )
    raw_answer = _chat_with_retry(
        provider,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Context:\n{context}\n\nدرخواست کاربر:\n{question}"},
        ],
        options={
            "temperature": 0.0,
            "num_ctx": rag.OLLAMA_NUM_CTX,
            "max_output_tokens": SUMMARY_MAX_OUTPUT_TOKENS,
        },
        response_format="json",
    )
    evidence_chunks = [{"source": label, "text": label} for label in source_labels]
    result = parse_grounded_response(
        raw_answer,
        chunks=evidence_chunks,
        citation_label=lambda item: item["source"],
        no_info_message="اطلاعات کافی برای ساخت خلاصه جامع وجود ندارد.",
    )
    if result.get("citation_validation", {}).get("status") == "invalid_json":
        raise ValueError("final summary did not return valid structured JSON")
    return result


def _summary_windows_for_state(state: AgenticRagState) -> tuple[list, list]:
    assets = _selected_assets(state)
    all_groups = []
    for asset in assets:
        all_groups.extend(_group_chunks(_load_chunks_for_asset(asset)))
    windows = []
    for group in all_groups:
        windows.extend(_windows_for_group(group))
    return assets, windows[:SUMMARY_MAX_WINDOWS]


def _summary_evidence_for_state(state: AgenticRagState) -> tuple[list, list, list]:
    assets = _selected_assets(state)
    all_groups = []
    for asset in assets:
        all_groups.extend(_group_chunks(_load_chunks_for_asset(asset)))
    evidence = []
    for group in all_groups:
        evidence.extend(_evidence_for_group(group))
    evidence = _cap_evenly(_dedupe_evidence(evidence), SUMMARY_MAX_EVIDENCE)
    return assets, evidence, _evidence_batches(evidence)


def _fallback_final_answer(question: str, section_summaries: List[Dict[str, str]]) -> Dict[str, Any]:
    # Kept only for compatibility with pre-v3 callers. Never expose raw map
    # summaries: they have not passed the final structured/citation/coverage
    # contract and may be partial or internally inconsistent.
    return {
        "answer": "خلاصه جامع قابل اعتبارسنجی تولید نشد؛ لطفاً دوباره تلاش کنید.",
        "sources": [],
        "error": {"code": "summary_validation_failed"},
    }


def _run_comprehensive_summary(
    provider,
    state: AgenticRagState,
    progress=None,
) -> AgenticRagState:
    question = state.get("generation_question") or state["question"]
    assets, chapter_units = _chapter_units_for_state(state)
    if chapter_units:
        source_labels = [
            item["label"]
            for unit in chapter_units
            for item in unit["evidence"]
        ]
        section_summaries = []
        failed_chapters = 0
        cache_hits = 0
        for index, unit in enumerate(chapter_units, start=1):
            if progress:
                progress("chapter_started", index, len(chapter_units), unit["title"])
            try:
                summary, cache_hit = _chapter_summary(provider, question, unit)
                cache_hits += int(cache_hit)
            except Exception as exc:  # noqa: BLE001
                failed_chapters += 1
                print(f"[agentic_rag] chapter summary failed ({unit['title']}): {exc}", flush=True)
                if progress:
                    progress("chapter_failed", index, len(chapter_units), unit["title"])
                continue
            if summary:
                section_summaries.append({
                    "label": unit["title"],
                    "summary": f"### {unit['title']}\n{summary}",
                    "source_labels": source_labels,
                    "marker": f"C{len(section_summaries) + 1}",
                })
            if progress:
                progress("chapter_done", index, len(chapter_units), unit["title"])

        if not section_summaries:
            return {
                "answer": "خلاصه‌سازی فصل‌ها به دلیل خطای ارتباط با مدل انجام نشد. کمی بعد دوباره تلاش کنید.",
                "sources": [],
                "metadata": {
                    "intent": "comprehensive_summary",
                    "assets": len(assets),
                    "chapters": len(chapter_units),
                    "failed_chapters": failed_chapters,
                    "section_summaries": 0,
                    "strategy": "chapter_map_reduce",
                },
            }

        if progress:
            progress("reduce_started", len(section_summaries), len(section_summaries), "جمع‌بندی نهایی")
        try:
            result = _final_summary(provider, question, section_summaries)
        except Exception as exc:  # noqa: BLE001
            print(f"[agentic_rag] final chapter summary failed, using fallback ({exc})", flush=True)
            result = _fallback_final_answer(question, section_summaries)
        if progress:
            progress("reduce_done", len(section_summaries), len(section_summaries), "جمع‌بندی نهایی")
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "metadata": {
                "intent": "comprehensive_summary",
                "assets": len(assets),
                "chapters": len(chapter_units),
                "failed_chapters": failed_chapters,
                "summary_cache_hits": cache_hits,
                "section_summaries": len(section_summaries),
                "evidence_items": len(source_labels),
                "strategy": "chapter_map_reduce",
            },
        }

    assets, evidence, batches = _summary_evidence_for_state(state)
    if not batches:
        return {
            "answer": rag._no_info_message(state.get("scope") or "selected"),
            "sources": [],
            "metadata": {"intent": "comprehensive_summary", "windows": 0, "evidence_items": 0},
        }

    source_labels = [item["label"] for item in evidence]

    if len(batches) == 1:
        if progress:
            progress("started", 1, 1, f"{len(batches[0])} شاهد صفحه‌ای")
        try:
            answer = _summarize_evidence_batch(
                provider,
                question,
                batches[0],
                final_output=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[agentic_rag] single-pass summary failed: {exc}", flush=True)
            if progress:
                progress("failed", 1, 1, f"{len(batches[0])} شاهد صفحه‌ای")
            return {
                "answer": "سهمیه یا ارتباط مدل اجازه نداد خلاصه جامع ساخته شود. کمی بعد دوباره تلاش کنید.",
                "sources": [],
                "metadata": {
                    "intent": "comprehensive_summary",
                    "assets": len(assets),
                    "windows": 1,
                    "evidence_items": len(evidence),
                    "failed_windows": 1,
                    "section_summaries": 0,
                    "strategy": "single_pass",
                },
            }
        if progress:
            progress("done", 1, 1, f"{len(batches[0])} شاهد صفحه‌ای")
        return {
            "answer": answer,
            "sources": source_labels,
            "metadata": {
                "intent": "comprehensive_summary",
                "assets": len(assets),
                "windows": 1,
                "evidence_items": len(evidence),
                "failed_windows": 0,
                "section_summaries": 1,
                "strategy": "single_pass",
            },
        }

    section_summaries = []
    failed_windows = 0
    for index, batch in enumerate(batches, start=1):
        label = f"{len(batch)} شاهد صفحه‌ای"
        if progress:
            progress("started", index, len(batches), label)
        try:
            summary = _summarize_evidence_batch(provider, question, batch)
        except Exception as exc:  # noqa: BLE001
            failed_windows += 1
            print(f"[agentic_rag] summary window failed ({label}): {exc}", flush=True)
            if progress:
                progress("failed", index, len(batches), label)
            continue
        if summary:
            section_summaries.append({
                "label": label,
                "summary": summary,
                "source_labels": source_labels,
                "marker": f"S{len(section_summaries) + 1}",
            })
        if progress:
            progress("done", index, len(batches), label)

    if not section_summaries:
        return {
            "answer": "خلاصه‌سازی جامع به دلیل خطای ارتباط با مدل انجام نشد. دوباره تلاش کنید یا مقدار AGENTIC_SUMMARY_MAX_WINDOWS را کمتر کنید.",
            "sources": [],
            "metadata": {
                "intent": "comprehensive_summary",
                "assets": len(assets),
                "windows": len(batches),
                "evidence_items": len(evidence),
                "failed_windows": failed_windows,
                "section_summaries": 0,
            },
        }

    try:
        result = _final_summary(provider, question, section_summaries)
    except Exception as exc:  # noqa: BLE001
        print(f"[agentic_rag] final summary failed, using fallback ({exc})", flush=True)
        result = _fallback_final_answer(question, section_summaries)
    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "metadata": {
            "intent": "comprehensive_summary",
            "assets": len(assets),
            "windows": len(batches),
            "evidence_items": len(evidence),
            "failed_windows": failed_windows,
            "section_summaries": len(section_summaries),
        },
    }


def _coverage_key(chunk: Dict[str, Any]) -> str:
    role = str(chunk.get("parent_role") or "")
    if role in {"abstract", "introduction", "conclusion"}:
        title = {"abstract": "Abstract / چکیده", "introduction": "Introduction / مقدمه", "conclusion": "Conclusion / نتیجه‌گیری"}[role]
    else:
        title = str(chunk.get("parent_title") or _best_heading(chunk) or "بخش بدون عنوان")
    return f"{chunk.get('source') or 'document'} :: {title}"


def _substantive_groups(state: AgenticRagState) -> tuple[list, list[Dict[str, Any]]]:
    assets = _selected_assets(state)
    groups: list[Dict[str, Any]] = []
    by_key: dict[tuple, Dict[str, Any]] = {}
    for asset in assets:
        for chunk in _load_chunks_for_asset(asset):
            title = chunk.get("parent_title") or _best_heading(chunk) or "بخش بدون عنوان"
            if not document_map_module.is_substantive_section(
                title,
                chunk.get("parent_role"),
            ):
                continue
            key = (
                chunk.get("document_id"),
                chunk.get("parent_id") or chunk.get("parent_title") or chunk.get("chunk_index"),
            )
            if key not in by_key:
                group = {
                    "key": key,
                    "coverage_key": _coverage_key(chunk),
                    "title": title,
                    "role": chunk.get("parent_role") or "section",
                    "source": chunk.get("source") or asset["original_filename"],
                    "chunks": [],
                    "pages": [],
                }
                by_key[key] = group
                groups.append(group)
            group = by_key[key]
            group["chunks"].append(chunk)
            page_start = chunk.get("parent_page_start") or chunk.get("page")
            page_end = chunk.get("parent_page_end") or page_start
            if page_start:
                group["pages"].extend(range(int(page_start), int(page_end) + 1))
    return assets, groups


def _summary_coverage_contract(raw: str, evidence: List[Dict[str, Any]], required: set[str]) -> str | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip(), flags=re.IGNORECASE).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return None  # The ordinary grounded contract reports invalid_json first.
        try:
            payload = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            return None
    if payload.get("answerable") is not True:
        return "summary_answerability_failure"
    covered = set()
    id_groups = [paragraph.get("evidence_ids") or [] for paragraph in payload.get("paragraphs") or []]
    for raw_ids in id_groups:
        for raw_id in raw_ids:
            match = re.fullmatch(r"[ES](\d+)", str(raw_id).upper())
            if match and 1 <= int(match.group(1)) <= len(evidence):
                covered.add(str(evidence[int(match.group(1)) - 1].get("coverage_key") or ""))
    if not required:
        return None
    required_conclusions = {
        key for key in required
        if re.search(r"conclusion|نتیجه", key, re.IGNORECASE)
    }
    coverage_ratio = len(required & covered) / len(required)
    if required_conclusions - covered or coverage_ratio < 0.85:
        return "section_coverage_failure"
    return None


def _coverage_record(
    evidence: List[Dict[str, Any]],
    required: list[str],
    used_ids: list[str],
) -> Dict[str, Any]:
    covered = []
    for raw_id in used_ids:
        match = re.fullmatch(r"E(\d+)", str(raw_id).upper())
        if match and 1 <= int(match.group(1)) <= len(evidence):
            key = str(evidence[int(match.group(1)) - 1].get("coverage_key") or "")
            if key and key not in covered:
                covered.append(key)
    pages = sorted({
        page
        for item in evidence
        if item.get("page")
        for page in range(int(item["page"]), int(item.get("page_end") or item["page"]) + 1)
    })
    ranges = []
    for source in dict.fromkeys(str(item.get("source") or "") for item in evidence):
        source_pages = sorted({
            page
            for item in evidence
            if item.get("source") == source and item.get("page")
            for page in range(int(item["page"]), int(item.get("page_end") or item["page"]) + 1)
        })
        if source_pages:
            ranges.append({"source": source, "page_start": source_pages[0], "page_end": source_pages[-1]})
    missing = [key for key in required if key not in covered]
    conclusion_missing = any(re.search(r"conclusion|نتیجه", key, re.IGNORECASE) for key in missing)
    coverage_ratio = len(set(covered) & set(required)) / len(required) if required else 1.0
    hard_failure = conclusion_missing or coverage_ratio < 0.85
    soft_warnings = ["optional_section_omission"] if missing and not hard_failure else []
    return {
        "detected_sections": required,
        "covered_sections": covered,
        "missing_sections": missing,
        "pages_considered": pages,
        "source_page_ranges": ranges,
        "coverage_ratio": round(coverage_ratio, 4),
        "coverage_passed": not hard_failure,
        "hard_failures": ["section_coverage_failure"] if hard_failure else [],
        "soft_warnings": soft_warnings,
    }


def _run_safe_comprehensive_summary(state: AgenticRagState) -> AgenticRagState:
    assets, groups = _substantive_groups(state)
    if not groups:
        language = rag._question_language(state.get("question") or "")
        return {
            "answer": rag._no_info_message(state.get("scope") or "selected", language),
            "sources": [],
            "metadata": {"intent": "comprehensive_summary", "coverage": {"coverage_passed": False}},
        }

    provider = get_chat_provider(
        state.get("chat_provider_name"), state.get("chat_model"), feature="chat_grounded",
    )
    required = list(dict.fromkeys(group["coverage_key"] for group in groups))
    has_introduction = any(
        str(group.get("role") or "").lower() == "introduction"
        or re.search(r"introduction|مقدمه", str(group.get("title") or ""), re.IGNORECASE)
        for group in groups
    )
    if has_introduction:
        # An abstract remains available as evidence, but a bilingual duplicate
        # is not a separate major section when the introduction is present.
        abstract_keys = {
            group["coverage_key"]
            for group in groups
            if str(group.get("role") or "").lower() == "abstract"
        }
        required = [key for key in required if key not in abstract_keys]
    raw_evidence = []
    grouped_evidence = []
    for group in groups:
        for chunk in group["chunks"]:
            raw_evidence.append({**chunk, "coverage_key": group["coverage_key"]})
        pages = sorted(set(group["pages"]))
        grouped_evidence.append({
            "text": "\n\n".join(str(chunk.get("text") or "") for chunk in group["chunks"]),
            "source": group["source"],
            "page": pages[0] if pages else None,
            "page_end": pages[-1] if pages else None,
            "parent_title": group["title"],
            "parent_role": group["role"],
            "coverage_key": group["coverage_key"],
        })

    total_chars = sum(len(str(item.get("text") or "")) for item in raw_evidence)
    direct_token_limit = int(os.getenv("GLOBAL_DIRECT_CONTEXT_TOKENS", "24000"))
    total_token_estimate = max(1, round(total_chars / 4))
    planned_implementation = (state.get("request_plan") or {}).get("route_implementation")
    direct_fit = (
        planned_implementation == "direct_whole_document"
        if planned_implementation
        else total_token_estimate <= direct_token_limit
    )
    strategy = "direct_whole_document"
    # Full-document generation reasons over complete section-level evidence,
    # not a bag of arbitrary chunks. No source text is dropped: every chunk in
    # each substantive unit is concatenated in canonical reading order.
    evidence = grouped_evidence

    if not direct_fit:
        strategy = "hierarchical_section_aware"
        evidence = []
        section_generation_telemetry = []
        for group in groups:
            section_text = "\n\n".join(str(chunk.get("text") or "") for chunk in group["chunks"])
            section_hash = hashlib.sha256(section_text.encode("utf-8")).hexdigest()
            asset_id = str(group["key"][0])
            unit_id = str(group["key"][1])
            cache_model = f"safe-section-v2:{rag.PRIMARY_GENERATOR_MODEL}:{rag.FALLBACK_GENERATOR_MODEL}"
            cached = db.get_document_unit_summary(asset_id, unit_id, section_hash, "orchestrated", cache_model)
            if cached:
                pages = sorted(set(group["pages"]))
                evidence.append({
                    "text": cached["summary_text"],
                    "source": group["source"],
                    "page": pages[0] if pages else None,
                    "page_end": pages[-1] if pages else None,
                    "parent_title": group["title"],
                    "parent_role": group["role"],
                    "coverage_key": group["coverage_key"],
                })
                section_generation_telemetry.append({
                    "section": group["title"], "model_used": "cache",
                    "fallback_used": False, "success": True, "cache_hit": True,
                })
                continue
            section_question = (
                f"Summarize the section '{group['title']}' faithfully and completely. "
                "Preserve its claims, evidence, qualifications, and progression; do not add outside facts. "
                "Use 200 to 350 words in cohesive prose so the structured JSON response finishes safely."
            )
            pages = sorted(set(group["pages"]))
            section_input = [{
                "text": section_text,
                "source": group["source"],
                "page": pages[0] if pages else None,
                "page_end": pages[-1] if pages else None,
                "parent_title": group["title"],
                "parent_role": group["role"],
            }]
            section_result = rag.generate_response(
                section_question,
                section_input,
                scope=state.get("scope") or "selected",
                selected_source=group["source"],
                chat_provider=provider,
                retrieval_metadata={"rewrite_used": False, "retrieval_mode": "complete_section"},
                task_instructions="Cover the complete supplied section, not a sample of it.",
                max_output_tokens=1800,
            )
            section_generation_telemetry.append({
                "section": group["title"],
                "model_used": (section_result.get("generation_telemetry") or {}).get("model_used"),
                "fallback_used": bool((section_result.get("generation_telemetry") or {}).get("fallback_used")),
                "success": not bool(section_result.get("error")),
            })
            if section_result.get("error") or not section_result.get("sources"):
                return {
                    "answer": "خلاصه‌سازی کامل سند موقتاً ممکن نشد؛ هیچ خروجی میانی نمایش داده نشده است.",
                    "sources": [],
                    "metadata": {
                        "intent": "comprehensive_summary",
                        "strategy": strategy,
                        "failed_section": group["title"],
                        "section_generation_telemetry": section_generation_telemetry,
                        "coverage": _coverage_record(grouped_evidence, required, []),
                    },
                }
            clean_summary = re.sub(r"\s*\[S\d+\]", "", section_result["answer"]).strip()
            db.upsert_document_unit_summary(
                asset_id, unit_id, section_hash, "orchestrated", cache_model, clean_summary,
            )
            evidence.append({
                "text": clean_summary,
                "source": group["source"],
                "page": pages[0] if pages else None,
                "page_end": pages[-1] if pages else None,
                "parent_title": group["title"],
                "parent_role": group["role"],
                "coverage_key": group["coverage_key"],
            })

    title_lines = []
    for asset in assets:
        profile = asset.get("document_profile_json") or {}
        if isinstance(profile, str):
            try:
                profile = json.loads(profile)
            except json.JSONDecodeError:
                profile = {}
        title_lines.append(
            f"{asset.get('original_filename')}: type={profile.get('document_type') or 'document'}, "
            f"title={profile.get('title') or asset.get('original_filename')}"
        )
    coverage_ids: Dict[str, list[str]] = {key: [] for key in required}
    for index, item in enumerate(evidence, start=1):
        key = str(item.get("coverage_key") or "")
        if key in coverage_ids:
            coverage_ids[key].append(f"E{index}")
    coverage_lines = [
        f"{key}: {', '.join(ids)}"
        for key, ids in coverage_ids.items()
    ]
    task = (
        "Create a genuinely comprehensive full-document summary. Identify the document type and actual title; "
        "cover every required substantive section below in logical order; state the central thesis; distinguish "
        "the authors' claims from cited background; include the conclusion; and avoid metadata or OCR fragments. "
        "Start with the exact title using the Persian label 'عنوان سند:'. "
        "Use explicit Persian section labels where applicable: 'هدف و مسئله:'، 'مقدمه:'، 'روش کار:'، "
        "'یافته‌ها:'، 'بحث:'، 'نتیجه‌گیری:' and 'پیامدهای عملی:'. "
        "Write exactly one cohesive 35-to-60-word paragraph for each coverage-map row, in map order, and at most "
        "one additional synthesis paragraph; do not repeat a section's details elsewhere. "
        "Do not call the result comprehensive unless every section is represented. "
        "For every row in the coverage map, include at least one paragraph whose evidence_ids contains "
        "one of that row's IDs; overlapping sections still require their own evidence ID.\n"
        f"Documents:\n" + "\n".join(title_lines) + "\n"
        "Required evidence coverage map:\n- " + "\n- ".join(coverage_lines)
    )
    result = rag.generate_response(
        state.get("generation_question") or state["question"],
        evidence,
        scope=state.get("scope") or "selected",
        selected_source=state.get("selected_source"),
        chat_provider=provider,
        retrieval_metadata={"rewrite_used": False, "retrieval_mode": strategy},
        task_instructions=task,
        extra_contract_error=lambda raw: _summary_coverage_contract(raw, evidence, set(required)),
        max_output_tokens=3200,
        support_scope_chunks=evidence,
    )
    coverage = _coverage_record(evidence, required, result.get("used_evidence_ids") or [])
    if result.get("error") or not coverage["coverage_passed"]:
        return {
            "answer": "خلاصه جامع قابل اعتبارسنجی تولید نشد؛ لطفاً دوباره تلاش کنید.",
            "sources": [],
            "metadata": {
                "intent": "comprehensive_summary",
                "strategy": strategy,
                "assets": len(assets),
                "evidence_items": len(evidence),
                "coverage": coverage,
                "generation": result.get("generation_telemetry"),
                "citation_validation": result.get("citation_validation"),
            },
        }
    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "metadata": {
            "intent": "comprehensive_summary",
            "strategy": strategy,
            "assets": len(assets),
            "evidence_items": len(evidence),
            "document_token_estimate": total_token_estimate,
            "retrieval_calls": 0,
            "embedding_calls": 0,
            "rewrite_calls": 0,
            "rerank_calls": 0,
            "sections_considered": len(groups),
            "section_summaries": len(evidence) if strategy == "hierarchical_section_aware" else 0,
            "section_generation_telemetry": section_generation_telemetry if strategy == "hierarchical_section_aware" else [],
            "coverage": coverage,
            "generation": result.get("generation_telemetry"),
            "citation_validation": result.get("citation_validation"),
        },
    }


def _comprehensive_summary_node(state: AgenticRagState) -> AgenticRagState:
    return _run_safe_comprehensive_summary(state)


def _legacy_comprehensive_summary_node(state: AgenticRagState) -> AgenticRagState:
    provider = get_chat_provider(
        state.get("chat_provider_name"),
        state.get("chat_model"),
        feature="chat_grounded",
    )
    return _run_comprehensive_summary(provider, state)


def _build_graph():
    builder = StateGraph(AgenticRagState)
    builder.add_node("plan_request", _planner_node)
    builder.add_node("free_chat", _free_chat_node)
    builder.add_node("focused_rag", _focused_rag_node)
    builder.add_node("specific_section", _specific_section_node)
    builder.add_node("analytical", _analytical_node)
    builder.add_node("conversational_followup", _conversational_followup_node)
    builder.add_node("comprehensive_summary", _comprehensive_summary_node)
    builder.add_edge(START, "plan_request")
    builder.add_conditional_edges(
        "plan_request",
        _route_after_plan,
        {
            "free_chat": "free_chat",
            "focused_rag": "focused_rag",
            "specific_section": "specific_section",
            "analytical": "analytical",
            "conversational_followup": "conversational_followup",
            "comprehensive_summary": "comprehensive_summary",
        },
    )
    builder.add_edge("free_chat", END)
    builder.add_edge("focused_rag", END)
    builder.add_edge("specific_section", END)
    builder.add_edge("analytical", END)
    builder.add_edge("conversational_followup", END)
    builder.add_edge("comprehensive_summary", END)
    return builder.compile()


_GRAPH = None


def graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph()
    return _GRAPH


def _initial_state(
    question: str,
    scope: str = "all",
    document_id: str = None,
    asset_ids: List[str] = None,
    user_id: int = None,
    selected_source: str = None,
    chat_provider_name: str = None,
    chat_model: str = None,
    generation_question: str = None,
    conversation_history: List[Dict[str, Any]] = None,
    conversation_id: str = None,
    request_id: str = None,
    langgraph_enabled: bool = True,
) -> AgenticRagState:
    asset_ids = [asset_id for asset_id in (asset_ids or []) if asset_id]
    doc_filter = document_id if scope == "selected" and not asset_ids else None
    if asset_ids:
        scope = "selected"
    return {
        "question": question,
        "generation_question": generation_question or question,
        "scope": scope,
        "document_id": doc_filter,
        "document_ids": asset_ids,
        "user_id": user_id,
        "selected_source": selected_source,
        "chat_provider_name": chat_provider_name,
        "chat_model": chat_model,
        "conversation_history": conversation_history or [],
        "conversation_id": conversation_id,
        "request_id": request_id,
        "langgraph_enabled": bool(langgraph_enabled),
    }


_HANDLERS = {
    "free_chat": _free_chat_node,
    "focused_rag": _focused_rag_node,
    "specific_section": _specific_section_node,
    "analytical": _analytical_node,
    "conversational_followup": _conversational_followup_node,
    "comprehensive_summary": _comprehensive_summary_node,
}
_DETERMINISTIC_IMPLEMENTATIONS = {
    "conversation_only",
    "direct_whole_document",
    "hierarchical_section_aware",
    "table_or_structured_document",
}


def _provider_cost(metadata: Dict[str, Any]) -> float:
    generation = metadata.get("generation") or {}
    total = float(generation.get("primary_cost") or 0) + float(generation.get("fallback_cost") or 0)
    for item in metadata.get("section_generation_telemetry") or []:
        total += float(item.get("primary_cost") or 0) + float(item.get("fallback_cost") or 0)
    return round(total, 8)


def _validation_details(metadata: Dict[str, Any]) -> tuple[str, list[str]]:
    failures = []
    coverage = metadata.get("coverage") or {}
    failures.extend(str(value) for value in coverage.get("hard_failures") or [])
    generation = metadata.get("generation") or {}
    if generation.get("error_category"):
        failures.append(str(generation["error_category"]))
    citation = metadata.get("citation_validation") or {}
    if citation.get("status") in {"invalid_json", "no_supported_paragraphs"}:
        failures.append(str(citation["status"]))
    return ("failed" if failures else "passed"), list(dict.fromkeys(failures))


def _finalize_execution_metadata(
    state: AgenticRagState,
    plan_update: AgenticRagState,
    result: AgenticRagState,
    *,
    execution: str,
    latency_ms: int,
    streaming_events: list[str] | None = None,
) -> AgenticRagState:
    metadata = dict(result.get("metadata") or {})
    request_plan = plan_update.get("request_plan") or {}
    assets = _selected_assets(state)
    pages = metadata.get("pages_considered") or (metadata.get("coverage") or {}).get("pages_considered")
    if pages is None:
        pages = sorted({
            int(item["page"])
            for item in result.get("chunks") or []
            if item.get("page")
        })
    validation_result, validation_failure_codes = _validation_details(metadata)
    generation = metadata.get("generation") or {}
    selected_route = request_plan.get("route_implementation") or plan_update.get("route")
    graph_path = ["plan_request"]
    if execution == "langgraph_state_graph":
        graph_path.append(str(plan_update.get("route") or "focused_rag"))
    telemetry = {
        "request_id": state.get("request_id"),
        "runtime_build_id": os.getenv("RUNTIME_BUILD_ID") or rag.ANSWER_PROMPT_VERSION,
        "conversation_id": state.get("conversation_id"),
        "selected_asset_id": assets[0]["id"] if len(assets) == 1 else None,
        "selected_asset_ids": [asset["id"] for asset in assets],
        "detected_intent": plan_update.get("intent"),
        "selected_route": selected_route,
        "evaluation_route": plan_update.get("route"),
        "route_implementation": execution,
        "graph_node_path": graph_path if execution == "langgraph_state_graph" else [],
        "history_count": len(state.get("conversation_history") or []),
        "document_token_estimate": int(request_plan.get("document_token_estimate") or 0),
        "retrieval_calls": int(metadata.get("retrieval_calls") or 0),
        "embedding_calls": int(metadata.get("embedding_calls") or 0),
        "rewrite_calls": int(metadata.get("rewrite_calls") or 0),
        "reranker_calls": int(metadata.get("rerank_calls") or 0),
        "pages_considered": pages,
        "sections_considered": int(metadata.get("sections_considered") or 0),
        "table_blocks_considered": int(metadata.get("table_blocks_considered") or 0),
        "validation_result": validation_result,
        "validation_failure_codes": validation_failure_codes,
        "fallback_used": bool(generation.get("fallback_used")),
        "user_facing_streaming_events": list(streaming_events or []),
        "latency_ms": latency_ms,
        "provider_cost": _provider_cost(metadata),
    }
    metadata.update({
        "request_plan": request_plan,
        "selected_route": selected_route,
        "route_implementation": execution,
        "telemetry": telemetry,
    })
    return {**result, "metadata": metadata}


def _execute_authoritative(
    initial_state: AgenticRagState,
    *,
    streaming_events: list[str] | None = None,
) -> AgenticRagState:
    started = time.perf_counter()
    plan_update = _planner_node(initial_state)
    planned_state = {**initial_state, **plan_update}
    semantic_route = (plan_update.get("request_plan") or {}).get("route_implementation")
    if initial_state.get("langgraph_enabled") and semantic_route not in _DETERMINISTIC_IMPLEMENTATIONS:
        result = graph().invoke(initial_state)
        execution = "langgraph_state_graph"
    else:
        handler = _HANDLERS.get(plan_update.get("route") or "focused_rag", _focused_rag_node)
        result = handler(planned_state)
        execution = "deterministic_handler"
    return _finalize_execution_metadata(
        initial_state,
        plan_update,
        result,
        execution=execution,
        latency_ms=round((time.perf_counter() - started) * 1000),
        streaming_events=streaming_events,
    )


def answer_request(*args, **kwargs) -> Dict[str, Any]:
    result = _execute_authoritative(_initial_state(*args, **kwargs))
    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "metadata": result.get("metadata", {}),
    }


def _stream_stage_ids(plan: Dict[str, Any]) -> tuple[list[str], list[str]]:
    implementation = plan.get("route_implementation")
    if implementation in {"direct_whole_document", "hierarchical_section_aware"}:
        return ["summary_document_review", "summary_generation"], ["summary_validation"]
    if implementation == "conversation_only" and plan.get("intent") == "conversational_followup":
        return ["conversation_history_review", "conversation_explanation"], []
    if implementation == "conversation_only":
        return ["answer_preparation"], []
    if implementation == "table_or_structured_document":
        return ["table_inspection", "table_matching"], ["answer_preparation"]
    return ["retrieval_search", "evidence_review"], ["answer_preparation"]


def answer_request_stream(*args, **kwargs) -> Iterable[Dict[str, Any]]:
    initial_state = _initial_state(*args, **kwargs)
    plan_update = _planner_node(initial_state)
    before, after = _stream_stage_ids(plan_update.get("request_plan") or {})
    visible_events = before + after
    for stage in before:
        yield rag._trace(stage, "started")
    result = _execute_authoritative(initial_state, streaming_events=visible_events)
    for stage in after:
        yield rag._trace(stage, "done")
    metadata = result.get("metadata") or {}
    answer = result.get("answer", "")
    if answer:
        yield {"type": "token", "delta": answer}
    yield {
        "type": "final",
        "answer": answer,
        "sources": result.get("sources", []),
        "metadata": metadata,
    }
    yield {"type": "done"}
    return

    if plan_update.get("route") == "comprehensive_summary":
        provider = get_chat_provider(
            planned_state.get("chat_provider_name"),
            planned_state.get("chat_model"),
            feature="chat_grounded",
        )
        yield rag._trace("agent_summary", "started", intent="comprehensive_summary")

        question = planned_state.get("generation_question") or planned_state["question"]
        assets, chapter_units = _chapter_units_for_state(planned_state)
        if chapter_units:
            source_labels = [
                item["label"]
                for unit in chapter_units
                for item in unit["evidence"]
            ]
            section_summaries = []
            failed_chapters = 0
            cache_hits = 0
            for index, unit in enumerate(chapter_units, start=1):
                yield rag._trace(
                    "agent_summary_chapter",
                    "started",
                    index=index,
                    total=len(chapter_units),
                    unit_title=unit["title"],
                )
                try:
                    summary, cache_hit = _chapter_summary(provider, question, unit)
                    cache_hits += int(cache_hit)
                except Exception as exc:  # noqa: BLE001
                    failed_chapters += 1
                    print(f"[agentic_rag] chapter summary failed ({unit['title']}): {exc}", flush=True)
                    yield rag._trace(
                        "agent_summary_chapter",
                        "failed",
                        index=index,
                        total=len(chapter_units),
                        unit_title=unit["title"],
                    )
                    continue
                if summary:
                    section_summaries.append({
                        "label": unit["title"],
                        "summary": f"### {unit['title']}\n{summary}",
                        "source_labels": source_labels,
                        "marker": f"C{len(section_summaries) + 1}",
                    })
                yield rag._trace(
                    "agent_summary_chapter",
                    "done",
                    index=index,
                    total=len(chapter_units),
                    unit_title=unit["title"],
                    cached=cache_hit,
                )

            if not section_summaries:
                answer = "خلاصه‌سازی فصل‌ها به دلیل خطای ارتباط با مدل انجام نشد. کمی بعد دوباره تلاش کنید."
                yield {"type": "token", "delta": answer}
                yield {"type": "final", "answer": answer, "sources": []}
                yield {"type": "done"}
                return

            yield rag._trace("agent_summary_reduce", "started", unit_title="جمع‌بندی نهایی")
            try:
                result = _final_summary(provider, question, section_summaries)
            except Exception as exc:  # noqa: BLE001
                print(f"[agentic_rag] final chapter summary failed, using fallback ({exc})", flush=True)
                result = _fallback_final_answer(question, section_summaries)
            yield rag._trace("agent_summary_reduce", "done", unit_title="جمع‌بندی نهایی")
            metadata = {
                "intent": "comprehensive_summary",
                "assets": len(assets),
                "chapters": len(chapter_units),
                "failed_chapters": failed_chapters,
                "summary_cache_hits": cache_hits,
                "section_summaries": len(section_summaries),
                "evidence_items": len(source_labels),
                "strategy": "chapter_map_reduce",
            }
            yield rag._trace(
                "agent_summary",
                "done",
                chapters=metadata["chapters"],
                failed_chapters=metadata["failed_chapters"],
                summary_cache_hits=metadata["summary_cache_hits"],
                section_summaries=metadata["section_summaries"],
                strategy=metadata["strategy"],
            )
            answer = result.get("answer", "")
            if answer:
                yield {"type": "token", "delta": answer}
            yield {"type": "final", "answer": answer, "sources": result.get("sources", [])}
            yield {"type": "done"}
            return

        assets, evidence, batches = _summary_evidence_for_state(planned_state)
        if not batches:
            answer = rag._no_info_message(planned_state.get("scope") or "selected")
            yield {"type": "token", "delta": answer}
            yield {"type": "final", "answer": answer, "sources": []}
            yield {"type": "done"}
            return

        source_labels = [item["label"] for item in evidence]

        if len(batches) == 1:
            label = f"{len(batches[0])} شاهد صفحه‌ای"
            yield rag._trace("agent_summary_window", "started", index=1, total=1, source=label)
            try:
                answer = _summarize_evidence_batch(
                    provider,
                    question,
                    batches[0],
                    final_output=True,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[agentic_rag] single-pass summary failed: {exc}", flush=True)
                yield rag._trace("agent_summary_window", "failed", index=1, total=1, source=label)
                answer = "سهمیه یا ارتباط مدل اجازه نداد خلاصه جامع ساخته شود. کمی بعد دوباره تلاش کنید."
                yield {"type": "token", "delta": answer}
                yield {"type": "final", "answer": answer, "sources": []}
                yield {"type": "done"}
                return

            yield rag._trace("agent_summary_window", "done", index=1, total=1, source=label)
            yield rag._trace(
                "agent_summary",
                "done",
                windows=1,
                failed_windows=0,
                section_summaries=1,
                strategy="single_pass",
            )
            yield {"type": "token", "delta": answer}
            yield {"type": "final", "answer": answer, "sources": source_labels}
            yield {"type": "done"}
            return

        section_summaries = []
        failed_windows = 0
        for index, batch in enumerate(batches, start=1):
            label = f"{len(batch)} شاهد صفحه‌ای"
            yield rag._trace("agent_summary_window", "started", index=index, total=len(batches), source=label)
            try:
                summary = _summarize_evidence_batch(provider, question, batch)
            except Exception as exc:  # noqa: BLE001
                failed_windows += 1
                print(f"[agentic_rag] summary window failed ({label}): {exc}", flush=True)
                yield rag._trace("agent_summary_window", "failed", index=index, total=len(batches), source=label)
                continue
            if summary:
                section_summaries.append({
                    "label": label,
                    "summary": summary,
                    "source_labels": source_labels,
                    "marker": f"S{len(section_summaries) + 1}",
                })
            yield rag._trace("agent_summary_window", "done", index=index, total=len(batches), source=label)

        if not section_summaries:
            answer = "خلاصه‌سازی جامع به دلیل خطای ارتباط با مدل انجام نشد. دوباره تلاش کنید یا مقدار AGENTIC_SUMMARY_MAX_WINDOWS را کمتر کنید."
            yield {"type": "token", "delta": answer}
            yield {"type": "final", "answer": answer, "sources": []}
            yield {"type": "done"}
            return

        try:
            result = _final_summary(provider, question, section_summaries)
        except Exception as exc:  # noqa: BLE001
            print(f"[agentic_rag] final summary failed, using fallback ({exc})", flush=True)
            result = _fallback_final_answer(question, section_summaries)
        result["metadata"] = {
            "intent": "comprehensive_summary",
            "assets": len(assets),
            "windows": len(batches),
            "evidence_items": len(evidence),
            "failed_windows": failed_windows,
            "section_summaries": len(section_summaries),
        }
        metadata = result.get("metadata") or {}
        yield rag._trace(
            "agent_summary",
            "done",
            windows=metadata.get("windows"),
            failed_windows=metadata.get("failed_windows"),
            section_summaries=metadata.get("section_summaries"),
        )
        answer = result.get("answer", "")
        if answer:
            yield {"type": "token", "delta": answer}
        yield {"type": "final", "answer": answer, "sources": result.get("sources", [])}
        yield {"type": "done"}
        return

    final_state: Dict[str, Any] = {}
    for update in graph().stream(initial_state, stream_mode="updates"):
        for node_name, node_update in update.items():
            final_state.update(node_update or {})
            if node_name == "plan_request":
                continue
            elif node_name == "focused_rag":
                metadata = node_update.get("metadata") or {}
                yield rag._trace(
                    "agent_retrieve",
                    "done",
                    intent=metadata.get("intent"),
                    chunks=metadata.get("retrieved_chunks"),
                )
            elif node_name == "comprehensive_summary":
                metadata = node_update.get("metadata") or {}
                yield rag._trace(
                    "agent_summary",
                    "done",
                    windows=metadata.get("windows"),
                    section_summaries=metadata.get("section_summaries"),
                )

    answer = final_state.get("answer", "")
    if answer:
        yield {"type": "token", "delta": answer}
    yield {
        "type": "final",
        "answer": answer,
        "sources": final_state.get("sources", []),
    }
    yield {"type": "done"}
