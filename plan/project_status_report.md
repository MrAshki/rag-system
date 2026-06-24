# Project Status Report

Last updated: 2026-06-24
Status snapshot taken read-only — no Chroma writes, no reindex, no eval run, no
external calls were made to produce this report.

This file is project memory. Read it before proposing architecture, workflow,
retrieval, or roadmap changes. It complements `plan/Plan.docx` (the original
approved architecture/strategy document) — this file tracks current state,
`Plan.docx` tracks the long-range strategic decisions.

---

## 1. Current project goal

A fully local, Persian-first RAG SaaS: users sign up by phone/OTP, subscribe via
ZarinPal, upload their own documents (TXT/PDF/DOCX), and ask grounded questions
answered strictly from their own uploaded documents, with citations and an
honest refusal when the answer isn't in the documents. Initial target users are
students/researchers; a legal-document workflow is planned as Phase 2.

## 2. Current local-only decision

Everything in the active pipeline runs locally: embeddings, vector store, and
generation. No external LLM/embedding API (OpenAI, Gemini, Anthropic, or any
paid/cloud service) is integrated anywhere in the codebase. A future, separate
comparison phase using Google's free API tier is planned but explicitly
out of scope until the local core is stable and evaluated. This decision is a
hard constraint, not a default — do not add API calls without explicit
re-approval.

## 3. Current architecture

- **Web/API**: Flask (`app.py`), dev server via `python app.py`, production via
  `waitress` (`serve.py`).
- **Auth**: phone + OTP, server-side sessions (`auth.py`).
- **Billing**: ZarinPal payment gateway (`payments.py`).
- **Database**: PostgreSQL via `psycopg` (`db.py`), connection string from
  `DATABASE_URL` in `.env`. Note: `README.md` still says "SQLite for
  users/plans/subscriptions/payments" — that is stale documentation drift, the
  actual code uses Postgres. (A leftover `app_data.sqlite3` file exists from
  before the Postgres migration; it is gitignored and gitignore comments it as
  "Legacy SQLite database (migrated to PostgreSQL) — never commit.")
- **Document normalization/chunking**: `ingest.py` (deterministic) +
  `llm_normalize.py` (optional, disabled) + `chunker.py` (heading-aware
  packing). As of this task these now live under `document_pipeline/` with
  root-level compatibility shims — see Section 12.
- **Vector store**: ChromaDB `PersistentClient` at `chroma_persistent_storage/`,
  single collection `document_qa_collection_local`, per-user isolation via a
  `user_id` field on every chunk's metadata (not separate collections).
- **Embeddings**: `bge-m3` via `sentence-transformers`
  (`EMBEDDING_MODEL=./models/bge-m3`), GPU when available (confirmed
  `cuda - NVIDIA GeForce RTX 5060` on this machine).
- **Generation**: Ollama, `gemma3:12b` (`OLLAMA_MODEL=gemma3:12b`), called via
  the `ollama` Python client with `temperature=0.0`, `num_ctx=4096`.
- **Frontend**: vanilla HTML/CSS/JS in `webapp/` (`index.html`, `login.html`,
  `admin.html`, `styles.css`).

## 4. Current models (confirmed live, read from `.env` at runtime)

- `EMBEDDING_MODEL=./models/bge-m3`
- `OLLAMA_MODEL=gemma3:12b`

Both are now fail-fast in `rag.py` (`_require_env`): if either is missing from
`.env`, the process raises `RuntimeError` at import time instead of silently
falling back to Chroma's default `all-MiniLM-L6-v2` or Ollama's `llama3.2`.
Verified directly: `rag.EMBEDDING_MODEL == "./models/bge-m3"`,
`rag.OLLAMA_MODEL == "gemma3:12b"`.

## 5. Current database / vector setup

- Postgres: users, plans, subscriptions, payments (see `db.py` for schema/queries).
- Chroma: one persistent collection, `document_qa_collection_local`, at
  `chroma_persistent_storage/` (gitignored, machine-local).
- Live collection count confirmed by direct read-only query: **903 chunks**.

## 6. Current live Chroma state

- Collection: `document_qa_collection_local`
- Count: **903** (read-only `collection.count()` check; not modified by this task)
- Holds exactly 3 approved real documents, all owned by `user_id=3`:
  - `Questline_Theory.docx` — 27 chunks
  - `cosmeticorexia_fa.txt` — 1 chunk
  - `determaind.txt` (built from the richer `converted/determaind.md` source via
    the `clean_determaind_md()` adapter, not the flat `docs/{id}.txt`) — 875 chunks
