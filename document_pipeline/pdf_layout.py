"""Deterministic, page-aware PDF layout analysis.

The ordinary ``PdfReader.extract_text`` output has useful reading order, but it
does not say which short lines are running headers, real headings, or journal
metadata.  This module combines that text with lightweight font/position signals
from pypdf's visitor API.  It deliberately does not rewrite prose or call a model.
"""
from __future__ import annotations

import math
import os
import re
from difflib import SequenceMatcher
from collections import Counter
from typing import Any


ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
LATIN_RE = re.compile(r"[A-Za-z]")
DIGIT_RE = re.compile(r"[0-9\u06f0-\u06f9\u0660-\u0669]+")
SECTION_MARKER_RE = re.compile(
    r"^(?:section\s+([0-9ivxlcdm]+)|([0-9]{1,2}|[ivxlcdm]+)[.)])\s*$",
    re.IGNORECASE,
)
REFERENCE_RE = re.compile(r"^(?:references|bibliography|منابع|کتابنامه)\s*$", re.IGNORECASE)
ABSTRACT_RE = re.compile(r"(?:^|\s)(abstract|چکیده)(?:\s|$)", re.IGNORECASE)
INTRO_RE = re.compile(r"^(?:introduction|مقدمه)\s*$", re.IGNORECASE)
CONCLUSION_RE = re.compile(
    r"^(?:conclusions?|discussion\s+and\s+conclusions?|نتیجه(?:\s|‌)*(?:گیری)?|جمع(?:\s|‌)*بندی)\s*$",
    re.IGNORECASE,
)
JOURNAL_BOILERPLATE_RE = re.compile(
    r"^(?:"
    r"print\s+issn|online\s+issn|issn\b|article\s+info|article\s+type|article\s+history|"
    r"received\s*:|accepted\s*:|published\s+online\s*:|keywords?\s*:|"
    r"cite\s+this\s+article\s*:|copyright\b|license\b|published\s+by\b|"
    r"اطلاعات\s+مقاله|نوع\s+مقاله\s*:|تاریخ\s+(?:دریافت|بازنگری|پذیرش|انتشار)\s*:|"
    r"کلیدواژه(?:ها)?\s*:|استناد\s*:|ناشر\s*:|شناخت$|shinakht$"
    r")",
    re.IGNORECASE,
)
CONTACT_RE = re.compile(r"(?:@|corresponding\s+author|رایانامه|نو[یي]سند[ۀه]\s+مسئول)", re.IGNORECASE)
URL_RE = re.compile(r"(?:https?://|www\.|doi\s*:)", re.IGNORECASE)
FOOTNOTE_START_RE = re.compile(r"^[0-9\u06f0-\u06f9]+\s+\S")


def normalize_visible(text: str) -> str:
    """Normalize character variants and extraction spacing without paraphrase."""
    value = (text or "").translate(str.maketrans({
        "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ـ": "", "\uf02a": "",
        "\u200e": "", "\u200f": "", "\u200b": "", "\u200d": "",
    }))
    value = re.sub(r"\s+", " ", value).strip()
    # Broken PDF text layers frequently split a Persian word around a single
    # glyph ("عل یت", "د یوی د", "فیز ی کی").  Joining only one-letter
    # Persian fragments, except the legitimate conjunction "و", repairs the
    # damage while leaving normal word boundaries intact.
    for _ in range(3):
        previous = value
        value = re.sub(
            r"(?<![\u0600-\u06ff])([ابتثجحخدذرزژسشصضطظعغفقکگلمنه])\s+(?=[\u0600-\u06ff]{2,})",
            r"\1",
            value,
        )
        value = re.sub(
            r"(?<=[\u0600-\u06ff]{2})\s+([ابتثجحخدذرزژسشصضطظعغفقکگلمنهی])(?![\u0600-\u06ff])",
            r"\1",
            value,
        )
        if value == previous:
            break
    value = re.sub(r"\bمی\s+(?=[\u0600-\u06ff])", "می\u200c", value)
    value = re.sub(r"\bنمی\s+(?=[\u0600-\u06ff])", "نمی\u200c", value)
    for broken, repaired in (
        (r"\bرو\s+یکرد", "رویکرد"),
        (r"\bد\s+یوی\s+د\b", "دیوید"),
        (r"\bدیوی\s+د\b", "دیوید"),
        (r"\bدیوی\s+د(?=بوهم)", "دیوید "),
        (r"\bفلسف\s+ی\b", "فلسفی"),
        (r"\bفلسف\s+ۀ", "فلسفۀ"),
        (r"\bعل\s+یت\b", "علیت"),
        (r"\bعل\s+ی\b", "علی"),
    ):
        value = re.sub(broken, repaired, value)
    value = re.sub(r"\s+([.!?؟،؛:])", r"\1", value)
    return value


