import unittest
from unittest.mock import patch

from backend.app.services import tool_runner
from backend.app.services.usage_tracking import current_usage_context, usage_context


class ToolRetrievalUsageContextTest(unittest.TestCase):
    def test_tool_retrieve_preserves_exam_generation_context_for_reranking(self):
        captured = {}

        def fake_retrieve(*args, **kwargs):
            captured["context"] = current_usage_context()
            return []

        tool = {"id": "exam_generation", "description": "Generate an exam"}

        with (
            usage_context(
                request_id="request-1",
                user_id=7,
                conversation_id="conversation-1",
                message_id="assistant-message-1",
                feature="exam_generation",
            ),
            patch.object(tool_runner.rag, "retrieve", side_effect=fake_retrieve),
        ):
            tool_runner._retrieve(tool, {}, "make an exam", asset_ids=["asset-1"], user_id=7)

        context = captured["context"]
        self.assertEqual(context["request_id"], "request-1")
        self.assertEqual(context["user_id"], 7)
        self.assertEqual(context["conversation_id"], "conversation-1")
        self.assertEqual(context["message_id"], "assistant-message-1")
        self.assertEqual(context["feature"], "exam_generation")
        self.assertEqual(context["metadata"]["tool_id"], "exam_generation")
        self.assertEqual(context["metadata"]["retrieval_for"], "exam_generation")


if __name__ == "__main__":
    unittest.main()
