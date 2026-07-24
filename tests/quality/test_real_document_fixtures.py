import unittest
from pathlib import Path

from document_pipeline import chunker, document_map, ingest, profiling


FIXTURE_ROOT = Path(r"C:\Users\ashkriz\Downloads\New folder")
EPR = FIXTURE_ROOT / "einsteinetal1935.pdf"
PERSIAN = FIXTURE_ROOT / "بررس ی انتقادی رو یکرد فلسفی د یوی د بوهم.pdf"
GOAL2_PERSIAN = Path(__file__).resolve().parents[2] / "composite_goldset_pdfs" / "doh-16-381.pdf"
GOAL3_FIXTURES = Path(__file__).resolve().parents[2] / "composite_goldset_pdfs"


@unittest.skipUnless(EPR.exists() and PERSIAN.exists(), "private validation PDFs are not installed")
class RealDocumentFixtureTests(unittest.TestCase):
    @staticmethod
    def normalize(path):
        with path.open("rb") as handle:
            result = ingest.normalize_document(path.name, handle, ".pdf")
        profile = profiling.profile_document(result["markdown_text"], result["meta"], filename=path.name)
        doc_map = document_map.build_document_map(result["markdown_text"], profile)
        chunks = chunker.parse_markdown_to_chunks(result["markdown_text"])
        document_map.assign_chunks_to_units(chunks, doc_map)
        return result, profile, doc_map, chunks

    def test_epr_starts_at_the_real_article_and_preserves_all_pages(self):
        result, profile, doc_map, chunks = self.normalize(EPR)
        self.assertEqual(profile.document_type, "research_article")
        self.assertEqual(profile.title, "Can Quantum-Mechanical Description of Physical Reality Be Considered Complete?")
        self.assertEqual(profile.page_count, 4)
        self.assertFalse(result["meta"]["ocr_required"])
        self.assertNotIn("lanthanum", result["markdown_text"].lower())
        self.assertIn("wave function does not provide a complete description", result["markdown_text"])
        self.assertEqual(sorted({chunk["page"] for chunk in chunks}), [1, 2, 3, 4])
        self.assertEqual([unit["title"] for unit in doc_map["units"]], ["Abstract", "Section I", "Section 2"])

    def test_persian_article_has_real_structure_without_journal_headers(self):
        result, profile, doc_map, chunks = self.normalize(PERSIAN)
        self.assertEqual(profile.document_type, "research_article")
        self.assertEqual(
            profile.title,
            "بررسی انتقادی رویکرد فلسفی دیوید بوهم به علیت براساس فلسفۀ ملاصدرا",
        )
        self.assertEqual(profile.page_count, 18)
        self.assertEqual(profile.language, "fa")
        self.assertFalse(result["meta"]["ocr_required"])
        self.assertNotIn("Print ISSN", result["markdown_text"])
        self.assertNotIn("Shinakht is a persian word", result["markdown_text"])
        titles = [unit["title"] for unit in doc_map["units"]]
        for required in (
            "مقدمه",
            "علیت در فیزیک جدید",
            "علیت از منظر بوهم",
            "تحلیل علیت از دو منظر کپنهاگی و بوهمی",
            "علیت در فلسفۀ صدرایی",
            "نتیجه‌گیری",
        ):
            self.assertIn(required, titles)
        self.assertEqual(next(unit for unit in doc_map["units"] if unit["title"] == "References")["role"], "references")
        self.assertEqual(sorted({chunk["page"] for chunk in chunks}), list(range(1, 19)))


@unittest.skipUnless(GOAL2_PERSIAN.exists(), "Goal 2 Persian fixture is not installed")
class Goal2DocumentFixtureTests(unittest.TestCase):
    def test_doh_16_381_title_type_and_substantive_sections(self):
        with GOAL2_PERSIAN.open("rb") as handle:
            result = ingest.normalize_document(GOAL2_PERSIAN.name, handle, ".pdf")
        profile = profiling.profile_document(
            result["markdown_text"],
            result["meta"],
            filename=GOAL2_PERSIAN.name,
        )
        doc_map = document_map.build_document_map(result["markdown_text"], profile)

        self.assertEqual(
            profile.title,
            "بازیافت آب در بیمارستان های عمومی استان مرکزی با استفاده از روش تصمیم گیری چندمعیاره تاپسیس ( TOPSIS ): شناسایی و اولویت بندی راهکارها",
        )
        self.assertEqual(profile.document_type, "research_article")
        roles = {unit["title"]: unit["role"] for unit in doc_map["units"]}
        for title in ("قدردانی ها", "مشارکت پدیدآوران", "منابع مالی", "ملاحظات اخلاقی", "تعارض منافع"):
            self.assertEqual(roles[title], "administrative")


@unittest.skipUnless(
    all((GOAL3_FIXTURES / name).exists() for name in (
        "fixture-003-mixed-persian-english.pdf",
        "fixture-004-intentional-no-answer.pdf",
        "fixture-005-ambiguous-followup.pdf",
    )),
    "Goal 3 controlled fixtures are not installed",
)
class Goal3ControlledFixtureTests(unittest.TestCase):
    @staticmethod
    def normalized(name):
        path = GOAL3_FIXTURES / name
        with path.open("rb") as handle:
            result = ingest.normalize_document(path.name, handle, ".pdf")
        profile = profiling.profile_document(result["markdown_text"], result["meta"], filename=path.name)
        return result, profile

    def test_short_sectioned_fixture_keeps_all_pages_and_rollback_number(self):
        result, profile = self.normalized("fixture-003-mixed-persian-english.pdf")
        self.assertTrue(profile.quality.indexable)
        self.assertIsNone(profile.title)
        self.assertIn("Deployment Policy", result["markdown_text"])
        self.assertIn("Rollback", result["markdown_text"])
        self.assertIn("۱۵ دقیقهای", result["markdown_text"])
        self.assertEqual(
            sorted({chunk["page"] for chunk in chunker.parse_markdown_to_chunks(result["markdown_text"])}),
            [1, 2, 3],
        )

    def test_intentional_no_answer_fixture_is_indexable_without_losing_rules(self):
        result, profile = self.normalized("fixture-004-intentional-no-answer.pdf")
        self.assertTrue(profile.quality.indexable)
        self.assertIn("۲۶ روز", result["markdown_text"])
        self.assertIn("اضافهکاری", result["markdown_text"])
        self.assertIn("حکمی ندارد", result["markdown_text"])

    def test_ambiguous_fixture_preserves_both_dates_and_clarification_rule(self):
        result, profile = self.normalized("fixture-005-ambiguous-followup.pdf")
        self.assertTrue(profile.quality.indexable)
        self.assertIn("۱۵ مهر", result["markdown_text"])
        self.assertIn("۳۰ مهر", result["markdown_text"])
        self.assertIn("هر دو پروژه", result["markdown_text"])
        self.assertIn("سؤال روشنکننده", result["markdown_text"])


if __name__ == "__main__":
    unittest.main()
