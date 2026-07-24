import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import rag
from backend.app.agents import rag_graph


class Goal2ProductionOrchestrationTests(unittest.TestCase):
    def test_variance_tuple_prefers_clean_percent_abstract(self):
        result = rag_graph._deterministic_variance_percent_answer(
            "مدل چه درصدی از واریانس عزت‌نفس، پرخاشگری و جرئت‌ورزی را توضیح داد؟",
            [
                {
                    "source": "paper.pdf",
                    "page": 4,
                    "parent_role": "abstract",
                    "text": "مدل 45 درصد، ۷ درصد و ۷ درصد از واریانس را تبیین کرد.",
                },
                {
                    "source": "paper.pdf",
                    "page": 1,
                    "parent_role": "abstract",
                    "text": (
                        "The research model explained 15% of the variance in self-esteem, "
                        "17% in aggressive assertiveness, and 27% in adaptive assertiveness."
                    ),
                },
            ],
        )
        self.assertEqual(
            result["answer"],
            "مدل به‌ترتیب ۱۵ درصد، ۱۷ درصد و ۲۷ درصد از واریانس متغیرهای نام‌برده را توضیح داد. [S1]",
        )
        self.assertEqual(result["sources"], ["paper.pdf - صفحه 1"])

    def test_variance_tuple_does_not_combine_percentages_across_blocks(self):
        result = rag_graph._deterministic_variance_percent_answer(
            "What percentage of variance was explained for the three outcomes?",
            [
                {"source": "paper.pdf", "page": 1, "text": "The model explained 15% of variance."},
                {"source": "paper.pdf", "page": 2, "text": "The model explained 17% and 27% elsewhere."},
            ],
        )
        self.assertIsNone(result)

    def test_method_numeric_tuple_uses_one_complete_valid_evidence_block(self):
        result = rag_graph._deterministic_method_numeric_answer(
            "در بخش کیفی چند خبره مصاحبه شدند، چند عامل شناسایی شد و ضریب کاپا چقدر بود؟",
            [
                {
                    "source": "paper.pdf",
                    "page": 4,
                    "text": "با 57 کارآفرین و متخصص، 43 عامل شناسایی و ضریب کاپای 82/4 گزارش شد.",
                },
                {
                    "source": "paper.pdf",
                    "page": 1,
                    "text": (
                        "Semi-structured interviews were conducted with 37 entrepreneurs and experts, "
                        "yielding 15 key factors (Cohen's kappa = 0.82)."
                    ),
                },
            ],
        )
        self.assertEqual(
            result["answer"],
            "۳۷ نفر مصاحبه شدند، ۱۵ عامل شناسایی شد و ضریب کاپا ۰٫۸۲ بود. [S1]",
        )
        self.assertEqual(result["sources"], ["paper.pdf - صفحه 1"])
        self.assertTrue(result["citation_validation"]["numeric_relations_checked"])

    def test_method_numeric_tuple_does_not_mix_incomplete_evidence_blocks(self):
        result = rag_graph._deterministic_method_numeric_answer(
            "How many experts, factors, and what kappa were reported?",
            [
                {"source": "paper.pdf", "page": 1, "text": "Interviews with 37 experts."},
                {"source": "paper.pdf", "page": 2, "text": "15 key factors and kappa = 0.82."},
            ],
        )
        self.assertIsNone(result)

    def test_criterion_weight_uses_readable_abstract_relation(self):
        result = rag_graph._deterministic_criterion_weight_answer(
            "اثرگذارترین معیار تصمیم‌گیری چه بود و چه وزنی داشت؟",
            [
                {
                    "source": "paper.pdf",
                    "page": 4,
                    "parent_role": "abstract",
                    "text": "معیار اق با وزن 35/0 به عنوان اثرگذارترین معیار شناسایی شد.",
                },
                {
                    "source": "paper.pdf",
                    "page": 1,
                    "parent_role": "abstract",
                    "text": (
                        "The economic criterion, with a weight of 0.35, was identified "
                        "as the most influential factor in the decision-making process."
                    ),
                },
            ],
        )
        self.assertEqual(result["answer"], "معیار اقتصادی با وزن ۰٫۳۵ اثرگذارترین معیار بود. [S1]")
        self.assertEqual(result["sources"], ["paper.pdf - صفحه 1"])

    def test_criterion_weight_requires_superlative_relation_in_same_block(self):
        result = rag_graph._deterministic_criterion_weight_answer(
            "Which criterion was most important and what was its weight?",
            [
                {"source": "paper.pdf", "page": 1, "text": "The economic criterion was discussed."},
                {"source": "paper.pdf", "page": 2, "text": "A weight of 0.35 was reported."},
            ],
        )
        self.assertIsNone(result)

    def test_small_document_conflict_reports_both_values_and_precedence(self):
        result = rag_graph._deterministic_small_document_answer(
            "مدت نگهداری پرونده چند سال است؟",
            [
                {"source": "policy.pdf", "page": 1, "text": "پرونده باید پنج سال نگهداری شود."},
                {"source": "policy.pdf", "page": 2, "text": "الحاقیه نگهداری را هفت سال تعیین می‌کند."},
                {
                    "source": "policy.pdf",
                    "page": 3,
                    "text": "سند فاقد بند تعیین‌کننده تقدم است و سیستم باید تعارض را گزارش کند.",
                },
            ],
        )
        self.assertIn("۵ سال", result["answer"])
        self.assertIn("۷ سال", result["answer"])
        self.assertIn("تقدم", result["answer"])
        self.assertEqual(
            result["sources"],
            ["policy.pdf - صفحه 1", "policy.pdf - صفحه 2", "policy.pdf - صفحه 3"],
        )

    def test_small_document_explicit_scope_exclusion_is_topic_specific(self):
        result = rag_graph._deterministic_small_document_answer(
            "نرخ اضافه‌کاری چقدر است؟",
            [{
                "source": "policy.pdf",
                "page": 3,
                "text": "این دستورالعمل درباره اضافهکاری، پاداش و بیمه حکمی ندارد.",
            }],
        )
        self.assertIn("اضافه", result["answer"])
        self.assertIn("خارج از دامنه", result["answer"])
        self.assertEqual(result["sources"], ["policy.pdf - صفحه 3"])

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

    def test_multi_value_method_question_adds_abstract_without_another_search(self):
        retrieved = [{
            "document_id": "asset-1",
            "chunk_index": 7,
            "page": 7,
            "parent_role": "discussion",
            "text": "بحث پژوهش",
        }]
        document = [
            {
                "document_id": "asset-1",
                "chunk_index": 1,
                "page": 1,
                "parent_role": "abstract",
                "text": "37 experts identified 15 factors; Cohen's kappa was 0.82.",
            },
            *retrieved,
        ]
        result = rag_graph._augment_method_evidence(
            "در بخش کیفی چند خبره مصاحبه شدند، چند عامل شناسایی شد و ضریب کاپا چقدر بود؟",
            retrieved,
            document,
        )
        self.assertEqual([item["page"] for item in result], [7, 1])

    def test_ordinary_fact_question_does_not_add_abstract(self):
        retrieved = [{"document_id": "a", "chunk_index": 2, "page": 2, "text": "value"}]
        abstract = {
            "document_id": "a",
            "chunk_index": 1,
            "page": 1,
            "parent_role": "abstract",
            "text": "method sample",
        }
        self.assertEqual(
            rag_graph._augment_method_evidence("مهلت قرارداد چیست؟", retrieved, [abstract, *retrieved]),
            retrieved,
        )


if __name__ == "__main__":
    unittest.main()
