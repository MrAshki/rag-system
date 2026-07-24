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
بازیافت آب شست وشوی تجهیزات پزشکی 75/0 3

این جدول نتیجه پردازش ماتریس تصمیم با روش تاپسیس است.
"""

COLLAPSED_TABLE_PAGE = (
    "جدول 4. نمره نهایی و رتبه هر راهکار "
    "گزینه ها (راهکارهای بازیافت آب) نمره هر گزینه "
    "(شاخص نزدیکی به ایده آل) رتبه "
    "بازیافت پساب دیالیز 87/0 1 "
    "بازیافت و بهره برداری از آب باران 78/0 2 "
    "بازیافت آب شست وشوی تجهیزات پزشکی 75/0 3 "
    "بازیافت آب خاکستری بخش های غیرعفونی بیمارستان 70/0 4 "
    "بازیافت آب برج های خن کننده 64/0 5 "
    "بازیافت آب شست وشوی ظروف غیرعفونی 58/0 6\n\n"
    "## بحث\nمعیار اقتصادی با وزن 35/0 بیشترین اهمیت را داشت."
)


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

    def test_false_numeric_rank_premise_is_rejected_and_corrected(self):
        evidence = [{
            "text": TABLE_PAGE,
            "source": "paper.pdf",
            "page": 9,
            "page_end": 9,
            "parent_title": "جدول 4",
        }]
        result = _deterministic_table_answer(
            "آیا بهره‌برداری از آب باران با امتیاز ۰٫۸۷ رتبه اول را گرفته است؟",
            evidence,
        )
        self.assertIn("خیر", result["answer"])
        self.assertIn("۰٫۷۸", result["answer"])
        self.assertIn("رتبه ۲", result["answer"])
        self.assertIn("بازیافت پساب دیالیز", result["answer"])
        self.assertIn("۰٫۸۷", result["answer"])
        self.assertTrue(result["citation_validation"]["relation_checked"])
        self.assertFalse(result["citation_validation"]["premise_correct"])

    def test_other_row_lookup_preserves_generic_row_value_rank_relation(self):
        evidence = [{
            "text": TABLE_PAGE,
            "source": "paper.pdf",
            "page": 9,
            "page_end": 9,
            "parent_title": "جدول 4",
        }]
        result = _deterministic_table_answer(
            "رتبه و امتیاز بازیافت آب شست‌وشوی تجهیزات پزشکی چیست؟",
            evidence,
        )
        self.assertIn("۰٫۷۵", result["answer"])
        self.assertIn("رتبه ۳", result["answer"])

    def test_collapsed_pdf_table_supports_ordinal_option_lookup(self):
        evidence = [{
            "text": COLLAPSED_TABLE_PAGE,
            "source": "paper.pdf",
            "page": 9,
            "page_end": 9,
            "parent_title": "جدول 4",
        }]
        result = _deterministic_table_answer(
            "گزینه دوم جدول ۴ کدام است و چه امتیازی دارد؟",
            evidence,
        )
        self.assertEqual(
            result["answer"],
            "بازیافت و بهره برداری از آب باران، ۰٫۷۸ [S1]",
        )

    def test_collapsed_pdf_table_corrects_false_rank_and_value_premise(self):
        evidence = [{
            "text": COLLAPSED_TABLE_PAGE,
            "source": "paper.pdf",
            "page": 9,
            "page_end": 9,
            "parent_title": "جدول 4",
        }]
        result = _deterministic_table_answer(
            "آیا بهره‌برداری از آب باران با امتیاز ۰٫۸۷ رتبه اول را گرفته است؟",
            evidence,
        )
        self.assertEqual(
            result["answer"],
            "خیر. بازیافت و بهره برداری از آب باران با امتیاز ۰٫۷۸ رتبه ۲ است. "
            "بازیافت پساب دیالیز با امتیاز ۰٫۸۷ رتبه ۱ را دارد. [S1]",
        )

    def test_arbitrary_table_rows_values_ranks_and_page_are_not_fixture_coupled(self):
        evidence = [{
            "text": (
                "Table 12. Candidate score rank "
                "Orchid protocol 0.413 3 "
                "Cedar protocol 0.972 1 "
                "Maple protocol 0.688 2"
            ),
            "source": "unseen-paper.pdf",
            "page": 27,
            "page_end": 27,
            "parent_title": "Table 12",
        }]
        result = _deterministic_table_answer(
            "Which option ranked second in table 12 and what was its score?",
            evidence,
        )
        self.assertIn("Maple protocol", result["answer"])
        self.assertIn("۰٫۶۸۸", result["answer"])
        self.assertEqual(result["sources"], ["unseen-paper.pdf - صفحه 27"])


if __name__ == "__main__":
    unittest.main()
