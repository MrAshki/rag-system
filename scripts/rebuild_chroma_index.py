"""One-off maintenance script: rebuild the Chroma collection cleanly to remove
stale/phantom HNSW index entries that have no backing document/metadata.

Does NOT change chunking, embedding model, or retrieval logic -- it re-reads the
exact documents/metadatas already stored via the existing rag.py collection
object, deletes the corrupted collection, recreates it with the same name and
embedding function, and re-upserts the same real records (embeddings are
recomputed fresh by the same embedding function rag.py already uses).

Run this only after a full directory backup of chroma_persistent_storage/, and
only with no other process (e.g. serve.py / app.py) holding the store open.

Usage (PowerShell, from the project venv):
    .\\venv\\Scripts\\python.exe scripts\\rebuild_chroma_index.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import rag  # noqa: E402  (reuses the exact same client/embedding config as production)

BATCH_SIZE = 200


def main():
    client = rag.chroma_client
    name = rag.COLLECTION_NAME
    old_collection = rag.collection

    reported_count = old_collection.count()
    print(f"Collection '{name}' reports count() = {reported_count}")

    data = old_collection.get(include=["documents", "metadatas"])
    ids = data["ids"]
    documents = data["documents"]
    metadatas = data["metadatas"]
    print(f"collection.get() returned {len(ids)} real records (this is the ground truth to re-index)")

    # Safety checks before any destructive operation.
    none_docs = sum(1 for d in documents if d is None)
    none_metas = sum(1 for m in metadatas if not m)
    if none_docs or none_metas:
        print(f"ABORT: found {none_docs} None documents / {none_metas} empty metadatas in the "
              "supposedly-clean get() result. Rebuild would propagate corruption. Not proceeding.")
        sys.exit(1)
    if len(ids) != reported_count:
        print(f"ABORT: id count ({len(ids)}) does not match collection.count() ({reported_count}).")
        sys.exit(1)

    by_source = {}
    for m in metadatas:
        by_source[m.get("source", "?")] = by_source.get(m.get("source", "?"), 0) + 1
    print("Records per source document:", by_source)

    print(f"\nDeleting collection '{name}' (backed up beforehand) ...")
    client.delete_collection(name=name)

    print(f"Recreating empty collection '{name}' with the same embedding function ...")
    new_collection = client.get_or_create_collection(name=name, embedding_function=rag.embedding_fn)

    print(f"Re-upserting {len(ids)} records in batches of {BATCH_SIZE} (embeddings recomputed fresh) ...")
    t0 = time.time()
    for start in range(0, len(ids), BATCH_SIZE):
        end = start + BATCH_SIZE
        new_collection.upsert(
            ids=ids[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
        )
        print(f"  {min(end, len(ids))}/{len(ids)} upserted", flush=True)
    elapsed = time.time() - t0

    final_count = new_collection.count()
    print(f"\nDone in {elapsed:.1f}s. New collection count() = {final_count} (expected {len(ids)})")
    if final_count != len(ids):
        print("WARNING: final count does not match expected count -- investigate before trusting the index.")
        sys.exit(1)

    print("\nValidation queries (checking for phantom/None results) ...")
    probe_questions = [
        "منظور از اراده‌ی نه‌گفتن و قدرت وتو در کتاب چیست؟",
        "کاسمتیکورکسیا چیست؟",
    ]
    for q in probe_questions:
        for n in (5, 10):
            res = new_collection.query(query_texts=[q], n_results=n, include=["documents", "metadatas"])
            docs = res["documents"][0]
            none_count = sum(1 for d in docs if d is None)
            print(f"  query={q[:30]!r} n_results={n} -> none_count={none_count}")

    print("\nRebuild complete.")


if __name__ == "__main__":
    main()
