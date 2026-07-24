import json
from unittest.mock import Mock, patch

from backend.app.agents import rag_graph
from backend.app.agents.intent_supervisor import supervise_request


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.last_call_metadata = {
            "provider_request_count": 1,
            "input_tokens": 80,
            "output_tokens": 30,
            "cost_usd": 0.0,
            "latency_ms": 4,
        }
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        return self.response


def decision(intent, scope, *, uses_history=False, requires_retrieval=True, confidence=0.96):
    return json.dumps({
        "intent": intent,
        "scope": scope,
        "uses_history": uses_history,
        "requires_retrieval": requires_retrieval,
        "target_capability": intent,
        "confidence": confidence,
    })


def run(response, *, question, asset_count, history=None):
    return supervise_request(
        question=question,
        conversation_history=history or [],
        selected_assets=[
            {"id": f"a-{index}", "title": f"Document {index}"}
            for index in range(1, asset_count + 1)
        ],
        document_token_estimate=1200,
        provider=FakeProvider(response),
    )


def test_single_document_summary_is_not_previous_answer_explanation():
    outcome = run(
        decision("single_document_summary", "single_document"),
        question="این سند رو خلاصه کن",
        asset_count=1,
        history=[{"role": "assistant", "content": "پاسخ قبلی"}],
    )
    assert outcome.validated_intent == "single_document_summary"
    assert outcome.plan["route"] == "comprehensive_summary"
    assert outcome.plan["route_implementation"] == "direct_whole_document"
    assert outcome.fallback_used is False


def test_multi_document_summary_dispatches_all_documents():
    outcome = run(
        decision("multi_document_summary", "multiple_documents"),
        question="این دو سند رو برام خلاصه کن",
        asset_count=2,
    )
    assert outcome.validated_intent == "multi_document_summary"
    assert outcome.target_capability == "multi_document_summary"
    assert outcome.plan["route"] == "multi_document_summary"


def test_multi_document_comparison_dispatches_comparison_handler():
    outcome = run(
        decision("multi_document_comparison", "multiple_documents"),
        question="تفاوت این دو منبع چیست؟",
        asset_count=2,
    )
    assert outcome.validated_intent == "multi_document_comparison"
    assert outcome.target_capability == "multi_document_comparison"


def test_conversation_explanation_uses_history_without_retrieval():
    outcome = run(
        decision(
            "conversation_explanation",
            "single_document",
            uses_history=True,
            requires_retrieval=False,
        ),
        question="این جواب را ساده‌تر بگو",
        asset_count=1,
        history=[{"role": "assistant", "content": "پاسخ قبلی"}],
    )
    assert outcome.validated_intent == "conversation_explanation"
    assert outcome.plan["route_implementation"] == "conversation_only"
    assert outcome.plan["supervisor_requires_retrieval"] is False


def test_comparison_with_one_document_requires_clarification():
    outcome = run(
        decision("multi_document_comparison", "single_document"),
        question="این دو منبع چه تفاوتی دارند؟",
        asset_count=1,
    )
    assert outcome.validated_intent == "clarification_required"
    assert outcome.target_capability == "clarification_required"
    assert outcome.plan["route"] == "clarification_required"
    assert outcome.plan["supervisor_requires_retrieval"] is False


def test_malformed_json_falls_back_to_current_router():
    outcome = run(
        "routing result: {not-json",
        question="این سند رو خلاصه کن",
        asset_count=1,
    )
    assert outcome.fallback_used is True
    assert outcome.failure_code == "invalid_supervisor_json"
    assert outcome.validated_intent == "single_document_summary"
    assert outcome.plan["route"] == "comprehensive_summary"