def compact_signature(text: str, *, drop_digits: bool = False) -> str:
    value = normalize_visible(text).lower()
    if drop_digits:
        value = DIGIT_RE.sub("", value)
    return "".join(re.findall(r"[a-z\u0600-\u06ff]+", value))


def _plausible_title(value: str | None) -> bool:
    value = normalize_visible(value or "")
    lowered = value.lower()
    return (
        8 <= len(value) <= 240
        and not lowered.startswith(("microsoft word", "untitled", "document"))
        and len(re.findall(r"[A-Za-z\u0600-\u06ff]", value)) >= 6
    )


def _dominant_language(text: str) -> str:
    arabic = len(ARABIC_RE.findall(text or ""))
    latin = len(LATIN_RE.findall(text or ""))
    return "fa" if arabic > latin else "en"


def _styled_lines(page: Any) -> dict[str, dict[str, Any]]:
    """Return compact signatures for visually heading-like horizontal lines."""
    rows: dict[float, list[tuple[str, str, float]]] = {}

    def visitor(text, _cm, tm, font_dict, font_size):
        visible = normalize_visible(text or "")
        if not visible:
            return
        y = round(float(tm[5]), 1)
        font = str((font_dict or {}).get("/BaseFont") or "").lower()
        rows.setdefault(y, []).append((visible, font, float(font_size or 0)))

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return {}

    output: dict[str, dict[str, Any]] = {}
    for y, fragments in rows.items():
        text = normalize_visible(" ".join(item[0] for item in fragments))
        signature = compact_signature(text)
        if not signature or len(text) > 180:
            continue
        fonts = [item[1] for item in fragments if item[0]]
        sizes = [item[2] for item in fragments if item[0]]
        title_font = bool(fonts) and all("titr" in font or "bold" in font for font in fonts)
        large_first_page_text = bool(sizes) and max(sizes) >= 15
        if title_font or large_first_page_text:
            output[signature] = {
                "text": text,
                "y": y,
                "font_heading": title_font,
                "max_size": max(sizes, default=0),
            }
    return output


def _find_filename_title(filename: str, pages: list[list[str]]) -> str | None:
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    stem_signature = compact_signature(stem)
    if len(stem_signature) < 8:
        return None
    candidates = []
    for page_index, lines in enumerate(pages[:3]):
        for line_index, raw in enumerate(lines[:20]):
            line = normalize_visible(raw)
            signature = compact_signature(line)
            if not signature or len(line) > 220:
                continue
            if stem_signature in signature or signature in stem_signature:
                candidates.append((len(signature), -page_index, -line_index, line))
    return max(candidates)[-1] if candidates else None


def _visual_title(styled_pages: list[dict[str, dict[str, Any]]], language: str) -> str | None:
    """Infer a multi-line article title from the largest text on early pages.

    Scholarly bilingual PDFs often have an English title page followed by the
    dominant-language title several pages later, while both PDF metadata and
    the opaque publisher filename are useless.  Requiring adjacent >=14pt
    heading lines and the document's dominant language avoids promoting author
    names, ARTICLE INFO labels, and ordinary section headings.
    """
    candidates: list[tuple[int, float, int, str]] = []
    for page_index, styled in enumerate(styled_pages[:4]):
        rows = sorted(
            (info for info in styled.values() if float(info.get("max_size") or 0) >= 14),
            key=lambda item: -float(item.get("y") or 0),
        )
        group: list[dict[str, Any]] = []
        groups: list[list[dict[str, Any]]] = []
        for row in rows:
            if group and abs(float(group[-1]["y"]) - float(row["y"])) > 36:
                groups.append(group)
                group = []
            group.append(row)
        if group:
            groups.append(group)
        for values in groups:
            text = normalize_visible(" ".join(str(item.get("text") or "") for item in values))
            if not _plausible_title(text) or _dominant_language(text) != language:
                continue
            candidates.append((
                len(text),
                max(float(item.get("max_size") or 0) for item in values),
                -page_index,
                text,
            ))
    return max(candidates)[-1] if candidates else None


