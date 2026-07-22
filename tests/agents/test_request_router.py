import unittest

from backend.app.agents.request_router import plan_request


class RequestRouterTests(unittest.TestCase):
    def test_exact_question_uses_small_budget_without_decomposition(self):
        plan = plan_request("نویسنده چه نظری درباره اراده آزاد دارد؟", has_document_scope=True)
        self.assertEqual(plan.intent, "exact_answer")
        self.assertEqual(plan.budget.evidence_k, 5)
        self.assertFalse(plan.decompose_query)

    def test_full_summary_uses_document_map(self):
        plan = plan_request("یک خلاصه کامل از کل کتاب بده", has_document_scope=True)
        self.assertEqual(plan.intent, "comprehensive_summary")
        self.assertTrue(plan.requires_document_map)
        self.assertFalse(plan.budget.use_reranker)

    def test_multi_question_allows_bounded_decomposition(self):
        plan = plan_request("موضوع اول چیست؟ موضوع دوم چه تفاوتی دارد؟", has_document_scope=True)
        self.assertTrue(plan.decompose_query)
        self.assertGreaterEqual(plan.budget.max_subqueries, 1)

    def test_no_scope_routes_to_free_chat(self):
        plan = plan_request("سلام، حالت چطوره؟", has_document_scope=False)
        self.assertEqual(plan.route, "free_chat")


if __name__ == "__main__":
    unittest.main()
