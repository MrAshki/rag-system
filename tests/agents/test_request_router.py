import unittest

from backend.app.agents.request_router import plan_request


class RequestRouterTests(unittest.TestCase):
    def test_exact_question_uses_small_budget_without_decomposition(self):
        plan = plan_request("نویسنده چه نظری درباره اراده آزاد دارد؟", has_document_scope=True)
        self.assertEqual(plan.intent, "exact_answer")
        self.assertEqual(plan.budget.evidence_k, 5)
        self.assertFalse(plan.decompose_query)

    def test_full_summary_uses_document_map(self):
        plan = plan_request(
            "یک خلاصه کامل از کل کتاب بده",
            has_document_scope=True,
            selected_document_count=1,
            document_token_estimate=12_000,
        )
        self.assertEqual(plan.intent, "comprehensive_summary")
        self.assertEqual(plan.route_implementation, "direct_whole_document")
        self.assertTrue(plan.requires_document_map)
        self.assertFalse(plan.budget.use_reranker)

    def test_oversized_or_multi_document_summary_is_hierarchical(self):
        plan = plan_request(
            "یک خلاصه جامع از همه سندها بده",
            has_document_scope=True,
            selected_document_count=2,
            document_token_estimate=50_000,
        )
        self.assertEqual(plan.route_implementation, "hierarchical_section_aware")

    def test_multi_question_allows_bounded_decomposition(self):
        plan = plan_request("موضوع اول چیست؟ موضوع دوم چه تفاوتی دارد؟", has_document_scope=True)
        self.assertTrue(plan.decompose_query)
        self.assertGreaterEqual(plan.budget.max_subqueries, 1)

    def test_no_scope_routes_to_free_chat(self):
        plan = plan_request("سلام، حالت چطوره؟", has_document_scope=False)
        self.assertEqual(plan.route, "free_chat")

    def test_abstract_question_uses_direct_section_route(self):
        plan = plan_request("چکیده مقاله چه می‌گوید؟", has_document_scope=True)
        self.assertEqual(plan.route, "specific_section")
        self.assertEqual(plan.target_section, "abstract")

    def test_page_question_uses_exact_page_route(self):
        plan = plan_request("در صفحه ۱۲ چه ادعایی مطرح شده؟", has_document_scope=True)
        self.assertEqual(plan.route, "specific_section")
        self.assertEqual(plan.target_page, 12)

    def test_comparison_uses_analytical_route(self):
        plan = plan_request("دیدگاه بوهم و ملاصدرا را مقایسه کن", has_document_scope=True)
        self.assertEqual(plan.route, "analytical")

    def test_short_clarification_resolves_against_assistant_history(self):
        history = [{"role": "assistant", "content": "پاسخ قبلی", "sources": ["paper.pdf - صفحه 7"]}]
        plan = plan_request("یعنی چی؟", has_document_scope=True, conversation_history=history)
        self.assertEqual(plan.route, "conversational_followup")
        self.assertEqual(plan.route_implementation, "conversation_only")
        self.assertTrue(plan.history_required)

    def test_quoted_statement_is_not_mistaken_for_history_only_followup(self):
        history = [{"role": "assistant", "content": "پاسخ قبلی"}]
        plan = plan_request(
            "در جمله «اصل علیت بدیهی است» یعنی چی؟",
            has_document_scope=True,
            conversation_history=history,
        )
        self.assertNotEqual(plan.route, "conversational_followup")
        self.assertEqual(plan.route_implementation, "quoted_document_explanation")

    def test_table_cue_precedes_generic_extraction(self):
        plan = plan_request(
            "طبق جدول ۴، کدام راهکار رتبه اول را دارد؟",
            has_document_scope=True,
            selected_document_count=1,
            document_token_estimate=12_000,
        )
        self.assertEqual(plan.route, "specific_section")
        self.assertEqual(plan.route_implementation, "table_or_structured_document")

    def test_stable_version_does_not_contain_the_word_table(self):
        plan = plan_request(
            "چه زمانی سیستم باید به previous stable version بازگردد؟",
            has_document_scope=True,
        )
        self.assertEqual(plan.route, "focused_rag")
        self.assertEqual(plan.route_implementation, "local_hybrid_retrieval")

    def test_descriptive_phrase_in_section_is_not_an_explicit_section_target(self):
        plan = plan_request(
            "در بخش کیفی چند خبره مصاحبه شدند و ضریب کاپا چقدر بود؟",
            has_document_scope=True,
        )
        self.assertEqual(plan.route, "focused_rag")

    def test_retry_reuses_previous_operation(self):
        history = [{"role": "assistant", "content": "خطا در تولید پاسخ."}]
        plan = plan_request("دوباره امتحان کن", has_document_scope=True, conversation_history=history)
        self.assertEqual(plan.route, "retry_previous")

    def test_short_anaphoric_followup_uses_conversation_route(self):
        history = [{"role": "assistant", "content": "آلفا و بتا مقایسه شدند."}]
        plan = plan_request(
            "آن را زودتر تحویل بدهند؟",
            has_document_scope=True,
            conversation_history=history,
        )
        self.assertEqual(plan.route, "conversational_followup")
        self.assertEqual(plan.route_implementation, "conversation_only")


if __name__ == "__main__":
    unittest.main()
