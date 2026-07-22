# Reliable RAG Architecture

The pipeline is split into deterministic document intelligence, retrieval, and
bounded LangGraph orchestration. LLMs are used only where language generation
adds value.

## Ingestion

1. `document_pipeline.ingest` extracts canonical Markdown and preserves PDF page markers.
2. `document_pipeline.profiling` classifies the document and applies quality gates without an API call.
3. `document_pipeline.document_map` builds stable parent units from chapters, headings, pages, or semantic windows.
4. `document_pipeline.chunker` creates retrieval-sized child chunks.
5. Parent IDs, page spans, and source metadata are stored with each Qdrant payload.

Artifacts are versioned by normalization, profile, and document-map versions.
`content_hash` prevents stale summaries from being reused after a document changes.

## Query path

1. `request_router` selects intent and a bounded retrieval budget using deterministic rules.
2. R2 compares the question language with the selected document language.
3. Same-language requests run one lexical+dense Nemotron search. Cross-language
   requests add exactly one retrieval-only rewrite and search both query forms.
4. Candidate lists are de-duplicated and fused with RRF.
5. The external reranker sees the bounded candidate set exactly once.
6. Results are diversified by parent unit before generation.
7. Gemini 2.5 Flash returns JSON paragraphs plus evidence IDs.
8. The backend validates IDs and renders citations only at paragraph ends.
9. On a technical or response-contract failure, GLM 5.2 receives the exact
   same immutable prompt and evidence context. Retrieval is not repeated.

Ordinary grounded questions use one embedding call, one rerank call, and one
generation call. Query decomposition is reserved for truly multi-question input.

## Comprehensive summaries

Each parent unit is summarized once and cached by asset, unit, content hash,
provider, and model. Later requests reuse those summaries and normally need only
the final reduce call. Evidence markers are local inside the cache and remapped
to current page-level source IDs at runtime.

## Trust boundaries

- Failed OCR or unusable extraction is rejected before indexing.
- Unknown evidence IDs and uncited generated paragraphs are rejected.
- Provider failures do not trigger unbounded agent loops. Generation is limited
  to one Gemini execution and at most one GLM fallback execution.
- Valid no-answer responses do not trigger fallback.
- The production vector path uses only `nvidia/nemotron-3-embed-1b:free` and
  the `rag_documents` Qdrant collection.

The retained model-selection rationale is in
[`docs/rag-model-selection-summary.md`](../docs/rag-model-selection-summary.md).
