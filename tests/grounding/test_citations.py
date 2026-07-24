import unittest

from backend.app.grounding.citations import (
    grounded_contract_error,
    normalize_citations_at_paragraph_end,
    parse_grounded_response,
    repair_grounded_contract,
)


CHUNKS = [
    {"source": "book.pdf", "page": 10, "text": "متن اول"},
    {"source": "book.pdf", "page": 12, "text": "متن دوم"},
]


def label(chunk):
    return f"{chunk['source']} - صفحه {chunk['page']}"


class CitationTests(unittest.TestCase):
    def test_citations_are_rendered_only_at_paragraph_end(self):
        raw = (
            '{"answerable":true,"paragraphs":['
            '{"text":"پاراگراف اول [S2] با متن تمیز.","evidence_ids":["E2"]},'
            '{"text":"پاراگراف دوم.","evidence_ids":["E1","E2"]}'
            "]}"
        )
        result = parse_grounded_response(raw, chunks=CHUNKS, citation_label=label, no_info_message="کافی نیست")
        paragraphs = result["answer"].split("\n\n")
        self.assertTrue(paragraphs[0].endswith("[S1]"))
        self.assertNotIn("[S2] با", paragraphs[0])
        self.assertTrue(paragraphs[1].endswith("[S2] [S1]"))
        self.assertEqual(result["citation_validation"]["status"], "validated")

    def test_unknown_evidence_ids_reject_paragraph(self):
        raw = '{"answerable":true,"paragraphs":[{"text":"ادعای بدون منبع","evidence_ids":["E99"]}]}'
        result = parse_grounded_response(raw, chunks=CHUNKS, citation_label=label, no_info_message="کافی نیست")
        self.assertEqual(result["answer"], "کافی نیست")
        self.assertEqual(result["sources"], [])

    def test_duplicate_source_labels_render_one_marker(self):
        chunks = [
            {"source": "book.pdf", "page": 10, "text": "بخش اول"},
            {"source": "book.pdf", "page": 10, "text": "بخش دوم"},
        ]
        raw = (
            '{"answerable":true,"paragraphs":['
            '{"text":"یک ادعای پشتیبانی‌شده.","evidence_ids":["E1","E2"]}'
            "]}"
        )

        result = parse_grounded_response(raw, chunks=chunks, citation_label=label, no_info_message="کافی نیست")

        self.assertTrue(result["answer"].endswith("[S1]"))
        self.assertNotIn("[S1] [S1]", result["answer"])

    def test_legacy_markers_are_moved_to_paragraph_end(self):
        result = normalize_citations_at_paragraph_end(
            "ادعا [S2] در وسط جمله است.\n\nپاراگراف بعد [S1].",
            ["page 1", "page 2"],
        )
        self.assertEqual(result["answer"], "ادعا در وسط جمله است. [S2]\n\nپاراگراف بعد. [S1]")
        self.assertEqual(result["sources"], ["page 1", "page 2"])

    def test_long_complete_paragraph_without_terminal_punctuation_is_not_called_truncated(self):
        raw = (
            '{"answerable":true,"paragraphs":[{"text":"'
            + ("This is a complete grounded paragraph with supported information " * 3).strip()
            + '","evidence_ids":["E1"]}]}'
        )
        self.assertIsNone(grounded_contract_error(raw, evidence_count=1))

    def test_paragraph_ending_in_conjunction_is_rejected_as_truncated(self):
        raw = (
            '{"answerable":true,"paragraphs":[{"text":"'
            + ("This is a long generated paragraph with supported information " * 3)
            + 'and","evidence_ids":["E1"]}]}'
        )
        self.assertEqual(grounded_contract_error(raw, evidence_count=1), "truncated_output")

    def test_numeric_claim_not_present_on_cited_page_is_rejected(self):
        raw = '{"answerable":true,"paragraphs":[{"text":"The value is 99.","evidence_ids":["E1"]}]}'
        result = parse_grounded_response(
            raw,
            chunks=[{"source": "paper.pdf", "page": 1, "text": "The measured value is 42."}],
            citation_label=label,
            no_info_message="No evidence.",
            verify_support=True,
        )
        self.assertEqual(result["answer"], "No evidence.")
        self.assertEqual(result["sources"], [])

    def test_persian_slash_decimal_supports_standard_decimal_claim(self):
        raw = '{"answerable":true,"paragraphs":[{"text":"امتیاز راهکار ۰٫۸۷ است.","evidence_ids":["E1"]}]}'
        result = parse_grounded_response(
            raw,
            chunks=[{
                "source": "paper.pdf",
                "page": 9,
                "text": "بازیافت پساب دیالیز 87/0 1",
            }],
            citation_label=label,
            no_info_message="کافی نیست",
            verify_support=True,
        )
        self.assertIn("۰٫۸۷", result["answer"])
        self.assertEqual(result["citation_validation"]["status"], "validated")

    def test_whole_document_summary_repairs_numeric_citation_to_supporting_page(self):
        raw = '{"answerable":true,"paragraphs":[{"text":"در سال ۲۰۲۵ مطالعه انجام شد.","evidence_ids":["E2"]}]}'
        chunks = [
            {"source": "paper.pdf", "page": 1, "text": "The study was conducted in 2025."},
            {"source": "paper.pdf", "page": 7, "text": "روش مطالعه و جامعه پژوهش."},
        ]
        result = parse_grounded_response(
            raw,
            chunks=chunks,
            citation_label=label,
            no_info_message="کافی نیست",
            verify_support=True,
            support_scope_chunks=chunks,
        )
        self.assertIn("۲۰۲۵", result["answer"])
        self.assertEqual(result["sources"], ["paper.pdf - صفحه 1"])
        self.assertEqual(result["citation_validation"]["support"][0]["status"], "repaired")

    def test_multiple_numeric_facts_use_minimal_supporting_pages(self):
        raw = (
            '{"answerable":true,"paragraphs":['
            '{"text":"نمونه ۳۷ نفر، ۱۵ عامل و کاپای ۰٫۸۲ داشت.","evidence_ids":["E2"]}'
            "]}"
        )
        chunks = [
            {
                "source": "paper.pdf",
                "page": 1,
                "text": "37 experts identified 15 factors (Cohen's kappa = 0.82).",
            },
            {"source": "paper.pdf", "page": 7, "text": "بحث عمومی روش پژوهش."},
        ]
        result = parse_grounded_response(
            raw,
            chunks=chunks,
            citation_label=label,
            no_info_message="کافی نیست",
            verify_support=True,
        )
        self.assertEqual(result["sources"], ["paper.pdf - صفحه 1"])
        self.assertEqual(result["citation_validation"]["status"], "validated")

    def test_numeric_tie_preserves_provider_section_evidence(self):
        raw = (
            '{"answerable":true,"paragraphs":['
            '{"text":"روش در ۳ مرحله و سال ۲۰۲۵ اجرا شد.","evidence_ids":["E2"]}'
            "]}"
        )
        chunks = [
            {
                "source": "paper.pdf",
                "page": 1,
                "text": "The introduction mentions a 3-stage study conducted in 2025.",
            },
            {
                "source": "paper.pdf",
                "page": 6,
                "text": "روش پژوهش در ۳ مرحله و سال ۲۰۲۵ اجرا شد.",
            },
        ]
        result = parse_grounded_response(
            raw,
            chunks=chunks,
            citation_label=label,
            no_info_message="کافی نیست",
            verify_support=True,
        )
        self.assertEqual(result["sources"], ["paper.pdf - صفحه 6"])
        self.assertEqual(result["used_evidence_ids"], ["E2"])

    def test_summary_scope_still_rejects_number_absent_from_whole_document(self):
        raw = '{"answerable":true,"paragraphs":[{"text":"در سال ۲۰۹۹ مطالعه انجام شد.","evidence_ids":["E2"]}]}'
        chunks = [
            {"source": "paper.pdf", "page": 1, "text": "The study was conducted in 2025."},
            {"source": "paper.pdf", "page": 7, "text": "روش مطالعه و جامعه پژوهش."},
        ]
        result = parse_grounded_response(
            raw,
            chunks=chunks,
            citation_label=label,
            no_info_message="کافی نیست",
            verify_support=True,
            support_scope_chunks=chunks,
        )
        self.assertEqual(result["answer"], "کافی نیست")

    def test_three_valid_summary_evidence_ids_are_locally_narrowed(self):
        raw = (
            '{"answerable":true,"paragraphs":['
            '{"text":"نتیجه اصلی بر شواهد چند بخش تکیه دارد.",'
            '"evidence_ids":["E1","E2","E3","E4"]}'
            "]}"
        )
        chunks = [
            {"source": "paper.pdf", "page": index, "text": "نتیجه اصلی و شواهد پژوهش"}
            for index in range(1, 5)
        ]
        self.assertEqual(
            grounded_contract_error(raw, evidence_count=4),
            "citation_marker_format_invalid",
        )
        raw = raw.replace('"E1","E2","E3","E4"', '"E1","E2","E3"')
        result = parse_grounded_response(
            raw,
            chunks=chunks,
            citation_label=label,
            no_info_message="کافی نیست",
            verify_support=True,
        )
        self.assertEqual(result["proposed_evidence_ids"], ["E1", "E2", "E3"])
        self.assertLessEqual(len(result["used_evidence_ids"]), 3)

    def test_bounded_contract_repair_removes_inline_markers_and_caps_ids(self):
        raw = (
            '{"answerable":true,"paragraphs":[{'
            '"text":"ادعای کامل [S1].",'
            '"evidence_ids":["S1","E2","E3","E4"]'
            "}]} "
        )
        repaired = repair_grounded_contract(raw, evidence_count=4)
        self.assertIsNotNone(repaired)
        self.assertIsNone(grounded_contract_error(repaired, evidence_count=4))
        self.assertNotIn("[S1]", repaired)
        self.assertNotIn("E4", repaired)

    def test_support_scope_can_narrow_summary_group_to_physical_page(self):
        raw = (
            '{"answerable":true,"paragraphs":[{'
            '"text":"نتیجه اصلی نیاز به هماهنگی دارد.",'
            '"evidence_ids":["E1"]'
            "}]} "
        )
        grouped = [{
            "source": "paper.pdf",
            "page": 4,
            "page_end": 7,
            "coverage_key": "paper :: findings",
            "text": "نتیجه اصلی نیاز به هماهنگی دارد و شواهد دیگری نیز هست.",
        }]
        support = [{
            "source": "paper.pdf",
            "page": 6,
            "coverage_key": "paper :: findings",
            "text": "نتیجه اصلی نیاز به هماهنگی دارد.",
        }]
        result = parse_grounded_response(
            raw,
            chunks=grouped,
            citation_label=label,
            no_info_message="کافی نیست",
            verify_support=True,
            support_scope_chunks=support,
        )
        self.assertEqual(result["sources"], ["paper.pdf - صفحه 6"])
        self.assertEqual(result["citation_validation"]["support"][0]["status"], "repaired")

    def test_exact_definition_prefers_precise_child_page_over_parent_range(self):
        raw = (
            '{"answerable":true,"paragraphs":[{'
            '"text":"حضورگرایی یعنی ادامه کار با وجود بیماری.",'
            '"evidence_ids":["E1"]}]}'
        )
        parent = [{
            "source": "paper.pdf", "page": 2, "page_end": 8,
            "coverage_key": "paper :: introduction",
            "text": "مقدمه درباره حضورگرایی و بیماری بحث می‌کند.",
        }]
        child = [{
            "source": "paper.pdf", "page": 3,
            "coverage_key": "paper :: introduction",
            "text": "حضورگرایی یعنی ادامه کار با وجود بیماری.",
        }]
        result = parse_grounded_response(
            raw, chunks=parent, citation_label=label, no_info_message="کافی نیست",
            verify_support=True, support_scope_chunks=child,
        )
        self.assertEqual(result["sources"], ["paper.pdf - صفحه 3"])

    def test_wrong_adjacent_page_is_repaired_to_exact_physical_page(self):
        raw = (
            '{"answerable":true,"paragraphs":[{'
            '"text":"ضریب نهایی ۰٫۶۴ بود.","evidence_ids":["E1"]}]}'
        )
        chunks = [
            {"source": "paper.pdf", "page": 8, "text": "شرح جدول بدون مقدار نهایی."},
            {"source": "paper.pdf", "page": 9, "text": "ضریب نهایی ۰٫۶۴ بود."},
        ]
        result = parse_grounded_response(
            raw, chunks=chunks, citation_label=label, no_info_message="کافی نیست",
            verify_support=True,
        )
        self.assertEqual(result["sources"], ["paper.pdf - صفحه 9"])

    def test_genuinely_multi_page_numeric_claim_keeps_both_pages(self):
        raw = (
            '{"answerable":true,"paragraphs":[{'
            '"text":"گروه اول ۴۱ نفر و گروه دوم ۵۹ نفر داشت.",'
            '"evidence_ids":["E1","E2"]}]}'
        )
        chunks = [
            {"source": "paper.pdf", "page": 4, "text": "گروه اول ۴۱ نفر داشت."},
            {"source": "paper.pdf", "page": 5, "text": "گروه دوم ۵۹ نفر داشت."},
        ]
        result = parse_grounded_response(
            raw, chunks=chunks, citation_label=label, no_info_message="کافی نیست",
            verify_support=True,
        )
        self.assertEqual(
            result["sources"],
            ["paper.pdf - صفحه 4", "paper.pdf - صفحه 5"],
        )

    def test_cross_language_claim_keeps_provider_selected_substantive_page(self):
        raw = (
            '{"answerable":true,"paragraphs":[{'
            '"text":"The guideline does not regulate overtime.",'
            '"evidence_ids":["E1"]}]}'
        )
        chunks = [{
            "source": "paper.pdf", "page": 2, "section_role": "body",
            "text": "این دستورالعمل درباره اضافه‌کاری حکمی ندارد.",
        }]
        result = parse_grounded_response(
            raw, chunks=chunks, citation_label=label, no_info_message="insufficient",
            verify_support=True,
        )
        self.assertEqual(result["sources"], ["paper.pdf - صفحه 2"])


if __name__ == "__main__":
    unittest.main()
