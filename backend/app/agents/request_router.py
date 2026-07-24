"""Deterministic fallback routing and retrieval budgeting.

Production requests are classified semantically by the intent supervisor and
validated deterministically. This router remains the bounded fallback for
malformed, timed-out, or low-confidence supervisor responses.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RetrievalBudget:
    candidate_k: int
    evidence_k: int
    use_reranker: bool = True
    max_subqueries: int = 1


@dataclass(frozen=True)
class RequestPlan:
    intent: str
    route: str
    route_implementation: str
    reason: str
    coverage: str
    detail: str
    citation_level: str
    requires_document_map: bool
    decompose_query: bool
    target_section: str | None
    target_page: int | None
    history_required: bool
    budget: RetrievalBudget

    def to_dict(self) -> dict:
        return asdict(self)


POLICIES = {
    "exact_answer": RetrievalBudget(candidate_k=18, evidence_k=5),
    "explain": RetrievalBudget(candidate_k=26, evidence_k=8),
    "compare": RetrievalBudget(candidate_k=36, evidence_k=10, max_subqueries=3),
    "analytical": RetrievalBudget(candidate_k=40, evidence_k=12, max_subqueries=3),
    "extract": RetrievalBudget(candidate_k=24, evidence_k=10),
    "specific_section": RetrievalBudget(candidate_k=0, evidence_k=14, use_reranker=False),
    "conversational_followup": RetrievalBudget(candidate_k=0, evidence_k=10, use_reranker=False),
    "retry_previous": RetrievalBudget(candidate_k=0, evidence_k=0, use_reranker=False),
    "focused_summary": RetrievalBudget(candidate_k=30, evidence_k=10),
    "comprehensive_summary": RetrievalBudget(candidate_k=0, evidence_k=0, use_reranker=False),
    "free_chat": RetrievalBudget(candidate_k=0, evidence_k=0, use_reranker=False),
}

DIRECT_DOCUMENT_TOKEN_LIMIT = 24_000
SUMMARY_RE = re.compile(r"خلاصه|جمع\s*بندی|چکیده|summar", re.IGNORECASE)
FULL_SCOPE_RE = re.compile(
    r"جامع|کامل|کل(?:\s|$)|همه|تمام|سرتاسر|کتاب|سند|فایل|"
    r"بخش(?:‌|\s)*به(?:‌|\s)*بخش|موضوعات اصلی|استدلال کامل|نمای کلی|"
    r"comprehensive|complete|entire|whole|section.by.section|main themes|complete argument|overview",
    re.IGNORECASE,
)
COMPARE_RE = re.compile(r"مقایسه|تفاوت|شباهت|در برابر|versus|\bvs\.?\b|compare|difference", re.IGNORECASE)
ANALYTICAL_RE = re.compile(
    r"رابطه|ارتباط|استدلال|ادعا|چرا|چگونه|تحلیل|مفهوم|درونمایه|مضمون|"
    r"relationship|relation|argument|claim|why|how|analy|concept|theme",
    re.IGNORECASE,
)
DEFINITION_RE = re.compile(
    r"(?:چگونه|چطور)\s+تعریف|تعریف\s+(?:شده|می‌شود)|(?:چیست|یعنی\s+چه)|"
    r"how\s+is\s+.+\s+defined|what\s+is\s+the\s+definition",
    re.IGNORECASE,
)
NUMERIC_FACT_RE = re.compile(
    r"(?:چند|چقدر|چه\s+درصد|چه\s+سهم|چند\s+درصد|how\s+many|how\s+much|what\s+percent)",
    re.IGNORECASE,
)
ATTRIBUTED_FACT_RE = re.compile(r"\baccording\s+to\s+(?:this|the)\b", re.IGNORECASE)
EXPLAIN_RE = re.compile(
    r"توضیح|تشریح|بیشتر بگو|دقیق(?:‌|\s)*تر|ساده|مثال|یاد بده|"
    r"explain|elaborate|teach|example",
    re.IGNORECASE,
)
EXTRACT_RE = re.compile(
    r"استخراج|فهرست|لیست|جدول|نام ببر|موارد|تاریخ(?:‌|\s)*ها|عدد(?:‌|\s)*ها|"
    r"extract|list|table|entities|dates",
    re.IGNORECASE,
)
DETAIL_RE = re.compile(r"مفصل|جامع|کامل|دقیق|با جزئیات|detailed|thorough", re.IGNORECASE)
PAGE_RE = re.compile(r"(?:صفحه|page)\s*([0-9۰-۹]+)", re.IGNORECASE)
SECTION_RE = re.compile(
    r"(?:چکیده|abstract|مقدمه|introduction|نتیجه(?:‌|\s)*گیری|conclusions?|"
    r"منابع|references|جدول|\btable\b|(?:طبق|در)\s+شکل(?:‌|\s)*[0-9۰-۹]+|"
    r"\bfigure\s*[0-9]*\b|بخش(?:‌|\s)+[^؟?،,.]{1,80})",
    re.IGNORECASE,
)
SHORT_FOLLOWUP_RE = re.compile(
    r"^(?:یعنی\s+چی|منظورت\s+چیه|چرا\s+این\s+اتفاق\s+افتاد|بیشتر\s+توضیح\s+بده|"
    r"(?:این|اون)\s+حرف\s+از\s+کجای\s+فایل\s+بود|بخش\s+\S+\s+رو\s+ساده(?:‌|\s)*تر\s+بگو|"
    r"what\s+does\s+that\s+mean|explain\s+that|why\s+did\s+that\s+happen|tell\s+me\s+more)\s*[؟?!.]*$",
    re.IGNORECASE,
)
RETRY_RE = re.compile(r"^(?:دوباره\s+(?:امتحان|تلاش)\s+کن|retry|try\s+again)\s*[.!]*$", re.IGNORECASE)
QUOTED_RE = re.compile(r"[«\"“][^»\"”]{3,}[»\"”]")
TABLE_RE = re.compile(
    r"(?:جدول|\btable\b)\s*[0-9۰-۹]*|رتبه(?:ٔ|‌|\s)*(?:اول|دوم|سوم|[0-9۰-۹]+)|"
    r"شاخص\s+نزدیکی|سطر|ردیف|ستون|coefficient|structured\s+data",
    re.IGNORECASE,
)
ANAPHORIC_FOLLOWUP_RE = re.compile(
    r"^(?:(?:این|آن|اون|همان|این\s+یکی|آن\s+یکی)\b|"
    r"از\s+میان\s+(?:آن\s*ها|آن‌ها|اون\s*ها|اون‌ها)\b).{0,140}[؟?!.]*$",
    re.IGNORECASE,
)
EVIDENCE_FOLLOWUP_RE = re.compile(
    r"^(?:از\s+میان\s+(?:آن\s*ها|آن‌ها|اون\s*ها|اون‌ها)|"
    r"(?:این|آن|اون|همان)\b.{0,60}(?:چند|چقدر|کدام|چه\s+زمان|چه\s+مقدار|چه\s+درصد))",
    re.IGNORECASE,
)


def _looks_multi_question(text: str) -> bool:
    marks = len(re.findall(r"[؟?]", text or ""))
    conjunction = bool(re.search(r"(?:^|\s)(?:همچنین|بعلاوه|و نیز|also|and also)(?:\s|$)", text or "", re.IGNORECASE))
    return marks >= 2 or (marks >= 1 and conjunction)


def _history_has_assistant(history: list[dict] | None) -> bool:
    return any(str(item.get("role") or "") == "assistant" and str(item.get("content") or "").strip() for item in (history or []))


def _target_section(text: str) -> str | None:
    lowered = text.lower()
    for pattern, role in (
        (r"چکیده|abstract", "abstract"),
        (r"مقدمه|introduction", "introduction"),
        (r"نتیجه(?:‌|\s)*گیری|conclusions?", "conclusion"),
        (r"منابع|references", "references"),
        (r"جدول|table", "table"),
        (r"(?:طبق|در)\s+شکل(?:‌|\s)*[0-9۰-۹]+|\bfigure\s*[0-9]*\b", "figure"),
    ):
        if re.search(pattern, lowered, re.IGNORECASE):
            return role
    named = re.search(r"(?:بخش|section)\s+[«\"“]([^»\"”]{1,80})[»\"”]", text, re.IGNORECASE)
    return named.group(1).strip() if named else None


def plan_request(
    question: str,
    *,
    has_document_scope: bool,
    conversation_history: list[dict] | None = None,
    selected_document_count: int | None = None,
    document_token_estimate: int | None = None,
    direct_document_token_limit: int = DIRECT_DOCUMENT_TOKEN_LIMIT,
) -> RequestPlan:
    text = (question or "").strip()
    detail = "detailed" if DETAIL_RE.search(text) else "concise"

    page_match = PAGE_RE.search(text)
    target_page = int(page_match.group(1).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))) if page_match else None
    target_section = _target_section(text)
    has_history = _history_has_assistant(conversation_history)
    history_required = False
    route_implementation = "local_hybrid_retrieval"

    # Routing precedence is deliberate: history reference, explicit quoted
    # document text, intent, selected-document count, token fit, table cues,
    # retrieval necessity, then the executable route.
    if RETRY_RE.match(text) and has_history:
        intent = route = "retry_previous"
        route_implementation = "conversation_only"
        reason, coverage, requires_map = "retry_previous_operation", "previous", False
        history_required = True
    elif (
        EVIDENCE_FOLLOWUP_RE.match(text)
        and has_history
        and not QUOTED_RE.search(text)
    ):
        intent = route = "conversational_followup"
        route_implementation = "history_aware_retrieval"
        reason, coverage, requires_map = "history_reference_requires_new_evidence", "focused", False
        history_required = True
    elif (
        (SHORT_FOLLOWUP_RE.match(text) or ANAPHORIC_FOLLOWUP_RE.match(text))
        and has_history
        and not QUOTED_RE.search(text)
    ):
        intent = route = "conversational_followup"
        route_implementation = "conversation_only"
        reason, coverage, requires_map = "clarify_previous_assistant_response", "previous_evidence", False
        history_required = True
    elif QUOTED_RE.search(text) and has_document_scope:
        intent, route = "explain", "focused_rag"
        route_implementation = "quoted_document_explanation"
        reason, coverage, requires_map = "explicit_quoted_document_text", "focused", False
    elif not has_document_scope:
        intent = route = "free_chat"
        route_implementation = "conversation_only"
        reason = "no_document_scope"
        coverage = "none"
        requires_map = False
    elif SUMMARY_RE.search(text) and FULL_SCOPE_RE.search(text):
        intent = route = "comprehensive_summary"
        fits = (
            selected_document_count == 1
            and document_token_estimate is not None
            and document_token_estimate <= direct_document_token_limit
        )
        route_implementation = "direct_whole_document" if fits else "hierarchical_section_aware"
        reason = "full_document_summary_requested"
        coverage = "comprehensive"
        requires_map = True
    elif TABLE_RE.search(text):
        intent, route = "specific_section", "specific_section"
        route_implementation = "table_or_structured_document"
        reason, coverage, requires_map = "table_or_structured_data_cue", "table", True
        target_section = "table"
    elif target_page is not None or (SECTION_RE.search(text) and target_section):
        intent, route = "specific_section", "specific_section"
        route_implementation = "local_hybrid_retrieval"
        reason, coverage, requires_map = "explicit_page_or_section_requested", "section", True
    elif SUMMARY_RE.search(text):
        intent, route = "focused_summary", "focused_rag"
        reason, coverage, requires_map = "focused_summary_requested", "focused", False
    elif DEFINITION_RE.search(text):
        intent, route = "exact_answer", "focused_rag"
        reason, coverage, requires_map = "definition_fact_requested", "focused", False
    elif NUMERIC_FACT_RE.search(text):
        intent, route = "exact_answer", "focused_rag"
        reason, coverage, requires_map = "numeric_fact_requested", "focused", False
    elif ATTRIBUTED_FACT_RE.search(text):
        intent, route = "exact_answer", "focused_rag"
        reason, coverage, requires_map = "attributed_fact_requested", "focused", False
    elif COMPARE_RE.search(text):
        intent, route = "compare", "analytical"
        reason, coverage, requires_map = "comparison_requested", "multi_source", False
    elif EXTRACT_RE.search(text):
        intent, route = "extract", "focused_rag"
        reason, coverage, requires_map = "structured_extraction_requested", "focused", False
    elif EXPLAIN_RE.search(text):
        intent, route = "explain", "focused_rag"
        reason, coverage, requires_map = "explanation_requested", "expanded", False
    elif ANALYTICAL_RE.search(text):
        intent, route = "analytical", "analytical"
        reason, coverage, requires_map = "cross_section_analysis_requested", "multi_section", True
    else:
        intent, route = "exact_answer", "focused_rag"
        reason, coverage, requires_map = "default_grounded_question", "focused", False

    return RequestPlan(
        intent=intent,
        route=route,
        route_implementation=route_implementation,
        reason=reason,
        coverage=coverage,
        detail=detail,
        citation_level="paragraph",
        requires_document_map=requires_map,
        decompose_query=_looks_multi_question(text) and route in {"focused_rag", "analytical"},
        target_section=target_section,
        target_page=target_page,
        history_required=history_required,
        budget=POLICIES[intent],
    )
