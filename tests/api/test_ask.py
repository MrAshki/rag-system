import unittest
from unittest.mock import patch

from backend.app.api.routes.ask import _prepare_ask


class AskRouteTests(unittest.TestCase):
    @patch(
        "backend.app.api.routes.ask.selected_assets_from_payload",
        return_value=(["asset-1"], ["sample.pdf"], None),
    )
    def test_grounded_route_ignores_client_model_selection(self, _selected_assets):
        payload, error = _prepare_ask(
            {"id": 7},
            {
                "question": "Summarize this document",
                "asset_ids": ["asset-1"],
                "chat_provider": "untrusted-provider",
                "chat_model": "untrusted-model",
            },
        )

        self.assertIsNone(error)
        self.assertEqual(payload["mode"], "grounded_chat")
        self.assertIsNone(payload["chat_provider"])
        self.assertIsNone(payload["chat_model"])


if __name__ == "__main__":
    unittest.main()
