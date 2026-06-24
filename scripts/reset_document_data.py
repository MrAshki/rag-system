"""Reusable maintenance script: reset all test/uploaded document data so the
app starts as if no user documents have ever been indexed.

Resets:
  - The live Chroma collection (document_qa_collection_local) to 0 chunks,
    via delete_collection() + get_or_create_collection(embedding_function=
    rag.embedding_fn) -- the same safe rebuild pattern used by
    structured_reindex.py. Never manually prunes Chroma's internal UUID
    segment folders.
  - docs/*  (raw uploaded files -- runtime data, not source)
  - converted/* (normalized Markdown + metadata sidecars -- regenerable output)

Does NOT touch:
  - books/ (original source material)
  - models/, .env, plan/, eval/golden_set.json, eval/run_eval.py, backups/
  - Postgres (no document records are stored there; only users/plans/
    subscriptions/payments)

Safety:
  - Caller is responsible for taking a timestamped backup of
    chroma_persistent_storage/ BEFORE running this (see backups/).
  - Always reuses rag.embedding_fn (./models/bge-m3) -- never accesses Chroma
    without it.
  - Asserts ENABLE_LLM_NORMALIZATION stays false (this script doesn't touch
    normalization, but keeps the same safety assertion used elsewhere).

Usage (PowerShell, from the project venv, run from the project root):
    .\\venv\\Scripts\\python.exe scripts\\reset_document_data.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import rag  # noqa: E402

assert os.getenv("ENABLE_LLM_NORMALIZATION", "false").lower() != "true", (
    "ENABLE_LLM_NORMALIZATION must stay false; aborting."
)

DOCS_DIR = "./docs"
CONVERTED_DIR = "./converted"


def clear_dir(path: str, keep=(".gitkeep",)) -> list:
    removed = []
    for name in os.listdir(path):
        if name in keep:
            continue
        full = os.path.join(path, name)
        if os.path.isfile(full):
            os.remove(full)
            removed.append(name)
    return removed


def main():
    print(f"Embedding function in use: {rag.EMBEDDING_MODEL} (project model, not Chroma default)")
    before_count = rag.collection.count()
    print(f"Live collection count before reset: {before_count}")

    print("Deleting and recreating the Chroma collection (safe rebuild, no manual segment pruning) ...")
    rag.chroma_client.delete_collection(name=rag.COLLECTION_NAME)
    rag.collection = rag.chroma_client.get_or_create_collection(
        name=rag.COLLECTION_NAME, embedding_function=rag.embedding_fn
    )
    after_count = rag.collection.count()
    print(f"Live collection count after reset: {after_count}")

    removed_docs = clear_dir(DOCS_DIR)
    removed_converted = clear_dir(CONVERTED_DIR)
    print(f"Removed {len(removed_docs)} file(s) from {DOCS_DIR}/")
    print(f"Removed {len(removed_converted)} file(s) from {CONVERTED_DIR}/")

    if after_count != 0:
        print("WARNING: collection count is not 0 after reset.")


if __name__ == "__main__":
    main()
