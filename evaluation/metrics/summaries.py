from __future__ import annotations

from .generation import normalize_text


def _coverage(items: list[str], answer: str) -> tuple[float, list[str]]:
    normalized = normalize_text(answer)
    hits = [item for item in items if normalize_text(item) in normalized]
    return (len(hits) / len(items) if items else 1.0, hits)


def score_summary(task: dict, answer: str, cited_pages: list[int]) -> dict:
    section_coverage, section_hits = _coverage(task.get("required_sections", []), answer)
    claim_recall, claim_hits = _coverage(task.get("required_key_claims", []), answer)
    contamination_items = [
        item for item in task.get("contamination_blacklist", [])
        if normalize_text(item) in normalize_text(answer)
    ]
    blacklist = task.get("contamination_blacklist", [])
    contamination_rate = len(contamination_items) / len(blacklist) if blacklist else 0.0
    conclusion_coverage = (
        any(token in normalize_text(answer) for token in ("نتیجه", "جمع بندی", "conclusion"))
        if task.get("conclusion_required")
        else True
    )
    distinct_pages = len(set(cited_pages))
    minimum = int(task.get("minimum_page_diversity", 1))
    page_diversity = min(1.0, distinct_pages / minimum)
    passed = all([
        section_coverage == 1.0,
        claim_recall == 1.0,
        conclusion_coverage,
        contamination_rate == 0.0,
        distinct_pages >= minimum,
    ])
    return {
        "substantive_section_coverage": section_coverage,
        "section_hits": section_hits,
        "key_claim_recall": claim_recall,
        "key_claim_hits": claim_hits,
        "conclusion_coverage": bool(conclusion_coverage),
        "contamination_rate": contamination_rate,
        "contamination_hits": contamination_items,
        "page_range_diversity": page_diversity,
        "distinct_cited_pages": distinct_pages,
        "comprehensive_summary_pass": passed,
    }
