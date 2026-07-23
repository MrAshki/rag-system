"""Build stable parent units for documents with or without explicit structure."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from document_pipeline.profiling import DocumentProfile


DOCUMENT_MAP_VERSION = "v3"
PAGE_RE = re.compile(r"^<!--\s*page:(\d+)\s*-->$")
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
CHAPTER_ID_RE = re.compile(
    r"^(فصل|chapter|part)\s+([0-9۰-۹]+|[ivxlcdm]+|"
    r"اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|"
    r"یازدهم|دوازدهم|سیزدهم|چهاردهم|پانزدهم|شانزدهم|"
    r"هفدهم|هجدهم|نوزدهم|بیستم)\b",
    re.IGNORECASE,
)
BLOCK_SEPARATOR_RE = re.compile(r"\n\s*\n+")
TARGET_FLAT_UNIT_CHARS = 6500
PAGES_PER_UNIT = 3


@dataclass(frozen=True)
class DocumentUnit:
    unit_id: str
    order: int
    unit_type: str
    role: str
    title: str
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    text_hash: str


def _blocks(markdown_text: str) -> list[dict[str, Any]]:
    result = []
    last = 0
    page = None
    for match in BLOCK_SEPARATOR_RE.finditer(markdown_text or ""):
        raw = markdown_text[last:match.start()]
        if raw.strip():
            result.append({"text": raw.strip(), "start": last, "end": match.start(), "page": page})
            page_match = PAGE_RE.match(raw.strip())
            if page_match:
                page = int(page_match.group(1))
                result[-1]["page"] = page
        last = match.end()
    raw = (markdown_text or "")[last:]
    if raw.strip():
        result.append({"text": raw.strip(), "start": last, "end": len(markdown_text), "page": page})
        page_match = PAGE_RE.match(raw.strip())
        if page_match:
            page = int(page_match.group(1))
            result[-1]["page"] = page

    current_page = None
    for block in result:
        page_match = PAGE_RE.match(block["text"])
        if page_match:
            current_page = int(page_match.group(1))
        block["page"] = current_page
    return result


def _section_role(title: str, unit_type: str) -> str:
    normalized = re.sub(r"[\s‌]+", " ", (title or "").strip().lower())
    if re.fullmatch(r"(?:abstract|چکیده)", normalized):
        return "abstract"
    if re.fullmatch(r"(?:introduction|مقدمه)", normalized):
        return "introduction"
    if re.fullmatch(r"(?:references|bibliography|منابع|کتابنامه)", normalized):
        return "references"
    if re.search(r"(?:conclusions?|جمع ?بندی|نتیجه ?گیری)", normalized):
        return "conclusion"
    if re.search(r"(?:methods?|methodology|materials? and methods?|روش ?کار|روش ?شناسی)", normalized):
        return "methodology"
    if re.fullmatch(r"(?:results?|findings?|یافته ?ها|نتایج)", normalized):
        return "findings"
    if re.fullmatch(r"(?:discussion|بحث)", normalized):
        return "discussion"
    if re.search(r"(?:practical implications?|پیامدهای عملی|کاربردهای عملی)", normalized):
        return "practical_implications"
    if re.search(
        r"(?:acknowledg(?:e)?ments?|قدردانی(?: ?ها)?|سپاسگزاری|"
        r"author contributions?|مشارکت پدیدآوران|مشارکت نویسندگان|"
        r"ما.?رکت پدید.?وران|"
        r"funding|financial support|منابع مالی|حمایت مالی|"
        r"ethics?|ethical considerations?|ملاحظات اخلاقی|"
        r"conflicts? of interests?|تعارض منافع|"
        r"article info|اطلاعات مقاله|publisher|ناشر|journal|مجله)",
        normalized,
    ):
        return "administrative"
    if unit_type in {"page_window", "semantic_window"}:
        return "body"
    return "section"


SUBSTANTIVE_ROLES = {
    "abstract",
    "introduction",
    "methodology",
    "findings",
    "discussion",
    "conclusion",
    "practical_implications",
    "body",
    "section",
}


def is_substantive_section(title: str, role: str | None = None) -> bool:
    """Classify summary scope without deleting queryable document metadata."""
    classified = _section_role(title, "section")
    effective = classified if classified != "section" else (role or "section")
    return effective in SUBSTANTIVE_ROLES and effective not in {"references", "administrative"}


def _unit(unit_type: str, title: str, order: int, blocks: list[dict[str, Any]]) -> DocumentUnit:
    content_blocks = [block for block in blocks if not PAGE_RE.match(block["text"])]
    selected = content_blocks or blocks
    text = "\n\n".join(block["text"] for block in selected)
    pages = [int(block["page"]) for block in selected if block.get("page")]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return DocumentUnit(
        unit_id=f"u{order:04d}-{digest[:10]}",
        order=order,
        unit_type=unit_type,
        role=_section_role(title, unit_type),
        title=title,
        char_start=min(block["start"] for block in selected),
        char_end=max(block["end"] for block in selected),
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        text_hash=digest,
    )


def _heading_units(blocks: list[dict[str, Any]], chapter_only: bool) -> list[DocumentUnit]:
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    current_title = "بخش آغازین"
    current: list[dict[str, Any]] = []
    current_heading_key = None
    for block in blocks:
        heading = HEADING_RE.match(block["text"])
        starts_unit = False
        title = None
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if chapter_only:
                chapter_match = CHAPTER_ID_RE.match(title)
                heading_key = (
                    f"{chapter_match.group(1)} {chapter_match.group(2)}".lower()
                    if chapter_match
                    else None
                )
                starts_unit = bool(heading_key and heading_key != current_heading_key)
            else:
                heading_key = re.sub(r"\s+", " ", title).strip().lower() if level <= 2 else None
                starts_unit = bool(heading_key and heading_key != current_heading_key)
        if starts_unit and any(not PAGE_RE.match(item["text"]) and not HEADING_RE.match(item["text"]) for item in current):
            groups.append((current_title, current))
            current = []
        elif starts_unit:
            current = []
        if starts_unit:
            current_title = title or current_title
            current_heading_key = heading_key
        current.append(block)
    if current and any(not PAGE_RE.match(item["text"]) and not HEADING_RE.match(item["text"]) for item in current):
        groups.append((current_title, current))
    return [_unit("chapter" if chapter_only else "section", title, i, group) for i, (title, group) in enumerate(groups, 1)]


def _page_units(blocks: list[dict[str, Any]]) -> list[DocumentUnit]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for block in blocks:
        if block.get("page") is not None:
            grouped.setdefault(int(block["page"]), []).append(block)
    pages = sorted(grouped)
    units = []
    for offset in range(0, len(pages), PAGES_PER_UNIT):
        page_slice = pages[offset:offset + PAGES_PER_UNIT]
        selected = [block for page in page_slice for block in grouped[page]]
        title = f"صفحات {page_slice[0]} تا {page_slice[-1]}" if len(page_slice) > 1 else f"صفحه {page_slice[0]}"
        units.append(_unit("page_window", title, len(units) + 1, selected))
    return units


def _semantic_units(blocks: list[dict[str, Any]]) -> list[DocumentUnit]:
    units = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for block in blocks:
        if PAGE_RE.match(block["text"]):
            continue
        block_chars = len(block["text"])
        if current and current_chars + block_chars > TARGET_FLAT_UNIT_CHARS:
            units.append(_unit("semantic_window", f"بخش {len(units) + 1}", len(units) + 1, current))
            current, current_chars = [], 0
        current.append(block)
        current_chars += block_chars
    if current:
        units.append(_unit("semantic_window", f"بخش {len(units) + 1}", len(units) + 1, current))
    return units


def build_document_map(markdown_text: str, profile: DocumentProfile) -> dict[str, Any]:
    blocks = _blocks(markdown_text)
    if profile.unit_strategy == "chapter":
        units = _heading_units(blocks, chapter_only=True)
    elif profile.unit_strategy in {"heading", "heading_or_semantic"}:
        units = _heading_units(blocks, chapter_only=False)
    elif profile.unit_strategy in {"page", "page_window"}:
        units = _page_units(blocks)
    else:
        units = _semantic_units(blocks)
    if not units and blocks:
        units = _semantic_units(blocks)
    return {
        "version": DOCUMENT_MAP_VERSION,
        "profile_version": profile.version,
        "document_type": profile.document_type,
        "unit_strategy": profile.unit_strategy,
        "content_hash": profile.content_hash,
        "units": [asdict(unit) for unit in units],
    }


def assign_chunks_to_units(chunks: list[dict[str, Any]], document_map: dict[str, Any]) -> list[dict[str, Any]]:
    units = document_map.get("units") or []
    for chunk in chunks:
        midpoint = (int(chunk.get("char_start") or 0) + int(chunk.get("char_end") or 0)) // 2
        parent = next(
            (unit for unit in units if int(unit["char_start"]) <= midpoint <= int(unit["char_end"])),
            None,
        )
        if parent is None and chunk.get("page"):
            page = int(chunk["page"])
            parent = next(
                (
                    unit for unit in units
                    if unit.get("page_start") is not None
                    and int(unit["page_start"]) <= page <= int(unit["page_end"])
                ),
                None,
            )
        if parent:
            chunk["parent_id"] = parent["unit_id"]
            chunk["parent_title"] = parent["title"]
            chunk["parent_type"] = parent["unit_type"]
            chunk["parent_role"] = parent.get("role")
            chunk["parent_page_start"] = parent.get("page_start")
            chunk["parent_page_end"] = parent.get("page_end")
    return chunks


def write_document_map(path: str, document_map: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document_map, handle, ensure_ascii=False, indent=2)
