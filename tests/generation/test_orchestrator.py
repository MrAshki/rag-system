import json
import unittest
from unittest.mock import Mock

import requests

from backend.app.generation import (
    GenerationPayload,
    GenerationUnavailableError,
    GroundedGenerationOrchestrator,
)
from backend.app.grounding import grounded_contract_error


VALID = json.dumps({
    "answerable": True,
    "paragraphs": [{"text": "Grounded answer.", "evidence_ids": ["E1"]}],
})
NO_ANSWER = json.dumps({"answerable": False, "paragraphs": [], "message": "No evidence."})


class FakeProvider:
    name = "openrouter"

    def __init__(self, model, *responses):
        self.model = model
        self.responses = list(responses)
        self.calls = []
        self.last_call_metadata = {}

    def chat(self, messages, options=None, response_format=None):
        self.calls.append({
            "messages": messages,
            "options": options,
            "response_format": response_format,
        })
        response = self.responses.pop(0)
        self.last_call_metadata = {
            "input_tokens": 10,
            "output_tokens": 4,
            "cost_usd": 0.001,
            "latency_ms": 5,
        }
        if isinstance(response, Exception):
            raise response
        return response


def payload():
    return GenerationPayload.build(
        question="What?",
        messages=[{"role": "system", "content": "Grounded"}, {"role": "user", "content": "Q"}],
        evidence=[{"text": "Evidence", "source": "a.pdf", "page": 1}],
        answer_language="en",
        answerability_policy="evidence_only",
        citation_policy="paragraph_end",
        rewrite_used=True,
    )


def parse(raw):
    return json.loads(raw)