def _match_title_line(line: str, title: str | None) -> bool:
    left = compact_signature(line)
    right = compact_signature(title or "")
    if not left or not right:
        return False
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) < 8:
        return False
    if shorter in longer and len(shorter) / len(longer) >= 0.30:
        return True
    return SequenceMatcher(a=left, b=right, autojunk=False).ratio() >= 0.82


def _repeated_margin_signatures(pages: list[list[str]]) -> set[str]:
    counts: Counter[str] = Counter()
    for lines in pages:
        visible = [normalize_visible(line) for line in lines if normalize_visible(line)]
        # Headers dominate the observed failures. Limit removal to a small
        # positional band so repeated meaningful body sentences survive.
        for line in visible[:3]:
            signature = compact_signature(line, drop_digits=True)
            if 5 <= len(signature) <= 140:
                counts[signature] += 1
    threshold = max(2, math.ceil(len(pages) * 0.30))
    return {signature for signature, count in counts.items() if count >= threshold}


def _footnote_start(lines: list[str]) -> int | None:
    """Find a bottom-of-page numbered footnote block, if one is present."""
    if len(lines) < 8:
        return None
    lower_band = max(1, int(len(lines) * 0.68))
    for index in range(lower_band, len(lines)):
        if not normalize_visible(lines[index]) and index + 1 < len(lines):
            next_line = normalize_visible(lines[index + 1])
            if FOOTNOTE_START_RE.match(next_line) and len(next_line) > 45:
                return index + 1
    return None


def _heading_match(line: str, styled: dict[str, dict[str, Any]]) -> bool:
    signature = compact_signature(line)
    if not signature:
        return False
    if signature in styled and styled[signature].get("font_heading"):
        return True
    # Visitor fragments can differ slightly from extract_text's reconstructed
    # line.  Permit a near containment match only for compact heading candidates.
    if len(line) <= 90:
        for candidate, info in styled.items():
            if info.get("font_heading") and min(len(signature), len(candidate)) >= 4:
                if signature in candidate or candidate in signature:
                    return True
    return False


