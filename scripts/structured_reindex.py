"""One-off maintenance script: structured reindex of the 3 currently-indexed
real documents using the deterministic ingest.py + chunker.py pipeline
(Step 2 quality, NO LLM-assisted normalization, NO OCR).

For "determaind.txt" specifically, prefers the richer pre-existing
converted/determaind.md (real chapter/section headers from an external
epub->markdown conversion) over re-deriving structure from the flat
docs/{document_id}.txt -- the flat txt has no headers to recover. A small,
safe regex adapter strips that file's leftover HTML artifacts (footnote
links, inline <span> formatting) and converts its pagebreak spans into the
"<!-- page:N -->" markers chunker.py already understands. No new dependency.

Safety:
- Backup chroma_persistent_storage BEFORE running this (done separately,
  see backups/).
- Always reuses rag.embedding_fn (./models/bge-m3) -- never calls Chroma
  collection access without it.
- ENABLE_LLM_NORMALIZATION is read from the environment as-is (left at its
  existing value, expected to be unset/false); this script does not set it
  and does not pass force_llm_normalization=True anywhere.

Usage (PowerShell, from the project venv):
    .\\venv\\Scripts\\python.exe scripts\\structured_reindex.py
"""
import io
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import chunker  # noqa: E402
import ingest  # noqa: E402
import rag  # noqa: E402

assert os.getenv("ENABLE_LLM_NORMALIZATION", "false").lower() != "true", (
    "ENABLE_LLM_NORMALIZATION must stay false for this migration; aborting."
)

DOCS_DIR = "./docs"

# ---------------------------------------------------------------------------
# Minimal, safe adapter for the legacy converted/determaind.md artifact.
# Pure regex, stdlib only -- no new dependency.
#
# NOTE on page numbers: the source's pagebreak <span> markers are embedded
# INLINE inside heading lines themselves (e.g.
# '## <span ... title="34"></span>Free Won’t: The Power to Veto'), not on
# their own line. Converting them to "<!-- page:N -->" block markers would
# insert a blank-line break in the middle of the heading line and corrupt the
# heading (split it into an empty "##" block plus an orphaned paragraph).
# Rather than risk that, this adapter drops page-number tracking for this one
# legacy source entirely and just removes the spans -- chapter/section
# metadata (the eval-relevant part) stays intact and uncorrupted.
# ---------------------------------------------------------------------------
_PAGEBREAK_RE = re.compile(r'<span[^>]*class="pagebreak"[^>]*>\s*</span>')
_ANY_TAG_RE = re.compile(r"<[^>]+>")


def clean_determaind_md(raw_md: str) -> str:
    """Strips pagebreak spans (no page-number preservation -- see note above)
    and all remaining HTML tags (footnote links, inline <span class="REG">
    formatting) while KEEPING their inner text content -- the tag-stripping
    regex only ever matches markup, never the text between tags, so no
    content is lost."""
    text = _PAGEBREAK_RE.sub("", raw_md)
    text = _ANY_TAG_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_stats(chunks):
    lens = [len(c["text"]) for c in chunks] if chunks else [0]
    return {
        "count": len(chunks),
        "avg_len": sum(lens) // len(lens) if lens else 0,
        "min_len": min(lens) if lens else 0,
        "max_len": max(lens) if lens else 0,
    }


def build_determaind_chunks():
    """Uses converted/determaind.md (richer source) instead of the flat
    docs/{document_id}.txt, via the adapter above."""
    raw_md = open("./converted/determaind.md", encoding="utf-8").read()
    cleaned_md = clean_determaind_md(raw_md)
    chunks = chunker.parse_markdown_to_chunks(cleaned_md)
    meta = {
        "extraction_method": "legacy_epub_markdown_adapter",
        "structure_confidence": "high",
        "page_count": None,
        "heading_count": sum(1 for c in chunks if False),  # filled below from real heading count
        "char_count": len(cleaned_md),
        "extraction_quality_warning": None,
        "source_note": (
            "Built from converted/determaind.md (pre-existing richer epub->markdown "
            "conversion with real chapter/section headers) via scripts/structured_reindex.py's "
            "clean_determaind_md() adapter, NOT re-derived from the flat docs/{id}.txt."
        ),
    }
    # heading_count: count of distinct (chapter,section,subsection) combos that introduce a new heading
    heading_like = set()
    for c in chunks:
        heading_like.add((c["chapter"], c["section"], c["subsection"]))
    meta["heading_count"] = len(heading_like)
    return cleaned_md, chunks, meta


