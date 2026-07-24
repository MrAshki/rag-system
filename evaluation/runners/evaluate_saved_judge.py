"""Judge saved production outcomes without re-running the RAG endpoint.

This is the calibrated DeepEval diagnostic layer for Goal 3.  ``prepare`` is
fully local: it joins unchanged Gold Set expectations to saved endpoint
responses and extracts only the cited/expected physical PDF pages. ``run``
performs one bounded judge request per saved outcome and writes an auditable
cost/report ledger.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
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
MODEL = "openai/gpt-4.1-mini"
RUBRIC_VERSION = "goal3_composite_v1"
MAX_EVIDENCE_CHARS = 14_000


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _gold_cases(kind: str) -> dict[str, dict]:
    from evaluation.runners import evaluate_goal3_expanded as expanded
    from evaluation.runners import evaluate_production_baseline as baseline

    cases = baseline._cases() if kind == "production15" else expanded._cases()
    return {case["query_id"]: case for case in cases}


def _pdf_evidence(filename: str, pages: list[int]) -> list[str]:
    from pypdf import PdfReader

    path = ROOT / "composite_goldset_pdfs" / filename
    if not path.exists():
        return []
    reader = PdfReader(str(path))
    evidence: list[str] = []
    remaining = MAX_EVIDENCE_CHARS
    for page_number in sorted({int(page) for page in pages if int(page) > 0}):
        if page_number > len(reader.pages) or remaining <= 0:
            continue
        text = (reader.pages[page_number - 1].extract_text() or "").strip()
        block = f"[physical page {page_number}]\n{text}"
        block = block[:remaining]
        evidence.append(block)
        remaining -= len(block)
    return evidence


def prepare(kind: str, report_path: Path, output: Path) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    gold = _gold_cases(kind)
    cases = []
    for result in report["results"]:
        task = gold[result["query_id"]]
        expected_pages = [
            int(page)
            for page in (
                task.get("relevant_pages")
                or task.get("expected_pages")
                or []
            )
            if str(page).isdigit()
        ]
        cited_pages = [int(page) for page in result.get("cited_pages", [])]
        evidence_pages = cited_pages + expected_pages
        reference_parts = list(task.get("acceptable_answers", []))
        if task.get("required_key_claims"):
            reference_parts.append(
                "Required summary claims: "
                + "; ".join(task["required_key_claims"])
            )
        if task.get("required_sections"):
            reference_parts.append(
                "Required summary sections: "
                + "; ".join(task["required_sections"])
            )
        cases.append({
            "case_id": result["query_id"],
            "task_type": task.get("task_type"),
            "answerability": task.get("answerability"),
            "query": task["query"],
            "reference_answer": "\n".join(reference_parts),
            "required_concepts": task.get("required_concepts", []),
            "actual_answer": result["answer"],
            "evidence": _pdf_evidence(result["filename"], evidence_pages),
            "citation_pages": cited_pages,
            "expected_pages": expected_pages,
            "deterministic": {
                "answer_correct": result["answer_correct"],
                "citation_page_correct": result["citation_page_correct"],
                "citation_valid": result["citation_valid"],
                "grounded_task_success": bool(
                    result["route_correct"]
                    and result["answer_correct"]
                    and result["citations_correct"]
                    and result["output_complete"]
                ),
            },
        })
    _write(output, {
        "kind": kind,
        "source_report": str(report_path),
        "framework": "DeepEval",
        "framework_version": "4.1.3",
        "judge_model": MODEL,
        "rubric_version": RUBRIC_VERSION,
        "case_count": len(cases),
        "estimated_provider_requests": len(cases),
        "estimated_input_tokens": sum(
            len(json.dumps(case, ensure_ascii=False)) // 3 for case in cases
        ),
        "estimated_output_tokens": len(cases) * 220,
        "projected_cost_usd": round(len(cases) * 0.0035, 6),
        "cases": cases,
    })
    print(json.dumps({
        "prepared": len(cases),
        "output": str(output),
        "projected_cost_usd": round(len(cases) * 0.0035, 6),
    }, indent=2))


def _bootstrap_interval(values: list[float]) -> dict[str, float]:
    if not values:
        return {"low": 0.0, "high": 0.0}
    # Exact percentile bootstrap with a fixed local PRNG; no provider calls.
    import random

    rng = random.Random(17)
    means = []
    for _ in range(2_000):
        means.append(statistics.mean(rng.choice(values) for _ in values))
    means.sort()
    return {
        "low": round(means[int(0.025 * len(means))], 6),
        "high": round(means[int(0.975 * len(means)) - 1], 6),
    }


def _fetch_cost(request_id: str, api_key: str) -> float | None:
    import requests

    for attempt in range(3):
        response = requests.get(
            "https://openrouter.ai/api/v1/generation",
            params={"id": request_id},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )
        if response.ok:
            value = (response.json().get("data") or {}).get("total_cost")
            return float(value) if value is not None else None
        if response.status_code != 404 or attempt == 2:
            return None
        time.sleep(1 + attempt)
    return None


def run(prepared_path: Path, output: Path) -> None:
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    load_dotenv(ROOT / ".env", override=False, encoding="utf-8-sig")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is unavailable")

    from deepeval.metrics import BaseMetric
    from deepeval.test_case import LLMTestCase
    from openai import OpenAI

    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    usage_rows: list[dict] = []

    class SavedOutcomeMetric(BaseMetric):
        threshold = 0.8
        async_mode = False
        evaluation_model = MODEL
        include_reason = True

        @property
        def __name__(self):
            return "Goal3SavedOutcome"

        def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
            payload = json.loads(test_case.additional_metadata["payload"])
            system = (
                "You are a strict multilingual RAG evaluator. Judge five independent boolean dimensions. "
                "Use the reference as requirements, not as required wording. Correct paraphrases pass. Wrong "
                "numbers, entities, contradictions, unsupported claims, false refusals, and wrong physical "
                "citation pages fail their applicable dimension. Faithfulness means all material claims are "
                "supported by the supplied physical-page evidence. Citation support requires cited pages to "
                "equal/support the expected claim; absence of a citation fails it when citations are expected. "
                "For an unanswerable task, refusal_correctness is true only for a topic-specific refusal that "
                "does not invent an answer. For answerable tasks it is true only when there is no false refusal. "
                "Return JSON only with booleans for answer_correctness, faithfulness, relevance, "
                "citation_support, refusal_correctness and one concise reason; no chain of thought."
            )
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
                seed=17,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            verdict = json.loads(response.choices[0].message.content or "{}")
            self.score_breakdown = {
                name: bool(verdict.get(name)) for name in LABELS
            }
            self.score = sum(self.score_breakdown.values()) / len(LABELS)
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

        async def a_measure(self, test_case: LLMTestCase, *args, **kwargs):
            return await asyncio.to_thread(self.measure, test_case, *args, **kwargs)

        def is_successful(self) -> bool:
            return bool(self.success)

    results = []
    for case in prepared["cases"]:
        payload = {
            key: case[key]
            for key in (
                "task_type", "answerability", "query", "reference_answer",
                "required_concepts", "actual_answer", "evidence",
                "citation_pages", "expected_pages",
            )
        }
        test_case = LLMTestCase(
            name=case["case_id"],
            input=case["query"],
            actual_output=case["actual_answer"],
            expected_output=case["reference_answer"],
            retrieval_context=case["evidence"],
            additional_metadata={"payload": json.dumps(payload, ensure_ascii=False)},
        )
        metric = SavedOutcomeMetric()
        metric.measure(test_case)
        results.append({
            "case_id": case["case_id"],
            "task_type": case["task_type"],
            "judge_labels": metric.score_breakdown,
            "score": metric.score,
            "pass": metric.is_successful(),
            "reason": metric.reason,
            "deterministic": case["deterministic"],
        })
    for row in usage_rows:
        row["cost_usd"] = _fetch_cost(row["request_id"], api_key)

    dimensions = {}
    for name in LABELS:
        values = [float(row["judge_labels"][name]) for row in results]
        dimensions[name] = {
            "mean": round(statistics.mean(values), 6),
            "pass_count": sum(values),
            "count": len(values),
            "bootstrap_95": _bootstrap_interval(values),
        }
    disagreements = {
        "answer_correctness": [
            row["case_id"] for row in results
            if row["judge_labels"]["answer_correctness"]
            != row["deterministic"]["answer_correct"]
        ],
        "citation_support": [
            row["case_id"] for row in results
            if row["judge_labels"]["citation_support"]
            != row["deterministic"]["citation_page_correct"]
        ],
    }
    report = {
        "framework": "DeepEval",
        "framework_version": "4.1.3",
        "judge_model": MODEL,
        "rubric_version": RUBRIC_VERSION,
        "temperature": 0,
        "seed": 17,
        "kind": prepared["kind"],
        "task_count": len(results),
        "pass_threshold": 0.8,
        "dimensions": dimensions,
        "score_distribution": dict(Counter(str(row["score"]) for row in results)),
        "mean_composite_score": round(
            statistics.mean(row["score"] for row in results), 6
        ),
        "composite_bootstrap_95": _bootstrap_interval(
            [row["score"] for row in results]
        ),
        "pass_count": sum(row["pass"] for row in results),
        "disagreements": disagreements,
        "usage": {
            "provider_request_count": len(usage_rows),
            "input_tokens": sum(row["input_tokens"] for row in usage_rows),
            "output_tokens": sum(row["output_tokens"] for row in usage_rows),
            "cost_usd": round(
                sum(float(row.get("cost_usd") or 0) for row in usage_rows), 8
            ),
            "requests": usage_rows,
        },
        "results": results,
    }
    _write(output, report)
    print(json.dumps({
        "task_count": report["task_count"],
        "mean_composite_score": report["mean_composite_score"],
        "pass_count": report["pass_count"],
        "dimensions": report["dimensions"],
        "usage": {
            key: report["usage"][key]
            for key in (
                "provider_request_count", "input_tokens", "output_tokens",
                "cost_usd",
            )
        },
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument(
        "--kind", choices=("production15", "expanded"), required=True
    )
    prepare_parser.add_argument("--report", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--prepared", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.kind, args.report, args.output)
    else:
        run(args.prepared, args.output)


if __name__ == "__main__":
    main()
