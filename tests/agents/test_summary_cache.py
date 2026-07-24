import unittest
from unittest.mock import patch

from backend.app.agents.rag_graph import _chapter_summary


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        return "خلاصه شاهد اول [E1]"


UNIT = {
    "asset_id": "asset-1",
    "unit_id": "unit-1",
    "content_hash": "hash-1",
    "title": "فصل اول",
    "pages": [10],
    "evidence": [
        {"marker": "S7", "label": "book.pdf - صفحه 10", "text": "متن شاهد"},
    ],
}


class SummaryCacheTests(unittest.TestCase):
    @patch("backend.app.agents.rag_graph.db.upsert_document_unit_summary")
    @patch("backend.app.agents.rag_graph.db.get_document_unit_summary", return_value=None)
    def test_cache_miss_calls_provider_and_stores_local_markers(self, _get, upsert):
        provider = FakeProvider()
        summary, cache_hit = _chapter_summary(provider, "خلاصه کن", UNIT)

        self.assertFalse(cache_hit)
        self.assertEqual(provider.calls, 1)
        self.assertIn("[S7]", summary)
        self.assertEqual(upsert.call_args.args[-1], "خلاصه شاهد اول [E1]")

    @patch(
        "backend.app.agents.rag_graph.db.get_document_unit_summary",
        return_value={"summary_text": "خلاصه ذخیره‌شده [E1]"},
    )
    def test_cache_hit_skips_provider(self, _get):
        provider = FakeProvider()
        summary, cache_hit = _chapter_summary(provider, "خلاصه کن", UNIT)

        self.assertTrue(cache_hit)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(summary, "خلاصه ذخیره‌شده [S7]")


if __name__ == "__main__":
    unittest.main()
