import json
import unittest
from unittest.mock import patch

from backend.app.agents.rag_graph import (
    _coverage_record,
    _run_safe_comprehensive_summary,
    _substantive_groups,
    _summary_coverage_contract,
    _summary_structure_guidance,
)


EVIDENCE = [
    {"coverage_key": "paper.pdf :: Abstract / چکیده"},
    {"coverage_key": "paper.pdf :: Introduction / مقدمه"},
    {"coverage_key": "paper.pdf :: Conclusion / نتیجه‌گیری"},
]


class GlobalSummaryTests(unittest.TestCase):
    @staticmethod
    def group(title, role="section", text=""):
        return {"title": title, "role": role, "chunks": [{"text": text}]}

    def test_summary_structure_adapts_to_applied_and_theoretical_research(self):
        applied, applied_guidance = _summary_structure_guidance(
            "research_article",
            [
                self.group("Methods", "methodology"),
                self.group("Results", "findings"),
                self.group("Discussion", "discussion"),
            ],
        )
        theoretical, theoretical_guidance = _summary_structure_guidance(
            "research_article",
            [
                self.group("Conceptual criterion", text="A logical argument and thought experiment"),
                self.group("Conclusion", "conclusion"),
            ],
        )
        self.assertEqual(applied, "applied_research")
        self.assertIn("method", applied_guidance)
        self.assertEqual(theoretical, "theoretical_research")
        self.assertIn("central argument", theoretical_guidance)
        self.assertIn("never as applied", theoretical_guidance)

    def test_generic_method_word_inside_theory_does_not_create_applied_schema(self):
        family, guidance = _summary_structure_guidance(
            "research_article",
            [
                self.group(
                    "Section I",
                    text=(
                        "This method of reasoning gives a result about the "
                        "criterion of physical reality."
                    ),
                ),
                self.group("Section 2", text="A logical argument follows."),
            ],
        )
        self.assertEqual(family, "theoretical_research")
        self.assertIn("never as applied", guidance)

    @patch("backend.app.agents.rag_graph._load_chunks_for_asset")
    @patch("backend.app.agents.rag_graph._selected_assets")
    def test_applied_subsections_roll_into_findings_and_admin_is_excluded(
        self, selected_assets, load_chunks,
    ):
        selected_assets.return_value = [{
            "id": "asset-1",
            "original_filename": "paper.pdf",
        }]
        rows = [
            ("u1", "مقدمه", "introduction", 1),
            ("u2", "روش کار", "methodology", 2),
            ("u3", "یافته ها", "findings", 3),
            ("u4", "۱. گزینه نخست", "section", 4),
            ("u5", "۲. گزینه دوم", "section", 5),
            ("u6", "بحث", "discussion", 6),
            ("u7", "نتیجه‌گیری", "conclusion", 7),
            ("u8", "تارض منافع", "section", 8),
        ]
        load_chunks.return_value = [
            {
                "document_id": "asset-1",
                "parent_id": unit_id,
                "parent_title": title,
                "parent_role": role,
                "source": "paper.pdf",
                "text": f"text {title}",
                "page": page,
                "chunk_index": page,
            }
            for unit_id, title, role, page in rows
        ]
        _assets, groups = _substantive_groups({})
        self.assertEqual(
            [group["role"] for group in groups],
            ["introduction", "methodology", "findings", "discussion", "conclusion"],
        )
        findings = next(group for group in groups if group["role"] == "findings")
        self.assertEqual(len(findings["chunks"]), 3)
        self.assertNotIn("تارض منافع", [group["title"] for group in groups])

    def test_summary_structure_adapts_to_review_policy_and_short_fixture(self):
        review, _ = _summary_structure_guidance(
            "review_article",
            [self.group("Systematic review method")],
        )
        policy, policy_guidance = _summary_structure_guidance(
            "sectioned_report",
            [self.group("Retention rules")],
        )
        short, short_guidance = _summary_structure_guidance(
            "flat_document",
            [self.group("Page 1")],
        )
        self.assertEqual(review, "review")
        self.assertEqual(policy, "policy_or_sectioned_report")
        self.assertIn("operative rules", policy_guidance)
        self.assertEqual(short, "source_led")
        self.assertIn("Do not impose research-method headings", short_guidance)

    def test_coverage_contract_rejects_missing_section(self):
        raw = json.dumps({
            "answerable": True,
            "paragraphs": [{"text": "Only the abstract.", "evidence_ids": ["E1"]}],
        })
        error = _summary_coverage_contract(
            raw,
            EVIDENCE,
            {item["coverage_key"] for item in EVIDENCE},
        )
        self.assertEqual(error, "section_coverage_failure")

    def test_coverage_contract_accepts_json_wrapped_by_provider_text(self):
        raw = "Result:\n" + json.dumps({
            "answerable": True,
            "paragraphs": [
                {"text": "A", "evidence_ids": ["E1"]},
                {"text": "B", "evidence_ids": ["E2"]},
                {"text": "C", "evidence_ids": ["E3"]},
            ],
        })
        error = _summary_coverage_contract(
            raw,
            EVIDENCE,
            {item["coverage_key"] for item in EVIDENCE},
        )
        self.assertIsNone(error)

    def test_one_non_conclusion_section_may_be_a_soft_warning_at_85_percent(self):
        evidence = [
            {"coverage_key": f"paper :: Section {index}"}
            for index in range(1, 7)
        ] + [{"coverage_key": "paper :: Conclusion / نتیجه‌گیری"}]
        raw = json.dumps({
            "answerable": True,
            "paragraphs": [
                {"text": f"Section {index}.", "evidence_ids": [f"E{index}"]}
                for index in range(1, 6)
            ] + [{"text": "Conclusion.", "evidence_ids": ["E7"]}],
        })
        self.assertIsNone(
            _summary_coverage_contract(
                raw,
                evidence,
                {item["coverage_key"] for item in evidence},
            )
        )

    def test_coverage_contract_does_not_duplicate_claim_support_validation(self):
        evidence = [
            {"coverage_key": "paper :: Abstract", "text": "No dates here", "source": "paper", "page": 1},
            {"coverage_key": "paper :: Conclusion", "text": "The conclusion is supported", "source": "paper", "page": 2},
        ]
        raw = json.dumps({
            "answerable": True,
            "paragraphs": [
                {"text": "The abstract claims this in 1952.", "evidence_ids": ["E1"]},
                {"text": "The conclusion is supported.", "evidence_ids": ["E2"]},
            ],
        })
        self.assertIsNone(
            _summary_coverage_contract(raw, evidence, {"paper :: Abstract", "paper :: Conclusion"})
        )

    def test_missing_conclusion_remains_a_hard_failure(self):
        evidence = [
            {"coverage_key": f"paper :: Section {index}"}
            for index in range(1, 7)
        ] + [{"coverage_key": "paper :: Conclusion / نتیجه‌گیری"}]
        record = _coverage_record(
            evidence,
            [item["coverage_key"] for item in evidence],
            [f"E{index}" for index in range(1, 7)],
        )
        self.assertFalse(record["coverage_passed"])
        self.assertEqual(record["hard_failures"], ["section_coverage_failure"])
        self.assertEqual(record["soft_warnings"], [])

    def test_one_optional_section_is_recorded_as_soft_warning(self):
        evidence = [
            {"coverage_key": f"paper :: Section {index}"}
            for index in range(1, 7)
        ] + [{"coverage_key": "paper :: Conclusion / نتیجه‌گیری"}]
        record = _coverage_record(
            evidence,
            [item["coverage_key"] for item in evidence],
            ["E1", "E2", "E3", "E4", "E5", "E7"],
        )
        self.assertTrue(record["coverage_passed"])
        self.assertEqual(record["hard_failures"], [])
        self.assertEqual(record["soft_warnings"], ["optional_section_omission"])

    @patch("backend.app.agents.rag_graph.get_chat_provider", return_value=object())
    @patch("backend.app.agents.rag_graph.rag.generate_response")
    @patch("backend.app.agents.rag_graph._substantive_groups")
    def test_direct_summary_concatenates_every_chunk_per_section(self, groups, generate, _provider):
        group = {
            "key": ("a", "u"), "coverage_key": "paper :: Section", "title": "Section",
            "role": "section", "source": "paper.pdf", "pages": [2, 3],
            "chunks": [
                {"text": "first half", "source": "paper.pdf", "page": 2},
                {"text": "second half", "source": "paper.pdf", "page": 3},
            ],
        }
        groups.return_value = ([{"original_filename": "paper.pdf", "document_profile_json": {}}], [group])
        generate.return_value = {
            "answer": "Complete. [S1]", "sources": ["paper.pdf - صفحات 2 تا 3"],
            "used_evidence_ids": ["E1"], "generation_telemetry": {},
        }
        result = _run_safe_comprehensive_summary({"question": "summary", "scope": "selected"})
        evidence = generate.call_args.args[1]
        self.assertEqual(len(evidence), 1)
        self.assertIn("first half", evidence[0]["text"])
        self.assertIn("second half", evidence[0]["text"])
        self.assertEqual((evidence[0]["page"], evidence[0]["page_end"]), (2, 3))
        self.assertEqual(result["metadata"]["coverage"]["pages_considered"], [2, 3])

    @patch("backend.app.agents.rag_graph.get_chat_provider", return_value=object())
    @patch("backend.app.agents.rag_graph.rag.generate_response")
    @patch("backend.app.agents.rag_graph._substantive_groups")
    def test_complete_summary_requires_every_group(self, groups, generate, _provider):
        chunks = []
        group_rows = []
        for index, item in enumerate(EVIDENCE, start=1):
            chunk = {
                "text": f"section evidence {index}",
                "source": "paper.pdf",
                "page": index,
                "parent_id": f"u{index}",
                "parent_title": item["coverage_key"].split(" :: ", 1)[1],
                "parent_role": "section",
                "chunk_index": index,
                "document_id": "asset-1",
            }
            chunks.append(chunk)
            group_rows.append({
                "key": ("asset-1", f"u{index}"),
                "coverage_key": item["coverage_key"],
                "title": chunk["parent_title"],
                "role": "section",
                "source": "paper.pdf",
                "chunks": [chunk],
                "pages": [index],
            })
        groups.return_value = ([{
            "original_filename": "paper.pdf",
            "document_profile_json": {"document_type": "research_article", "title": "Paper"},
        }], group_rows)
        generate.return_value = {
            "answer": "Validated summary. [S1] [S2] [S3]",
            "sources": ["paper.pdf - page 1"],
            "used_evidence_ids": ["E1", "E2", "E3"],
            "generation_telemetry": {"fallback_used": False},
        }
        result = _run_safe_comprehensive_summary({
            "question": "Summarize the whole document",
            "generation_question": "Summarize the whole document",
            "scope": "selected",
        })
        self.assertTrue(result["metadata"]["coverage"]["coverage_passed"])
        self.assertEqual(result["metadata"]["strategy"], "direct_whole_document")
        task = generate.call_args.kwargs["task_instructions"]
        self.assertIn("Required evidence coverage map", task)
        self.assertIn("35-to-60-word", task)
        self.assertIn("E1", task)
        self.assertEqual(generate.call_args.kwargs["max_output_tokens"], 3200)

    @patch("backend.app.agents.rag_graph.get_chat_provider", return_value=object())
    @patch("backend.app.agents.rag_graph.rag.generate_response")
    @patch("backend.app.agents.rag_graph._substantive_groups")
    def test_incomplete_summary_returns_controlled_error_not_partial_maps(self, groups, generate, _provider):
        chunk = {
            "text": "evidence",
            "source": "paper.pdf",
            "page": 1,
            "parent_id": "u1",
            "parent_title": "Introduction",
            "parent_role": "introduction",
            "chunk_index": 1,
            "document_id": "asset-1",
        }
        groups.return_value = ([{"original_filename": "paper.pdf", "document_profile_json": {}}], [{
            "key": ("asset-1", "u1"),
            "coverage_key": "paper.pdf :: Introduction / مقدمه",
            "title": "Introduction",
            "role": "introduction",
            "source": "paper.pdf",
            "chunks": [chunk],
            "pages": [1],
        }])
        generate.return_value = {
            "answer": "raw partial map summary",
            "sources": [],
            "used_evidence_ids": [],
            "error": {"code": "generation_unavailable"},
        }
        result = _run_safe_comprehensive_summary({"question": "summary", "scope": "selected"})
        self.assertNotIn("raw partial", result["answer"])
        self.assertFalse(result["metadata"]["coverage"]["coverage_passed"])

    @patch("backend.app.agents.rag_graph.get_chat_provider", return_value=object())
    @patch("backend.app.agents.rag_graph.rag.generate_response")
    @patch("backend.app.agents.rag_graph._substantive_groups")
    def test_summary_coverage_uses_supported_proposed_section_ids_after_citation_repair(
        self, groups, generate, _provider,
    ):
        group_rows = []
        for index, role in enumerate(("introduction", "methodology", "findings"), start=1):
            chunk = {
                "text": f"evidence {role}",
                "source": "paper.pdf",
                "page": index,
                "parent_id": role,
                "parent_title": role,
                "parent_role": role,
                "chunk_index": index,
                "document_id": "asset-1",
            }
            group_rows.append({
                "key": ("asset-1", role),
                "coverage_key": f"paper.pdf :: {role}",
                "title": role,
                "role": role,
                "source": "paper.pdf",
                "chunks": [chunk],
                "pages": [index],
            })
        groups.return_value = ([{
            "id": "asset-1",
            "original_filename": "paper.pdf",
            "document_profile_json": {"document_type": "research_article", "title": "Paper"},
        }], group_rows)
        generate.return_value = {
            "answer": "Validated summary.",
            "sources": ["paper.pdf - page 1"],
            "used_evidence_ids": ["E1"],
            "proposed_evidence_ids": ["E1", "E2", "E3"],
            "generation_telemetry": {"fallback_used": False},
        }
        result = _run_safe_comprehensive_summary({
            "question": "Summarize",
            "generation_question": "Summarize",
            "scope": "selected",
        })
        self.assertTrue(result["metadata"]["coverage"]["coverage_passed"])
        self.assertEqual(len(result["metadata"]["coverage"]["covered_sections"]), 3)


if __name__ == "__main__":
    unittest.main()
