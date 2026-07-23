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


if __name__ == "__main__":
    unittest.main()
