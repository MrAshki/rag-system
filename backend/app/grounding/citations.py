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
    task_instructions: str | None = None,
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
        f"{task_instructions or ''}\n"
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


def load_json_object(raw: str) -> dict[str, Any] | None:
    """Parse a provider JSON object through fenced, prefixed, or cut-off wrappers."""
    cleaned = FENCE_RE.sub("", (raw or "").strip()).strip()
    candidates = [cleaned]
    start = cleaned.find("{")
    if start > 0:
        candidates.append(cleaned[start:])
    for candidate in candidates:
        try:
            value, _end = json.JSONDecoder().raw_decode(candidate)
            return value if isinstance(value, dict) else None
        except (json.JSONDecodeError, TypeError):
            pass

    # Bounded repair for provider truncation that omitted only final object or
    # array delimiters. Never invent keys, values, or close a cut string.
    candidate = cleaned[start:] if start >= 0 else ""
    candidate = re.sub(r"\s*```$", "", candidate).strip()
    in_string = False
    escaped = False
    stack: list[str] = []
    for char in candidate:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack:
            if char != stack[-1]:
                return None
            stack.pop()
    if candidate and not in_string and stack:
        try:
            value = json.loads(candidate + "".join(reversed(stack)))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            pass
    return None


def _load_json(raw: str) -> dict[str, Any] | None:
    """Backward-compatible alias for the shared structured-output parser."""
    return load_json_object(raw)


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
        stripped = text.strip()
        if re.search(r"(?:\b(?:and|or|because|that|with)|(?:^|\s)(?:و|که|از|به|در))\s*$", stripped, re.IGNORECASE):
            return "truncated_output"
        if stripped.endswith(("-", "–", "—", ":")):
            return "unfinished_output"
        if not 1 <= len(evidence_ids) <= 3:
            return "citation_marker_format_invalid"
        normalized = [str(value or "").upper().replace("S", "E", 1) for value in evidence_ids]
        if any(not re.fullmatch(r"E\d+", value) for value in normalized):
            return "citation_marker_format_invalid"
        if any(int(value[1:]) < 1 or int(value[1:]) > evidence_count for value in normalized):
            return "citation_marker_format_invalid"
    return None


def repair_grounded_contract(raw: str, *, evidence_count: int) -> str | None:
    """Apply one bounded local repair to citation-format-only defects.

    The repair never invents text or evidence. It removes leaked inline
    markers, normalizes valid E/S identifiers, de-duplicates them, and narrows
    each paragraph to at most three existing evidence IDs.
    """
    payload = _load_json(raw)
    if not payload or not isinstance(payload.get("answerable"), bool):
        return None
    paragraphs = payload.get("paragraphs")
    if not isinstance(paragraphs, list):
        return None
    if payload["answerable"] is False:
        if paragraphs:
            return None
        return json.dumps(payload, ensure_ascii=False)

    repaired = []
    for item in paragraphs[:12]:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            return None
        text = _clean_paragraph(item["text"])
        ids = []
        for raw_id in item.get("evidence_ids") or []:
            evidence_id = str(raw_id or "").upper().replace("S", "E", 1)
            if (
                re.fullmatch(r"E\d+", evidence_id)
                and 1 <= int(evidence_id[1:]) <= evidence_count
                and evidence_id not in ids
            ):
                ids.append(evidence_id)
        if not text or not ids:
            return None
        repaired.append({"text": text, "evidence_ids": ids[:3]})
    if not repaired:
        return None
    candidate = json.dumps(
        {"answerable": True, "paragraphs": repaired},
        ensure_ascii=False,
    )
    return (
        candidate
        if grounded_contract_error(candidate, evidence_count=evidence_count) is None
        else None
    )


def _clean_paragraph(text: str) -> str:
    text = SOURCE_MARKER_RE.sub("", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.!?؟،؛:])", r"\1", text)
    return text


def _numeric_anchors(text: str) -> set[str]:
    """Normalize Persian digits and right-to-left decimal slash notation."""
    normalized = (text or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))

    def replace_slash(match: re.Match) -> str:
        left, right = match.group(1), match.group(2)
        if right == "0":
            return f"0.{left}"
        if left == "0":
            return f"0.{right}"
        return match.group(0)

    normalized = re.sub(r"(?<!\w)([0-9]{1,4})\s*/\s*([0-9]{1,4})(?!\w)", replace_slash, normalized)
    normalized = normalized.replace("٫", ".").replace(",", ".")
    return set(re.findall(r"(?<!\w)[0-9]+(?:\.[0-9]+)?", normalized))


def _claim_terms(text: str) -> set[str]:
    stopwords = {
        "است", "بود", "شد", "شده", "برای", "این", "آن", "در", "به", "از", "را", "که", "و", "با",
        "the", "a", "an", "is", "was", "were", "of", "to", "in", "and", "for", "with",
    }
    return {
        term
        for term in re.findall(r"[A-Za-z\u0600-\u06ff]{3,}", (text or "").lower())
        if term not in stopwords
    }


