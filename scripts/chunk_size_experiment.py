"""Chunk-size A/B experiment (read-only against the live index).

Compares the CURRENT live structured index (baseline) against two candidate
chunk sizes, WITHOUT touching the live collection:

  - Baseline : current live collection `document_qa_collection_local`
               (queried read-only; never rebuilt/overwritten/deleted).
  - Candidate A : target ~1000 chars / max ~1450  (smaller chunks)
  - Candidate B : target ~1400 chars / max ~1900  (medium chunks)

Candidates are built in-memory from the SAME sources/builders the live index
was built from (Questline_Theory.docx + cosmeticorexia_fa.txt via ingest, and
determaind via converted/determaind.md adapter), then indexed into TEMPORARY
collections that live in a SEPARATE chromadb client at a scratchpad path -- so
the production store on disk is never written to at all for the candidates.

Strict rules honored:
  * Live collection is never modified/rebuilt/overwritten/deleted.
  * Every Chroma collection (temp client included) is created/accessed with the
    project embedding function rag.embedding_fn (./models/bge-m3). The Chroma
    default ONNX/all-MiniLM-L6-v2 is never triggered.
  * ENABLE_LLM_NORMALIZATION stays false (asserted). No OCR. No reranker/BM25/
    hybrid/query-rewrite. No external API. Nothing downloaded/installed.

Usage (PowerShell, from the project venv):
    .\\venv\\Scripts\\python.exe scripts\\chunk_size_experiment.py
"""
import functools
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "eval"))
sys.stdout.reconfigure(encoding="utf-8")

import chromadb  # noqa: E402
import chunker  # noqa: E402
import ingest  # noqa: E402
import rag  # noqa: E402
import run_eval  # noqa: E402  (eval/run_eval.py)

assert os.getenv("ENABLE_LLM_NORMALIZATION", "false").lower() != "true", (
    "ENABLE_LLM_NORMALIZATION must stay false for this experiment; aborting."
)

DOCS_DIR = os.path.join(ROOT, "docs")
EVAL_DIR = os.path.join(ROOT, "eval")
GOLDEN = os.path.join(EVAL_DIR, "golden_set.json")

SCRATCH = os.environ.get(
    "CLAUDE_SCRATCH",
    r"C:\Users\ashkriz\AppData\Local\Temp\claude\d--rag-system\f9a265c6-180b-4699-b538-ae4c22c7aac6\scratchpad",
)
EXP_CHROMA_PATH = os.path.join(SCRATCH, "chroma_exp")

DETERMAIND_ID = "34038160b1a44b129f8f3c05cccd07fe"
QUESTLINE_ID = "48480f24643b40fbb0b04f4a5f2e9634"
COSMETIC_ID = "a5ee20ddba014770843204d0b12dffe7"

# ---------------------------------------------------------------------------
# determaind.md adapter (identical logic to scripts/structured_reindex.py)
# ---------------------------------------------------------------------------
_PAGEBREAK_RE = re.compile(r'<span[^>]*class="pagebreak"[^>]*>\s*</span>')
_ANY_TAG_RE = re.compile(r"<[^>]+>")


def clean_determaind_md(raw_md: str) -> str:
    text = _PAGEBREAK_RE.sub("", raw_md)
    text = _ANY_TAG_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_determaind_chunks():
    raw_md = open(os.path.join(ROOT, "converted", "determaind.md"), encoding="utf-8").read()
    cleaned_md = clean_determaind_md(raw_md)
    return chunker.parse_markdown_to_chunks(cleaned_md)


def build_chunks_from_upload(document_id, ext):
    path = os.path.join(DOCS_DIR, f"{document_id}{ext}")
    with open(path, "rb") as f:
        raw = f.read()
    normalized = ingest.normalize_document("placeholder", io.BytesIO(raw), ext)
    return chunker.parse_markdown_to_chunks(normalized["markdown_text"])


DOCS = [
    {"document_id": QUESTLINE_ID, "source": "Questline_Theory.docx", "type": "docx",
     "builder": lambda: build_chunks_from_upload(QUESTLINE_ID, ".docx")},
    {"document_id": COSMETIC_ID, "source": "cosmeticorexia_fa.txt", "type": "txt",
     "builder": lambda: build_chunks_from_upload(COSMETIC_ID, ".txt")},
    {"document_id": DETERMAIND_ID, "source": "determaind.txt", "type": "txt",
     "builder": build_determaind_chunks},
]

USER_ID = 3

