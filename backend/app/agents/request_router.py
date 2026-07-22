"""Low-cost request classification and retrieval budgeting.

The router is deterministic by default. It gives LangGraph an explicit plan
without spending an LLM call on ordinary requests. Ambiguous multi-question
messages can still opt into the existing model-based decomposition step.
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
    reason: str
    coverage: str
    detail: str
    citation_level: str
    requires_document_map: bool
    decompose_query: bool
    budget: RetrievalBudget

    def to_dict(self) -> dict:
        return asdict(self)


POLICIES = {
    "exact_answer": RetrievalBudget(candidate_k=18, evidence_k=5),
    "explain": RetrievalBudget(candidate_k=26, evidence_k=8),
    "compare": RetrievalBudget(candidate_k=36, evidence_k=10, max_subqueries=3),
    "extract": RetrievalBudget(candidate_k=24, evidence_k=10),
    "focused_summary": RetrievalBudget(candidate_k=30, evidence_k=10),
    "comprehensive_summary": RetrievalBudget(candidate_k=0, evidence_k=0, use_reranker=False),
    "free_chat": RetrievalBudget(candidate_k=0, evidence_k=0, use_reranker=False),
}

SUMMARY_RE = re.compile(r"خلاصه|جمع\s*بندی|چکیده|summar", re.IGNORECASE)
FULL_SCOPE_RE = re.compile(
    r"جامع|کامل|کل(?:\s|$)|همه|تمام|سرتاسر|کتاب|سند|فایل|"
    r"comprehensive|complete|entire|whole",
    re.IGNORECASE,
)
COMPARE_RE = re.compile(r"مقایسه|تفاوت|شباهت|در برابر|versus|\bvs\.?\b|compare|difference", re.IGNORECASE)
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


def _looks_multi_question(text: str) -> bool:
    marks = len(re.findall(r"[؟?]", text or ""))
    conjunction = bool(re.search(r"(?:^|\s)(?:همچنین|بعلاوه|و نیز|also|and also)(?:\s|$)", text or "", re.IGNORECASE))
    return marks >= 2 or (marks >= 1 and conjunction)


def plan_request(question: str, *, has_document_scope: bool) -> RequestPlan:
    text = (question or "").strip()
    detail = "detailed" if DETAIL_RE.search(text) else "concise"

    if not has_document_scope:
        intent = route = "free_chat"
        reason = "no_document_scope"
        coverage = "none"
        requires_map = False
    elif SUMMARY_RE.search(text) and FULL_SCOPE_RE.search(text):
        intent = route = "comprehensive_summary"
        reason = "full_document_summary_requested"
        coverage = "comprehensive"
        requires_map = True
    elif SUMMARY_RE.search(text):
        intent, route = "focused_summary", "focused_rag"
        reason, coverage, requires_map = "focused_summary_requested", "focused", False
    elif COMPARE_RE.search(text):
        intent, route = "compare", "focused_rag"
        reason, coverage, requires_map = "comparison_requested", "multi_source", False
    elif EXTRACT_RE.search(text):
        intent, route = "extract", "focused_rag"
        reason, coverage, requires_map = "structured_extraction_requested", "focused", False
    elif EXPLAIN_RE.search(text):
        intent, route = "explain", "focused_rag"
        reason, coverage, requires_map = "explanation_requested", "expanded", False
    else:
        intent, route = "exact_answer", "focused_rag"
        reason, coverage, requires_map = "default_grounded_question", "focused", False

    return RequestPlan(
        intent=intent,
        route=route,
        reason=reason,
        coverage=coverage,
        detail=detail,
        citation_level="paragraph",
        requires_document_map=requires_map,
        decompose_query=_looks_multi_question(text) and route == "focused_rag",
        budget=POLICIES[intent],
    )
