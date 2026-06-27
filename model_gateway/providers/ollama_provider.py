from typing import Dict, Iterable, List, Optional

import ollama

from model_gateway.base import Message


class OllamaChatProvider:
    name = "ollama"

    def __init__(self, model: str):
        self.model = model

    def chat(
        self,
        messages: List[Message],
        options: Optional[Dict] = None,
        response_format: Optional[str] = None,
    ) -> str:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "options": options or {},
        }
        if response_format:
            kwargs["format"] = response_format
        response = ollama.chat(**kwargs)
        return (response.get("message") or {}).get("content", "")

    def stream_chat(
        self,
        messages: List[Message],
        options: Optional[Dict] = None,
    ) -> Iterable[str]:
        stream = ollama.chat(
            model=self.model,
            messages=messages,
            options=options or {},
            stream=True,
        )
        for chunk in stream:
            delta = (chunk.get("message") or {}).get("content") or ""
            if delta:
                yield delta

    def health(self) -> Dict:
        return {
            "provider": self.name,
            "model": self.model,
        }