- This matches the post-Candidate-B-reindex state from the prior session; no
  reindex has happened since.
- 5 orphaned UUID-named segment directories currently exist on disk under
  `chroma_persistent_storage/` alongside `chroma.sqlite3` — leftovers from past
  `delete_collection()`/rebuild cycles that Chroma doesn't always garbage-collect.
  Flagged, not touched (deleting them is a live-Chroma operation and out of
  scope for this task).

## 7. Current chunking configuration

- `chunker.TARGET_CHARS = 1400`
- `chunker.MAX_CHARS = 1900`
- `chunker.OVERLAP_RATIO = 0.18`

These were chosen via a chunk-size A/B experiment (Candidate B) that fixed a
true-negative refusal regression caused by context-window dilution from
oversized chunks. See `eval/chunk_size_experiment_report.txt` for the full
A/B comparison (baseline vs. Candidate A 1000/1450 vs. Candidate B 1400/1900).

## 8. Current eval results (after Candidate B live reindex)

From `eval/final_candidateB_live_reindex_report.txt`:

- Recall@5: 100.0%
- Recall@10: 100.0%
- MRR: 0.892
- False refusals: 0/17 positive items
- True negatives correct: 2/2
- LLM-judge: correct=3, partial=14, incorrect=0
- Faithfulness: faithful_yes=17, faithful_no=0

This meets every success criterion set for the live reindex (Recall@5 ~100%,
Recall@10 100%, true negatives 2/2, no faithfulness regression).

## 9. What has been completed so far

- Deterministic document normalization pipeline (TXT/PDF/DOCX → canonical
  Markdown), heading detection via Word styles or regex heuristics, page
  markers for PDFs, list detection (explicit + implicit runs).
- Heading-aware structured chunker with section-boundary-respecting overlap.
- Multi-user Flask app: phone/OTP auth, ZarinPal subscriptions, Postgres
  persistence, per-user document isolation in Chroma via `user_id` metadata.
- Citation system (`_citation_label` in `rag.py`): filename — chapter —
  section — page — chunk, with graceful fallback for older chunks without
  structural metadata.
- Refusal-as-feature: explicit "insufficient information" responses instead of
  hallucinated answers, validated by the golden eval set's 2 true-negative items.
- Eval harness (`eval/run_eval.py`) with Recall@5/@10, MRR, false-refusal count,
  true-negative correctness, and an LLM-judge (gemma3 self-grading) for
  correctness/faithfulness, against a 19-item golden Persian Q&A set
  (17 positive + 2 true-negative).
- Chunk-size A/B experiment methodology (reusable script,
  `scripts/chunk_size_experiment.py`) and its result, now applied live.
- `rag.py` config hardening: `EMBEDDING_MODEL`/`OLLAMA_MODEL` fail fast instead
  of silently defaulting to the wrong model.
- This task: normalization/chunking subsystem isolated into its own package
  (`document_pipeline/`) — see Section 12.

## 10. What was built and is currently active

- `document_pipeline/ingest.py` (deterministic normalization, imported as
  `ingest` via the root shim)
- `document_pipeline/chunker.py` (structured chunking)
- `rag.py` (retrieval + generation, fail-fast config)
- `app.py` (Flask routes, upload/ask/admin/auth/payment)
- `auth.py`, `db.py`, `payments.py`, `ratelimit.py` (supporting subsystems)
- `webapp/` frontend

## 11. What was built but is currently disabled / not used

- `document_pipeline/llm_normalize.py` (Step 2.5, LLM-assisted structure
  relabeling) — gated by `ENABLE_LLM_NORMALIZATION=false` in `.env.example`/`.env`.
  Built and tested (`eval/llm_normalization_step_report.*`) but intentionally
  left off: the deterministic pass already reaches "high" structure confidence
  on the current 3 documents, and turning this on adds LLM latency/risk for
  documents that don't need it. It only ever relabels structure (heading vs.
  paragraph vs. list, etc.) — it can never rewrite, translate, or regenerate
  document text; this is enforced by construction (see the module docstring
  and `reassemble_blocks_from_units`, which always re-splices the original
  text regardless of label).
