import unittest

from backend.app.grounding.citations import (
    grounded_contract_error,
    normalize_citations_at_paragraph_end,
    parse_grounded_response,
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

    def test_mid_sentence_long_output_is_rejected_before_display(self):
        raw = (
            '{"answerable":true,"paragraphs":[{"text":"'
            + ("This is a long unfinished generated paragraph that continues without a safe ending " * 3).strip()
            + '","evidence_ids":["E1"]}]}'
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

    def test_whole_document_summary_may_validate_anchor_across_supplied_scope(self):
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
        self.assertEqual(result["sources"], ["paper.pdf - صفحه 7"])

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


if __name__ == "__main__":
    unittest.main()
