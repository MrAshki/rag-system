"""Primary/fallback generation over one immutable grounded request payload."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from backend.app.services.usage_tracking import record_usage_event
from model_gateway.base import ChatProvider


RETRYABLE_PROVIDER_CODES = {429, 500, 502, 503, 504, 529}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GenerationPayload:
    question: str
    final_context: str
    context_hash: str
    evidence: tuple[dict[str, Any], ...]
    prompt_hash: str
    answer_language: str
    answerability_policy: str
    citation_policy: str
    rewrite_used: bool = False

    @classmethod
    def build(
        cls,
        *,
        question: str,
        messages: list[dict[str, str]],
        evidence: list[dict[str, Any]],
        answer_language: str,
        answerability_policy: str,
        citation_policy: str,
        rewrite_used: bool = False,
    ) -> "GenerationPayload":
        final_context = _canonical_json(messages)
        frozen_evidence = tuple(dict(item) for item in evidence)
        return cls(
            question=question,
            final_context=final_context,
            context_hash=_sha256(_canonical_json(frozen_evidence)),
            evidence=frozen_evidence,
            prompt_hash=_sha256(final_context),
            answer_language=answer_language,
            answerability_policy=answerability_policy,
            citation_policy=citation_policy,
            rewrite_used=rewrite_used,
        )

    def messages(self) -> list[dict[str, str]]:
        self.verify()
        value = json.loads(self.final_context)
        if not isinstance(value, list):
            raise ValueError("generation payload messages are invalid")
        return value

    def verify(self) -> None:
        if _sha256(self.final_context) != self.prompt_hash:
            raise ValueError("generation prompt hash changed")
        if _sha256(_canonical_json(self.evidence)) != self.context_hash:
            raise ValueError("generation evidence context hash changed")


class GenerationUnavailableError(RuntimeError):
    def __init__(self, reason: str, telemetry: dict[str, Any]):
        super().__init__("Grounded generation is temporarily unavailable.")
        self.reason = reason
        self.telemetry = telemetry


def _provider_metadata(provider: ChatProvider) -> dict[str, Any]:
    value = getattr(provider, "last_call_metadata", {}) or {}
    return dict(value) if isinstance(value, dict) else {}


def _technical_failure_reason(exc: Exception) -> str | None:
    if isinstance(exc, requests.Timeout):
        return "primary_timeout"
    if isinstance(exc, requests.ConnectionError):
        return "primary_connection_failure"
    if isinstance(exc, requests.HTTPError):
        status = getattr(exc.response, "status_code", None)
        if status in RETRYABLE_PROVIDER_CODES or status == 404:
            return "retryable_http_failure"
        return None
    message = str(exc)
    code_match = re.search(r"(?:error|failed)[^0-9]*(429|5\d\d|529)", message, re.IGNORECASE)
    if isinstance(exc, RuntimeError) and (
        code_match
        or "provider unavailable" in message.lower()
        or "retryable provider" in message.lower()
    ):
        return "retryable_provider_error"
    return None


class GroundedGenerationOrchestrator:
    def __init__(
        self,
        *,
        primary_provider: ChatProvider,
        fallback_provider: ChatProvider,
        primary_model: str,
        fallback_model: str,
        fallback_enabled: bool = True,
        max_attempts: int = 2,
        max_output_tokens: int = 900,
        telemetry_recorder: Callable[..., Any] = record_usage_event,
    ):
        if max_attempts not in {1, 2}:
            raise ValueError("max_attempts must be 1 or 2")
        if fallback_enabled and max_attempts != 2:
            raise ValueError("enabled fallback requires max_attempts=2")
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.fallback_enabled = fallback_enabled
        self.max_attempts = max_attempts
        self.max_output_tokens = max_output_tokens
        self.telemetry_recorder = telemetry_recorder
        self.last_telemetry: dict[str, Any] = {}

    def _base_telemetry(self, payload: GenerationPayload) -> dict[str, Any]:
        return {
            "primary_model": self.primary_model,
            "fallback_model": self.fallback_model,
            "model_used": self.primary_model,
            "fallback_used": False,
            "fallback_reason": None,
            "primary_success": False,
            "fallback_success": None,
            "primary_latency_ms": 0,
            "fallback_latency_ms": 0,
            "total_generation_latency_ms": 0,
            "primary_input_tokens": 0,
            "primary_output_tokens": 0,
            "fallback_input_tokens": 0,
            "fallback_output_tokens": 0,
            "primary_cost": 0.0,
            "fallback_cost": 0.0,
            "provider": getattr(self.primary_provider, "name", "unknown"),
            "rewrite_used": payload.rewrite_used,
            "context_hash": payload.context_hash,
            "prompt_hash": payload.prompt_hash,
            "error_category": None,
        }

    @staticmethod
    def _copy_usage(telemetry: dict[str, Any], prefix: str, provider: ChatProvider) -> None:
        metadata = _provider_metadata(provider)
        telemetry[f"{prefix}_input_tokens"] = int(metadata.get("input_tokens") or 0)
        telemetry[f"{prefix}_output_tokens"] = int(metadata.get("output_tokens") or 0)
        telemetry[f"{prefix}_cost"] = float(metadata.get("cost_usd") or 0)
        if metadata.get("latency_ms") is not None:
            telemetry[f"{prefix}_latency_ms"] = int(metadata["latency_ms"])

    def _record(self, telemetry: dict[str, Any], *, status: str) -> None:
        self.last_telemetry = dict(telemetry)
        self.telemetry_recorder(
            feature="chat_grounded",
            operation_type="generation_orchestration",
            provider=telemetry["provider"],
            model=telemetry["model_used"],
            status=status,
            error_type=telemetry.get("error_category"),
            metadata=dict(telemetry),
        )

    def _call(self, provider: ChatProvider, messages: list[dict[str, str]]) -> str:
        return provider.chat(
            messages=messages,
            options={
                "temperature": 0.0,
                "max_tokens": self.max_output_tokens,
                "reasoning": {"effort": "none", "exclude": True},
                "seed": 17,
            },
            response_format="json",
        )

    def generate(
        self,
        *,
        payload: GenerationPayload,
        contract_error: Callable[[str], str | None],
        parse_response: Callable[[str], dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload.verify()
        messages = payload.messages()
        telemetry = self._base_telemetry(payload)
        total_started = time.perf_counter()
        fallback_reason = None

        primary_started = time.perf_counter()
        try:
            raw = self._call(self.primary_provider, messages)
            telemetry["primary_latency_ms"] = round((time.perf_counter() - primary_started) * 1000)
            self._copy_usage(telemetry, "primary", self.primary_provider)
        except Exception as exc:
            telemetry["primary_latency_ms"] = round((time.perf_counter() - primary_started) * 1000)
            self._copy_usage(telemetry, "primary", self.primary_provider)
            fallback_reason = _technical_failure_reason(exc)
            if fallback_reason is None:
                telemetry["error_category"] = "non_retryable_primary_failure"
                telemetry["total_generation_latency_ms"] = round((time.perf_counter() - total_started) * 1000)
                self._record(telemetry, status="error")
                raise GenerationUnavailableError(telemetry["error_category"], telemetry) from exc
        else:
            fallback_reason = contract_error(raw)
            if fallback_reason is None:
                try:
                    result = parse_response(raw)
                except Exception:
                    fallback_reason = "structured_output_parsing_failure"
                else:
                    telemetry["primary_success"] = True
                    telemetry["total_generation_latency_ms"] = round((time.perf_counter() - total_started) * 1000)
                    self._record(telemetry, status="success")
                    return result, telemetry

        if not self.fallback_enabled or self.max_attempts < 2:
            telemetry["error_category"] = fallback_reason or "primary_generation_failure"
            telemetry["total_generation_latency_ms"] = round((time.perf_counter() - total_started) * 1000)
            self._record(telemetry, status="error")
            raise GenerationUnavailableError(telemetry["error_category"], telemetry)

        payload.verify()
        telemetry.update({
            "fallback_used": True,
            "fallback_reason": fallback_reason,
            "model_used": self.fallback_model,
            "provider": getattr(self.fallback_provider, "name", "unknown"),
        })
        fallback_started = time.perf_counter()
        try:
            fallback_raw = self._call(self.fallback_provider, messages)
            telemetry["fallback_latency_ms"] = round((time.perf_counter() - fallback_started) * 1000)
            self._copy_usage(telemetry, "fallback", self.fallback_provider)
            fallback_contract_error = contract_error(fallback_raw)
            if fallback_contract_error is not None:
                raise ValueError(fallback_contract_error)
            result = parse_response(fallback_raw)
            telemetry["fallback_success"] = True
            telemetry["total_generation_latency_ms"] = round((time.perf_counter() - total_started) * 1000)
            self._record(telemetry, status="success")
            return result, telemetry
        except Exception as exc:
            telemetry["fallback_latency_ms"] = round((time.perf_counter() - fallback_started) * 1000)
            self._copy_usage(telemetry, "fallback", self.fallback_provider)
            telemetry["fallback_success"] = False
            telemetry["error_category"] = "fallback_generation_failure"
            telemetry["total_generation_latency_ms"] = round((time.perf_counter() - total_started) * 1000)
            self._record(telemetry, status="error")
            raise GenerationUnavailableError(telemetry["error_category"], telemetry) from exc
