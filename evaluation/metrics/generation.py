from __future__ import annotations

import re
import unicodedata

from .proportions import proportion_result


GENERIC_FAILURE_RE = re.compile(r"خطا در تولید پاسخ|اعتبارسنجی پاسخ ناموفق|unable to (?:answer|generate)", re.I)
REFUSAL_RE = re.compile(r"اطلاعات کافی|در سند.*نیست|نمی‌توانم پاسخ|insufficient information|cannot answer", re.I)
TRUNCATION_RE = re.compile(r"(?:\.\.\.|…|\[truncated\])\s*$", re.I)


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹كي", "0123456789کی"))
    return " ".join(re.sub(r"[^\w.%]+", " ", text, flags=re.UNICODE).split())


def score_generation(task: dict, answer: str) -> dict:
    normalized = normalize_text(answer)
    acceptable = [normalize_text(item) for item in task.get("acceptable_answers", [])]
    concepts = [normalize_text(item) for item in task.get("required_concepts", [])]
    forbidden = [normalize_text(item) for item in task.get("forbidden_claims", [])]
    concept_hits = [item for item in concepts if item and item in normalized]
    forbidden_hits = [item for item in forbidden if item and item in normalized]
    exact = bool(acceptable and normalized in acceptable)
    acceptable_match = bool(
        normalized
        and acceptable
        and any(item in normalized or normalized in item for item in acceptable)
    )
    refusal = bool(REFUSAL_RE.search(answer or ""))
    return {
        "normalized_answer_match": exact,
        "acceptable_answer_match": acceptable_match,
        "required_concept_coverage": len(concept_hits) / len(concepts) if concepts else 1.0,
        "required_concept_hits": concept_hits,
        "forbidden_claim": bool(forbidden_hits),
        "forbidden_claim_hits": forbidden_hits,
        "generic_failure": bool(GENERIC_FAILURE_RE.search(answer or "")),
        "false_refusal": task.get("answerability") == "answerable" and refusal,
        "answerable_for_false_refusal": task.get("answerability") == "answerable",
        "truncation": bool(TRUNCATION_RE.search(answer or "")),
    }


def aggregate_generation(scored: list[dict]) -> dict:
    count = len(scored)
    answerable = [row for row in scored if row.get("answerable_for_false_refusal")]
    return {
        "normalized_answer_match": proportion_result(sum(row["normalized_answer_match"] for row in scored), count),
        "acceptable_answer_match": proportion_result(sum(row["acceptable_answer_match"] for row in scored), count),
        "required_concept_coverage_mean": sum(row["required_concept_coverage"] for row in scored) / count if count else 0.0,
        "forbidden_claim_rate": proportion_result(sum(row["forbidden_claim"] for row in scored), count),
        "generic_failure_rate": proportion_result(sum(row["generic_failure"] for row in scored), count),
        "false_refusal_rate": proportion_result(sum(row["false_refusal"] for row in answerable), len(answerable)),
        "truncation_rate": proportion_result(sum(row["truncation"] for row in scored), count),
    }
