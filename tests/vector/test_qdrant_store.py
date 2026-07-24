import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from backend.app.vector.qdrant_store import QdrantStore


class QdrantReadTests(unittest.TestCase):
    def store(self):
        store = QdrantStore.__new__(QdrantStore)
        store.collection_name = "isolated_read_test"
        store.client = Mock()
        store._filter = Mock(return_value=None)
        return store

    def test_search_maps_query_points_without_writing(self):
        store = self.store()
        store.client.query_points.return_value = SimpleNamespace(points=[
            SimpleNamespace(
                payload={
                    "text": "evidence",
                    "source": "sample.pdf",
                    "chunk_id": "chunk-7",
                    "chunk_index": 7,
                    "document_id": "doc-1",
                    "metadata": {"page": 3},
                },
                score=0.91,
            )
        ])

        results = store.search([0.1, 0.2], {"user_id": 5}, top_k=1)

        self.assertEqual(results[0].text, "evidence")
        self.assertEqual(results[0].metadata["page"], 3)
        self.assertEqual(results[0].metadata["chunk_id"], "chunk-7")
        store.client.query_points.assert_called_once()
        store.client.upsert.assert_not_called()

    def test_search_uses_read_only_rest_fallback(self):
        store = self.store()
        store.client.query_points.side_effect = RuntimeError("client unavailable")
        store._search_rest = Mock(return_value=[{
            "payload": {
                "text": "fallback evidence",
                "source": "sample.pdf",
                "chunk_index": 2,
                "document_id": "doc-2",
                "metadata": {},
            },
            "score": 0.8,
        }])

        results = store.search([0.3], top_k=2)

        self.assertEqual(results[0].document_id, "doc-2")
        store._search_rest.assert_called_once_with([0.3], None, 2)

    def test_list_chunks_maps_scroll_payload_without_writing(self):
        store = self.store()
        store._scroll_rest = Mock(return_value=[{
            "payload": {
                "text": "listed evidence",
                "source": "sample.pdf",
                "chunk_id": "chunk-4",
                "chunk_index": 4,
                "document_id": "doc-3",
                "metadata": {"section": "Intro"},
            }
        }])

        results = store.list_chunks({"document_id": "doc-3"}, limit=10)

        self.assertEqual(results[0].metadata["section"], "Intro")
        self.assertEqual(results[0].metadata["chunk_id"], "chunk-4")
        store._scroll_rest.assert_called_once_with(None, 10)


if __name__ == "__main__":
    unittest.main()
