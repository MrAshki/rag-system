from __future__ import annotations

import re

from .generation import atomic_claim_match, concept_match, normalize_text


SECTION_ROLES = {
    "abstract": (r"چکیده|abstract|مسئله|هدف", r"عنوان سند|هدف|مسئله|زمینه|اهمیت|نقش"),
    "introduction": (r"مقدمه|introduction|مسئله|هدف", r"مقدمه|زمینه|هدف|مسئله|اهمیت|نقش"),
    "method": (r"روش|method|مرور", r"روش|مرور تطبیقی|تحلیلی تطبیقی|method"),
    "findings": (r"یافته|نتایج|وضع ایران|تجارب منتخب", r"یافته|نتایج|ارزیابی عملکرد|منتخب|مرور تطبیقی"),
    "discussion": (r"بحث|discussion", r"بحث|تفسیر|تحلیل"),
    "conclusion": (r"نتیجه|جمع بندی|conclusion", r"نتیجه|جمع بندی|conclusion"),
    "recommendations": (r"توصیه|پیشنهاد|پیامد|گزینه سیاستی", r"توصیه|پیشنهاد|پیامد|گزینه سیاستی"),
}


def _semantic_section_match(label: str, answer: str) -> bool:
    normalized_label = normalize_text(label)
    normalized_answer = normalize_text(answer)
    label_tokens = set(normalized_label.split())
    if label_tokens and label_tokens.issubset(set(normalized_answer.split())):
        return True
    for _role, (label_pattern, answer_pattern) in SECTION_ROLES.items():
        if re.search(label_pattern, normalized_label, re.I):
            if _role == "conclusion":
                return _conclusion_present(answer)
            return bool(re.search(answer_pattern, normalized_answer, re.I))
    return atomic_claim_match(answer, label, threshold=0.75)


def _conclusion_present(answer: str) -> bool:
    normalized = normalize_text(answer)
    if any(token in normalized for token in ("نتیجه", "جمع بندی", "conclusion")):
        return True
    paragraphs = [part for part in re.split(r"\n\s*\n+", answer or "") if part.strip()]
    if not paragraphs:
        return False
    last = normalize_text(paragraphs[-1])
    cues = (
        "نیازمند", "بنابراین", "در مجموع", "ضرور", "پیشنهاد", "توصیه",
        "چارچوب", "عامل کلیدی", "فراهم", "می تواند", "should", "therefore",
        "in conclusion", "requires", "recommend",
    )
    return sum(cue in last for cue in cues) >= 2


def _coverage(items: list[str], answer: str, *, sections: bool = False) -> tuple[float, list[str]]:
    hits = (
        [item for item in items if _semantic_section_match(item, answer)]
        if sections
        else [item for item in items if atomic_claim_match(answer, item)]
    )
    return (len(hits) / len(items) if items else 1.0, hits)


def score_summary(task: dict, answer: str, cited_pages: list[int]) -> dict:
    section_coverage, section_hits = _coverage(task.get("required_sections", []), answer, sections=True)
    claim_recall, claim_hits = _coverage(task.get("required_key_claims", []), answer)
    contamination_items = [
        item for item in task.get("contamination_blacklist", [])
        if normalize_text(item) in normalize_text(answer)
    ]
    blacklist = task.get("contamination_blacklist", [])
    contamination_rate = len(contamination_items) / len(blacklist) if blacklist else 0.0
    conclusion_coverage = _conclusion_present(answer) if task.get("conclusion_required") else True
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
