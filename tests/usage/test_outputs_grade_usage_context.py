import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend.app.api.routes import outputs
from backend.app.services.usage_tracking import current_usage_context


class OutputsGradeUsageContextTest(unittest.TestCase):
    def test_grading_backfills_usage_context_with_message_and_output(self):
        output_id = "output-1"
        conversation_id = "conversation-1"
        message_id = "assistant-message-1"
        user = {"id": 7}
        output_row = {
            "id": output_id,
            "user_id": user["id"],
            "conversation_id": conversation_id,
            "type": "exam_generation",
            "title": "Exam",
            "content_json": json.dumps(
                {
                    "kind": "exam",
                    "questions": [
                        {
                            "id": "q1",
                            "type": "descriptive",
                            "prompt": "Explain.",
                            "points": 5,
                        }
                    ],
                }
            ),
            "content_markdown": "",
            "source_asset_ids_json": "[]",
            "template_id": "exam_generation",
            "template_params_json": "{}",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        source_message = {
            "id": message_id,
            "conversation_id": conversation_id,
            "generated_output_id": output_id,
            "role": "assistant",
        }
        captured = {}

        def fake_grade_exam(*args, **kwargs):
            captured["context_during_grade"] = current_usage_context()
            return {"total_score": 0, "total_max": 5, "questions": []}

        with (
            patch.object(outputs.db, "get_generated_output", return_value=output_row),
            patch.object(outputs.db, "get_message_for_generated_output", return_value=source_message) as get_message,
            patch.object(outputs.db, "update_usage_events_context", return_value=1) as update_context,
            patch.object(outputs, "grade_exam", side_effect=fake_grade_exam),
        ):
            response = outputs.outputs_grade(
                output_id,
                data={"answers": {"q1": "answer"}, "chat_provider": "litellm", "chat_model": "chat_free"},
                user=user,
            )

        self.assertIn("grade", response)
        get_message.assert_called_once_with(output_id)
        context = captured["context_during_grade"]
        self.assertEqual(context["user_id"], user["id"])
        self.assertEqual(context["conversation_id"], conversation_id)
        self.assertEqual(context["message_id"], message_id)
        self.assertEqual(context["output_id"], output_id)
        self.assertEqual(context["feature"], "exam_grading_descriptive")
        update_context.assert_called_once()
        _, kwargs = update_context.call_args
        self.assertEqual(kwargs["user_id"], user["id"])
        self.assertEqual(kwargs["conversation_id"], conversation_id)
        self.assertEqual(kwargs["message_id"], message_id)
        self.assertEqual(kwargs["output_id"], output_id)


if __name__ == "__main__":
    unittest.main()
