"""Structured grounded-answer contract and deterministic citation rendering."""
from __future__ import annotations

import json
import re
from typing import Any, Callable


FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
SOURCE_MARKER_RE = re.compile(r"\[(?:S|E)(\d+)\]")


def build_grounded_messages(
    *,
    question: str,
    chunks: list[dict[str, Any]],
    citation_label: Callable[[dict[str, Any]], str],
    no_info_message: str,
    language: str,
    selected_source: str | None = None,
) -> list[dict[str, str]]:
    evidence = "\n\n".join(
        f"<evidence id=\"E{index}\" source=\"{citation_label(chunk)}\">\n{chunk['text']}\n</evidence>"
        for index, chunk in enumerate(chunks, 1)
    )
    language_rule = "Write fluent Persian." if language == "fa" else "Write fluent English."
    scope_rule = f'Use only the selected document "{selected_source}".' if selected_source else ""
    source_names = {str(chunk.get("source") or "") for chunk in chunks if chunk.get("source")}
    multi_source_rule = (
        "When the user asks for a comparison, support every side of the comparison "
        "with evidence from its corresponding document; do not describe an uncited side."
        if len(source_names) > 1
        else ""
    )
    schema = (
        '{"answerable": true, "paragraphs": ['
        '{"text": "paragraph without citation markers", "evidence_ids": ["E1", "E2"]}'
        "]}"
    )
    system = (
        "Answer the user's question using only the evidence blocks. "
        f"{language_rule} {scope_rule} {multi_source_rule}\n"
        "Do not use outside knowledge. If the evidence is insufficient, set answerable=false. "
        "Every factual paragraph must list one to three exact evidence IDs that best support that paragraph. "
        "Keep separate topics in separate paragraphs instead of attaching many citations to one paragraph. "
        "Never put citations, source IDs, a Sources section, or footnotes inside paragraph text. "
        "Use cohesive paragraphs; do not use bullets or headings unless the user explicitly asks for them. "
        "Do not attribute a claim to a named person unless that person's name appears in the cited evidence.\n"
        "Return only valid JSON matching this schema:\n"
        f"{schema}\n"
        f'For an unanswerable question return: {{"answerable": false, "paragraphs": [], "message": "{no_info_message}"}}'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Evidence:\n{evidence}\n\nQuestion: {question}"},
    ]


def _load_json(raw: str) -> dict[str, Any] | None:
    cleaned = FENCE_RE.sub("", (raw or "").strip()).strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(cleaned[start:end + 1])
                return value if isinstance(value, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def grounded_contract_error(raw: str, *, evidence_count: int) -> str | None:
    """Return a stable fallback reason when the structured answer contract is invalid."""
    if not (raw or "").strip():
        return "primary_response_missing"
    payload = _load_json(raw)
    if payload is None:
        return "invalid_json"
    if not isinstance(payload.get("answerable"), bool):
        return "schema_validation_failure"
    paragraphs = payload.get("paragraphs")
    if not isinstance(paragraphs, list):
        return "required_response_fields_missing"
    if payload["answerable"] is False:
        return None if not paragraphs else "schema_validation_failure"
    if not paragraphs:
        return "schema_validation_failure"
    for item in paragraphs[:12]:
        if not isinstance(item, dict):
            return "schema_validation_failure"
        text = item.get("text")
        evidence_ids = item.get("evidence_ids")
        if not isinstance(text, str) or not text.strip() or not isinstance(evidence_ids, list):
            return "required_response_fields_missing"
        if SOURCE_MARKER_RE.search(text):
            return "citation_marker_format_invalid"
        if not 1 <= len(evidence_ids) <= 3:
            return "citation_marker_format_invalid"
        normalized = [str(value or "").upper().replace("S", "E", 1) for value in evidence_ids]
        if any(not re.fullmatch(r"E\d+", value) for value in normalized):
            return "citation_marker_format_invalid"
        if any(int(value[1:]) < 1 or int(value[1:]) > evidence_count for value in normalized):
            return "citation_marker_format_invalid"
    return None


def _clean_paragraph(text: str) -> str:
    text = SOURCE_MARKER_RE.sub("", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.!?؟،؛:])", r"\1", text)
    return text


def parse_grounded_response(
    raw: str,
    *,
    chunks: list[dict[str, Any]],
    citation_label: Callable[[dict[str, Any]], str],
    no_info_message: str,
) -> dict[str, Any]:
    payload = _load_json(raw)
    if not payload:
        return {
            "answer": "پاسخ مدل ساختار قابل اعتبارسنجی نداشت؛ لطفاً دوباره تلاش کنید.",
            "sources": [],
            "citation_validation": {"status": "invalid_json", "paragraphs": 0},
        }
    if payload.get("answerable") is False:
        return {
            "answer": no_info_message,
            "sources": [],
            "citation_validation": {"status": "unanswerable", "paragraphs": 0},
        }

    evidence = {f"E{index}": chunk for index, chunk in enumerate(chunks, 1)}
    rendered_sources: list[str] = []
    source_positions: dict[str, int] = {}
    rendered_paragraphs = []
    rejected = 0

    for item in (payload.get("paragraphs") or [])[:12]:
        if not isinstance(item, dict):
            rejected += 1
            continue
        text = _clean_paragraph(str(item.get("text") or ""))
        ids = []
        for raw_id in (item.get("evidence_ids") or [])[:3]:
            evidence_id = str(raw_id or "").upper().replace("S", "E", 1)
            if evidence_id in evidence and evidence_id not in ids:
                ids.append(evidence_id)
        if not text or not ids:
            rejected += 1
            continue

        markers = []
        for evidence_id in ids:
            label = citation_label(evidence[evidence_id])
            if label not in source_positions:
                rendered_sources.append(label)
                source_positions[label] = len(rendered_sources)
            marker = f"[S{source_positions[label]}]"
            if marker not in markers:
                markers.append(marker)
        rendered_paragraphs.append(f"{text} {' '.join(markers)}")

    if not rendered_paragraphs:
        return {
            "answer": no_info_message,
            "sources": [],
            "citation_validation": {"status": "no_supported_paragraphs", "paragraphs": 0, "rejected": rejected},
        }
    return {
        "answer": "\n\n".join(rendered_paragraphs),
        "sources": rendered_sources,
        "citation_validation": {
            "status": "validated",
            "paragraphs": len(rendered_paragraphs),
            "rejected": rejected,
        },
    }


def normalize_citations_at_paragraph_end(text: str, sources: list[str]) -> dict[str, Any]:
    """Repair legacy map-stage text while preserving source-index alignment."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text or "") if part.strip()]
    rendered = []
    used_indexes = set()
    for paragraph in paragraphs:
        indexes = []
        for match in SOURCE_MARKER_RE.finditer(paragraph):
            index = int(match.group(1))
            if 1 <= index <= len(sources) and index not in indexes:
                indexes.append(index)
                used_indexes.add(index)
        clean = _clean_paragraph(paragraph)
        if not clean:
            continue
        markers = " ".join(f"[S{index}]" for index in indexes)
        rendered.append(f"{clean} {markers}".strip())
    return {
        "answer": "\n\n".join(rendered),
        # Keep positional alignment because existing S indexes are preserved.
        "sources": sources if used_indexes else [],
    }