class GenerationOrchestratorTests(unittest.TestCase):
    def make(self, primary_response, fallback_response=VALID):
        self.primary = FakeProvider("google/gemini-2.5-flash", primary_response)
        self.fallback = FakeProvider("z-ai/glm-5.2", fallback_response)
        self.record = Mock()
        return GroundedGenerationOrchestrator(
            primary_provider=self.primary,
            fallback_provider=self.fallback,
            primary_model=self.primary.model,
            fallback_model=self.fallback.model,
            fallback_enabled=True,
            max_attempts=2,
            telemetry_recorder=self.record,
        )

    @staticmethod
    def invoke(orchestrator, value=None):
        value = value or payload()
        return orchestrator.generate(
            payload=value,
            contract_error=lambda raw: grounded_contract_error(raw, evidence_count=1),
            parse_response=parse,
        )

    def test_primary_success_does_not_call_glm(self):
        result, telemetry = self.invoke(self.make(VALID))
        self.assertTrue(result["answerable"])
        self.assertFalse(telemetry["fallback_used"])
        self.assertEqual(len(self.fallback.calls), 0)

    def test_primary_timeout_reuses_exact_context_for_glm(self):
        orchestrator = self.make(requests.Timeout("timeout"))
        result, telemetry = self.invoke(orchestrator)
        self.assertTrue(result["answerable"])
        self.assertEqual(self.primary.calls[0]["messages"], self.fallback.calls[0]["messages"])
        self.assertEqual(telemetry["fallback_reason"], "primary_timeout")

    def test_retryable_provider_error_calls_glm_once(self):
        orchestrator = self.make(RuntimeError("retryable provider error 503"))
        _result, telemetry = self.invoke(orchestrator)
        self.assertEqual(len(self.fallback.calls), 1)
        self.assertEqual(telemetry["fallback_reason"], "retryable_provider_error")

    def test_invalid_json_calls_glm_once(self):
        orchestrator = self.make("not-json")
        _result, telemetry = self.invoke(orchestrator)
        self.assertEqual(len(self.fallback.calls), 1)
        self.assertEqual(telemetry["fallback_reason"], "invalid_json")

    def test_schema_invalid_output_calls_glm_once(self):
        orchestrator = self.make(json.dumps({"answerable": True, "paragraphs": []}))
        _result, telemetry = self.invoke(orchestrator)
        self.assertEqual(len(self.fallback.calls), 1)
        self.assertEqual(telemetry["fallback_reason"], "schema_validation_failure")

    def test_structured_parser_failure_calls_glm_once(self):
        orchestrator = self.make(VALID)
        calls = 0

        def flaky_parse(raw):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ValueError("parser failed")
            return json.loads(raw)

        result, telemetry = orchestrator.generate(
            payload=payload(),
            contract_error=lambda raw: grounded_contract_error(raw, evidence_count=1),
            parse_response=flaky_parse,
        )
        self.assertTrue(result["answerable"])
        self.assertEqual(len(self.fallback.calls), 1)
        self.assertEqual(telemetry["fallback_reason"], "structured_output_parsing_failure")

    def test_valid_no_answer_does_not_call_glm(self):
        result, telemetry = self.invoke(self.make(NO_ANSWER))
        self.assertFalse(result["answerable"])
        self.assertFalse(telemetry["fallback_used"])
        self.assertEqual(len(self.fallback.calls), 0)

    def test_valid_grounded_answer_does_not_call_glm(self):
        _result, telemetry = self.invoke(self.make(VALID))
        self.assertTrue(telemetry["primary_success"])
        self.assertIsNone(telemetry["fallback_success"])

    def test_glm_fallback_success_is_returned(self):
        fallback = json.dumps({
            "answerable": True,
            "paragraphs": [{"text": "GLM answer.", "evidence_ids": ["E1"]}],
        })
        result, telemetry = self.invoke(self.make("bad-json", fallback))
        self.assertEqual(result["paragraphs"][0]["text"], "GLM answer.")
        self.assertEqual(telemetry["model_used"], "z-ai/glm-5.2")

    def test_glm_failure_returns_controlled_error(self):
        orchestrator = self.make("bad-json", "also-bad")
        with self.assertRaises(GenerationUnavailableError) as caught:
            self.invoke(orchestrator)
        self.assertEqual(caught.exception.reason, "fallback_generation_failure")

    def test_no_fallback_loop_is_possible(self):
        orchestrator = self.make("bad-json", "also-bad")
        with self.assertRaises(GenerationUnavailableError):
            self.invoke(orchestrator)
        self.assertEqual(len(self.primary.calls), 1)
        self.assertEqual(len(self.fallback.calls), 1)

    def test_context_hash_is_identical_for_primary_and_fallback(self):
        value = payload()
        orchestrator = self.make("bad-json")
        _result, telemetry = self.invoke(orchestrator, value)
        self.assertEqual(telemetry["context_hash"], value.context_hash)
        self.assertEqual(self.primary.calls[0]["messages"], self.fallback.calls[0]["messages"])

    def test_prompt_hash_is_identical_for_primary_and_fallback(self):
        value = payload()
        orchestrator = self.make("bad-json")
        _result, telemetry = self.invoke(orchestrator, value)
        primary_json = json.dumps(self.primary.calls[0]["messages"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fallback_json = json.dumps(self.fallback.calls[0]["messages"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(primary_json, fallback_json)
        self.assertEqual(telemetry["prompt_hash"], value.prompt_hash)

    def test_generator_fallback_does_not_repeat_retrieval(self):
        retrieve = Mock(return_value=payload())
        value = retrieve()
        self.invoke(self.make("bad-json"), value)
        retrieve.assert_called_once_with()

    def test_telemetry_records_selected_model_and_reason(self):
        orchestrator = self.make("bad-json")
        _result, telemetry = self.invoke(orchestrator)
        self.assertEqual(telemetry["model_used"], "z-ai/glm-5.2")
        self.assertEqual(telemetry["fallback_reason"], "invalid_json")
        metadata = self.record.call_args.kwargs["metadata"]
        self.assertNotIn("final_context", metadata)
        self.assertNotIn("evidence", metadata)


if __name__ == "__main__":
    unittest.main()
