import unittest
from unittest.mock import Mock, patch

from model_gateway.providers.openrouter_provider import OpenRouterChatProvider


class OpenRouterProviderTests(unittest.TestCase):
    def test_retries_retryable_error_inside_http_200_response(self):
        api_error = Mock(ok=True, status_code=200, headers={})
        api_error.json.return_value = {"error": {"code": 500, "message": "temporary"}}
        success = Mock(ok=True, status_code=200, headers={})
        success.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        provider = OpenRouterChatProvider("test-model", "test-key")

        with patch(
            "model_gateway.providers.openrouter_provider.requests.post",
            side_effect=[api_error, success],
        ) as post, patch("model_gateway.providers.openrouter_provider.time.sleep"):
            response = provider._post({"messages": []})

        self.assertIs(response, success)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(provider._request_metadata["provider_request_count"], 2)
        self.assertEqual(provider._request_metadata["retry_count"], 1)

    def test_payload_forwards_non_thinking_and_seed_options(self):
        provider = OpenRouterChatProvider("test-model", "test-key")

        payload = provider._payload(
            [{"role": "user", "content": "test"}],
            options={"reasoning": {"effort": "none"}, "seed": 7},
        )

        self.assertEqual(payload["reasoning"], {"effort": "none"})
        self.assertEqual(payload["seed"], 7)


if __name__ == "__main__":
    unittest.main()
