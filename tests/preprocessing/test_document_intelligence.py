import unittest

from document_pipeline import chunker, document_map, ingest, profiling


class DocumentIntelligenceTests(unittest.TestCase):
    def test_chaptered_document_builds_stable_parent_units(self):
        markdown = (
            "# کتاب نمونه\n\n"
            "## فصل اول: شروع\n\n" + ("متن فصل اول. " * 80) + "\n\n"
            "## فصل دوم: ادامه\n\n" + ("متن فصل دوم. " * 80)
        )
        meta = {"page_count": None, "structure_confidence": "high"}
        profile = profiling.profile_document(markdown, meta, filename="کتاب نمونه.txt")
        doc_map = document_map.build_document_map(markdown, profile)
        chunks = chunker.parse_markdown_to_chunks(markdown)
        document_map.assign_chunks_to_units(chunks, doc_map)

        self.assertEqual(profile.document_type, "chaptered_book")
        self.assertEqual(profile.unit_strategy, "chapter")
        self.assertGreaterEqual(len(doc_map["units"]), 2)
        self.assertTrue(all(chunk.get("parent_id") for chunk in chunks))

    def test_repeated_pdf_chapter_headers_do_not_create_duplicate_units(self):
        markdown = (
            "<!-- page:1 -->\n\n## فصل اول: شروع\n\nمتن صفحه اول.\n\n"
            "<!-- page:2 -->\n\n## فصل اول: شروع\n\nمتن صفحه دوم.\n\n"
            "<!-- page:3 -->\n\n## فصل دوم: ادامه\n\nمتن صفحه سوم."
        )
        meta = {"page_count": 3, "structure_confidence": "high"}
        profile = profiling.profile_document(markdown, meta, filename="book.pdf")
        doc_map = document_map.build_document_map(markdown, profile)
        titles = [unit["title"] for unit in doc_map["units"]]
        self.assertEqual(titles, ["بخش آغازین", "فصل اول: شروع", "فصل دوم: ادامه"])

    def test_flat_document_uses_semantic_windows_without_llm(self):
        paragraphs = [f"این پاراگراف شماره {index} است. " * 40 for index in range(12)]
        markdown = "\n\n".join(paragraphs)
        meta = {"page_count": None, "structure_confidence": "low"}
        profile = profiling.profile_document(markdown, meta, filename="notes.txt")
        doc_map = document_map.build_document_map(markdown, profile)

        self.assertEqual(profile.document_type, "flat_document")
        self.assertEqual(profile.unit_strategy, "semantic_window")
        self.assertGreater(len(doc_map["units"]), 1)
        self.assertTrue(all(unit["title"].startswith("بخش ") for unit in doc_map["units"]))

    def test_unusable_ocr_output_is_rejected(self):
        markdown = "<!-- page:1 -->\n\n???"
        meta = {
            "page_count": 1,
            "structure_confidence": "low",
            "ocr_required": True,
            "ocr_status": "unavailable",
        }
        profile = profiling.profile_document(markdown, meta, filename="scan.pdf")

        self.assertEqual(profile.document_type, "noisy_scan")
        self.assertEqual(profile.quality.status, "rejected")
        self.assertFalse(profile.quality.indexable)

    def test_english_prose_is_not_misclassified_as_persian_mojibake(self):
        text = (
            "Artificial intelligence systems should be governed and evaluated "
            "throughout their lifecycle. " * 20
        )

        self.assertFalse(ingest._looks_garbled(text))

    def test_sparse_unavailable_ocr_pages_only_warn(self):
        markdown = "\n\n".join(
            [f"<!-- page:{page} -->\n\nمتن سالم صفحه {page}. " * 20 for page in range(1, 101)]
        )
        meta = {
            "page_count": 100,
            "structure_confidence": "high",
            "ocr_required": True,
            "ocr_status": "unavailable",
            "ocr_pages_skipped": 2,
            "ocr_blocking": False,
        }

        profile = profiling.profile_document(markdown, meta, filename="book.pdf")

        self.assertTrue(profile.quality.indexable)
        self.assertEqual(profile.quality.status, "warning")
        self.assertIn("partial_ocr_pages_skipped", profile.quality.warnings)

    def test_formal_meeting_speakers_are_detected_as_transcript(self):
        names = ["ADAMS", "BAKER", "CLARK", "DAVIS", "EVANS", "FRANK", "GREEN", "HALL", "IRWIN"]
        turns = [
            f"MR. {name}. This is a substantive meeting statement number {index}."
            for index, name in enumerate(names, start=1)
        ]
        markdown = "\n\n".join(turns)
        profile = profiling.profile_document(
            markdown,
            {"structure_confidence": "low"},
            filename="meeting.pdf",
        )

        self.assertEqual(profile.document_type, "transcript")
        self.assertEqual(profile.unit_strategy, "semantic_window")

    def test_numeric_table_row_is_not_promoted_to_heading(self):
        row = "62 Serbia 0.833 76.8 15.0 11.6 23,115 7 61"

        self.assertFalse(ingest._generic_heading_candidate(row))


if __name__ == "__main__":
    unittest.main()
