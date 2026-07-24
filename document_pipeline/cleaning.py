"""Deterministic text cleanup before chunking/embedding.

This is intentionally conservative: it removes repeated PDF-export watermarks,
OCR bookkeeping fragments, and obvious catalog noise while preserving page
markers so citations can still point back to the original PDF page.
"""
import os
import re
from collections import Counter
from typing import Dict, Tuple


PAGE_MARKER_RE = re.compile(r"^\s*<!--\s*page:\d+\s*-->\s*$")
URL_OR_WATERMARK_RE = re.compile(r"(https?://|www\.|takbook(?:\.com)?)", re.IGNORECASE)
OCR_CODE_RE = re.compile(r"^\s*\[?\s*ووزه\b.*$")
BIBLIOGRAPHY_RE = re.compile(
    r"^\s*("
    r"سرشناسه|عنوان و نام پدیدآور|مشخصات ظاهری|شابک|موضوع\s*:|"
    r"رده‌بندی|شماره کتابشناسی|اطلاعات رکورد|ناشر\s*:|ویراستار\s*:|"
    r"وبراستار\s*:|صفحه‌آرا|طراح جلد|نوبت چاپ|قیمت|حق چاپ"
    r")\b"
)
HEADING_RE = re.compile(r"^\s*#{1,3}\s+")
FIRST_CONTENT_HEADING_RE = re.compile(
    r"^\s*#{1,3}\s+(\u0641\u0635\u0644|\u0628\u062e\u0634|chapter|part)\b",
    re.IGNORECASE,
)

CHAR_TRANS = str.maketrans({
    "\u064a": "\u06cc",  # Arabic ya -> Persian ya
    "\u0649": "\u06cc",
    "\u0643": "\u06a9",  # Arabic kaf -> Persian kaf
    "\u0629": "\u0647",
    "\u00a0": " ",
    "\u0640": "",
    "\u200b": "",
    "\u200c": "\u200c",
    "\u200d": "",
    "\u200e": "",
    "\u200f": "",
})


def _normalize_chars(text: str) -> str:
    return (text or "").translate(CHAR_TRANS)


def _compact_signature(text: str) -> str:
    text = _normalize_chars(text).lower()
    text = re.sub(r"^\s*#{1,3}\s+", "", text)
    return "".join(re.findall(r"[0-9A-Za-z\u0600-\u06ff]+", text))


def _has_letters(text: str) -> bool:
    return bool(re.search(r"[A-Za-z\u0600-\u06ff]", text or ""))


def _line_noise_score(line: str) -> Tuple[int, int]:
    letters = len(re.findall(r"[A-Za-z\u0600-\u06ff]", line or ""))
    digits = len(re.findall(r"[0-9\u06f0-\u06f9]", line or ""))
    return letters, digits


def _is_substantive_body_line(line: str) -> bool:
    letters, _digits = _line_noise_score(line)
    return len(line or "") >= 180 and letters >= 120


def _is_tiny_code_line(line: str) -> bool:
    stripped = re.sub(r"\s+", "", line or "")
    if not stripped:
        return False
    letters, digits = _line_noise_score(stripped)
    if letters == 0 and len(stripped) <= 8:
        return True
    return len(stripped) <= 40 and digits >= 3 and letters <= 6 and digits >= letters * 2


def _visible_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def clean_markdown(markdown_text: str, filename: str = "") -> Tuple[str, Dict]:
    lines = _normalize_chars(markdown_text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    title_signature = _compact_signature(stem)
    first_content_index = next(
        (
            index
            for index, line in enumerate(lines)
            if FIRST_CONTENT_HEADING_RE.match(_visible_line(line))
        ),
        None,
    )
    first_body_index = None
    if first_content_index is not None:
        first_body_index = next(
            (
                index
                for index, line in enumerate(lines[first_content_index + 1:], start=first_content_index + 1)
                if _is_substantive_body_line(_visible_line(line))
            ),
            None,
        )

    signatures = Counter()
    for line in lines:
        stripped = _visible_line(line)
        if not stripped or PAGE_MARKER_RE.match(stripped):
            continue
        signature = _compact_signature(stripped)
        if signature and _has_letters(signature) and len(stripped) <= 100:
            signatures[signature] += 1

    cleaned = []
    seen_title = False
    removed = Counter()

    for index, line in enumerate(lines):
        stripped = _visible_line(line)
        if not stripped:
            cleaned.append("")
            continue
        if PAGE_MARKER_RE.match(stripped):
            cleaned.append(stripped)
            continue
        if first_content_index is not None and index < first_content_index:
            removed["front_matter"] += 1
            continue
        if (
            first_body_index is not None
            and first_content_index < index < first_body_index
            and not HEADING_RE.match(stripped)
        ):
            removed["preface_toc"] += 1
            continue

        signature = _compact_signature(stripped)
        is_title_line = bool(title_signature and signature == title_signature)

        if URL_OR_WATERMARK_RE.search(stripped):
            removed["url_or_watermark"] += 1
            continue
        if OCR_CODE_RE.match(stripped):
            removed["ocr_code"] += 1
            continue
        if BIBLIOGRAPHY_RE.match(stripped):
            removed["bibliography"] += 1
            continue
        if _is_tiny_code_line(stripped):
            removed["tiny_code"] += 1
            continue
        if signature and signatures[signature] >= 5 and not HEADING_RE.match(stripped):
            if is_title_line and not seen_title:
                seen_title = True
                cleaned.append(stem or stripped)
            else:
                removed["repeated_line"] += 1
            continue
        if is_title_line:
            seen_title = True
            cleaned.append(stem or stripped)
            continue

        cleaned.append(stripped)

    collapsed = []
    blank = False
    for line in cleaned:
        if line:
            collapsed.append(line)
            blank = False
        elif not blank:
            collapsed.append("")
            blank = True

    cleaned_text = "\n".join(collapsed).strip() + "\n"
    removed_total = sum(removed.values())
    meta = {
        "text_cleanup_enabled": True,
        "text_cleanup_version": "v1",
        "text_cleanup_removed_lines": removed_total,
        "text_cleanup_removed_by_reason": dict(removed),
        "text_cleanup_char_count_before": len(markdown_text or ""),
        "text_cleanup_char_count_after": len(cleaned_text),
    }
    return cleaned_text, meta
