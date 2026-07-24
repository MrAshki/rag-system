"""Low-cost semantic intent supervision with deterministic safety validation."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from backend.app.agents.request_router import (
    DIRECT_DOCUMENT_TOKEN_LIMIT,
    POLICIES,
    RequestPlan,
    plan_request,
)
from backend.app.grounding.citations import load_json_object


INTENTS = {
    "conversation_explanation",
    "single_document_summary",
    "multi_document_summary",
    "multi_document_comparison",
    "document_question_answering",
    "table_or_numeric_qa",
    "quoted_text_explanation",
    "section_lookup",
    "analytical_synthesis",
    "general_chat",
    "clarification_required",
}
CAPABILITIES = tuple(sorted(INTENTS))
NO_RETRIEVAL_INTENTS = {
    "conversation_explanation",
    "general_chat",
    "clarification_required",
}
MIN_CONFIDENCE = float(os.getenv("RAG_SUPERVISOR_MIN_CONFIDENCE", "0.65"))
SUPERVISOR_MODEL = os.getenv(
    "RAG_SUPERVISOR_MODEL",
    "google/gemini-2.5-flash-lite",
).strip()


@dataclass(frozen=True)
class SupervisorDecision:
    intent: str
    scope: str
    uses_history: bool
    requires_retrieval: bool
    target_capability: str
    confidence: float


@dataclass(frozen=True)
class SupervisorOutcome:
    supervisor_intent: str | None
    supervisor_confidence: float
    validated_intent: str
    target_capability: str
    fallback_used: bool
    failure_code: str | None
    plan: dict[str, Any]
    provider_request_count: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int

    def telemetry(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if key != "plan"
        }


def summarize_relevant_history(history: list[dict[str, Any]] | None) -> str:
    """Return a bounded, non-logged history digest for semantic resolution."""
    rows = []
    for item in (history or [])[-4:]:
        role = str(item.get("role") or "")
        content = " ".join(str(item.get("content") or "").split())
        if role in {"user", "assistant"} and content:
            rows.append(f"{role}: {content[:500]}")
    return "\n".join(rows) if rows else "(none)"


def _messages(
    *,
    question: str,
    history_summary: str,
    selected_assets: list[dict[str, str]],
    has_previous_answer: bool,
    has_quoted_text: bool,
) -> list[dict[str, str]]:
    schema = (
        '{"intent":"document_question_answering","scope":"single_document",'
        '"uses_history":false,"requires_retrieval":true,'
        '"target_capability":"document_question_answering","confidence":0.95}'
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a semantic intent supervisor for a document RAG system. "
                "Classify meaning, not exact wording. Do not answer the user. "
                "Return one JSON object only, with no reasoning or extra keys. "
                f"Allowed intents and target capabilities: {', '.join(CAPABILITIES)}. "
                "Allowed scope values: no_document, single_document, multiple_documents. "
                "no_answer is forbidden; evidence sufficiency is decided downstream. "
                "Use conversation_explanation only when the user asks to restate, simplify, "
                "or explain the preceding assistant answer. A request to summarize selected "
                "documents is never conversation_explanation. Use multi_document_summary for "
                "separate coverage of every selected document plus synthesis. Use "
                "multi_document_comparison for similarities or differences across documents. "
                "Use clarification_required when the requested capability cannot be executed "
                "with the available state. Schema example: "
                f"{schema}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Latest user message:\n{question[:3000]}\n\n"
                f"Relevant history summary:\n{history_summary[:2200]}\n\n"
                f"Selected documents ({len(selected_assets)}):\n"
                + "\n".join(
                    f"- id={item['id']}; title={item['title'][:240]}"
                    for item in selected_assets
                )
                + f"\n\nPrevious assistant answer exists: {has_previous_answer}"
                + f"\nQuoted text exists: {has_quoted_text}"
                + f"\nAvailable capabilities: {', '.join(CAPABILITIES)}"
            ),
        },
    ]


def _decision_from_payload(payload: dict[str, Any]) -> SupervisorDecision | None:
    try:
        intent = str(payload["intent"]).strip()
        scope = str(payload["scope"]).strip()
        target = str(payload["target_capability"]).strip()
        confidence = float(payload["confidence"])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        intent not in INTENTS
        or target not in CAPABILITIES
        or scope not in {"no_document", "single_document", "multiple_documents"}
        or not isinstance(payload.get("uses_history"), bool)
        or not isinstance(payload.get("requires_retrieval"), bool)
        or not 0 <= confidence <= 1
    ):
        return None
    return SupervisorDecision(
        intent=intent,
        scope=scope,
        uses_history=payload["uses_history"],
        requires_retrieval=payload["requires_retrieval"],
        target_capability=target,
        confidence=confidence,
    )


def _has_previous_answer(history: list[dict[str, Any]] | None) -> bool:
    return any(
        item.get("role") == "assistant" and str(item.get("content") or "").strip()
        for item in (history or [])
    )


def _fallback_capability(plan: RequestPlan, selected_document_count: int) -> str:
    implementation = plan.route_implementation
    if implementation == "conversation_only":
        return (
            "conversation_explanation"
            if plan.intent == "conversational_followup"
            else "general_chat"
        )
    if implementation in {"direct_whole_document", "hierarchical_section_aware"}:
        return (
            "multi_document_summary"
            if selected_document_count > 1
            else "single_document_summary"
        )
    if implementation == "table_or_structured_document":
        return "table_or_numeric_qa"
    if implementation == "quoted_document_explanation":
        return "quoted_text_explanation"
    if plan.route == "specific_section":
        return "section_lookup"
    if plan.route == "analytical":
        return (
            "multi_document_comparison"
            if selected_document_count > 1 and plan.intent == "compare"
            else "analytical_synthesis"
        )
    return "document_question_answering"


def deterministic_fallback_outcome(
    *,
    question: str,
    conversation_history: list[dict[str, Any]] | None,
    selected_document_count: int,
    document_token_estimate: int,
    failure_code: str,
    fallback_used: bool = True,
) -> SupervisorOutcome:
    plan = plan_request(
        question,
        has_document_scope=selected_document_count > 0,
        conversation_history=conversation_history,
        selected_document_count=selected_document_count,
        document_token_estimate=document_token_estimate,
    )
    capability = _fallback_capability(plan, selected_document_count)
    payload = plan.to_dict()
    payload["target_capability"] = capability
    payload["supervisor_requires_retrieval"] = capability not in NO_RETRIEVAL_INTENTS
    return SupervisorOutcome(
        supervisor_intent=None,
        supervisor_confidence=0.0,
        validated_intent=capability,
        target_capability=capability,
        fallback_used=fallback_used,
        failure_code=failure_code,
        plan=payload,
        provider_request_count=0,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )


def _validated_plan(
    decision: SupervisorDecision,
    *,
    fallback_plan: RequestPlan,
    selected_document_count: int,
    document_token_estimate: int,
    has_previous_answer: bool,
    has_quoted_text: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    intent = decision.intent
    expected_scope = (
        "multiple_documents"
        if selected_document_count > 1
        else "single_document"
        if selected_document_count == 1
        else "no_document"
    )
    if decision.scope != expected_scope:
        return None, "scope_count_mismatch"
    if decision.target_capability != intent:
        return None, "intent_capability_mismatch"
    if decision.requires_retrieval != (intent not in NO_RETRIEVAL_INTENTS):
        return None, "retrieval_requirement_mismatch"
    if intent == "conversation_explanation" and not decision.uses_history:
        return None, "history_requirement_mismatch"
    if intent.startswith("multi_document_") and selected_document_count < 2:
        intent = "clarification_required"
    elif intent == "single_document_summary" and selected_document_count != 1:
        intent = "clarification_required"
    elif intent == "conversation_explanation" and not has_previous_answer:
        intent = "clarification_required"
    elif intent == "quoted_text_explanation" and not has_quoted_text:
        return None, "quoted_text_missing"
    elif intent not in {"general_chat", "conversation_explanation", "clarification_required"} and selected_document_count < 1:
        intent = "clarification_required"

    common = {
        "reason": "semantic_supervisor",
        "detail": fallback_plan.detail,
        "citation_level": "paragraph",
        "decompose_query": False,
        "target_section": fallback_plan.target_section,
        "target_page": fallback_plan.target_page,
    }
    if intent == "conversation_explanation":
        plan = RequestPlan(
            intent="conversational_followup", route="conversational_followup",
            route_implementation="conversation_only", coverage="previous_evidence",
            requires_document_map=False, history_required=True,
            budget=POLICIES["conversational_followup"], **common,
        )
    elif intent == "single_document_summary":
        implementation = (
            "direct_whole_document"
            if document_token_estimate <= DIRECT_DOCUMENT_TOKEN_LIMIT
            else "hierarchical_section_aware"
        )
        plan = RequestPlan(
            intent="comprehensive_summary", route="comprehensive_summary",
            route_implementation=implementation, coverage="comprehensive",
            requires_document_map=True, history_required=False,
            budget=POLICIES["comprehensive_summary"], **common,
        )
    elif intent == "multi_document_summary":
        plan = RequestPlan(
            intent=intent, route=intent, route_implementation=intent,
            coverage="multiple_documents", requires_document_map=True,
            history_required=False, budget=POLICIES["comprehensive_summary"], **common,
        )
    elif intent == "multi_document_comparison":
        plan = RequestPlan(
            intent=intent, route=intent, route_implementation=intent,
            coverage="multi_source", requires_document_map=True,
            history_required=False, budget=POLICIES["compare"], **common,
        )
    elif intent == "table_or_numeric_qa":
        plan = RequestPlan(
            intent="specific_section", route="specific_section",
            route_implementation="table_or_structured_document", coverage="table",
            requires_document_map=True, history_required=False,
            budget=POLICIES["specific_section"], **common,
        )
    elif intent == "quoted_text_explanation":
        plan = RequestPlan(
            intent="explain", route="focused_rag",
            route_implementation="quoted_document_explanation", coverage="focused",
            requires_document_map=False, history_required=False,
            budget=POLICIES["explain"], **common,
        )
    elif intent == "section_lookup":
        plan = RequestPlan(
            intent="specific_section", route="specific_section",
            route_implementation="local_hybrid_retrieval", coverage="section",
            requires_document_map=True, history_required=False,
            budget=POLICIES["specific_section"], **common,
        )
    elif intent == "analytical_synthesis":
        plan = RequestPlan(
            intent="analytical", route="analytical",
            route_implementation="local_hybrid_retrieval", coverage="multi_section",
            requires_document_map=True, history_required=False,
            budget=POLICIES["analytical"], **common,
        )
    elif intent == "general_chat":
        plan = RequestPlan(
            intent="free_chat", route="free_chat",
            route_implementation="conversation_only", coverage="none",
            requires_document_map=False, history_required=False,
            budget=POLICIES["free_chat"], **common,
        )
    elif intent == "clarification_required":
        plan = RequestPlan(
            intent=intent, route=intent, route_implementation=intent,
            coverage="none", requires_document_map=False, history_required=False,
            budget=POLICIES["free_chat"], **common,
        )
    else:
        plan = RequestPlan(
            intent="exact_answer", route="focused_rag",
            route_implementation="local_hybrid_retrieval", coverage="focused",
            requires_document_map=False, history_required=False,
            budget=POLICIES["exact_answer"], **common,
        )
    result = plan.to_dict()
    result["target_capability"] = intent
    result["supervisor_requires_retrieval"] = intent not in NO_RETRIEVAL_INTENTS
    return result, None


def supervise_request(
    *,
    question: str,
    conversation_history: list[dict[str, Any]] | None,
    selected_assets: list[dict[str, str]],
    document_token_estimate: int,
    provider: Any,
    confidence_threshold: float = MIN_CONFIDENCE,
) -> SupervisorOutcome:
    selected_count = len(selected_assets)
    fallback_plan = plan_request(
        question,
        has_document_scope=selected_count > 0,
        conversation_history=conversation_history,
        selected_document_count=selected_count,
        document_token_estimate=document_token_estimate,
    )
    has_previous = _has_previous_answer(conversation_history)
    has_quote = any(mark in (question or "") for mark in ("«", "»", '"', "“", "”"))
    failure_code = None
    decision = None
    try:
        raw = provider.chat(
            messages=_messages(
                question=question,
                history_summary=summarize_relevant_history(conversation_history),
                selected_assets=selected_assets,
                has_previous_answer=has_previous,
                has_quoted_text=has_quote,
            ),
            options={
                "temperature": 0.0,
                "max_tokens": 220,
                "reasoning": {"effort": "none", "exclude": True},
                "seed": 23,
            },
            response_format="json",
        )
        decision = _decision_from_payload(load_json_object(raw) or {})
        if decision is None:
            failure_code = "invalid_supervisor_json"
        elif decision.confidence < confidence_threshold:
            failure_code = "low_supervisor_confidence"
    except Exception as exc:  # Timeout/provider failures deterministically fall back.
        failure_code = f"supervisor_{exc.__class__.__name__.lower()}"

    metadata = dict(getattr(provider, "last_call_metadata", {}) or {})
    if decision is not None and failure_code is None:
        validated_plan, validation_error = _validated_plan(
            decision,
            fallback_plan=fallback_plan,
            selected_document_count=selected_count,
            document_token_estimate=document_token_estimate,
            has_previous_answer=has_previous,
            has_quoted_text=has_quote,
        )
        if validation_error is None and validated_plan is not None:
            return SupervisorOutcome(
                supervisor_intent=decision.intent,
                supervisor_confidence=decision.confidence,
                validated_intent=str(validated_plan["target_capability"]),
                target_capability=str(validated_plan["target_capability"]),
                fallback_used=False,
                failure_code=None,
                plan=validated_plan,
                provider_request_count=int(metadata.get("provider_request_count") or 1),
                input_tokens=int(metadata.get("input_tokens") or 0),
                output_tokens=int(metadata.get("output_tokens") or 0),
                cost_usd=float(metadata.get("cost_usd") or 0),
                latency_ms=int(metadata.get("latency_ms") or 0),
            )
        failure_code = validation_error

    fallback = fallback_plan.to_dict()
    capability = _fallback_capability(fallback_plan, selected_count)
    fallback["target_capability"] = capability
    fallback["supervisor_requires_retrieval"] = capability not in NO_RETRIEVAL_INTENTS
    return SupervisorOutcome(
        supervisor_intent=decision.intent if decision else None,
        supervisor_confidence=decision.confidence if decision else 0.0,
        validated_intent=capability,
        target_capability=capability,
        fallback_used=True,
        failure_code=failure_code or "supervisor_unavailable",
        plan=fallback,
        provider_request_count=int(metadata.get("provider_request_count") or 1),
        input_tokens=int(metadata.get("input_tokens") or 0),
        output_tokens=int(metadata.get("output_tokens") or 0),
        cost_usd=float(metadata.get("cost_usd") or 0),
        latency_ms=int(metadata.get("latency_ms") or 0),
    )
