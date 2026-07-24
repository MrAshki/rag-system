from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ROUTES = {
    "focused_rag", "specific_section", "analytical", "comprehensive_summary",
    "conversational_followup", "retry_previous", "free_chat",
}
RETRIEVAL_POLICIES = {"required", "allowed", "forbidden"}


class GoldSetValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise GoldSetValidationError([f"{path}:{number}: malformed JSON: {exc}"]) from exc
    return rows


def validate_goldset(base: Path, pdf_dir: Path, *, verify_source_hashes: bool = True) -> dict:
    errors: list[str] = []
    manifest = load_jsonl(base / "manifest.jsonl")
    tasks = load_jsonl(base / "tasks.jsonl")
    conversations = load_jsonl(base / "conversations.jsonl")
    qrels = json.loads((base / "qrels.json").read_text(encoding="utf-8"))
    schema = json.loads((base / "schema.json").read_text(encoding="utf-8"))
    if "$defs" not in schema:
        errors.append("schema.json: missing $defs")

    filenames = [row.get("filename") for row in manifest]
    if len(filenames) != len(set(filenames)):
        errors.append("manifest: duplicate filenames")
    hashes = [row.get("sha256") for row in manifest]
    if any(not re.fullmatch(r"[0-9a-f]{64}", str(value or "")) for value in hashes):
        errors.append("manifest: invalid or missing SHA-256")
    by_file = {row["filename"]: row for row in manifest if row.get("filename")}

    for row in manifest:
        filename = row.get("filename")
        source = pdf_dir / filename
        if not source.exists():
            errors.append(f"manifest:{filename}: source PDF missing")
            continue
        if verify_source_hashes:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if digest != row.get("sha256"):
                errors.append(f"manifest:{filename}: SHA-256 mismatch")
        try:
            pages = len(PdfReader(source).pages)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"manifest:{filename}: unreadable PDF: {exc}")
            continue
        if pages != row.get("page_count"):
            errors.append(f"manifest:{filename}: page count {row.get('page_count')} != {pages}")

    query_ids = [row.get("query_id") for row in tasks]
    duplicates = sorted({value for value in query_ids if query_ids.count(value) > 1})
    if duplicates:
        errors.append(f"tasks: duplicate query IDs: {duplicates}")
    for row in tasks:
        query_id = row.get("query_id", "<missing>")
        doc = by_file.get(row.get("filename"))
        if not doc:
            errors.append(f"task:{query_id}: unknown filename")
            continue
        if not row.get("document_sha256") or row.get("document_sha256") != doc.get("sha256"):
            errors.append(f"task:{query_id}: missing or mismatched document hash")
        pages = row.get("relevant_pages")
        if not isinstance(pages, list):
            errors.append(f"task:{query_id}: relevant_pages must be a list")
            pages = []
        invalid_pages = [page for page in pages if not isinstance(page, int) or page < 1 or page > doc["page_count"]]
        if invalid_pages:
            errors.append(f"task:{query_id}: invalid page(s) {invalid_pages}")
        if row.get("expected_route") not in ROUTES:
            errors.append(f"task:{query_id}: invalid route {row.get('expected_route')!r}")
        if row.get("retrieval_policy") not in RETRIEVAL_POLICIES:
            errors.append(f"task:{query_id}: invalid retrieval policy")
        answerability = row.get("answerability")
        if answerability == "answerable" and not pages:
            errors.append(f"task:{query_id}: answerable task has no evidence page")
        if answerability == "unanswerable" and not row.get("forbidden_claims"):
            errors.append(f"task:{query_id}: unanswerable task lacks forbidden-claim guard")
        if answerability == "conflicting" and len(pages) < 2:
            errors.append(f"task:{query_id}: conflicting task needs at least two evidence pages")
        if answerability == "ambiguous" and len(pages) < 2:
            errors.append(f"task:{query_id}: ambiguous task needs multiple candidate pages")
        evidence_pages = [item.get("page") for item in row.get("evidence_descriptions", [])]
        if evidence_pages != pages:
            errors.append(f"task:{query_id}: evidence descriptions do not align with relevant_pages")
        if row.get("task_type") == "comprehensive_summary":
            required = {
                "required_sections", "required_key_claims", "conclusion_required",
                "argument_structure_items", "contamination_blacklist",
                "minimum_page_diversity", "administrative_sections_to_exclude",
            }
            missing = sorted(required - row.keys())
            if missing:
                errors.append(f"task:{query_id}: summary fields missing: {missing}")
        if row.get("table_identifier"):
            required = {
                "table_page", "expected_row", "expected_column",
                "expected_value", "acceptable_numeric_formats",
            }
            missing = sorted(required - row.keys())
            if missing:
                errors.append(f"task:{query_id}: table fields missing: {missing}")

    conversation_ids = [row.get("conversation_id") for row in conversations]
    if len(conversation_ids) != len(set(conversation_ids)):
        errors.append("conversations: duplicate conversation IDs")
    for conversation in conversations:
        conversation_id = conversation.get("conversation_id", "<missing>")
        doc = by_file.get(conversation.get("filename"))
        if not doc or conversation.get("document_sha256") != doc.get("sha256"):
            errors.append(f"conversation:{conversation_id}: missing/mismatched document")
        turns = conversation.get("turns") or []
        expected_ids = [f"t{index}" for index in range(1, len(turns) + 1)]
        actual_ids = [turn.get("turn_id") for turn in turns]
        if actual_ids != expected_ids:
            errors.append(f"conversation:{conversation_id}: malformed turn ordering {actual_ids}")
        seen: set[str] = set()
        for turn in turns:
            turn_id = turn.get("turn_id", "<missing>")
            antecedent = turn.get("antecedent")
            if antecedent is not None and antecedent not in seen:
                errors.append(f"conversation:{conversation_id}:{turn_id}: antecedent is not earlier")
            if turn.get("must_use_history") and not antecedent:
                errors.append(f"conversation:{conversation_id}:{turn_id}: history required without antecedent")
            if turn.get("expected_route") not in ROUTES:
                errors.append(f"conversation:{conversation_id}:{turn_id}: invalid route")
            if turn.get("retrieval_policy") not in RETRIEVAL_POLICIES:
                errors.append(f"conversation:{conversation_id}:{turn_id}: invalid retrieval policy")
            seen.add(turn_id)

    qrel_queries = qrels.get("queries", {})
    if set(qrel_queries) != set(query_ids):
        errors.append("qrels: query ID set differs from tasks.jsonl")
    for row in tasks:
        judgments = qrel_queries.get(row["query_id"], [])
        judged_pages = [item.get("page") for item in judgments]
        if judged_pages != row["relevant_pages"]:
            errors.append(f"qrels:{row['query_id']}: pages differ from task")
        if any(item.get("document_sha256") != row["document_sha256"] for item in judgments):
            errors.append(f"qrels:{row['query_id']}: document hash mismatch")

    if not 60 <= len(tasks) <= 75:
        errors.append(f"tasks: expected 60..75, got {len(tasks)}")
    turn_count = sum(len(row.get("turns", [])) for row in conversations)
    if not 8 <= len(conversations) <= 12:
        errors.append(f"conversations: expected 8..12, got {len(conversations)}")
    if turn_count < 20:
        errors.append(f"conversations: expected at least 20 turns, got {turn_count}")
    if len(manifest) != 20:
        errors.append(f"manifest: expected 20 documents, got {len(manifest)}")
    if errors:
        raise GoldSetValidationError(errors)
    return {
        "documents": len(manifest),
        "pages": sum(row["page_count"] for row in manifest),
        "tasks": len(tasks),
        "conversations": len(conversations),
        "conversation_turns": turn_count,
        "source_hashes_verified": verify_source_hashes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goldset", type=Path, default=ROOT / "evaluation" / "dev_goldset")
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "composite_goldset_pdfs")
    parser.add_argument("--skip-source-hashes", action="store_true")
    args = parser.parse_args()
    result = validate_goldset(args.goldset, args.pdf_dir, verify_source_hashes=not args.skip_source_hashes)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
