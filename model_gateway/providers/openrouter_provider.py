import json
import os
import time
from typing import Dict, Iterable, List, Optional

import requests

from backend.app.services.usage_tracking import (
    estimate_tokens_from_messages,
    estimate_tokens_from_text,
    record_usage_event,
)
from model_gateway.base import Message


class OpenRouterChatProvider:
    name = "openrouter"

    def __init__(self, model: str, api_key: str, base_url: Optional[str] = None):
        self.model = model
        self.api_key = api_key
        self.last_call_metadata: Dict = {}
        self._request_metadata: Dict = {}
        self.base_url = (base_url or os.getenv(
            "OPENROUTER_BASE_URL",
            "https://openrouter.ai/api/v1",
        )).rstrip("/")

    def _url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        site_url = os.getenv("OPENROUTER_SITE_URL") or os.getenv("PUBLIC_BASE_URL")
        app_name = os.getenv("OPENROUTER_APP_NAME", "rag-system")
        if site_url:
            headers["HTTP-Referer"] = site_url
        if app_name:
            headers["X-Title"] = app_name
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
        if "max_output_tokens" in options:
            payload["max_tokens"] = options["max_output_tokens"]
        if "max_tokens" in options:
            payload["max_tokens"] = options["max_tokens"]
        if "reasoning" in options:
            payload["reasoning"] = options["reasoning"]
        if "seed" in options:
            payload["seed"] = options["seed"]
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _post(self, payload: Dict, stream: bool = False, timeout=(10, 180)):
        last_error = None
        retryable_codes = {429, 500, 502, 503, 504, 529}
        request_metadata = {
            "provider_request_count": 0,
            "retry_count": 0,
            "rate_limit_events": 0,
        }
        for attempt in range(4):
            request_metadata["provider_request_count"] += 1
            try:
                response = requests.post(
                    self._url(),
                    headers=self._headers(),
                    json=payload,
                    stream=stream,
                    timeout=timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                if attempt == 3:
                    self._request_metadata = request_metadata
                    raise
                request_metadata["retry_count"] += 1
                time.sleep(0.75 * (attempt + 1))
                continue

            api_error_code = None
            if response.ok and not stream:
                try:
                    error = (response.json() or {}).get("error")
                    if isinstance(error, dict):
                        api_error_code = error.get("code")
                    elif error:
                        api_error_code = 500
                    api_error_code = int(api_error_code) if api_error_code is not None else None
                except (ValueError, TypeError):
                    api_error_code = None

            if response.status_code not in retryable_codes and api_error_code not in retryable_codes:
                response.raise_for_status()
                self._request_metadata = request_metadata
                return response
            last_error = response
            if response.status_code == 429 or api_error_code == 429:
                request_metadata["rate_limit_events"] += 1
            if attempt < 3:
                request_metadata["retry_count"] += 1
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 0.75 * (attempt + 1)
                except ValueError:
                    delay = 0.75 * (attempt + 1)
                time.sleep(min(max(delay, 0.5), 10.0))

        if isinstance(last_error, requests.Response):
            self._request_metadata = request_metadata
            last_error.raise_for_status()
            self._raise_for_api_error(last_error.json())
        self._request_metadata = request_metadata
        raise last_error or RuntimeError("OpenRouter request failed without a response.")

    def _extract_text(self, data: Dict) -> str:
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    def _raise_for_api_error(self, data: Dict):
        error = data.get("error") if isinstance(data, dict) else None
        if error:
            message = error.get("message") if isinstance(error, dict) else str(error)
            code = error.get("code") if isinstance(error, dict) else None
            raise RuntimeError(f"OpenRouter API error{f' {code}' if code else ''}: {message}")

    def _record_success(
        self,
        *,
        messages: List[Message],
        answer: str,
        usage: Optional[Dict],
        response_model: str = None,
        response_id: str = None,
        latency_ms: int,
        stream: bool,
    ):
        usage = usage or {}
        input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or estimate_tokens_from_messages(messages)
        output_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or estimate_tokens_from_text(answer)
        total_tokens = usage.get("total_tokens") or int(input_tokens or 0) + int(output_tokens or 0)
        cost = usage.get("cost") or 0
        self.last_call_metadata = {
            **self._request_metadata,
            "status": "success",
            "model": response_model or self.model,
            "response_id": response_id,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "total_tokens": int(total_tokens or 0),
            "cost_usd": float(cost or 0),
            "latency_ms": latency_ms,
            "stream": stream,
            "usage_source": "openrouter" if usage else "estimated_fallback",
        }
        record_usage_event(
            provider=self.name,
            model=response_model or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=cost,
            latency_ms=latency_ms,
            status="success",
            metadata={
                "response_id": response_id,
                "usage_source": "openrouter" if usage else "estimated_fallback",
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
        self.last_call_metadata = {
            **self._request_metadata,
            "status": "error",
            "model": self.model,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "total_tokens": int(input_tokens + output_tokens),
            "cost_usd": 0.0,
            "latency_ms": latency_ms,
            "stream": stream,
            "error_type": error_type,
            "usage_source": "estimated_after_error",
        }
        record_usage_event(
            provider=self.name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
            status="error",
            error_type=error_type,
            metadata={"usage_source": "estimated_after_error", "stream": stream},
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
            self._raise_for_api_error(data)
            answer = self._extract_text(data)
            self._record_success(
                messages=messages,
                answer=answer,
                usage=data.get("usage"),
                response_model=data.get("model"),
                response_id=data.get("id"),
                latency_ms=round((time.perf_counter() - start) * 1000),
                stream=False,
            )
            return answer
        except Exception as exc:
            self._record_error(
                messages=messages,
                latency_ms=round((time.perf_counter() - start) * 1000),
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
        try:
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
                raw_data = line.removeprefix("data:").strip()
                if raw_data == "[DONE]":
                    break
                data = json.loads(raw_data)
                self._raise_for_api_error(data)
                response_model = data.get("model") or response_model
                response_id = data.get("id") or response_id
                if data.get("usage"):
                    usage = data["usage"]
                delta = ((data.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if delta:
                    answer_parts.append(delta)
                    yield delta

            self._record_success(
                messages=messages,
                answer="".join(answer_parts),
                usage=usage,
                response_model=response_model,
                response_id=response_id,
                latency_ms=round((time.perf_counter() - start) * 1000),
                stream=True,
            )
        except Exception as exc:
            self._record_error(
                messages=messages,
                answer="".join(answer_parts),
                latency_ms=round((time.perf_counter() - start) * 1000),
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
