import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from backend.app.core.config import settings
from backend.app.retrieval.r2 import REWRITE_SYSTEM_PROMPT, retrieve_r2


def chunk(index):
    return {"document_id": "doc", "chunk": index, "text": f"chunk {index}"}


class R2RetrievalTests(unittest.TestCase):
    def test_same_language_skips_rewrite_and_reranks_once(self):
        provider = Mock()
        search = Mock(return_value=[chunk(1)])
        rerank = Mock(side_effect=lambda _query, rows: rows)
        result = retrieve_r2(
            query="English question", document_language="en", search=search,
            rerank=rerank, finalize=lambda rows: rows, rewrite_provider=provider,
            candidate_k=30,
        )
        provider.chat.assert_not_called()
        search.assert_called_once_with("English question")
        self.assertEqual(rerank.call_count, 1)
        self.assertEqual(result.search_count, 1)

    def test_cross_language_uses_exactly_one_rewrite_and_one_rerank(self):
        provider = Mock()
        provider.chat.return_value = json.dumps({"rewritten_query": "English quantum query 42"})
        search = Mock(side_effect=[[chunk(1)], [chunk(1), chunk(2)]])
        rerank = Mock(side_effect=lambda _query, rows: rows)
        result = retrieve_r2(
            query="پرسش کوانتومی 42", document_language="en", search=search,
            rerank=rerank, finalize=lambda rows: rows, rewrite_provider=provider,
            candidate_k=30,
        )
        self.assertEqual(provider.chat.call_count, 1)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(rerank.call_count, 1)
        self.assertEqual(result.search_count, 2)
        self.assertEqual(len(result.chunks), 2)

    def test_reranker_receives_fused_candidates_once(self):
        provider = Mock()
        provider.chat.return_value = json.dumps({"rewritten_query": "translated query"})
        search = Mock(side_effect=[[chunk(1), chunk(2)], [chunk(2), chunk(3)]])
        rerank = Mock(side_effect=lambda _query, rows: rows)
        retrieve_r2(
            query="پرسش", document_language="en", search=search, rerank=rerank,
            finalize=lambda rows: rows, rewrite_provider=provider, candidate_k=30,
        )
        self.assertEqual(rerank.call_count, 1)
        reranked_rows = rerank.call_args.args[1]
        self.assertEqual({row["chunk"] for row in reranked_rows}, {1, 2, 3})

    def test_rewrite_failure_falls_back_to_original_query(self):
        provider = Mock()
        provider.chat.side_effect = RuntimeError("offline")
        search = Mock(return_value=[chunk(1)])
        rerank = Mock(side_effect=lambda _query, rows: rows)
        result = retrieve_r2(
            query="پرسش", document_language="en", search=search, rerank=rerank,
            finalize=lambda rows: rows, rewrite_provider=provider, candidate_k=30,
        )
        search.assert_called_once_with("پرسش")
        self.assertEqual(rerank.call_count, 1)
        self.assertEqual(result.rewrite.status, "fallback")

    def test_rewrite_prompt_preserves_critical_query_content(self):
        for term in ("names", "numbers", "quoted phrases", "technical", "negation", "Do not answer"):
            self.assertIn(term, REWRITE_SYSTEM_PROMPT)

    def test_production_embedding_is_only_nemotron(self):
        self.assertEqual(settings.embedding_model, "nvidia/nemotron-3-embed-1b:free")
        self.assertEqual(settings.qdrant_collection, "rag_documents")

    def test_production_path_has_no_alternative_embedding_collection(self):
        production_files = [
            Path("rag.py"),
            Path("backend/app/core/config.py"),
            Path("backend/app/retrieval/r2.py"),
            Path("backend/app/vector/factory.py"),
        ]
        source = "\n".join(path.read_text(encoding="utf-8") for path in production_files)
        for forbidden in ("eval_embed_", "qwen/qwen3-embedding", "text-embedding-3-large", "E2", "E3"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