def test_authoritative_dispatch_uses_validated_multi_document_capability():
    provider = FakeProvider(decision("multi_document_summary", "multiple_documents"))
    assets = [
        {
            "id": "a-1",
            "original_filename": "one.pdf",
            "document_profile_json": {"char_count": 1000, "title": "One"},
        },
        {
            "id": "a-2",
            "original_filename": "two.pdf",
            "document_profile_json": {"char_count": 1000, "title": "Two"},
        },
    ]
    handler = Mock(return_value={
        "answer": "هر دو سند پوشش داده شدند.",
        "sources": ["one.pdf - صفحه 1", "two.pdf - صفحه 1"],
        "metadata": {
            "retrieval_calls": 0,
            "embedding_calls": 0,
            "rerank_calls": 0,
            "generation": {},
        },
    })
    state = rag_graph._initial_state(
        "این دو سند رو برام خلاصه کن",
        scope="selected",
        asset_ids=["a-1", "a-2"],
        semantic_supervisor_enabled=True,
        langgraph_enabled=True,
    )
    with patch("backend.app.agents.rag_graph._selected_assets", return_value=assets), patch(
        "backend.app.agents.rag_graph.get_chat_provider", return_value=provider,
    ), patch.dict(rag_graph._HANDLERS, {"multi_document_summary": handler}):
        result = rag_graph._execute_authoritative(state)

    handler.assert_called_once()
    telemetry = result["metadata"]["telemetry"]
    assert telemetry["selected_asset_count"] == 2
    assert telemetry["supervisor_intent"] == "multi_document_summary"
    assert telemetry["validated_intent"] == "multi_document_summary"
    assert telemetry["target_capability"] == "multi_document_summary"


def test_multi_document_handlers_supply_evidence_from_every_asset():
    assets = [
        {
            "id": "a-1", "original_filename": "one.pdf",
            "document_profile_json": {"title": "One"},
        },
        {
            "id": "a-2", "original_filename": "two.pdf",
            "document_profile_json": {"title": "Two"},
        },
    ]
    groups = [
        {
            "key": ("a-1", "g-1"), "coverage_key": "one :: body",
            "title": "Body", "role": "section", "source": "one.pdf",
            "pages": [1], "chunks": [{"text": "first evidence", "page": 1}],
        },
        {
            "key": ("a-2", "g-2"), "coverage_key": "two :: body",
            "title": "Body", "role": "section", "source": "two.pdf",
            "pages": [2], "chunks": [{"text": "second evidence", "page": 2}],
        },
    ]
    generated = {
        "answer": "سند اول و سند دوم پوشش داده شدند. [S1] [S2]",
        "sources": ["one.pdf - صفحه 1", "two.pdf - صفحه 2"],
        "proposed_evidence_ids": ["E1", "E2"],
        "used_evidence_ids": ["E1", "E2"],
        "generation_telemetry": {},
        "citation_validation": {"status": "validated"},
    }
    with patch("backend.app.agents.rag_graph._substantive_groups", return_value=(assets, groups)), patch(
        "backend.app.agents.rag_graph.get_chat_provider", return_value=object(),
    ), patch("backend.app.agents.rag_graph.rag.generate_response", return_value=generated) as generate:
        summary = rag_graph._run_multi_document_operation(
            {"question": "هر دو را خلاصه کن", "scope": "selected"},
            comparison=False,
        )
        comparison = rag_graph._run_multi_document_operation(
            {"question": "هر دو را مقایسه کن", "scope": "selected"},
            comparison=True,
        )

    assert summary["metadata"]["document_coverage_passed"] is True
    assert comparison["metadata"]["document_coverage_passed"] is True
    for call in generate.call_args_list:
        assert {item["document_id"] for item in call.args[1]} == {"a-1", "a-2"}


def test_shared_parser_accepts_fenced_prefixed_and_missing_final_brace():
    raw = "classification:\n```json\n" + decision(
        "single_document_summary", "single_document"
    )[:-1] + "\n```"
    outcome = run(
        raw,
        question="این سند را خلاصه کن",
        asset_count=1,
    )
    assert outcome.fallback_used is False
    assert outcome.validated_intent == "single_document_summary"
