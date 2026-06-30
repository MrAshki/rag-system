import unittest
from unittest.mock import patch

import rag
from backend.app.services.usage_tracking import record_compute_usage_event, usage_context


class ComputeUsageTrackingTest(unittest.TestCase):
    def test_record_compute_usage_event_uses_compute_table_and_context(self):
        with (
            usage_context(
                request_id="request-1",
                user_id=7,
                conversation_id="conversation-1",
                message_id="message-1",
                output_id="output-1",
                feature="exam_generation",
            ),
            patch("db.create_compute_usage_event", return_value={"id": "compute-1"}) as create_compute,
            patch("db.create_usage_event") as create_llm,
        ):
            record_compute_usage_event(
                operation_type="embedding",
                provider="local_gpu",
                model="./models/bge-m3",
                device="cuda",
                latency_ms=42,
                input_count=3,
                input_chars=1200,
                batch_size=3,
            )

        create_llm.assert_not_called()
        create_compute.assert_called_once()
        kwargs = create_compute.call_args.kwargs
        self.assertEqual(kwargs["request_id"], "request-1")
        self.assertEqual(kwargs["user_id"], 7)
        self.assertEqual(kwargs["conversation_id"], "conversation-1")
        self.assertEqual(kwargs["message_id"], "message-1")
        self.assertEqual(kwargs["output_id"], "output-1")
        self.assertEqual(kwargs["feature"], "exam_generation")
        self.assertEqual(kwargs["operation_type"], "embedding")
        self.assertEqual(kwargs["provider"], "local_gpu")
        self.assertEqual(kwargs["device"], "cuda")
        self.assertEqual(kwargs["input_count"], 3)
        self.assertEqual(kwargs["input_chars"], 1200)

    def test_reranking_records_compute_usage_not_llm_usage(self):
        class FakeReranker:
            def predict(self, pairs):
                return [0.9, 0.1]

        chunks = [{"text": "first chunk"}, {"text": "second chunk"}]

        with (
            usage_context(
                request_id="request-2",
                user_id=7,
                conversation_id="conversation-2",
                message_id="message-2",
                feature="exam_generation",
            ),
            patch.object(rag, "ENABLE_RERANKER", True),
            patch.object(rag, "_get_reranker", return_value=FakeReranker()),
            patch.object(rag, "record_compute_usage_event") as record_compute,
            patch.object(rag, "record_usage_event", create=True) as record_llm,
        ):
            result = rag.rerank("query", chunks, top_k=1)

        self.assertEqual(result, [chunks[0]])
        record_llm.assert_not_called()
        record_compute.assert_called_once()
        kwargs = record_compute.call_args.kwargs
        self.assertEqual(kwargs["operation_type"], "reranking")
        self.assertEqual(kwargs["feature"] if "feature" in kwargs else "exam_generation", "exam_generation")
        self.assertEqual(kwargs["input_count"], 2)
        self.assertEqual(kwargs["chunk_count"], 2)
        self.assertEqual(kwargs["pair_count"], 2)
        self.assertEqual(kwargs["query_count"], 1)
        self.assertGreater(kwargs["input_chars"], 0)


if __name__ == "__main__":
    unittest.main()
