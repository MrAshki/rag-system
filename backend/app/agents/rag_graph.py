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
from model_gateway import get_chat_provider
from backend.app.agents.request_router import plan_request
from backend.app.grounding import normalize_citations_at_paragraph_end, parse_grounded_response


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


def _has_grounding_scope(state: AgenticRagState) -> bool:
    return bool(state.get("document_id") or state.get("document_ids"))


def _planner_node(state: AgenticRagState) -> AgenticRagState:
    plan = plan_request(
        state.get("question") or state.get("generation_question") or "",
        has_document_scope=_has_grounding_scope(state),
    )
    return {
        "intent": plan.intent,
        "route": plan.route,
        "route_reason": plan.reason,
        "request_plan": plan.to_dict(),
    }


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
        except RuntimeError as exc:
            return {
                "answer": str(exc),
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
        except RuntimeError as exc:
            blocks.append(f"❖ {sq['user_question']}\n{exc}")
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
    lines = [
        "خلاصه جامع سند بر اساس بخش‌هایی که با موفقیت پردازش شدند:",
        "",
    ]
    for item in section_summaries:
        lines.append(f"- {item['summary']}")
    lines.append("")
    lines.append("جمع‌بندی: این خلاصه از مسیر agentic map-reduce ساخته شده، اما مرحله ترکیب نهایی مدل کامل نشد؛ بنابراین خلاصه‌های بخشی به شکل مستقیم نمایش داده شدند.")
    labels = section_summaries[0].get("source_labels", []) if section_summaries else []
    if not labels:
        labels = [item["label"] for item in section_summaries]
    return normalize_citations_at_paragraph_end("\n".join(lines), labels)


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


def _comprehensive_summary_node(state: AgenticRagState) -> AgenticRagState:
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
    builder.add_node("comprehensive_summary", _comprehensive_summary_node)
    builder.add_edge(START, "plan_request")
    builder.add_conditional_edges(
        "plan_request",
        _route_after_plan,
        {
            "free_chat": "free_chat",
            "focused_rag": "focused_rag",
            "comprehensive_summary": "comprehensive_summary",
        },
    )
    builder.add_edge("free_chat", END)
    builder.add_edge("focused_rag", END)
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
    }


def answer_request(*args, **kwargs) -> Dict[str, Any]:
    result = graph().invoke(_initial_state(*args, **kwargs))
    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "metadata": result.get("metadata", {}),
    }


def answer_request_stream(*args, **kwargs) -> Iterable[Dict[str, Any]]:
    initial_state = _initial_state(*args, **kwargs)
    yield rag._trace("agent_graph", "started")

    plan_update = _planner_node(initial_state)
    planned_state = dict(initial_state)
    planned_state.update(plan_update)
    yield rag._trace(
        "agent_plan",
        "done",
        intent=plan_update.get("intent"),
        route=plan_update.get("route"),
        reason=plan_update.get("route_reason"),
    )

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
