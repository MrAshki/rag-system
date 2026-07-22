import os
import unittest
from unittest.mock import patch

from backend.app.core.config import Settings


class ProductionConfigTests(unittest.TestCase):
    def test_final_architecture_is_the_default(self):
        with patch.dict(os.environ, {"FLASK_SECRET_KEY": "test-secret"}, clear=True):
            settings = Settings()

        self.assertEqual(settings.embedding_provider, "openrouter")
        self.assertEqual(settings.embedding_model, "nvidia/nemotron-3-embed-1b:free")
        self.assertEqual(settings.embedding_dim, 2048)
        self.assertEqual(settings.vector_backend, "qdrant")
        self.assertEqual(settings.qdrant_collection, "rag_documents")
        self.assertEqual(settings.rag_retrieval_mode, "r2")
        self.assertEqual(settings.rag_primary_generator_model, "google/gemini-2.5-flash")
        self.assertEqual(settings.rag_fallback_generator_model, "z-ai/glm-5.2")
        self.assertEqual(settings.rag_max_generator_attempts, 2)

    def test_fallback_rejects_more_or_fewer_than_two_attempts(self):
        with patch.dict(
            os.environ,
            {
                "FLASK_SECRET_KEY": "test-secret",
                "RAG_GENERATOR_FALLBACK_ENABLED": "true",
                "RAG_MAX_GENERATOR_ATTEMPTS": "1",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "Fallback requires"):
                Settings()


if __name__ == "__main__":
    unittest.main()