- OCR fallback (`ingest.normalize_pdf`'s `enable_ocr_fallback` path,
  `ENABLE_OCR_FALLBACK=false`) — scaffolding only (detects low-text-density
  PDFs and records `ocr_backend_available`), no OCR backend installed, no
  actual OCR rendering implemented. `ingest.OCR_SETUP_NOTES` documents the
  lightest future Windows setup (Tesseract + pytesseract + pdf2image,
  ~100-150MB, one-time) if/when approved.

## 12. What exists only for experiments or future phases

- `scripts/chunk_size_experiment.py` — reusable chunk-size A/B harness (builds
  candidates in-memory, indexes into a separate scratch Chroma client, never
  touches the live collection). Kept for future chunk-tuning experiments.
- `eval/chunk_exp_*`, `chunk_size_experiment_report.*` — the specific A/B
  experiment's results (baseline vs. candidateA_1000 vs. candidateB_1400).
- `experiments/` (`cag.py`, `rac.py`, `RAG-guide.txt`) — early standalone
  prototype scripts, explicitly *not* part of the product, must never be run
  against the production vector store (per `README.md`).
- `scripts/normalize_existing_documents.py` and
  `scripts/rebuild_chroma_index.py` — one-off/maintenance migration scripts
  from earlier pipeline iterations (pre-structured-chunking). Still functional
  but superseded for routine use by `scripts/structured_reindex.py`.
- `converted/48480f24643b40fbb0b04f4a5f2e9634.llm_assisted_sample.md` — a
  leftover sample output from testing the (disabled) LLM-normalization step.
  Gitignored, harmless, not used by any code path.

## 13. What the normalization pipeline currently does

`document_pipeline/ingest.py` (formerly root `ingest.py`):

1. Dispatches by file extension (`.txt`, `.docx`, `.pdf`) to a format-specific
   normalizer.
2. TXT/PDF: tokenizes lines via regex heuristics — chapter/section keywords
   ("Chapter N"/"فصل"/"بخش"), numbered-section markers, a positional title
   check on the first block, explicit bullet/numbered markers, and a fuzzy
   "generic heading candidate" check for short capitalized standalone lines
   (Latin-script only — Persian has no letter case, so this deliberately never
   fires on pure-Persian text; a documented limitation, not a bug).
3. DOCX: uses real Word heading/list styles when present (high-confidence,
   "native" structure); falls back to the same regex heuristics for
   `Normal`-styled paragraphs.
4. PDF: per-page text extraction via `pypdf`, page markers preserved as
   `<!-- page:N -->`, implicit-list detection disabled for PDFs (page-wrap line
   breaks would cause false positives).
5. Produces a `structure_confidence` rating (`high`/`medium`/`low`) and an
   `extraction_quality_warning` (e.g. `weak_structure_no_headings_detected`,
   `low_text_density_possible_scanned_pdf`, `ocr_required`).
6. Writes canonical Markdown + a JSON metadata sidecar to `converted/`.
7. Never rewrites, translates, or regenerates the source text — only
   classifies/labels structure deterministically.

`document_pipeline/chunker.py`:

1. Splits the canonical Markdown on heading boundaries into chapter/section/
   subsection groups.
2. Greedily packs paragraph/list blocks within each group up to
   `TARGET_CHARS` (1400), never letting an overlap tail cross a heading
   boundary.
3. Hard-splits any single block exceeding `MAX_CHARS` (1900) at sentence
   boundaries (or raw length as a last resort).
4. Each packed chunk carries ~18% overlap (`OVERLAP_RATIO`) from the end of
   the previous chunk in the same group.
5. `build_embedded_text()` prepends a short contextual header
   (Chapter/Section/Subsection/Page) to the literal text that gets embedded
   and stored, so retrieval and citations both benefit from that context.

## 14. What LLM-assisted normalization does and why it is disabled

`document_pipeline/llm_normalize.py` takes the blocks already produced by the
deterministic tokenizer and asks the local Ollama model (`gemma3:12b`) to
*relabel* them (heading level, paragraph, list item, etc.) — it is shown only
short text previews and returns `{"index", "label"}` pairs; the original block
text is always spliced back in untouched, so there is no code path where
model-generated text becomes document content. It exists to improve structure
detection on messy/unstructured documents where the deterministic heuristics
land on `medium`/`low` confidence. It is disabled
(`ENABLE_LLM_NORMALIZATION=false`) because: (a) the current 3 production
documents already reach high deterministic confidence, so it would add LLM
latency for no benefit yet, (b) per the approved roadmap, "LLM-normalization
disabled" was an explicit decision to keep the deterministic core stable
before layering in more LLM-dependent steps, and (c) it has only been
validated on a one-off manual test (`eval/llm_normalization_step_report.*`),
not against the full golden eval set.