def analyze_pdf(
    reader: Any,
    page_texts: list[str],
    *,
    filename: str,
) -> dict[str, Any]:
    """Return cleaned per-page tokenizer entries and layout metadata.

    Each entry is ``(text, forced_classification_or_none)`` and can be handed
    directly to ingest's shared tokenizer.
    """
    raw_pages = [[line for line in (text or "").splitlines()] for text in page_texts]
    # Decorative drop caps can be emitted as a one-letter line followed by the
    # rest of the first word ("A" + "NY serious ..."). Rejoin that layout
    # artifact before paragraph assembly.
    for lines in raw_pages:
        for index in range(len(lines) - 1):
            left = normalize_visible(lines[index])
            right = normalize_visible(lines[index + 1])
            if re.fullmatch(r"[A-Z]", left) and re.match(r"^[A-Z]{1,3}\b", right):
                lines[index + 1] = left + right
                lines[index] = ""
    styled_pages = [_styled_lines(page) for page in reader.pages]
    metadata = reader.metadata or {}
    metadata_title = normalize_visible(str(metadata.get("/Title") or ""))
    filename_title = _find_filename_title(filename, raw_pages)
    all_text = "\n".join(page_texts)
    language = _dominant_language(all_text)
    visual_title = _visual_title(styled_pages, language)
    title = (
        filename_title
        if language == "fa" and _plausible_title(filename_title)
        else visual_title if _plausible_title(visual_title)
        else metadata_title if _plausible_title(metadata_title)
        else filename_title if _plausible_title(filename_title)
        else None
    )
    large_title_signatures = {
        signature
        for styled in styled_pages[:4]
        for signature, info in styled.items()
        if float(info.get("max_size") or 0) >= 14
    }
    repeated = _repeated_margin_signatures(raw_pages)
    image_counts = []
    for page in reader.pages:
        try:
            image_counts.append(len(page.images))
        except Exception:
            image_counts.append(0)
    table_candidate_pages = [
        index + 1
        for index, lines in enumerate(raw_pages)
        if any(
            re.search(r"(?:\btable\b|جدول|article\s+info|اطلاعات\s+مقاله)", line, re.IGNORECASE)
            for line in lines
        )
    ]

    authors = []
    metadata_author = normalize_visible(str(metadata.get("/Author") or ""))
    if metadata_author and metadata_author.lower() not in {"none", "unknown"}:
        authors.append(metadata_author)

    title_page_anchor = None
    if title:
        for page_index, lines in enumerate(raw_pages[:4]):
            for line_index, raw in enumerate(lines):
                if _match_title_line(raw, title):
                    title_page_anchor = (page_index, line_index)
                    break
            if title_page_anchor:
                break

    entries_by_page: list[list[tuple[str, tuple | None]]] = []
    removed = Counter()
    heading_titles: list[str] = []
    title_emitted = False
    abstract_active = False
    abstract_pages: dict[str, int] = {}

    for page_index, lines in enumerate(raw_pages):
        entries: list[tuple[str, tuple | None]] = []
        styled = styled_pages[page_index]
        abstract_seen_on_page = False
        awaiting_inferred_abstract = False
        in_inferred_abstract = False
        infer_first_section = False
        skip_metadata_block = False
        footnote_at = _footnote_start(lines)
        visible_positions = [i for i, line in enumerate(lines) if normalize_visible(line)]
        header_positions = set(visible_positions[:3])

        for line_index, raw in enumerate(lines):
            line = normalize_visible(raw)
            if not line:
                skip_metadata_block = False
                if in_inferred_abstract:
                    in_inferred_abstract = False
                    infer_first_section = True
                entries.append(("", None))
                continue
            if (
                title_page_anchor
                and page_index == title_page_anchor[0]
                and language == "en"
                and line_index < title_page_anchor[1]
            ):
                removed["pre_title_spillover"] += 1
                continue
            if footnote_at is not None and line_index >= footnote_at:
                removed["footnote"] += 1
                continue

            margin_signature = compact_signature(line, drop_digits=True)
            if line_index in header_positions and margin_signature in repeated:
                removed["repeated_header"] += 1
                continue
            if title and _match_title_line(line, title):
                if not title_emitted:
                    entries.append((title, ("heading", 1, "strong")))
                    title_emitted = True
                    awaiting_inferred_abstract = language == "en"
                else:
                    removed["repeated_title"] += 1
                continue
            if compact_signature(line) in large_title_signatures:
                # Keep only the selected dominant-language title.  Parallel
                # English/Persian title lines are useful metadata, but they are
                # not substantive sections and must not enter embeddings.
                removed["alternate_title"] += 1
                continue

            if awaiting_inferred_abstract:
                if (
                    re.match(r"^\(?received\b", line, re.IGNORECASE)
                    or re.search(r"(?:institute|university|[A-Z]\.[ ]*[A-Z])", line)
                    or len(line) < 45
                ):
                    removed["title_metadata"] += 1
                    continue
                entries.append(("Abstract", ("heading", 2, "strong")))
                heading_titles.append("Abstract")
                abstract_seen_on_page = True
                awaiting_inferred_abstract = False
                in_inferred_abstract = True

            if infer_first_section:
                entries.append(("Section I", ("heading", 2, "strong")))
                heading_titles.append("Section I")
                infer_first_section = False

            abstract_match = ABSTRACT_RE.search(line)
            if abstract_match:
                label = "چکیده" if abstract_match.group(1) == "چکیده" else "Abstract"
                if label in abstract_pages and page_index > abstract_pages[label]:
                    removed["repeated_abstract_heading"] += 1
                    abstract_seen_on_page = True
                    continue
                entries.append((label, ("heading", 2, "strong")))
                heading_titles.append(label)
                abstract_pages[label] = page_index
                abstract_active = True
                abstract_seen_on_page = True
                continue

            if skip_metadata_block:
                removed["publication_metadata_continuation"] += 1
                continue
            boilerplate = JOURNAL_BOILERPLATE_RE.match(line)
            if boilerplate or URL_RE.search(line):
                if re.match(r"^(?:cite\s+this\s+article|استناد|copyright|ناشر)\b", line, re.IGNORECASE):
                    skip_metadata_block = True
                removed["publication_metadata"] += 1
                continue
            if CONTACT_RE.search(line):
                if 2 <= len(line.split()) <= 14 and not authors:
                    authors.append(line)
                removed["contact_metadata"] += 1
                continue

            if (
                title_page_anchor
                and page_index == title_page_anchor[0]
                and not abstract_seen_on_page
            ):
                if (
                    compact_signature(line) not in large_title_signatures
                    and len(line) <= 90
                    and 1 <= len(line.split()) <= 10
                    and not JOURNAL_BOILERPLATE_RE.match(line)
                    and not authors
                ):
                    authors.append(re.sub(r"[\d*]+", "", line).strip())
                removed["title_page_metadata"] += 1
                continue

            # On bilingual journal title pages, everything before the abstract
            # is descriptive metadata. The dominant-language title has already
            # been emitted and author data is retained in the sidecar.
            if language == "fa" and page_index <= 1 and not abstract_seen_on_page:
                removed["front_matter"] += 1
                continue

            # Article-info columns are commonly emitted before the abstract
            # prose.  Suppress their short values until real prose begins.
            if abstract_active and len(line) < 70 and not re.search(r"[.!؟]$", line):
                removed["abstract_sidebar_metadata"] += 1
                continue
            if abstract_active and len(line) >= 70:
                abstract_active = False

            if REFERENCE_RE.match(line):
                canonical = "منابع" if ARABIC_RE.search(line) else "References"
                entries.append((canonical, ("heading", 2, "strong")))
                heading_titles.append(canonical)
                continue
            if (
                title_page_anchor
                and language == "fa"
                and page_index < title_page_anchor[0]
                and _heading_match(line, styled)
            ):
                # English extended-abstract continuation pages often render
                # emphasized sentence fragments in bold.  They belong to the
                # already-open Abstract unit, not to independent sections.
                entries.append((line, ("body",)))
                continue
            if INTRO_RE.match(line) or CONCLUSION_RE.match(line) or _heading_match(line, styled):
                heading_line = "نتیجه‌گیری" if re.fullmatch(r"نتیجه\s*گیری", line) else line
                entries.append((heading_line, ("heading", 2, "strong")))
                heading_titles.append(heading_line)
                continue
            section = SECTION_MARKER_RE.match(line)
            if section:
                number = section.group(1) or section.group(2)
                label = f"Section {number.upper()}"
                entries.append((label, ("heading", 2, "strong")))
                heading_titles.append(label)
                continue

            # Standalone publication dates, keyword values, and author lists are
            # metadata, not the article's argument.  Long prose is never removed
            # by these guards.
            if len(line) < 70 and (
                re.match(r"^(?:research\s+article|november\s+\d{4}|\d{4})$", line, re.IGNORECASE)
                or ("|" in line and len(line.split()) <= 12)
            ):
                removed["publication_metadata"] += 1
                continue

            entries.append((line, ("body",)))
        entries_by_page.append(entries)

    # Some PDFs have a meaningful metadata title but no exact extract_text line.
    # Emit it once at the beginning while keeping the physical page marker first.
    if title and not title_emitted:
        entries_by_page[0].insert(0, (title, ("heading", 1, "strong")))

    return {
        "entries_by_page": entries_by_page,
        "document_title": title,
        "document_authors": authors,
        "detected_heading_titles": heading_titles,
        "layout_removed_by_reason": dict(removed),
        "layout_removed_lines": sum(removed.values()),
        "repeated_margin_signatures": len(repeated),
        "layout_analysis_version": "v1",
        "embedded_image_count": sum(image_counts),
        "image_pages": [index + 1 for index, count in enumerate(image_counts) if count],
        "has_embedded_images": any(image_counts),
        "table_candidate_pages": table_candidate_pages,
        "has_table_candidates": bool(table_candidate_pages),
    }
