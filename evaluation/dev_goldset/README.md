# Development Gold Set

This directory contains a human-audited development set for measuring the
current RAG system. It is evaluation infrastructure, not a production
benchmark and not a dataset-suitability audit.

## Contents

- `manifest.jsonl`: 20 source-document records, SHA-256 hashes, physical page
  counts, roles, limitations, and document-quality flags.
- `tasks.jsonl`: 65 single-turn tasks with gold answers/concepts, physical PDF
  pages, route and retrieval expectations, negative constraints, and citation
  requirements.
- `conversations.jsonl`: 10 conversations and 25 ordered user turns with
  antecedents, history requirements, selected-document persistence, and
  retrieval-required/allowed/forbidden labels.
- `qrels.json`: graded page-level relevance judgments keyed by `query_id`.
- `schema.json`: the normative record shapes and enumerations.

Physical PDF page numbers are used throughout. The source PDFs remain
untracked under `composite_goldset_pdfs/`; their hashes link annotations to
the exact local bytes.

## Human verification

The annotations were drafted only after extracting every page from the actual
PDFs with `pypdf`. Each retained fact, number, page, table cell, answerability
label, and evidence description was checked against that page. Layout-sensitive
fixtures and `doh-16-381.pdf` table 4 were rendered at 2x with `pypdfium2`;
the rank-1 row (`بازیافت پساب دیالیز`, `۰٫۸۷`) was visually verified on
physical page 9. Full-document searches were used for intentional no-answer
labels. The visibly garbled text layer in `doh-14-54.pdf` is marked limited;
only manually checked slices are used.

Run deterministic validation with:

```powershell
D:\rag-system\venv\Scripts\python.exe evaluation\runners\evaluate_ingestion.py
D:\rag-system\venv\Scripts\python.exe -m pytest tests\evaluation -q
```

## Coverage and limitations

The set covers Persian born-digital journal PDFs, Persian/English mixtures,
repeated headers and footers, tables and numeric cells, comprehensive
summaries, page-specific questions, no-answer, conflicting evidence, and
ambiguous conversational follow-ups.

Known gaps are English-only documents, fully scanned OCR documents, equations,
and multi-document reasoning. These gaps prevent generalizing results to a
production benchmark but do not invalidate this development baseline.
