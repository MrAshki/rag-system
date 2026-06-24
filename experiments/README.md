# Experiments — not part of the production app

The files in this folder (`cag.py`, `rac.py`, `RAG-guide.txt`) are early,
standalone prototype scripts from before the current product architecture
(`app.py` + `rag.py` + `document_pipeline/`) existed.

Rules for this folder:

- **Not part of the production app.** Nothing here is imported by `app.py`,
  `rag.py`, `document_pipeline/`, or any `scripts/`/`eval/` tool.
- **Must never be run against the production Chroma store**
  (`chroma_persistent_storage/`). They predate the per-user `user_id`
  isolation, structured chunking, and fail-fast model config used in
  production, and could corrupt or mis-embed data if pointed at the live
  collection.
- **Must not be used as the main RAG pipeline.** Use `app.py` (via the web UI)
  or the `scripts/` maintenance tools for any real document indexing/querying.
- Kept only for historical reference (early design ideas), not for execution
  against real data.
