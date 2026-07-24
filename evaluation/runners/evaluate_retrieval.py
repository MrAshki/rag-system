from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.metrics.retrieval import (  # noqa: E402
    evaluate_rankings,
    evidence_set_recall,
    expected_document_recall,
    expected_page_recall,
)
from evaluation.runners.evaluate_ingestion import load_jsonl  # noqa: E402


TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    normalized = (text or "").casefold().translate(str.maketrans("كي", "کی"))
    return [token for token in TOKEN_RE.findall(normalized) if len(token) > 1]


def build_page_index(manifest: list[dict], pdf_dir: Path) -> list[dict]:
    pages = []
    for doc in manifest:
        reader = PdfReader(pdf_dir / doc["filename"])
        for page_number, page in enumerate(reader.pages, start=1):
            tokens = tokenize(page.extract_text() or "")
            pages.append({
                "evidence_id": f"{doc['sha256']}#page={page_number}",
                "document_sha256": doc["sha256"],
                "filename": doc["filename"],
                "page": page_number,
                "tokens": tokens,
                "tf": Counter(tokens),
            })
    return pages


def rank_bm25(query: str, pages: list[dict], top_k: int = 10) -> list[dict]:
    query_tokens = tokenize(query)
    document_frequency = Counter()
    for token in set(query_tokens):
        document_frequency[token] = sum(token in page["tf"] for page in pages)
    average_length = sum(len(page["tokens"]) for page in pages) / len(pages)
    scored = []
    for page in pages:
        score = 0.0
        length = len(page["tokens"])
        for token in query_tokens:
            tf = page["tf"].get(token, 0)
            if not tf:
                continue
            df = document_frequency[token]
            idf = math.log(1 + (len(pages) - df + 0.5) / (df + 0.5))
            score += idf * tf * 2.2 / (tf + 1.2 * (1 - 0.75 + 0.75 * length / average_length))
        if score:
            scored.append({key: page[key] for key in ("evidence_id", "document_sha256", "filename", "page")} | {"score": score})
    return sorted(scored, key=lambda item: (-item["score"], item["evidence_id"]))[:top_k]


def run_isolated_index(goldset: Path, pdf_dir: Path) -> dict:
    manifest = load_jsonl(goldset / "manifest.jsonl")
    tasks = load_jsonl(goldset / "tasks.jsonl")
    pages = build_page_index(manifest, pdf_dir)
    qrel_payload = json.loads((goldset / "qrels.json").read_text(encoding="utf-8"))["queries"]
    qrels = {
        query_id: {item["evidence_id"]: item["relevance"] for item in rows}
        for query_id, rows in qrel_payload.items()
        if rows
    }
    ranked = {
        task["query_id"]: rank_bm25(
            task["query"],
            [page for page in pages if page["document_sha256"] == task["document_sha256"]],
            10,
        )
        for task in tasks
        if task["query_id"] in qrels
    }
    run = {query_id: [item["evidence_id"] for item in rows] for query_id, rows in ranked.items()}
    result = evaluate_rankings(qrels, run)
    task_by_id = {task["query_id"]: task for task in tasks}
    supplemental = {}
    for query_id, retrieved in ranked.items():
        task = task_by_id[query_id]
        supplemental[query_id] = {
            "expected_page_recall": expected_page_recall(task["relevant_pages"], retrieved),
            "expected_document_recall": expected_document_recall([task["document_sha256"]], retrieved),
            "evidence_set_recall": evidence_set_recall(qrels[query_id], retrieved),
            "retrieved": retrieved,
        }
    for name in ("expected_page_recall", "expected_document_recall", "evidence_set_recall"):
        values = [row[name] for row in supplemental.values()]
        result["means"][name] = sum(values) / len(values) if values else 0.0
    result["per_task_evidence"] = supplemental
    result["index"] = {
        "kind": "isolated_deterministic_pdf_page_bm25",
        "scope": "selected_document",
        "documents": len(manifest),
        "pages": len(pages),
        "network_calls": 0,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goldset", type=Path, default=ROOT / "evaluation" / "dev_goldset")
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "composite_goldset_pdfs")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_isolated_index(args.goldset, args.pdf_dir)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("query_count", "means", "index")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
