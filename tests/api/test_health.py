import unittest
from unittest.mock import patch

from backend.app.api.routes.health import health


class HealthTests(unittest.TestCase):
    @patch("backend.app.api.routes.health.rag.indexed_chunk_count", return_value=1382)
    def test_health_exposes_safe_final_architecture_only(self, _count):
        result = health()
        self.assertEqual(result["embedding_model"], "nvidia/nemotron-3-embed-1b:free")
        self.assertEqual(result["retrieval_mode"], "r2")
        self.assertTrue(result["cross_language_rewrite_enabled"])
        self.assertEqual(result["primary_generator"], "google/gemini-2.5-flash")
        self.assertEqual(result["fallback_generator"], "z-ai/glm-5.2")
        self.assertTrue(result["fallback_enabled"])
        serialized = str(result).lower()
        for secret in ("api_key", "authorization", "bearer", "token"):
            self.assertNotIn(secret, serialized)


if __name__ == "__main__":
    unittest.main()