def _best_supporting_ids(
    *,
    text: str,
    proposed_ids: list[str],
    evidence: dict[str, dict[str, Any]],
) -> tuple[list[str], str]:
    """Narrow or repair a paragraph's evidence IDs inside the supplied context.

    Numeric claims are treated as a small set-cover problem: every number must
    occur on the finally cited page(s). This prevents a correct answer from
    carrying broad unrelated citations while allowing a bounded same-context
    repair when the provider chose the wrong evidence ID.
    """
    numbers = _numeric_anchors(text)
    quotes = [value.strip() for value in re.findall(r"[«\"“]([^»\"”]{3,})[»\"”]", text)]
    terms = _claim_terms(text)
    candidates = []
    proposed_scopes = {
        str(evidence[evidence_id].get("coverage_key") or "")
        for evidence_id in proposed_ids
        if evidence_id in evidence and evidence[evidence_id].get("coverage_key")
    }
    for evidence_id, chunk in evidence.items():
        chunk_text = str(chunk.get("text") or "")
        chunk_numbers = _numeric_anchors(chunk_text)
        covered_numbers = numbers & chunk_numbers
        quote_hits = sum(value in chunk_text for value in quotes)
        term_hits = len(terms & _claim_terms(chunk_text))
        proposed = evidence_id in proposed_ids
        if numbers and not covered_numbers:
            continue
        if quotes and not quote_hits and not covered_numbers:
            continue
        candidates.append({
            "id": evidence_id,
            "numbers": covered_numbers,
            "quotes": quote_hits,
            "terms": term_hits,
            "proposed": proposed,
            "scope_match": bool(
                proposed_scopes
                and str(chunk.get("coverage_key") or "") in proposed_scopes
            ),
            "page_width": max(
                0,
                int(chunk.get("page_end") or chunk.get("page") or 0)
                - int(chunk.get("page") or 0),
            ),
        })

    if not numbers:
        scoped = [
            item for item in candidates
            if item["scope_match"] and not item["proposed"] and item["terms"]
        ]
        if scoped:
            scoped.sort(
                key=lambda item: (
                    item["terms"],
                    item["quotes"],
                    -item["page_width"],
                ),
                reverse=True,
            )
            best_terms = scoped[0]["terms"]
            selected = [
                item["id"] for item in scoped
                if item["terms"] == best_terms
            ][:3]
            return selected, "repaired"
        retained = [
            item["id"]
            for item in candidates
            if item["proposed"] and (item["terms"] or item["quotes"] or not terms)
        ][:3]
        return (retained or proposed_ids[:3]), "retained"

    selected: list[str] = []
    remaining = set(numbers)
    while remaining and len(selected) < 3:
        ranked = sorted(
            candidates,
            key=lambda item: (
                len(item["numbers"] & remaining),
                item["scope_match"],
                item["proposed"],
                item["terms"],
                item["quotes"],
                -item["page_width"],
            ),
            reverse=True,
        )
        if not ranked or not (ranked[0]["numbers"] & remaining):
            break
        chosen = ranked[0]
        selected.append(chosen["id"])
        remaining -= chosen["numbers"]
        candidates = [item for item in candidates if item["id"] != chosen["id"]]
    if remaining:
        return [], "anchor_mismatch"
    if quotes:
        combined = "\n".join(str(evidence[value].get("text") or "") for value in selected)
        if any(value not in combined for value in quotes):
            return [], "quote_mismatch"
    return selected, "repaired" if selected != proposed_ids[:len(selected)] else "retained"


def parse_grounded_response(
    raw: str,
    *,
    chunks: list[dict[str, Any]],
    citation_label: Callable[[dict[str, Any]], str],
    no_info_message: str,
    verify_support: bool = False,
    support_scope_chunks: list[dict[str, Any]] | None = None,
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

    all_chunks = list(chunks)
    seen = {
        (
            str(chunk.get("document_id") or ""),
            str(chunk.get("source") or ""),
            int(chunk.get("page") or 0),
            int(chunk.get("chunk_index") or chunk.get("chunk") or -1),
            str(chunk.get("text") or ""),
        )
        for chunk in all_chunks
    }
    for chunk in support_scope_chunks or []:
        fingerprint = (
            str(chunk.get("document_id") or ""),
            str(chunk.get("source") or ""),
            int(chunk.get("page") or 0),
            int(chunk.get("chunk_index") or chunk.get("chunk") or -1),
            str(chunk.get("text") or ""),
        )
        if fingerprint not in seen:
            seen.add(fingerprint)
            all_chunks.append(chunk)
    evidence = {
        f"E{index}": chunk for index, chunk in enumerate(all_chunks, 1)
    }
    rendered_sources: list[str] = []
    source_positions: dict[str, int] = {}
    rendered_paragraphs = []
    used_evidence_ids: list[str] = []
    proposed_evidence_ids: list[str] = []
    support_results: list[dict[str, Any]] = []
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

        support_status = "not_checked"
        if verify_support:
            ids, support_status = _best_supporting_ids(
                text=text,
                proposed_ids=ids,
                evidence=evidence,
            )
            if not ids:
                rejected += 1
                support_results.append({"status": support_status, "evidence_ids": ids})
                continue
        for evidence_id in [
            str(raw_id or "").upper().replace("S", "E", 1)
            for raw_id in (item.get("evidence_ids") or [])[:3]
        ]:
            if evidence_id in evidence and evidence_id not in proposed_evidence_ids:
                proposed_evidence_ids.append(evidence_id)
        support_results.append({"status": support_status, "evidence_ids": ids})
        for evidence_id in ids:
            if evidence_id not in used_evidence_ids:
                used_evidence_ids.append(evidence_id)

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
            "support": support_results,
        },
        "used_evidence_ids": used_evidence_ids,
        "proposed_evidence_ids": proposed_evidence_ids,
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