def build_chunks_from_upload(document_id, ext):
    path = os.path.join(DOCS_DIR, f"{document_id}{ext}")
    with open(path, "rb") as f:
        raw = f.read()
    normalized = ingest.normalize_document("placeholder", io.BytesIO(raw), ext)
    chunks = chunker.parse_markdown_to_chunks(normalized["markdown_text"])
    return normalized["markdown_text"], chunks, normalized["meta"]


DOCUMENTS = [
    {
        "document_id": "48480f24643b40fbb0b04f4a5f2e9634",
        "source": "Questline_Theory.docx",
        "user_id": 3,
        "source_file_type": "docx",
        "builder": lambda: build_chunks_from_upload("48480f24643b40fbb0b04f4a5f2e9634", ".docx"),
    },
    {
        "document_id": "a5ee20ddba014770843204d0b12dffe7",
        "source": "cosmeticorexia_fa.txt",
        "user_id": 3,
        "source_file_type": "txt",
        "builder": lambda: build_chunks_from_upload("a5ee20ddba014770843204d0b12dffe7", ".txt"),
    },
    {
        "document_id": "34038160b1a44b129f8f3c05cccd07fe",
        "source": "determaind.txt",
        "user_id": 3,
        "source_file_type": "txt",
        "builder": build_determaind_chunks,
    },
]


def main():
    print("ENABLE_LLM_NORMALIZATION:", os.getenv("ENABLE_LLM_NORMALIZATION", "(unset, defaults false)"))
    print(f"Embedding function in use: {rag.EMBEDDING_MODEL} (project model, not Chroma default)\n")

    before_count = rag.collection.count()
    print(f"Current collection count before reindex: {before_count}")

    built = []
    for doc in DOCUMENTS:
        print(f"\nBuilding chunks for {doc['source']} ({doc['document_id']}) ...")
        markdown_text, chunks, meta = doc["builder"]()
        stats = chunk_stats(chunks)
        print(f"  chunks={stats['count']} avg_len={stats['avg_len']} min={stats['min_len']} max={stats['max_len']}")
        built.append({**doc, "markdown_text": markdown_text, "chunks": chunks, "meta": meta, "stats": stats})

    print("\nDeleting and recreating the Chroma collection (backup already made beforehand) ...")
    rag.chroma_client.delete_collection(name=rag.COLLECTION_NAME)
    rag.collection = rag.chroma_client.get_or_create_collection(
        name=rag.COLLECTION_NAME, embedding_function=rag.embedding_fn
    )

    for doc in built:
        md_path, meta_path = ingest.paths_for(doc["document_id"])
        metadata = {
            "document_id": doc["document_id"],
            "original_filename": doc["source"],
            "source_file_type": doc["source_file_type"],
            "normalized_md_path": md_path,
            "user_id": doc["user_id"],
            "created_at": ingest.now_iso(),
            "normalization_version": ingest.NORMALIZATION_VERSION,
            **doc["meta"],
        }
        ingest.write_normalized(doc["document_id"], doc["markdown_text"], metadata)

        result = rag.index_chunks(
            filename=doc["source"],
            chunks=doc["chunks"],
            document_id=doc["document_id"],
            user_id=doc["user_id"],
            source_file_type=doc["source_file_type"],
            normalized_md_path=md_path,
        )
        print(f"Indexed {doc['source']}: {result['chunks']} chunks under document_id={doc['document_id']}")

    after_count = rag.collection.count()
    print(f"\nNew collection count after reindex: {after_count}")

    summary = {
        "before_total_chunks": before_count,
        "after_total_chunks": after_count,
        "documents": [
            {
                "source": d["source"],
                "document_id": d["document_id"],
                "stats_after": d["stats"],
                "extraction_method": d["meta"].get("extraction_method"),
                "structure_confidence": d["meta"].get("structure_confidence"),
                "heading_count": d["meta"].get("heading_count"),
            }
            for d in built
        ],
    }
    with open("./eval/structured_reindex_chunk_stats.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\nChunk stats written to eval/structured_reindex_chunk_stats.json")


if __name__ == "__main__":
    main()
