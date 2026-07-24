# RAG production-path fixes (Goal 2)

This checkpoint fixes the four production failures confirmed by the unchanged
Goal 1 Development Gold Set. It does not change Gold Set expectations, metric
formulas, embedding/generation models, source PDFs, or the production Qdrant
collection.

## Root causes and authoritative path

The production endpoint previously had two orchestration behaviours. The
LangGraph-enabled stream manually selected graph nodes and exposed an
`agent_plan` event, while the non-graph entry point retained a separate legacy
router. Router unit tests exercised neither production dispatch consistently.
Consequently, `ENABLE_LANGGRAPH_RAG` could change the router, not merely the
execution wrapper.

There is now one authoritative path:

`ChatApp → Next /api/ask/stream → FastAPI ask route → conversation/history load
→ rag.answer_request_stream → rag_graph._execute_authoritative
→ request_router.build_plan → deterministic handler or LangGraph StateGraph
→ generation → coverage/grounding/citation validation → streamed final event`.

`ENABLE_LANGGRAPH_RAG=True` now means that eligible retrieval and analytical
routes execute through the StateGraph. It does not select a second router.
Deterministic `conversation_only`, `direct_whole_document`, and
`table_or_structured_document` routes bypass graph overhead while retaining the
same plan and telemetry contract.

The other root causes were:

- History/anaphora detection ran too late and a clarification could fall into
  standalone rewrite and retrieval. The conversation handler was also missing
  its bounded previous-answer generation helper.
- Comprehensive summaries were sometimes fed top-k or hierarchical context
  even when the normalized document fit. Administrative OCR headings entered
  required coverage, soft coverage preferences were promoted to hard failures,
  immutable whole-document support was unavailable to citation validation, and
  an overlong per-section output instruction increased truncation risk.
- Table 4 straddled normalized page/chunk boundaries. Generic top-k retrieval
  could refuse before inspecting a page-aware table block, and RTL/Persian
  decimal normalization did not match `۰٫۸۷` reliably.
- The backend emitted the internal `agent_plan` trace and the frontend rendered
  it as `برنامه پاسخ انتخاب شد...`, regardless of whether the advertised stage
  actually ran.

## Resulting route behaviour

Routing order is now history reference, explicit quoted text, intent, selected
document count, token fit, structured/table cues, retrieval necessity, then
final route. A bare `یعنی چی؟` after an assistant answer is
`conversation_only` and performs zero retrieval, embedding, rewrite, and
reranking calls. Explicit quoted text remains document-grounded.

A fit-safe single-document comprehensive request uses the complete normalized,
page-aware document as `direct_whole_document` context. It performs one primary
generation, structured parsing and validation, and at most one same-context
repair. A shorter 35–60-word paragraph budget per required section prevents
output truncation without removing any required section. Soft style/heading
warnings no longer discard an otherwise grounded summary.

Small selected documents are inspected page by page before no-answer.
Table/structured questions inspect table blocks and surrounding page text before
refusal. Table 4 now deterministically preserves its caption, row/column
relation, physical page 9, rank 1, and closeness coefficient `۰٫۸۷`.

## Title and sections

For `doh-16-381.pdf`, the profile retains `research_article` and a non-null
title. The final summary surfaces the title:

> بازیافت آب در بیمارستان‌های عمومی استان مرکزی با استفاده از روش
> تصمیم‌گیری چندمعیاره تاپسیس (TOPSIS): شناسایی و اولویت‌بندی راهکارها

Document-map v3 classifies methodology, findings, discussion, conclusion,
practical implications, and administrative sections explicitly. Authors,
journal/publisher metadata, acknowledgements, funding, ethics, author
contributions, and conflicts are not required substantive summary sections, but
remain stored and available for explicit questions. Page provenance is
preserved.

## Streaming and telemetry

User-visible statuses are emitted only for executed stages:

| Route | Visible execution stages |
| --- | --- |
| Direct summary | `در حال بررسی کل سند...` → `در حال تهیه خلاصه جامع...` → `در حال بررسی پوشش مطالب و منابع...` |
| Conversation clarification | `در حال بررسی پیام قبلی...` → `در حال آماده‌سازی توضیح...` |
| Table QA | `در حال بررسی جدول‌ها و داده‌های سند...` → `در حال تطبیق مقادیر...` → `در حال آماده‌سازی پاسخ...` |
| Local retrieval | `در حال جست‌وجوی بخش‌های مرتبط...` → `در حال بررسی شواهد...` → `در حال آماده‌سازی پاسخ...` |

Route names, graph nodes, model/fallback names, JSON parsing, and validation
codes are telemetry-only. Sanitized telemetry includes request/build/
conversation/asset identifiers, plan and implementation, graph path, history
and token estimates, operation counts, page/section/table coverage, validation,
fallback flag, emitted stage identifiers, latency, and provider cost. Prompts,
document text, credentials, and provider bodies are not logged.

## Comparable checkpoint

The post-fix checkpoint uses the exact same 15 production tasks as Goal 1.

| Metric | Goal 1 baseline | Goal 2 checkpoint |
| --- | ---: | ---: |
| Route selection | 9/15 (60.0%) | 12/15 (80.0%) |
| Retrieval necessity | 6/15 (40.0%) | 12/15 (80.0%) |
| False refusal | 7/12 (58.3%) | 3/12 (25.0%) |
| Substantive comprehensive answers | 0/2 | 2/2 |
| Summary conclusion coverage | 0/2 | 2/2 |
| Summary section coverage mean | 0 | 0.5833 |
| Summary key-claim recall mean | 0 | 0 |
| Follow-up resolution | 0/2 | 2/2 |
| Unnecessary follow-up retrieval | 2/2 | 0/2 |
| Strict citation validity | 0/15 | 6/13 |
| Citation validity where citations were returned | 0 | 6/6 (100%) |
| Strict Grounded Task Success | 0/15 | 2/15 (13.3%) |
| Latency p50 | 3573 ms | 1361 ms |
| Latency p95 | 35211 ms | 35739 ms |

The exact UI gates passed in one conversation. The summary used pages 1–12
(excluding administrative boilerplate), clarification used only the preceding
answer with all document-operation counters at zero, and Table 4 returned
`بازیافت پساب دیالیز، ۰٫۸۷` with physical page 9. No
`برنامه پاسخ انتخاب شد...` text was exposed.

## Verification

Automated commands:

```powershell
D:\rag-system\venv\Scripts\python.exe -m pytest -q
cd D:\rag-system\apps\web
npm run lint
npm run build
npm run test:e2e
```

Goal 2 adds regression coverage for shared production/test routing,
LangGraph-enabled dispatch, whole-document fit, title/administrative section
classification, hard versus soft summary validation, bounded repair, previous
answer/history use, quoted explanations, table numeric/digit/rank/provenance
handling, evidence-before-refusal, and execution-derived streaming.

## Known limitations

This goal intentionally stops before Goal 3 optimization. Strict acceptable
answer match remains 1/15, summary key-claim recall remains 0 under the
unchanged lexical Gold Set scorer, strict citation page accuracy remains 5/13,
and strict Grounded Task Success remains 2/15. Three tasks whose prepared
fixture asset is intentionally unavailable remain route/retrieval misses, and
one small-document analytical initial turn can still refuse even though its
ambiguous follow-up now resolves correctly without retrieval. Fit-safe
summaries can still require the one permitted same-context repair and remain the
p95 latency driver.
