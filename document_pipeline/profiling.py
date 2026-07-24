"""Deterministic document profiling and extraction quality gates.

This module does not call an LLM. It converts normalization metadata and the
canonical Markdown into a small, stable contract used by chunking and RAG
routing. Keeping this step deterministic makes ingestion cheap and repeatable.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any


PROFILE_VERSION = "v2"

PAGE_RE = re.compile(r"^<!--\s*page:(\d+)\s*-->$", re.MULTILINE)
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
CHAPTER_RE = re.compile(
    r"^(?:فصل|chapter|part)\s+(?:[0-9۰-۹]+|[ivxlcdm]+|"
    r"اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|"
    r"یازدهم|دوازدهم|سیزدهم|چهاردهم|پانزدهم|شانزدهم|"
    r"هفدهم|هجدهم|نوزدهم|بیستم)\b",
    re.IGNORECASE,
)
TIMESTAMP_RE = re.compile(r"(?:^|\s)(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\s|$)", re.MULTILINE)
SPEAKER_RE = re.compile(r"^[^\n:]{1,40}:\s+\S", re.MULTILINE)
FORMAL_SPEAKER_RE = re.compile(
    r"(?:^|\s)(?:(?:VICE\s+)?CHAIRMAN|PRESIDENT|GOVERNOR|MR|MS|DR)\.?\s+"
    r"[A-Z][A-Z'’-]{1,30}\.\s+",
    re.MULTILINE,
)
QUESTION_RE = re.compile(r"(?:^|\n)[^\n]{2,180}[؟?]\s*(?:\n|$)")
LETTER_RE = re.compile(r"[A-Za-z\u0600-\u06ff]")


@dataclass(frozen=True)
class QualityAssessment:
    status: str
    score: float
    indexable: bool
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentProfile:
    version: str
    title: str | None
    authors: list[str]
    document_type: str
    type_confidence: float
    unit_strategy: str
    language: str
    content_hash: str
    char_count: int
    page_count: int | None
    heading_count: int
    chapter_count: int
    paragraph_count: int
    detected_sections: list[str]
    quality: QualityAssessment

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _body_text(markdown_text: str) -> str:
    text = PAGE_RE.sub("", markdown_text or "")
    text = HEADING_RE.sub(lambda match: match.group(2), text)
    return text.strip()


def _language(text: str) -> str:
    arabic = len(re.findall(r"[\u0600-\u06ff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if arabic > latin * 1.5:
        return "fa"
    if latin > arabic * 1.5:
        return "en"
    return "mixed" if arabic or latin else "unknown"


def assess_quality(markdown_text: str, normalization_meta: dict[str, Any]) -> QualityAssessment:
    body = _body_text(markdown_text)
    char_count = len(body)
    letters = len(LETTER_RE.findall(body))
    replacement_count = body.count("\ufffd")
    letter_ratio = letters / max(char_count, 1)
    replacement_ratio = replacement_count / max(char_count, 1)
    page_count = normalization_meta.get("page_count")
    avg_chars_per_page = char_count / max(int(page_count or 1), 1)

    warnings: list[str] = []
    score = 1.0
    indexable = True

    ocr_required = bool(normalization_meta.get("ocr_required"))
    ocr_status = normalization_meta.get("ocr_status")
    ocr_blocking = bool(
        normalization_meta.get(
            "ocr_blocking",
            ocr_required and ocr_status != "applied",
        )
    )
    if ocr_required and ocr_blocking:
        warnings.append("ocr_required_but_not_applied")
        score -= 0.75
        indexable = False
    elif normalization_meta.get("ocr_pages_skipped"):
        warnings.append("partial_ocr_pages_skipped")
        score -= 0.08
    if char_count < 80:
        warnings.append("very_little_extracted_text")
        score -= 0.65
        indexable = False
    elif char_count < 300:
        warnings.append("little_extracted_text")
        score -= 0.2
    if letter_ratio < 0.35:
        warnings.append("low_letter_ratio")
        score -= 0.25
    if replacement_ratio > 0.005:
        warnings.append("invalid_character_ratio")
        score -= 0.35
    if page_count and avg_chars_per_page < 30:
        warnings.append("low_text_density")
        score -= 0.2
    if normalization_meta.get("structure_confidence") == "low":
        warnings.append("weak_document_structure")
        score -= 0.08

    score = round(max(0.0, min(score, 1.0)), 3)
    if score < 0.45:
        indexable = False
    status = "rejected" if not indexable else ("warning" if warnings else "ready")
    return QualityAssessment(
        status=status,
        score=score,
        indexable=indexable,
        warnings=warnings,
        metrics={
            "letters": letters,
            "letter_ratio": round(letter_ratio, 4),
            "replacement_ratio": round(replacement_ratio, 6),
            "avg_chars_per_page": round(avg_chars_per_page, 1) if page_count else None,
        },
    )


def profile_document(
    markdown_text: str,
    normalization_meta: dict[str, Any],
    *,
    filename: str = "",
) -> DocumentProfile:
    body = _body_text(markdown_text)
    headings = [title.strip() for _marks, title in HEADING_RE.findall(markdown_text or "")]
    h1_titles = [heading.strip() for marks, heading in HEADING_RE.findall(markdown_text or "") if len(marks) == 1]
    title = str(normalization_meta.get("document_title") or "").strip() or (h1_titles[0] if h1_titles else None)
    authors = [
        str(value).strip()
        for value in (normalization_meta.get("document_authors") or [])
        if str(value).strip()
    ]
    sections = [heading for heading in headings if not title or heading != title]
    chapters = [heading for heading in headings if CHAPTER_RE.match(heading)]
    pages = [int(value) for value in PAGE_RE.findall(markdown_text or "")]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", body) if part.strip()]
    quality = assess_quality(markdown_text, normalization_meta)

    timestamp_hits = len(TIMESTAMP_RE.findall(body))
    speaker_hits = len(SPEAKER_RE.findall(body)) + len(FORMAL_SPEAKER_RE.findall(body))
    question_hits = len(QUESTION_RE.findall(body))
    average_page_chars = len(body) / max(len(set(pages)), 1) if pages else None

    if not quality.indexable:
        document_type, confidence, strategy = "noisy_scan", 0.95, "quality_review"
    elif len(chapters) >= 2:
        document_type, confidence, strategy = "chaptered_book", 0.95, "chapter"
    elif timestamp_hits >= 3 or speaker_hits >= max(4, len(paragraphs) // 5):
        document_type, confidence, strategy = "transcript", 0.85, "semantic_window"
    elif question_hits >= max(3, len(paragraphs) // 5):
        document_type, confidence, strategy = "faq_or_notes", 0.8, "heading_or_semantic"
    elif pages and average_page_chars is not None and average_page_chars < 700 and len(pages) >= 4:
        document_type, confidence, strategy = "slide_deck", 0.72, "page"
    elif len(headings) >= 2:
        lowered = f"{filename} {' '.join(headings[:5])}".lower()
        all_headings = " ".join(headings).lower()
        is_paper = (
            any(term in lowered for term in ("abstract", "چکیده", "method", "روش"))
            or any(term in all_headings for term in ("references", "منابع", "introduction", "مقدمه"))
            or bool(normalization_meta.get("document_title") and normalization_meta.get("page_count"))
        )
        document_type = "research_article" if is_paper else "sectioned_report"
        confidence, strategy = (0.92, "heading") if is_paper else (0.8, "heading")
    else:
        document_type, confidence = "flat_document", 0.7
        strategy = "page_window" if pages else "semantic_window"

    content_hash = hashlib.sha256((markdown_text or "").encode("utf-8")).hexdigest()
    return DocumentProfile(
        version=PROFILE_VERSION,
        title=title,
        authors=authors,
        document_type=document_type,
        type_confidence=confidence,
        unit_strategy=strategy,
        language=_language(body),
        content_hash=content_hash,
        char_count=len(body),
        page_count=int(normalization_meta.get("page_count") or max(pages, default=0)) or None,
        heading_count=len(headings),
        chapter_count=len(chapters),
        paragraph_count=len(paragraphs),
        detected_sections=sections,
        quality=quality,
    )
