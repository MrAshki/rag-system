import unittest
from unittest.mock import patch

import rag
from backend.app.agents.rag_graph import _conversational_followup_node


class ConversationFollowupTests(unittest.TestCase):
    def test_conversation_explanation_uses_bounded_single_paragraph_json(self):
        class Provider:
            def chat(self, **kwargs):
                self.kwargs = kwargs
                return '{"explanation":"یعنی پژوهش، بازیافت پساب دیالیز را بهترین گزینه دانسته است."}'

        provider = Provider()
        result = rag.generate_conversation_response("یعنی چی؟", "پاسخ قبلی", chat_provider=provider)
        self.assertEqual(
            result["answer"],
            "یعنی پژوهش، بازیافت پساب دیالیز را بهترین گزینه دانسته است.",
        )
        self.assertEqual(provider.kwargs["options"]["max_tokens"], 360)
        self.assertEqual(provider.kwargs["response_format"], "json")

    def test_conversation_parser_accepts_fenced_preamble_plain_and_complete_truncated_shapes(self):
        cases = [
            ('```json\n{"explanation":"توضیح حصاردار"}\n```', "توضیح حصاردار", "json"),
            ('نتیجه:\n{"explanation":"توضیح پس از مقدمه"}', "توضیح پس از مقدمه", "json"),
            ("توضیح مستقیم و بدون JSON", "توضیح مستقیم و بدون JSON", "plain_text"),
            ('{"explanation":"توضیح کامل است.', "توضیح کامل است.", "repaired_json"),
        ]
        for raw, expected, parse_mode in cases:
            with self.subTest(raw=raw):
                class Provider:
                    last_call_metadata = {}

                    def chat(self, **_kwargs):
                        return raw

                result = rag.generate_conversation_response(
                    "یعنی چی؟",
                    "پاسخ قبلی",
                    chat_provider=Provider(),
                )
                self.assertEqual(result["answer"], expected)
                self.assertEqual(result["generation_telemetry"]["response_parse_mode"], parse_mode)

    def test_incomplete_truncated_conversation_json_uses_local_fallback(self):
        class Provider:
            def chat(self, **_kwargs):
                return '{"explanation":"این پیام به این معنی است که سیستم نتوانسته یک خلاصه'

        result = rag.generate_conversation_response(
            "یعنی چی؟",
            "نتیجه اصلی این است. [S1]",
            chat_provider=Provider(),
        )
        self.assertEqual(result["answer"], "به زبان ساده: نتیجه اصلی این است.")
        self.assertNotIn("نتوانسته یک خلاصه", result["answer"])

    def test_empty_or_serialization_only_conversation_output_uses_local_fallback(self):
        for raw in ("", "{}"):
            with self.subTest(raw=raw):
                class Provider:
                    def chat(self, **_kwargs):
                        return raw

                result = rag.generate_conversation_response(
                    "یعنی چی؟",
                    "نتیجه اصلی این است. [S1]",
                    chat_provider=Provider(),
                )
                self.assertEqual(result["answer"], "به زبان ساده: نتیجه اصلی این است.")
                self.assertNotIn("{", result["answer"])

    @patch("backend.app.agents.rag_graph.get_chat_provider")
    def test_ambiguous_antecedent_asks_clarification_without_provider_or_retrieval(self, provider):
        result = _conversational_followup_node({
            "question": "آن را زودتر تحویل بدهند؟",
            "generation_question": "آن را زودتر تحویل بدهند؟",
            "conversation_history": [{
                "role": "assistant",
                "content": "پروژه آلفا ۱۵ مهر و پروژه بتا ۳۰ مهر تحویل می‌شوند.",
            }],
        })
        provider.assert_not_called()
        self.assertEqual(result["answer"], "منظورتان پروژه آلفاست یا بتا؟")
        self.assertTrue(result["metadata"]["antecedent_ambiguous"])
        self.assertEqual(result["metadata"]["retrieval_calls"], 0)
        self.assertEqual(result["metadata"]["embedding_calls"], 0)
        self.assertEqual(result["metadata"]["rerank_calls"], 0)

    @patch("backend.app.agents.rag_graph.get_chat_provider")
    def test_ambiguous_antecedent_uses_previous_user_when_assistant_refused(self, provider):
        result = _conversational_followup_node({
            "question": "آن را زودتر تحویل بدهند؟",
            "generation_question": "آن را زودتر تحویل بدهند؟",
            "conversation_history": [
                {
                    "role": "user",
                    "content": "موعد پروژه آلفا و پروژه بتا را مقایسه کن.",
                },
                {
                    "role": "assistant",
                    "content": "در سند انتخاب‌شده اطلاعات کافی برای پاسخ وجود ندارد.",
                },
            ],
        })
        provider.assert_not_called()
        self.assertEqual(result["answer"], "منظورتان پروژه آلفاست یا بتا؟")
        self.assertTrue(result["metadata"]["antecedent_ambiguous"])
        self.assertEqual(result["metadata"]["retrieval_calls"], 0)
        self.assertEqual(result["metadata"]["embedding_calls"], 0)
        self.assertEqual(result["metadata"]["rewrite_calls"], 0)
        self.assertEqual(result["metadata"]["rerank_calls"], 0)

    @patch("backend.app.agents.rag_graph.get_chat_provider", return_value=object())
    @patch("backend.app.agents.rag_graph.rag.generate_conversation_response")
    @patch("backend.app.agents.rag_graph._all_selected_chunks")
    @patch("backend.app.agents.rag_graph._focused_rag_node")
    def test_uses_previous_answer_without_document_retrieval(
        self, focused, all_chunks, generate, _provider,
    ):
        generate.return_value = {
            "answer": "توضیح سادهٔ پاسخ قبلی",
            "sources": [],
        }
        result = _conversational_followup_node({
            "question": "یعنی چی؟",
            "generation_question": "یعنی چی؟",
            "scope": "selected",
            "conversation_history": [{
                "role": "assistant",
                "content": "پاسخ پیشین",
                "sources": ["paper.pdf - صفحه 7 تا 8"],
            }],
        })
        focused.assert_not_called()
        all_chunks.assert_not_called()
        self.assertEqual(generate.call_args.args[:2], ("یعنی چی؟", "پاسخ پیشین"))
        self.assertEqual(result["metadata"]["retrieval_calls"], 0)
        self.assertEqual(result["metadata"]["embedding_calls"], 0)
        self.assertEqual(result["metadata"]["rerank_calls"], 0)
        self.assertEqual(result["metadata"]["strategy"], "previous_answer_only")

    @patch("backend.app.agents.rag_graph._focused_rag_node")
    def test_evidence_seeking_followup_uses_history_aware_retrieval(self, focused):
        focused.return_value = {
            "answer": "۳٫۶ درصد [S1]",
            "sources": ["paper.pdf - صفحه ۱"],
            "metadata": {
                "retrieval_calls": 1,
                "embedding_calls": 1,
                "rewrite_calls": 0,
                "reranker_calls": 1,
            },
        }
        result = _conversational_followup_node({
            "question": "از میان آن‌ها چند درصد به بیمارستان رفتند؟",
            "generation_question": "از میان آن‌ها چند درصد به بیمارستان رفتند؟",
            "scope": "selected",
            "document_id": "asset-1",
            "request_plan": {
                "route_implementation": "history_aware_retrieval",
            },
            "conversation_history": [
                {
                    "role": "user",
                    "content": "نتیجه غربالگری مرحله دوم چه بود؟",
                },
                {
                    "role": "assistant",
                    "content": "بیش از ۴۲ میلیون نفر غربال شدند.",
                },
            ],
        })
        focused_state = focused.call_args.args[0]
        self.assertIn("نتیجه غربالگری", focused_state["question"])
        self.assertIn("از میان آن‌ها", focused_state["question"])
        self.assertEqual(result["answer"], "۳٫۶ درصد [S1]")
        self.assertEqual(result["metadata"]["strategy"], "history_aware_retrieval")
        self.assertTrue(result["metadata"]["history_resolved"])
        self.assertEqual(result["metadata"]["retrieval_calls"], 1)


if __name__ == "__main__":
    unittest.main()
