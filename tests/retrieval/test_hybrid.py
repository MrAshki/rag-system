import unittest

import rag
from backend.app.retrieval.hybrid import lexical_rank, reciprocal_rank_fusion
from backend.app.vector.base import SearchResult


def result(document_id, chunk, text):
    return SearchResult(text=text, source="sample", chunk=chunk, document_id=document_id)


class HybridRetrievalTests(unittest.TestCase):
    def test_lexical_rank_recovers_exact_rare_term(self):
        chunks = [
            result("d1", 1, "توضیح عمومی درباره فیزیک"),
            result("d1", 2, "آزمایش Stern Gerlach رفتار اسپین را نشان می‌دهد"),
        ]
        ranked = lexical_rank("Stern Gerlach", chunks, top_k=2)
        self.assertEqual(ranked[0].chunk, 2)

    def test_rrf_rewards_result_present_in_both_rankings(self):
        shared = result("d1", 2, "shared")
        dense = [result("d1", 1, "dense"), shared]
        lexical = [shared, result("d1", 3, "lexical")]
        fused = reciprocal_rank_fusion(dense, lexical, top_k=3)
        self.assertEqual(fused[0].chunk, 2)
        self.assertEqual(fused[0].metadata["retrieval"], "hybrid_rrf")

    def test_single_parent_does_not_shrink_evidence_budget(self):
        chunks = [
            {"document_id": "doc", "chunk": index, "parent_id": "only-parent", "text": str(index)}
            for index in range(1, 7)
        ]

        diversified = rag.diversify_chunks(chunks, top_k=5)

        self.assertEqual([item["chunk"] for item in diversified], [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
