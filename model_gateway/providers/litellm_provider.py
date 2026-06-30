import json
import os
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional

import requests

from backend.app.services.usage_tracking import (
    current_usage_context,
    estimate_tokens_from_messages,
    estimate_tokens_from_text,
    record_usage_event,
)
from model_gateway.base import Message


class LiteLLMChatProvider:
    name = "litellm"

    def __init__(self, model: str, api_key: str, base_url: Optional[str] = None):
        self.model = model
        self.api_key = api_key
        raw_base_url = (base_url or os.getenv("LITELLM_BASE_URL") or "http://localhost:4000").rstrip("/")
        self.base_url = raw_base_url if raw_base_url.endswith("/v1") else f"{raw_base_url}/v1"

    def _url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        context = current_usage_context()
        if context.get("user_id") is not None:
            headers["x-litellm-end-user-id"] = str(context["user_id"])
        if context.get("feature"):
            headers["x-litellm-tags"] = f"feature:{context['feature']}"
        metadata = {
            key: value
            for key, value in {
                "request_id": context.get("request_id"),
                "user_id": context.get("user_id"),
                "conversation_id": context.get("conversation_id"),
                "message_id": context.get("message_id"),
                "feature": context.get("feature"),
                "operation_type": context.get("operation_type"),
            }.items()
            if value is not None
        }
        if metadata:
            headers["x-litellm-spend-logs-metadata"] = json.dumps(metadata, ensure_ascii=True)
        return headers

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
        if stream:
            payload["stream_options"] = {"include_usage": True}
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

    def _extract_text(self, data: Dict) -> str:
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    def _cost_from_headers(self, headers) -> Decimal:
        raw = headers.get("x-litellm-response-cost") or headers.get("X-LiteLLM-Response-Cost")
        if raw is None:
            return Decimal("0")
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    def _record_success(
        self,
        *,
        messages: List[Message],
        answer: str,
        usage: Optional[Dict],
        response_headers,
        response_model: str = None,
        response_id: str = None,
        latency_ms: int,
        stream: bool,
    ):
        usage = usage or {}
        input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
        output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
        if input_tokens is None:
            input_tokens = estimate_tokens_from_messages(messages)
        if output_tokens is None:
            output_tokens = estimate_tokens_from_text(answer)
        total_tokens = usage.get("total_tokens") or int(input_tokens or 0) + int(output_tokens or 0)
        usage_source = "litellm" if usage else "estimated_fallback"
        record_usage_event(
            provider=self.name,
            model=response_model or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=self._cost_from_headers(response_headers),
            latency_ms=latency_ms,
            status="success",
            metadata={
                "route_alias": self.model,
                "litellm_response_id": response_id,
                "usage_source": usage_source,
                "stream": stream,
            },
        )

    def _record_error(
        self,
        *,
        messages: List[Message],
        answer: str = "",
        latency_ms: int,
        error_type: str,
        stream: bool,
    ):
        input_tokens = estimate_tokens_from_messages(messages)
        output_tokens = estimate_tokens_from_text(answer)
        record_usage_event(
            provider=self.name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
            status="error",
            error_type=error_type,
            metadata={
                "route_alias": self.model,
                "usage_source": "estimated_after_error",
                "stream": stream,
            },
        )

    def chat(
        self,
        messages: List[Message],
        options: Optional[Dict] = None,
        response_format: Optional[str] = None,
    ) -> str:
        start = time.perf_counter()
        try:
            response = self._post(
                self._payload(messages, options, response_format, stream=False),
                timeout=(10, 180),
            )
            data = response.json()
            answer = self._extract_text(data)
            latency_ms = round((time.perf_counter() - start) * 1000)
            self._record_success(
                messages=messages,
                answer=answer,
                usage=data.get("usage"),
                response_headers=response.headers,
                response_model=data.get("model"),
                response_id=data.get("id"),
                latency_ms=latency_ms,
                stream=False,
            )
            return answer
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000)
            self._record_error(
                messages=messages,
                latency_ms=latency_ms,
                error_type=exc.__class__.__name__,
                stream=False,
            )
            raise

    def stream_chat(
        self,
        messages: List[Message],
        options: Optional[Dict] = None,
    ) -> Iterable[str]:
        start = time.perf_counter()
        answer_parts = []
        usage = None
        response_model = None
        response_id = None
        response_headers = {}
        try:
            response = self._post(
                self._payload(messages, options, stream=True),
                stream=True,
                timeout=(10, 300),
            )
            response_headers = response.headers
            response.encoding = "utf-8"

            for raw_line in response.iter_lines(decode_unicode=True):
                line = (raw_line or "").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                response_model = chunk.get("model") or response_model
                response_id = chunk.get("id") or response_id
                if chunk.get("usage"):
                    usage = chunk["usage"]
                delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if delta:
                    answer_parts.append(delta)
                    yield delta

            latency_ms = round((time.perf_counter() - start) * 1000)
            self._record_success(
                messages=messages,
                answer="".join(answer_parts),
                usage=usage,
                response_headers=response_headers,
                response_model=response_model,
                response_id=response_id,
                latency_ms=latency_ms,
                stream=True,
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000)
            self._record_error(
                messages=messages,
                answer="".join(answer_parts),
                latency_ms=latency_ms,
                error_type=exc.__class__.__name__,
                stream=True,
            )
            raise

    def health(self) -> Dict:
        return {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
        }
