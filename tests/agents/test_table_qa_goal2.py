import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.agents.rag_graph import (
    _deterministic_table_answer,
    _persian_decimal,
    _specific_section_node,
)


TABLE_PAGE = """<!-- page:8 -->

متن توضیحی پیش از جدول.

<!-- page:9 -->

جدول 4. نمره نهایی و رتبه هر راهکار
گزینه ها (راهکارهای بازیافت آب) نمره هر گزینه (شاخص نزدیکی به ایده آل) رتبه
بازیافت پساب دیالیز 87/0 1
بازیافت و بهره برداری از آب باران 78/0 2

این جدول نتیجه پردازش ماتریس تصمیم با روش تاپسیس است.
"""


class Goal2TableQaTests(unittest.TestCase):
    def test_persian_and_latin_numeric_variants_are_equivalent(self):
        self.assertEqual(_persian_decimal("87/0"), "۰٫۸۷")
        self.assertEqual(_persian_decimal("0.87"), "۰٫۸۷")
        self.assertEqual(_persian_decimal("۰٫۸۷"), "۰٫۸۷")

    def test_rank_lookup_keeps_row_column_relationship_and_page(self):
        evidence = [{
            "text": TABLE_PAGE,
            "source": "doh-16-381.pdf",
            "page": 9,
            "page_end": 9,
            "parent_title": "جدول 4",
        }]
        result = _deterministic_table_answer(
            "طبق جدول ۴، کدام راهکار رتبهٔ اول را کسب کرد و شاخص نزدیکی به ایده‌آل آن چه بود؟",
            evidence,
        )
        self.assertEqual(result["answer"], "بازیافت پساب دیالیز، ۰٫۸۷ [S1]")
        self.assertEqual(result["sources"], ["doh-16-381.pdf - صفحه 9"])

    def test_page_aware_lookup_runs_before_no_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            normalized = Path(tmp) / "normalized.md"
            normalized.write_text(TABLE_PAGE, encoding="utf-8")
            asset = {
                "id": "asset-1",
                "original_filename": "doh-16-381.pdf",
                "normalized_md_path": str(normalized),
            }
            with patch("backend.app.agents.rag_graph._selected_assets", return_value=[asset]):
                result = _specific_section_node({
                    "question": "طبق جدول ۴، کدام راهکار رتبه اول را دارد؟",
                    "generation_question": "طبق جدول ۴، کدام راهکار رتبه اول را دارد؟",
                    "scope": "selected",
                    "request_plan": {
                        "route_implementation": "table_or_structured_document",
                        "target_section": "table",
                    },
                })

        self.assertNotIn("اطلاعات کافی", result["answer"])
        self.assertEqual(result["answer"], "بازیافت پساب دیالیز، ۰٫۸۷ [S1]")
        self.assertEqual(result["metadata"]["pages_considered"], [9])
        self.assertEqual(result["metadata"]["table_blocks_considered"], 1)
        self.assertTrue(result["metadata"]["evidence_lookup_completed"])
        self.assertEqual(result["metadata"]["embedding_calls"], 0)
        self.assertEqual(result["metadata"]["rerank_calls"], 0)


if __name__ == "__main__":
    unittest.main()
