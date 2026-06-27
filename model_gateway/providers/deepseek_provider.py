import json
import os
import time
from typing import Dict, Iterable, List, Optional

import requests

from model_gateway.base import Message


class DeepSeekChatProvider:
    name = "deepseek"

    def __init__(self, model: str, api_key: str, base_url: Optional[str] = None):
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or os.getenv(
            "DEEPSEEK_BASE_URL",
            "https://api.deepseek.com",
        )).rstrip("/")

    def _url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: List[Message],
        options: Optional[Dict] = None,
        response_format: Optional[str] = None,
        stream: bool = False,
    ) -> Dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        options = options or {}
        if "temperature" in options:
            payload["temperature"] = options["temperature"]
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _post(self, payload: Dict, stream: bool = False, timeout=(10, 180)):
        last_error = None
        for attempt in range(3):
            response = requests.post(
                self._url(),
                headers=self._headers(),
                json=payload,
                stream=stream,
                timeout=timeout,
            )
            if response.status_code not in (429, 500, 502, 503, 504):
                response.raise_for_status()
                return response
            last_error = response
            time.sleep(0.75 * (attempt + 1))
        last_error.raise_for_status()
        return last_error

    def chat(
        self,
        messages: List[Message],
        options: Optional[Dict] = None,
        response_format: Optional[str] = None,
    ) -> str:
        response = self._post(
            self._payload(messages, options, response_format, stream=False),
            timeout=(10, 180),
        )
        data = response.json()
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    def stream_chat(
        self,
        messages: List[Message],
        options: Optional[Dict] = None,
    ) -> Iterable[str]:
        response = self._post(
            self._payload(messages, options, stream=True),
            stream=True,
            timeout=(10, 300),
        )
        response.encoding = "utf-8"

        for raw_line in response.iter_lines(decode_unicode=True):
            line = (raw_line or "").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                break
            delta = ((json.loads(data).get("choices") or [{}])[0].get("delta") or {}).get("content")
            if delta:
                yield delta

    def health(self) -> Dict:
        return {
            "provider": self.name,
            "model": self.model,
        }
