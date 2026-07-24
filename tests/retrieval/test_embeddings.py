import unittest
from unittest.mock import Mock, patch

from backend.app.vector import embeddings


class OpenRouterEmbeddingTests(unittest.TestCase):
    def test_openrouter_inputs_are_split_into_bounded_batches(self):
        texts = [f"text-{index}" for index in range(130)]

        def fake_embed(batch, input_type):
            self.assertEqual(input_type, "passage")
            return [[float(index)] for index, _text in enumerate(batch)]

        with patch.object(embeddings, "OPENROUTER_EMBED_BATCH_SIZE", 64), patch.object(
            embeddings,
            "_embed_texts_openrouter",
            side_effect=fake_embed,
        ) as mocked:
            result = embeddings.embed_texts(texts)

        self.assertEqual(len(result), 130)
        self.assertEqual([len(call.args[0]) for call in mocked.call_args_list], [64, 64, 2])

    def test_openrouter_error_includes_provider_detail(self):
        response = Mock()
        response.ok = False
        response.status_code = 403
        response.json.return_value = {"error": "Access denied by security policy."}

        with self.assertRaisesRegex(RuntimeError, "Access denied by security policy"):
            embeddings._raise_openrouter_error(response)


if __name__ == "__main__":
    unittest.main()
