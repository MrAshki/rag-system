import unittest

from backend.app.grounding.citations import normalize_citations_at_paragraph_end, parse_grounded_response


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


if __name__ == "__main__":
    unittest.main()
