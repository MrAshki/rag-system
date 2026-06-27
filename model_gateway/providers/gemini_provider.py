import json
import os
import time
from typing import Dict, Iterable, List, Optional

import requests

from model_gateway.base import Message


class GeminiChatProvider:
    name = "gemini"

    def __init__(self, model: str, api_key: str, base_url: Optional[str] = None):
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or os.getenv(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        )).rstrip("/")

    def _url(self, method: str) -> str:
        return f"{self.base_url}/models/{self.model}:{method}"

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

    def _payload(
        self,
        messages: List[Message],
        options: Optional[Dict] = None,
        response_format: Optional[str] = None,
    ) -> Dict:
        system_parts = []
        contents = []
        for message in messages:
            role = message.get("role")
            content = (message.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                system_parts.append({"text": content})
            else:
                contents.append({
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": content}],
                })

        generation_config = {}
        options = options or {}
        if "temperature" in options:
            generation_config["temperature"] = options["temperature"]
        if response_format == "json":
            generation_config["responseMimeType"] = "application/json"

        payload = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        if generation_config:
            payload["generationConfig"] = generation_config
        return payload

    def _extract_text(self, data: Dict) -> str:
        texts = []
        for candidate in data.get("candidates") or []:
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                text = part.get("text")
                if text:
                    texts.append(text)
        return "".join(texts)

    def _post(self, method: str, *, params=None, payload=None, stream: bool = False, timeout=(10, 180)):
        last_error = None
        for attempt in range(3):
            response = requests.post(
                self._url(method),
                params=params,
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
            "generateContent",
            payload=self._payload(messages, options, response_format),
            timeout=(10, 180),
        )
        return self._extract_text(response.json())

    def stream_chat(
        self,
        messages: List[Message],
        options: Optional[Dict] = None,
    ) -> Iterable[str]:
        response = self._post(
            "streamGenerateContent",
            params={"alt": "sse"},
            payload=self._payload(messages, options),
            stream=True,
            timeout=(10, 300),
        )
        response.encoding = "utf-8"

        data_lines = []
        for raw_line in response.iter_lines(decode_unicode=True):
            line = (raw_line or "").strip()
            if not line:
                if data_lines:
                    data = "".join(data_lines).strip()
                    data_lines = []
                    if data and data != "[DONE]":
                        delta = self._extract_text(json.loads(data))
                        if delta:
                            yield delta
                continue

            if line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
            elif data_lines:
                data_lines.append(line)

        if data_lines:
            data = "".join(data_lines).strip()
            if data and data != "[DONE]":
                delta = self._extract_text(json.loads(data))
                if delta:
                    yield delta

    def health(self) -> Dict:
        return {
            "provider": self.name,
            "model": self.model,
        }
