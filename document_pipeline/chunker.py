"""Heading-aware Markdown chunker (Step 2).

Parses the canonical Markdown produced by ingest.py into chapter/section/
subsection-aware chunks, packing paragraphs/list-blocks greedily up to a
target size and never letting overlap text cross a heading boundary.

Pure, deterministic text processing -- no LLM calls, no network access.
"""
import re
from typing import Dict, List, Optional, Tuple

TARGET_CHARS = 1400   # ~350 tokens at a ~4 chars/token mixed Persian/English estimate
MAX_CHARS = 1900       # hard cap before a block is forced to split
OVERLAP_RATIO = 0.18   # ~18%, within the requested 15-20% range
# Chosen via the chunk-size A/B experiment (see eval/chunk_size_experiment_report.txt):
# the prior 2800/3600 target tripled chunk size during the structured reindex and
# diluted the LLM's context window enough to regress true-negative refusals (2/2 -> 1/2).
# 1400/1900 (Candidate B) fixed the regression, improved Recall@5 and MRR, and kept
# judge-faithfulness higher than the smaller 1000/1450 candidate.

PAGE_MARKER_RE = re.compile(r"^<!--\s*page:(\d+)\s*-->$")
HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?؟۔])\s+")


def _split_blocks_with_offsets(markdown_text: str) -> List[Tuple[str, int, int]]:
    """Split on blank-line separators, returning (text, start, end) offsets
    into the original string so callers can record exact char spans."""
    sep_re = re.compile(r"\n\s*\n+")
    blocks = []
    last_end = 0
    for m in sep_re.finditer(markdown_text):
        seg = markdown_text[last_end:m.start()]
        if seg.strip():
            blocks.append((seg, last_end, m.start()))
        last_end = m.end()
    seg = markdown_text[last_end:len(markdown_text)]
    if seg.strip():
        blocks.append((seg, last_end, len(markdown_text)))
    return blocks


def _hard_split_oversized(text: str, max_chars: int) -> List[str]:
    """Last-resort split of a single block that exceeds max_chars, at sentence
    boundaries, packed greedily so pieces stay under the cap where possible."""
    if len(text) <= max_chars:
        return [text]
    sentences = SENTENCE_SPLIT_RE.split(text)
    pieces = []
    cur = ""
    for s in sentences:
        candidate = (cur + " " + s).strip() if cur else s
        if len(candidate) > max_chars and cur:
            pieces.append(cur)
            cur = s
        else:
            cur = candidate
    if cur:
        pieces.append(cur)
    # A single sentence longer than max_chars on its own: hard-cut by length.
    final = []
    for p in pieces:
        if len(p) <= max_chars:
            final.append(p)
        else:
            for i in range(0, len(p), max_chars):
                final.append(p[i:i + max_chars])
    return final


def _overlap_tail(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return ""
    cut = len(text) - overlap_chars
    boundaries = [m.end() for m in SENTENCE_SPLIT_RE.finditer(text) if m.end() <= len(text)]
    snap_points = [b for b in boundaries if b >= cut]
    start = snap_points[0] if snap_points else cut
    return text[start:].strip()


def _pack_section_group(
    blocks: List[Dict],
    target_chars: int = TARGET_CHARS,
    max_chars: int = MAX_CHARS,
    overlap_ratio: float = OVERLAP_RATIO,
) -> List[Dict]:
    """blocks: list of {"text","start","end","page"} sharing the same
    chapter/section/subsection. Returns packed chunk dicts (without chapter/
    section/subsection, added by the caller)."""
    # Expand any oversized single block into multiple pseudo-blocks first.
    expanded = []
    for b in blocks:
        pieces = _hard_split_oversized(b["text"], max_chars)
        if len(pieces) == 1:
            expanded.append(b)
        else:
            for p in pieces:
                expanded.append({"text": p, "start": b["start"], "end": b["end"], "page": b["page"]})

    chunks = []
    cur_bodies: List[str] = []
    cur_start = None
    cur_end = None
    cur_page = None
    cur_len = 0
    overlap_chars = int(target_chars * overlap_ratio)
    prev_body = ""

    def flush():
        nonlocal cur_bodies, cur_start, cur_end, cur_page, cur_len, prev_body
        if not cur_bodies:
            return
        body = "\n\n".join(cur_bodies)
        tail = _overlap_tail(prev_body, overlap_chars) if chunks else ""
        full_text = f"{tail}\n\n{body}" if tail else body
        chunks.append({
            "text": full_text,
            "start": cur_start,
            "end": cur_end,
            "page": cur_page,
        })
        prev_body = body
        cur_bodies = []
        cur_len = 0

    for b in expanded:
        b_len = len(b["text"])
        if cur_bodies and cur_len + b_len > target_chars:
            flush()
        if not cur_bodies:
            cur_start = b["start"]
            cur_page = b["page"]
        cur_bodies.append(b["text"])
        cur_end = b["end"]
        cur_len += b_len
    flush()
    return chunks


def parse_markdown_to_chunks(markdown_text: str) -> List[Dict]:
    """Parse canonical Markdown into structure-aware chunks.

    Returns a list of dicts: chapter, section, subsection, page, chunk_index
    (1-based, global), char_start, char_end, text (raw chunk text, no header).
    """
    blocks = _split_blocks_with_offsets(markdown_text)

    chapter = section = subsection = None
    page = None
    section_groups: List[Dict] = []
    current_group = None

    def start_new_group():
        nonlocal current_group
        current_group = {
            "chapter": chapter, "section": section, "subsection": subsection,
            "blocks": [],
        }
        section_groups.append(current_group)

    for text, start, end in blocks:
        stripped = text.strip()
        m_page = PAGE_MARKER_RE.match(stripped)
        if m_page:
            page = int(m_page.group(1))
            continue
        m_head = HEADING_RE.match(stripped)
        if m_head:
            level = len(m_head.group(1))
            title = m_head.group(2).strip()
            if level == 1:
                chapter, section, subsection = title, None, None
            elif level == 2:
                section, subsection = title, None
            else:
                subsection = title
            current_group = None  # force a fresh group under the new heading
            continue
        if current_group is None or (
            current_group["chapter"] != chapter
            or current_group["section"] != section
            or current_group["subsection"] != subsection
        ):
            start_new_group()
        current_group["blocks"].append({"text": stripped, "start": start, "end": end, "page": page})

    chunks = []
    for group in section_groups:
        if not group["blocks"]:
            continue
        packed = _pack_section_group(group["blocks"])
        for p in packed:
            chunks.append({
                "chapter": group["chapter"],
                "section": group["section"],
                "subsection": group["subsection"],
                "page": p["page"],
                "char_start": p["start"],
                "char_end": p["end"],
                "text": p["text"],
            })

    for i, c in enumerate(chunks, start=1):
        c["chunk_index"] = i
    return chunks


def build_embedded_text(chunk: Dict) -> str:
    """The literal text stored/embedded in Chroma: a short contextual header
    (chapter/section/page, only the parts that are known) followed by the
    chunk's own text."""
    header_lines = []
    if chunk.get("chapter"):
        header_lines.append(f"Chapter: {chunk['chapter']}")
    if chunk.get("section"):
        header_lines.append(f"Section: {chunk['section']}")
    if chunk.get("subsection"):
        header_lines.append(f"Subsection: {chunk['subsection']}")
    if chunk.get("page"):
        header_lines.append(f"Page: {chunk['page']}")
    if not header_lines:
        return chunk["text"]
    return "\n".join(header_lines) + "\n\n" + chunk["text"]