## 15. OCR status

Deferred, as approved. `ingest.normalize_pdf` detects low-text-density/likely-
scanned PDFs and would record `ocr_backend_available` if
`ENABLE_OCR_FALLBACK=true` were set, but no OCR backend (tesseract/pytesseract/
pdf2image) is installed and no actual OCR rendering is implemented. Turning
the flag on today is a no-op (just logs unavailability); nothing breaks.

## 16. Scripts inventory

| Script | Status |
|---|---|
| `scripts/structured_reindex.py` | Reusable. The canonical way to rebuild the live collection from the 3 approved documents with current chunker settings. |
| `scripts/chunk_size_experiment.py` | Reusable. Read-only-against-live A/B chunk-size harness for future chunk-tuning experiments. |
| `scripts/normalize_existing_documents.py` | Superseded for routine use by `structured_reindex.py`, but still functional; from an earlier pipeline iteration (normalization-only, pre-chunking-rework). |
| `scripts/rebuild_chroma_index.py` | Superseded for routine use by `structured_reindex.py`; earlier flat-chunking rebuild script. |
| `make_admin.py` | Reusable. Creates an admin account (used in local setup). |
| `serve.py` | Reusable. Production entrypoint (waitress). |

## 17. Reports inventory — which are important

| Report | Importance |
|---|---|
| `eval/final_candidateB_live_reindex_report.{json,txt}` | **Most important** — current live-state validation. |
| `eval/chunk_size_experiment_report.{json,txt}` | Important — the A/B decision record for why 1400/1900 was chosen. |
| `eval/chunk_exp_baseline_report.*`, `chunk_exp_candidateA_1000_report.*`, `chunk_exp_candidateB_1400_report.*` | Supporting detail behind the combined chunk-size report. |
| `eval/structured_reindex_chunk_stats.json` | Current — per-document chunk stats from the live reindex. |
| `eval/structured_reindex_report.{json,txt}` | Eval run immediately after the structured-chunking migration (pre chunk-size A/B). Historical. |
| `eval/llm_normalization_step_report.{json,txt}` | Validation of the disabled LLM-normalization step. Keep for reference if that feature is revisited. |
| `eval/normalization_step_report.{json,txt}`, `eval/step2_regression_check_report.{json,txt}` | Historical eval runs from the deterministic-normalization migration. Superseded by later reports but document the migration history. |
| `eval/baseline_report.*`, `eval/baseline_after_chroma_rebuild_report.*` | Oldest baseline reports, from before structured chunking existed. Historical only. |
| `eval/golden_set.json` | **Critical** — the golden Q&A set every eval run depends on. Never delete. |
| `eval/run_eval.py` | **Critical** — the eval harness. Never delete. |

## 18. Known risks / footguns already fixed

- `rag.py`'s `EMBEDDING_MODEL`/`OLLAMA_MODEL` silently falling back to the
  wrong model if `.env` was misconfigured — fixed via `_require_env()` fail-fast.
- Oversized chunks (old 2800/3600 target) diluting the LLM's context window
  and regressing true-negative refusals — fixed via the Candidate B chunk-size
  change (1400/1900).

## 19. Known risks still open

- 5 orphaned UUID segment directories accumulating in
  `chroma_persistent_storage/` across collection rebuilds (Chroma doesn't
  always garbage-collect old segments on `delete_collection()`). Not harmful
  to correctness, just disk usage; cleanup would require a live-Chroma
  operation, out of scope here.
- `README.md` says "SQLite for users/plans/subscriptions/payments" but the
  code actually uses PostgreSQL (`db.py` uses `psycopg`) — stale documentation,
  not a functional bug.
- Persian-only documents with no Latin-script headings can't benefit from the
  "generic heading candidate" weak heuristic (by design — see Section 13) —
  unmarked Persian subsection headings are a known structure-detection gap.
  LLM-assisted normalization (currently disabled) is the planned mitigation.
- `llm_normalize.py`'s batch-classification approach has only been validated
  on one manual test run, not the full golden eval set — would need eval
  coverage before being enabled by default.