# Determined sections to verify are preserved (searched case-insensitively in the
# stored/embedded text, which includes the chapter/section/subsection header).
SECTION_MARKERS = {
    "Free Won't": ["free won"],
    "The Final Three Minutes of a Movie": ["final three minutes of a movie"],
    "Where Does Intent Come From": ["where does intent come from"],
    "chaos/unpredictability": ["chaos", "unpredictab"],
    "quantum/randomness": ["quantum", "random"],
    "change under determinism / Ancient Gears": ["ancient gears"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def patched_pack(target, maxc, overlap=0.18):
    """Context manager: rebind chunker._pack_section_group with new sizes."""
    orig = chunker._pack_section_group

    class _Ctx:
        def __enter__(self):
            chunker._pack_section_group = functools.partial(
                orig, target_chars=target, max_chars=maxc, overlap_ratio=overlap
            )

        def __exit__(self, *a):
            chunker._pack_section_group = orig

    return _Ctx()


def chunk_len_stats(lengths):
    if not lengths:
        return {"count": 0, "avg_len": 0, "min_len": 0, "max_len": 0}
    return {
        "count": len(lengths),
        "avg_len": sum(lengths) // len(lengths),
        "min_len": min(lengths),
        "max_len": max(lengths),
    }


def section_preservation(embedded_texts):
    blob = "\n".join(embedded_texts).lower()
    out = {}
    for label, kws in SECTION_MARKERS.items():
        matched = [kw for kw in kws if kw in blob]
        out[label] = {"present": bool(matched), "matched_keywords": matched}
    return out


def measure_context_tokens(collection, questions, top_k=5):
    """Avg chars/tokens of the top-k retrieved context the generator would receive
    (run_eval feeds top5 to generate_response). Retrieval only -- no LLM call."""
    prev = rag.collection
    rag.collection = collection
    try:
        per_q_chars = []
        for q in questions:
            chunks = rag.query_documents(q, n_results=top_k, document_id=None, user_id=None)
            per_q_chars.append(sum(len(c.get("text") or "") for c in chunks[:top_k]))
    finally:
        rag.collection = prev
    avg_chars = (sum(per_q_chars) / len(per_q_chars)) if per_q_chars else 0
    return {
        "avg_context_chars_top5": round(avg_chars, 1),
        "approx_avg_context_tokens_top5": round(avg_chars / 4, 1),  # ~4 chars/token
        "max_context_chars_top5": max(per_q_chars) if per_q_chars else 0,
    }


def build_candidate(target, maxc):
    """Build the 3 docs' chunks at the given size; return per-doc chunk lists +
    raw-text stats + determaind section preservation."""
    built = {}
    with patched_pack(target, maxc):
        for d in DOCS:
            built[d["document_id"]] = d["builder"]()
    per_doc = {}
    total = 0
    for d in DOCS:
        chunks = built[d["document_id"]]
        per_doc[d["source"]] = chunk_len_stats([len(c["text"]) for c in chunks])
        total += len(chunks)
    det_embedded = [chunker.build_embedded_text(c) for c in built[DETERMAIND_ID]]
    return {
        "built": built,
        "total_chunks": total,
        "per_doc": per_doc,
        "section_preservation": section_preservation(det_embedded),
    }


def index_into_temp(exp_client, coll_name, built):
    try:
        exp_client.delete_collection(name=coll_name)
    except Exception:
        pass
    coll = exp_client.get_or_create_collection(
        name=coll_name, embedding_function=rag.embedding_fn
    )
    prev = rag.collection
    rag.collection = coll
    try:
        for d in DOCS:
            rag.index_chunks(
                filename=d["source"],
                chunks=built[d["document_id"]],
                document_id=d["document_id"],
                user_id=USER_ID,
                source_file_type=d["type"],
                normalized_md_path=None,
            )
    finally:
        rag.collection = prev
    return coll


def run_eval_against(collection, tag):
    """Point rag.collection at `collection`, run the full eval (with judge), restore."""
    prev = rag.collection
    rag.collection = collection
    try:
        report = run_eval.run(
            GOLDEN,
            os.path.join(EVAL_DIR, f"chunk_exp_{tag}_report.json"),
            os.path.join(EVAL_DIR, f"chunk_exp_{tag}_report.txt"),
            n_results=10,
            use_judge=True,
        )
    finally:
        rag.collection = prev
    return report["aggregate"]


def baseline_chunk_stats_from_live():
    """Read-only per-doc stats from the live collection's stored documents, plus
    determaind section preservation from the actual indexed text."""
    per_doc = {}
    total = 0
    det_embedded = []
    for d in DOCS:
        data = rag.collection.get(where={"document_id": d["document_id"]}, include=["documents"])
        docs = data.get("documents") or []
        per_doc[d["source"]] = chunk_len_stats([len(x) for x in docs])
        total += len(docs)
        if d["document_id"] == DETERMAIND_ID:
            det_embedded = docs
    return total, per_doc, section_preservation(det_embedded)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("CHUNK-SIZE A/B EXPERIMENT (live collection is read-only)")
    print("=" * 70)
    print(f"Embedding model : {rag.EMBEDDING_MODEL} (project model; Chroma default NOT used)")
    print(f"Ollama model    : {rag.OLLAMA_MODEL}")
    print(f"Live collection : {rag.COLLECTION_NAME} (count={rag.collection.count()}) -- NEVER modified")
    print(f"Temp Chroma path: {EXP_CHROMA_PATH} (separate client; production store untouched)")
    print(f"ENABLE_LLM_NORMALIZATION: {os.getenv('ENABLE_LLM_NORMALIZATION', '(unset->false)')}")

    with open(GOLDEN, encoding="utf-8") as f:
        questions = [it["question_fa"] for it in json.load(f)["items"]]

    os.makedirs(EXP_CHROMA_PATH, exist_ok=True)
    exp_client = chromadb.PersistentClient(path=EXP_CHROMA_PATH)

    results = {}

    # ---- Baseline (live, read-only) ----
    print("\n--- BASELINE (live collection, read-only) ---")
    base_total, base_per_doc, base_sections = baseline_chunk_stats_from_live()
    base_ctx = measure_context_tokens(rag.collection, questions)
    print("Running full eval against live collection ...")
    base_agg = run_eval_against(rag.collection, "baseline")
    results["baseline"] = {
        "collection_name": rag.COLLECTION_NAME,
        "total_chunks": base_total,
        "per_doc": base_per_doc,
        "context": base_ctx,
        "section_preservation": base_sections,
        "eval": base_agg,
    }

    # ---- Candidates ----
    candidates = [
        ("candidateA_1000", 1000, 1450, "exp_a_1000"),
        ("candidateB_1400", 1400, 1900, "exp_b_1400"),
    ]
    for tag, target, maxc, coll_name in candidates:
        print(f"\n--- {tag}: target={target} max={maxc} ---")
        cand = build_candidate(target, maxc)
        print(f"  built total_chunks={cand['total_chunks']}")
        coll = index_into_temp(exp_client, coll_name, cand["built"])
        ctx = measure_context_tokens(coll, questions)
        print("  Running full eval ...")
        agg = run_eval_against(coll, tag)
        results[tag] = {
            "collection_name": coll_name,
            "temp_chroma_path": EXP_CHROMA_PATH,
            "target_chars": target,
            "max_chars": maxc,
            "total_chunks": cand["total_chunks"],
            "per_doc": cand["per_doc"],
            "context": ctx,
            "section_preservation": cand["section_preservation"],
            "eval": agg,
        }

    # ---- Write combined report ----
    out_json = os.path.join(EVAL_DIR, "chunk_size_experiment_report.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    write_combined_txt(os.path.join(EVAL_DIR, "chunk_size_experiment_report.txt"), results)
    print(f"\nDONE. Combined report: {out_json}")
    print("Temp collections retained for inspection:",
          ", ".join(c[3] for c in candidates), f"(at {EXP_CHROMA_PATH})")


def write_combined_txt(path, results):
    def fmt_pct(v):
        return "n/a" if v is None else f"{v * 100:.1f}%"

    def fmt_num(v):
        return "n/a" if v is None else f"{v:.3f}"

    order = ["baseline", "candidateA_1000", "candidateB_1400"]
    lines = ["CHUNK-SIZE A/B EXPERIMENT REPORT", "=" * 70, ""]
    for key in order:
        r = results[key]
        e = r["eval"]
        lines.append(f"### {key}  (collection: {r['collection_name']})")
        if "target_chars" in r:
            lines.append(f"target_chars={r['target_chars']}  max_chars={r['max_chars']}")
        lines.append(f"total_chunks: {r['total_chunks']}")
        for src, s in r["per_doc"].items():
            lines.append(f"  {src}: count={s['count']} avg={s['avg_len']} min={s['min_len']} max={s['max_len']}")
        c = r["context"]
        lines.append(f"context top5: avg_chars={c['avg_context_chars_top5']} "
                     f"~avg_tokens={c['approx_avg_context_tokens_top5']} max_chars={c['max_context_chars_top5']}")
        lines.append(f"Recall@5={fmt_pct(e.get('recall_at_5'))}  Recall@10={fmt_pct(e.get('recall_at_10'))}  "
                     f"MRR={fmt_num(e.get('mrr'))}")
        lines.append(f"false_refusals={e.get('false_refusal_count')}/{e.get('n_positive_items')}  "
                     f"true_neg_correct={e.get('true_negative_correct_count')}/{e.get('n_true_negative_items')}  "
                     f"true_neg_hallucinated={e.get('true_negative_hallucination_count')}/{e.get('n_true_negative_items')}")
        if "judge_correct_count" in e:
            lines.append(f"judge: correct={e['judge_correct_count']} partial={e['judge_partial_count']} "
                         f"incorrect={e['judge_incorrect_count']} | faithful_yes={e['judge_faithful_yes_count']} "
                         f"faithful_no={e['judge_faithful_no_count']} unparsed/err={e['judge_unparsed_or_error_count']}")
        lines.append("Determined section preservation:")
        for label, info in r["section_preservation"].items():
            mark = "OK " if info["present"] else "MISSING"
            lines.append(f"  [{mark}] {label}  matched={info['matched_keywords']}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
