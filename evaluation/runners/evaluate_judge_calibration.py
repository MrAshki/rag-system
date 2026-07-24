from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LABELS = (
    "answer_correctness",
    "faithfulness",
    "relevance",
    "citation_support",
    "refusal_correctness",
)
RUBRIC_VERSION = "goal3_composite_v1"
DEFAULT_MODEL = "openai/gpt-4.1-mini"


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def classification_stats(expected: list[bool], predicted: list[bool]) -> dict:
    tp = sum(e and p for e, p in zip(expected, predicted))
    tn = sum(not e and not p for e, p in zip(expected, predicted))
    fp = sum(not e and p for e, p in zip(expected, predicted))
    fn = sum(e and not p for e, p in zip(expected, predicted))
    accuracy = (tp + tn) / max(len(expected), 1)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    return {
        "accuracy": round(accuracy, 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
    }


def cohens_kappa(expected: list[bool], predicted: list[bool]) -> float:
    total = max(len(expected), 1)
    agreement = sum(e == p for e, p in zip(expected, predicted)) / total
    expected_yes = sum(expected) / total
    predicted_yes = sum(predicted) / total
    chance = expected_yes * predicted_yes + (1 - expected_yes) * (1 - predicted_yes)
    return round((agreement - chance) / max(1 - chance, 1e-12), 6)


def fetch_generation_cost(request_id: str, api_key: str) -> float | None:
    import requests

    for attempt in range(3):
        response = requests.get(
            "https://openrouter.ai/api/v1/generation",
            params={"id": request_id},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )
        if response.ok:
            data = response.json().get("data") or {}
            value = data.get("total_cost")
            return float(value) if value is not None else None
        if response.status_code != 404 or attempt == 2:
            return None
        time.sleep(1 + attempt)
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "evaluation" / "judge_calibration" / "cases.jsonl",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    load_dotenv(ROOT / ".env", override=False, encoding="utf-8-sig")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is unavailable")

    from deepeval.metrics import BaseMetric
    from deepeval.test_case import LLMTestCase
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    usage_rows: list[dict] = []

    class CompositeCalibrationMetric(BaseMetric):
        threshold = 0.8
        async_mode = False
        evaluation_model = args.model
        include_reason = True

        @property
        def __name__(self):
            return "Goal3CompositeCalibration"

        def measure(self, test_case: LLMTestCase, *unused_args, **unused_kwargs) -> float:
            payload = json.loads(test_case.additional_metadata["calibration_payload"])
            system = (
                "You are a strict multilingual RAG evaluator. Judge five independent boolean dimensions. "
                "Wrong numbers, wrong entities, contradictions, unsupported claims, false refusals, and wrong "
                "citation pages must fail their applicable dimension. A false refusal must not be rewarded for "
                "faithfulness. Citation support is true only when the cited physical pages equal/support the claim; "
                "for a correct refusal with no citation, it may be true when the evidence explicitly establishes "
                "absence. Return JSON only with booleans for answer_correctness, faithfulness, relevance, "
                "citation_support, refusal_correctness and one concise reason (no chain of thought)."
            )
            response = client.chat.completions.create(
                model=args.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
                seed=17,
                max_tokens=350,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            verdict = json.loads(raw)
            predicted = {name: bool(verdict.get(name)) for name in LABELS}
            self.score_breakdown = predicted
            self.score = sum(predicted.values()) / len(LABELS)
            self.reason = str(verdict.get("reason") or "")[:500]
            self.success = self.score >= self.threshold
            usage = response.usage
            usage_rows.append({
                "case_id": test_case.name,
                "request_id": response.id,
                "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            })
            return self.score

        async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
            return await asyncio.to_thread(self.measure, test_case, *args, **kwargs)

        def is_successful(self) -> bool:
            return bool(self.success)

    cases = load_cases(args.cases)
    results = []
    for case in cases:
        judge_payload = {
            key: case[key]
            for key in (
                "query", "reference_answer", "actual_answer", "evidence",
                "citation_pages", "expected_pages",
            )
        }
        test_case = LLMTestCase(
            name=case["case_id"],
            input=case["query"],
            actual_output=case["actual_answer"],
            expected_output=case["reference_answer"],
            retrieval_context=case["evidence"],
            additional_metadata={
                "calibration_payload": json.dumps(judge_payload, ensure_ascii=False),
            },
        )
        metric = CompositeCalibrationMetric()
        metric.measure(test_case)
        results.append({
            "case_id": case["case_id"],
            "human_labels": case["human_labels"],
            "judge_labels": metric.score_breakdown,
            "agreement": {
                name: bool(case["human_labels"][name]) == bool(metric.score_breakdown[name])
                for name in LABELS
            },
            "score": metric.score,
            "reason": metric.reason,
        })
    for row in usage_rows:
        row["cost_usd"] = fetch_generation_cost(row["request_id"], api_key)

    per_label = {}
    flat_expected = []
    flat_predicted = []
    for name in LABELS:
        expected = [bool(row["human_labels"][name]) for row in results]
        predicted = [bool(row["judge_labels"][name]) for row in results]
        per_label[name] = classification_stats(expected, predicted)
        per_label[name]["cohens_kappa"] = cohens_kappa(expected, predicted)
        flat_expected.extend(expected)
        flat_predicted.extend(predicted)
    overall = classification_stats(flat_expected, flat_predicted)
    overall["cohens_kappa"] = cohens_kappa(flat_expected, flat_predicted)
    report = {
        "framework": "DeepEval",
        "framework_version": "4.1.3",
        "model": args.model,
        "rubric_version": RUBRIC_VERSION,
        "temperature": 0,
        "seed": 17,
        "case_count": len(cases),
        "dimensions": list(LABELS),
        "per_dimension": per_label,
        "overall": overall,
        "release_supporting": overall["accuracy"] >= 0.80,
        "usage": {
            "provider_request_count": len(usage_rows),
            "input_tokens": sum(row["input_tokens"] for row in usage_rows),
            "output_tokens": sum(row["output_tokens"] for row in usage_rows),
            "cost_usd": round(sum(float(row.get("cost_usd") or 0) for row in usage_rows), 8),
            "requests": usage_rows,
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "framework": report["framework"],
        "case_count": report["case_count"],
        "overall": report["overall"],
        "release_supporting": report["release_supporting"],
        "usage": {
            key: report["usage"][key]
            for key in ("provider_request_count", "input_tokens", "output_tokens")
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