- Older chunks indexed before structured chunking existed (if any remain from
  pre-migration testing) would lack chapter/section/page metadata; the
  citation builder (`_citation_label`) already handles this gracefully via
  fallback to "filename — chunk N", but it's worth confirming no such stale
  chunks linger in the live collection from `user_id` values other than 3.

## 20. Current roadmap (approved, do not restart from scratch)

1. **Immediate next**: provider abstraction layer for the LLM call — still
   local Ollama only, no API integration yet. Purpose is to make the
   generation call swappable later without touching call sites.
2. Task orchestration layer (routing different question/task types to
   different retrieval/generation strategies).
3. MVP workflows for students/researchers (the first real product surface).
4. Legal-document workflows (Phase 2, after the student/researcher MVP is
   validated).
5. API comparison experiment using Google's free tier only — explicitly
   deferred until the local core is stable and evaluated; a separate,
   bounded experiment, not a switch to API-first.

## 21. What should not be touched yet

- Live Chroma collection / chunk size / retrieval behavior (currently
  validated and stable — see Section 8).
- `ENABLE_LLM_NORMALIZATION` must stay `false` until it has its own eval
  validation pass.
- OCR (no backend installed, no approval to install one yet).
- Any external API integration (OpenAI/Gemini/Anthropic/Google) — the upcoming
  "provider abstraction" step is about code structure, not actually calling
  an API.
- Reranker/BM25/hybrid retrieval/query rewriting — none approved yet.
- Deleting backups, eval reports, scripts, or source/converted documents (see
  cleanup recommendations below — recommendations only, not actions).

---

## 22. Cleanup recommendations (NOT executed — recommendations only)

### Keep permanently
- `plan/` (Plan.docx, this report)
- `eval/golden_set.json`, `eval/run_eval.py`
- `document_pipeline/` (real implementation), root shims
  (`ingest.py`, `chunker.py`, `llm_normalize.py`)
- `app.py`, `rag.py`, `db.py`, `auth.py`, `payments.py`, `ratelimit.py`, `serve.py`, `make_admin.py`
- `webapp/`
- `.env.example`, `requirements.txt`, `README.md`, `.gitignore`
- `models/` (bge-m3 weights), `chroma_persistent_storage/` (production data)
- `docs/`, `converted/`, `books/` (source/converted user & reference documents)

### Keep for now
- `experiments/` (`cag.py`, `rac.py`, `RAG-guide.txt`) — explicitly kept per
  `README.md` as historical reference; low cost to keep.
- `converted/48480f24643b40fbb0b04f4a5f2e9634.llm_assisted_sample.md` — small,
  gitignored, harmless; useful if LLM-normalization work resumes.

### Reusable maintenance scripts
- `scripts/structured_reindex.py`
- `scripts/chunk_size_experiment.py`

### Old experiment reports (historical, low risk to remove later, not removed now)
- `eval/baseline_report.{json,txt}`
- `eval/baseline_after_chroma_rebuild_report.{json,txt}`
- `eval/normalization_step_report.{json,txt}`
- `eval/step2_regression_check_report.{json,txt}`
- `eval/structured_reindex_report.{json,txt}` (superseded by
  `final_candidateB_live_reindex_report.*`)

### Safe-to-delete-later-with-approval
- `scripts/normalize_existing_documents.py`, `scripts/rebuild_chroma_index.py`
  — superseded by `structured_reindex.py`; recommend keeping until
  `structured_reindex.py` has been relied on for at least one more full
  reindex cycle, then deleting with explicit approval.
- Oldest backup: `backups/chroma_persistent_storage_backup_20260623_162205`
  (pre-dates the current live state; the two newer backups
  `..._20260624_100058` and `..._20260624_120757` cover the current state and
  its immediate predecessor). Recommend deleting only the oldest one, with
  approval, once a newer backup is confirmed healthy.
- 5 orphaned UUID segment directories inside `chroma_persistent_storage/` —
  cleanup requires a live-Chroma maintenance operation (e.g. a fresh
  Chroma-side compaction or a verified rebuild), out of scope for this task;
  flag for the next live-Chroma maintenance window.

### Never delete
- `chroma_persistent_storage/` (production vector store)
- `.env`
- `models/`
- `docs/`, `books/`, `converted/` (source/converted material)
- `plan/`
- `eval/golden_set.json`, `eval/run_eval.py`
- Any backup until a newer one is confirmed healthy and at least one backup remains
