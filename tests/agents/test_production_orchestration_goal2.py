import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import rag
from backend.app.agents import rag_graph


class Goal2ProductionOrchestrationTests(unittest.TestCase):
    def test_sync_production_entrypoint_always_uses_authoritative_orchestrator(self):
        expected = {"answer": "ok", "sources": [], "metadata": {}}
        for enabled in (False, True):
            with self.subTest(enabled=enabled), patch.object(rag, "ENABLE_LANGGRAPH_RAG", enabled), patch(
                "backend.app.agents.rag_graph.answer_request",
                return_value=expected,
            ) as orchestrator:
                result = rag.answer_request(
                    "question",
                    conversation_id="conversation-1",
                    request_id="request-1",
                )
            self.assertEqual(result, expected)
            self.assertEqual(orchestrator.call_args.kwargs["langgraph_enabled"], enabled)
            self.assertEqual(orchestrator.call_args.kwargs["conversation_id"], "conversation-1")
            self.assertEqual(orchestrator.call_args.kwargs["request_id"], "request-1")

    def test_langgraph_wraps_eligible_route_without_changing_router(self):
        state = rag_graph._initial_state(
            "پاسخ دقیق این سؤال چیست؟",
            scope="selected",
            document_id="asset-1",
            langgraph_enabled=True,
        )
        fake_graph = Mock()
        fake_graph.invoke.return_value = {
            "answer": "grounded",
            "sources": [],
            "metadata": {
                "retrieval_calls": 1,
                "embedding_calls": 1,
                "rerank_calls": 1,
            },
        }
        asset = {"id": "asset-1", "document_profile_json": {"char_count": 1000}}
        with patch("backend.app.agents.rag_graph.graph", return_value=fake_graph), patch(
            "backend.app.agents.rag_graph._selected_assets",
            return_value=[asset],
        ):
            result = rag_graph._execute_authoritative(state)

        fake_graph.invoke.assert_called_once()
        telemetry = result["metadata"]["telemetry"]
        self.assertEqual(telemetry["selected_route"], "local_hybrid_retrieval")
        self.assertEqual(telemetry["route_implementation"], "langgraph_state_graph")
        self.assertEqual(telemetry["graph_node_path"], ["plan_request", "focused_rag"])

    def test_deterministic_summary_bypasses_graph_but_uses_same_plan(self):
        state = rag_graph._initial_state(
            "یک خلاصه جامع از کل سند بده",
            scope="selected",
            document_id="asset-1",
            langgraph_enabled=True,
        )
        asset = {"id": "asset-1", "document_profile_json": {"char_count": 1000}}
        direct = {
            "answer": "summary",
            "sources": [],
            "metadata": {
                "strategy": "direct_whole_document",
                "retrieval_calls": 0,
                "embedding_calls": 0,
                "rerank_calls": 0,
                "coverage": {"coverage_passed": True},
            },
        }
        with patch("backend.app.agents.rag_graph.graph") as graph_mock, patch(
            "backend.app.agents.rag_graph._selected_assets",
            return_value=[asset],
        ), patch(
            "backend.app.agents.rag_graph._comprehensive_summary_node",
            return_value=direct,
        ), patch.dict(
            rag_graph._HANDLERS,
            {"comprehensive_summary": Mock(return_value=direct)},
        ):
            result = rag_graph._execute_authoritative(state)

        graph_mock.assert_not_called()
        self.assertEqual(result["metadata"]["selected_route"], "direct_whole_document")
        self.assertEqual(result["metadata"]["telemetry"]["retrieval_calls"], 0)

    def test_stream_exposes_execution_stages_not_internal_plan(self):
        history = [{"role": "assistant", "content": "پاسخ قبلی"}]
        final = {
            "answer": "توضیح",
            "sources": [],
            "metadata": {"telemetry": {}},
        }
        with patch("backend.app.agents.rag_graph._execute_authoritative", return_value=final):
            events = list(rag_graph.answer_request_stream(
                "یعنی چی؟",
                conversation_history=history,
                langgraph_enabled=True,
            ))
        stages = [event.get("stage") for event in events if event.get("type") == "trace"]
        self.assertEqual(stages, ["conversation_history_review", "conversation_explanation"])
        self.assertNotIn("agent_plan", stages)

        frontend = (
            Path(__file__).resolve().parents[2]
            / "apps"
            / "web"
            / "src"
            / "features"
            / "chat"
            / "utils"
            / "stream.ts"
        ).read_text(encoding="utf-8")
        self.assertNotIn("برنامه پاسخ انتخاب شد", frontend)
        self.assertIn("در حال بررسی پیام قبلی", frontend)

    def test_small_selected_document_is_inspected_page_by_page_before_no_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            normalized = Path(tmp) / "normalized.md"
            normalized.write_text(
                "<!-- page:1 -->\n\nپروژه آلفا ۱۵ مهر.\n\n"
                "<!-- page:2 -->\n\nپروژه بتا ۳۰ مهر.",
                encoding="utf-8",
            )
            asset = {
                "id": "asset-1",
                "original_filename": "fixture.pdf",
                "normalized_md_path": str(normalized),
            }
            generated = {
                "answer": "آلفا ۱۵ مهر و بتا ۳۰ مهر. [S1] [S2]",
                "sources": ["fixture.pdf - صفحه 1", "fixture.pdf - صفحه 2"],
                "generation_telemetry": {},
                "citation_validation": {"status": "validated"},
            }
            with patch(
                "backend.app.agents.rag_graph._selected_assets",
                return_value=[asset],
            ), patch(
                "backend.app.agents.rag_graph.get_chat_provider",
                return_value=object(),
            ), patch(
                "backend.app.agents.rag_graph.rag.generate_response",
                return_value=generated,
            ) as generate:
                result = rag_graph._direct_small_document_result({
                    "question": "آلفا و بتا را مقایسه کن",
                    "generation_question": "آلفا و بتا را مقایسه کن",
                    "scope": "selected",
                    "request_plan": {
                        "selected_document_count": 1,
                        "document_token_estimate": 30,
                    },
                })
        self.assertEqual([item["page"] for item in generate.call_args.args[1]], [1, 2])
        self.assertEqual(result["metadata"]["retrieval_calls"], 1)
        self.assertEqual(result["metadata"]["embedding_calls"], 0)
        self.assertEqual(result["metadata"]["rerank_calls"], 0)


if __name__ == "__main__":
    unittest.main()
