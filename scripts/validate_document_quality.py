"""Offline, human-auditable validation for the two private document fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from document_pipeline import chunker, document_map, ingest, profiling


LEGACY_OBSERVED = {
    "einsteinetal1935.pdf": {
        "document_type": "sectioned_report",
        "title": ".DESC RI PT ION OF P H YSI CAL REALITY",
        "headings": 9,
        "chunks": 13,
        "substantive_units": 1,
        "header_contamination": True,
    },
    "بررس ی انتقادی رو یکرد فلسفی د یوی د بوهم.pdf": {
        "document_type": "article_or_paper",
        "title": "Shinakht",
        "headings": 41,
        "chunks": 56,
        "substantive_units": 1,
        "header_contamination": True,
    },
}


def terms(text: str) -> set[str]:
    text = (text or "").translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه"})).lower()
    return {value for value in re.findall(r"[0-9a-z\u0600-\u06ff]{2,}", text) if len(value) > 1}


def ranked_chunks(question: str, chunks: list[dict], limit: int = 5) -> list[dict]:
    wanted = terms(question)
    scored = []
    for chunk in chunks:
        overlap = len(wanted & terms(" ".join([
            str(chunk.get("parent_title") or ""), str(chunk.get("text") or ""),
        ])))
        scored.append((overlap, -int(chunk.get("chunk_index") or 0), chunk))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[:limit] if item[0] > 0]


def hierarchy_chunks(case: dict, chunks: list[dict]) -> list[dict]:
    kind = case["kind"]
    role = {"abstract": "abstract", "introduction": "introduction", "conclusion": "conclusion"}.get(kind)
    if role:
        return [chunk for chunk in chunks if chunk.get("parent_role") == role]
    if kind == "full_summary":
        return [chunk for chunk in chunks if chunk.get("parent_role") != "references"]
    seeds = ranked_chunks(case["question"], chunks, limit=8)
    parents = []
    for seed in seeds:
        key = seed.get("parent_id") or seed.get("parent_title")
        if key not in parents:
            parents.append(key)
        if len(parents) >= (3 if "comparison" in kind or "relation" in kind else 1):
            break
    expanded = [chunk for chunk in chunks if (chunk.get("parent_id") or chunk.get("parent_title")) in parents]
    return expanded[:12]


def graph_candidate_chunks(case: dict, chunks: list[dict]) -> list[dict]:
    """Small section/concept graph candidate used only for architecture comparison."""
    groups: dict[str, list[dict]] = {}
    for chunk in chunks:
        key = str(chunk.get("parent_id") or chunk.get("parent_title") or chunk.get("chunk_index"))
        groups.setdefault(key, []).append(chunk)
    group_terms = {key: terms(" ".join(str(item.get("text") or "") for item in values)) for key, values in groups.items()}
    wanted = terms(case["question"])
    seeds = sorted(groups, key=lambda key: len(wanted & group_terms[key]), reverse=True)[:2]
    selected = set(seed for seed in seeds if wanted & group_terms[seed])
    for seed in list(selected):
        neighbors = sorted(
            (key for key in groups if key != seed),
            key=lambda key: len(group_terms[seed] & group_terms[key]),
            reverse=True,
        )[:1]
        selected.update(neighbors)
    return [chunk for key in groups if key in selected for chunk in groups[key]][:12]


def page_recall(selected: list[dict], expected: list[int]) -> float | None:
    if not expected:
        return None
    pages = {int(chunk["page"]) for chunk in selected if chunk.get("page")}
    return round(len(pages & set(expected)) / len(set(expected)), 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tests" / "quality" / "gold_expectations.json",
    )
    args = parser.parse_args()
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    report = {"documents": {}, "architecture_comparison": {}}
    hierarchy_scores = []
    graph_scores = []

    for filename, expectation in gold.items():
        path = args.fixture_dir / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if digest != expectation["sha256"]:
            raise SystemExit(f"fixture hash mismatch: {filename}")
        with path.open("rb") as handle:
            normalized = ingest.normalize_document(filename, handle, path.suffix)
        profile = profiling.profile_document(normalized["markdown_text"], normalized["meta"], filename=filename)
        doc_map = document_map.build_document_map(normalized["markdown_text"], profile)
        chunks = chunker.parse_markdown_to_chunks(normalized["markdown_text"])
        document_map.assign_chunks_to_units(chunks, doc_map)
        cases = []
        for case in expectation.get("cases", []):
            baseline = ranked_chunks(case["question"], chunks, limit=5)
            hierarchy = hierarchy_chunks(case, chunks)
            graph = graph_candidate_chunks(case, chunks)
            row = {
                "id": case["id"],
                "kind": case["kind"],
                "baseline_lexical_page_recall": page_recall(baseline, case.get("expected_pages") or []),
                "hierarchy_page_recall": page_recall(hierarchy, case.get("expected_pages") or []),
                "graph_candidate_page_recall": page_recall(graph, case.get("expected_pages") or []),
            }
            cases.append(row)
            if row["hierarchy_page_recall"] is not None:
                hierarchy_scores.append(row["hierarchy_page_recall"])
                graph_scores.append(row["graph_candidate_page_recall"] or 0.0)
        report["documents"][filename] = {
            "sha256": digest,
            "page_count": profile.page_count,
            "title": profile.title,
            "document_type": profile.document_type,
            "language": profile.language,
            "ocr_required": normalized["meta"].get("ocr_required"),
            "embedded_image_count": normalized["meta"].get("embedded_image_count"),
            "table_candidate_pages": normalized["meta"].get("table_candidate_pages"),
            "sections": [unit["title"] for unit in doc_map["units"]],
            "substantive_units": len([unit for unit in doc_map["units"] if unit.get("role") != "references"]),
            "chunks": len(chunks),
            "header_contamination": any(
                value in normalized["markdown_text"]
                for value in ("Print ISSN", "Shinakht is a persian word", "of lanthanum is 7/2")
            ),
            "cases": cases,
        }
    hierarchy_mean = sum(hierarchy_scores) / max(len(hierarchy_scores), 1)
    graph_mean = sum(graph_scores) / max(len(graph_scores), 1)
    report["architecture_comparison"] = {
        "legacy_observed": LEGACY_OBSERVED,
        "hierarchy_mean_expected_page_recall": round(hierarchy_mean, 3),
        "graph_candidate_mean_expected_page_recall": round(graph_mean, 3),
        "graph_retained": graph_mean > hierarchy_mean + 0.05,
        "decision": "section hierarchy and parent expansion" if graph_mean <= hierarchy_mean + 0.05 else "graph hybrid",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
