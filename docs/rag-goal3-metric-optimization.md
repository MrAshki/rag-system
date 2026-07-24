# Goal 3 — controlled RAG metric optimization

## Scope and safety

Goal 3 started from the verified annotated tag
`rag-goal2-stable-20260723` at
`4bed823d2d6a72990247d4428d8cac454d17cf44` on the local branch
`feature/rag-goal3-metric-optimization`. The initial working tree was clean.
The safety records are under `tmp/rag-quality-goal/goal3/`.

The Development Gold Set, its expected answers/pages, the production embedding
(`nvidia/nemotron-3-embed-1b:free`), primary generator
(`google/gemini-2.5-flash`), fallback (`z-ai/glm-5.2`), Qdrant collection, and
Goal 2 tag were not changed. No Goal 3 change was staged, committed, tagged, or
pushed.

## Evaluation tools

The deterministic reference implementation retained for parity is
`pytrec-eval-terrier==0.5.10`, isolated in `requirements-eval.txt`. Its
Recall@K, Precision@K, Hit Rate@K, MRR, MAP, and nDCG@K agree with hand-derived
toy qrels and the project implementation; the parity tests exercise both
per-query and aggregate values.

`DeepEval==4.1.3` was retained in an ignored, isolated evaluation environment.
It was selected over Ragas because it supported the configured judge, concise
verdict reasons, custom calibrated dimensions, and controlled saved-output
batches on this Windows/Python environment. Ragas was rejected after its
Python 3.14 dependency path required an unavailable MSVC native build. Neither
package is a production dependency. Phoenix and Opik were not installed:
existing sanitized JSON telemetry already contained route, operation, latency,
cost, and validation spans, so another service added no release value.

The judge used `openai/gpt-4.1-mini`, rubric `goal3_composite_v1`,
temperature 0, seed 17, bounded retries/timeouts, and verdicts without
chain-of-thought. The 12-case human-labelled calibration covers grounded
correctness, wrong numbers/entities/pages, plausible unsupported claims,
correct and false refusals, partial summaries, paraphrases, contradictions,
and irrelevant lexical overlap in Persian and English.

Calibration agreement:

| Dimension | Accuracy | F1 | Confusion matrix TP/TN/FP/FN | Cohen κ |
|---|---:|---:|---:|---:|
| answer correctness | 91.7% | 0.909 | 5/6/1/0 | 0.833 |
| faithfulness | 91.7% | 0.923 | 6/5/0/1 | 0.833 |
| relevance | 91.7% | 0.952 | 10/1/1/0 | 0.625 |
| citation support | 91.7% | 0.857 | 3/8/0/1 | 0.800 |
| refusal correctness | 75.0% | 0.842 | 8/1/0/3 | 0.308 |
| overall | 88.3% | 0.901 | — | 0.759 |

Answer correctness, faithfulness, relevance, and citation support are
release-supporting diagnostics. Refusal correctness remains experimental.
No judge result overrides a deterministic wrong number, entity, page,
answerability decision, or strict GTS component.

## Scorer audit

Goal 2 scoring had five material defects:

1. acceptable answers and summary claims required contiguous lexical matches;
2. Persian/Arabic characters, half-spaces, citation markers, digit systems,
   decimals, and safe English inflections were handled inconsistently;
3. summary section labels were treated as literal headings rather than
   semantic document roles;
4. page accuracy passed when any cited page overlapped, even when extra pages
   were wrong or unnecessarily broad;
5. conversation history was not treated as evidence for a conversation-only
   answer.

Corrections add bounded normalization and safe variants while retaining exact
number/entity/negation constraints. Page scoring now requires cited pages to
be a nonempty subset of expected pages. Adversarial tests reject wrong numbers,
entities, contradictions, missing facts, partial answers, false refusals, and
irrelevant lexical overlap.

Re-scoring saved Goal 2 output, without provider calls, changed acceptable
answer match from 1/15 to 5/15, false refusal from 3/12 to 4/12, strict page
accuracy from 5/13 to 2/13, section coverage from 0.5833 to 1.0, key-claim
recall from 0 to 0.8333, and left strict GTS at 2/15. These are scorer-only
changes and are not counted as new production quality.

## Initial 15-task failure matrix

The full field-level matrix is retained at
`tmp/rag-quality-goal/goal3/checkpoints/checkpoint-b-failure-matrix/`.

| Query | First failure stage | Root cause at Goal 2 |
|---|---|---|
| d16381-summary | scorer | correct paraphrases rejected; broad page scoring |
| conv-d381-summary-clarify:t2 | passed/scorer | behavior passed; page inheritance was scored too broadly |
| d16381-table4 | passed | exact table relation and page 9 already correct |
| d16381-fact-economic | citation selection | correct value, non-minimal pages |
| fx004-fact-leave | fixture preparation | stale failed asset was reused |
| fx003-fact-rollback | ingestion | RTL Persian ۱۵ extracted as ۵۱ |
| fx005-fact-alpha | ingestion | reversed date and incorrect page-title collapse |
| d16395-num-method | validation | supported numeric paragraph rejected |
| d16345-summary | scorer/generation | labels rejected and country detail omitted |
| fx004-noanswer-overtime | fixture preparation | stale failed asset |
| fx001-conflict | ingestion | wrong title anchor hid conflicting pages |
| fx003-cross-threshold | ingestion | wrong page-title anchor hid page 1 |
| fx004-cross | fixture preparation | stale failed asset |
| conv-fx005-ambiguous:t1 | ingestion | reversed dates and missing page content |
| conv-fx005-ambiguous:t2 | scorer | correct clarification; history evidence ignored |

The fixture runner now binds owner, filename, byte size, source SHA-256,
normalization version, and asset ID; it retains assets until all dependent
turns complete and deletes only exact created rows/points afterward. All
previously unavailable fixture tasks remain in the denominator.

## Retained production changes

- Ingestion normalization v5 de-duplicates repeated furniture before the
  garble heuristic, restores multi-digit Persian RTL runs, and avoids treating
  per-page headings in short documents as a global title.
- Routing gives history references and explicit quotes their required
  precedence, recognizes broader factual/numeric/structured cues, and uses
  history-aware retrieval only when a follow-up genuinely needs document
  evidence.
- Conversation JSON parsing no longer assumes perfect JSON. It accepts fenced
  JSON, prefixed JSON, plain prose, and a narrowly repairable truncated value.
  A malformed response falls back locally to the previous answer and never
  starts retrieval. The Goal 2 `JSONDecodeError` came from calling
  `json.loads` directly on a provider response that did not exactly match the
  requested JSON envelope.
- Small-document, numeric, quoted, and multi-section evidence selection was
  widened only within the selected asset, with numeric relation preservation,
  duplicate removal, and history-aware context when needed.
- Table parsing preserves collapsed caption/header/row sequences, Persian and
  Latin digits, rank/value/label relationships, and table page provenance.
  False premises now explicitly correct every compared rank and score.
- Summary structure is selected from actual structural roles. Empirical
  research gets objective/method/findings/discussion/conclusion guidance;
  theoretical papers such as EPR are not forced into fabricated applied
  headings.
- Citation validation adds bounded local marker repair, support-scope
  validation, summary child-evidence page narrowing, number/entity checks, and
  redundant marker removal. It does not invent evidence.

No embedding, generator, reranker, vector database, or broad retrieval
architecture was replaced. Optional contextual chunking, late chunking,
ColBERT, and alternative rerankers were not retained: the remaining IR misses
need a separate measured retrieval experiment and none justified the added
operational complexity within this controlled run. GraphRAG, RAPTOR, parser
migration, and unbounded agents were outside scope.

## Deterministic retrieval

The isolated page-level BM25 index covers 20 documents, 223 pages, and 64
applicable qrels with zero network calls:

| Metric | Goal 3 | Target | Result |
|---|---:|---:|---|
| Recall@5 | 0.6672 | 0.88 | missed |
| Recall@10 | 0.7489 | 0.93 | missed |
| MRR | 0.6881 | 0.80 | missed |
| MAP | 0.6041 | reported | — |
| nDCG@10 | 0.6442 | 0.85 | missed |
| expected-page recall | 0.7489 | reported | — |
| expected-document recall | 0.9688 | reported | — |
| cross-language Recall@10 | 1.0000 (2 tasks) | 0.85 | passed |

Misses are concentrated in sparse page ranking for paraphrased, analytical,
and multi-page evidence. Production improvements focused on correctness and
evidence handling rather than replacing the retrieval architecture; iteration
stopped after the paid production gates and budgeted representative run because
an optional retriever change had not demonstrated the required three-point
gain without citation/latency risk.

## Unchanged 15-task production checkpoint

| Metric | Goal 2 stored | Goal 2 corrected | Goal 3 |
|---|---:|---:|---:|
| route accuracy | 12/15 | 12/15 | 15/15 |
| retrieval necessity | 12/15 | 12/15 | 15/15 |
| acceptable answer | 1/15 | 5/15 | 15/15 |
| false refusal | 3/12 | 4/12 | 0/12 |
| summary section coverage | 0.5833 | 1.0000 | 1.0000 |
| summary key-claim recall | 0 | 0.8333 | 1.0000 |
| summary conclusion | 2/2 | 2/2 | 2/2 |
| citation validity/document | 6/13 | 6/13 | 13/13 |
| strict citation page | 5/13 | 2/13 | 10/13 |
| follow-up resolution | 2/2 | 2/2 | 2/2 |
| unnecessary follow-up retrieval | 0/2 | 0/2 | 0/2 |
| strict GTS | 2/15 | 2/15 | 12/15 |
| latency p50 | 1361 ms | 1361 ms | 2699 ms |
| latency p95 | 35739 ms | 35739 ms | 35598 ms |

All 15 routes, retrieval policies, and answers pass. The three remaining strict
failures are `d16381-summary`, `conv-d381-summary-clarify:t2`, and
`d16345-summary`, all at strict page selection. The summary generator still
uses substantively valid but broader/different page allocations than the
Gold Set. Provider p95 also misses the 25-second target; the two summary calls
dominate, while deterministic table/no-answer paths remain milliseconds.

DeepEval diagnostics on these saved 15 outputs used 15 judge requests:
composite mean 0.8267, 11/15 at the 0.8 pass threshold; answer correctness
0.8000, faithfulness 0.7333, relevance 1.0000, citation support 0.6000, and
refusal correctness 1.0000. Diagnostic failures were `fx004-fact-leave`,
`fx003-fact-rollback`, `fx005-fact-alpha`, and
`conv-fx005-ambiguous:t1`; deterministic exact-value scoring passed them,
illustrating why judge output is secondary.

## Expanded representative subset

The fixed 26-request selection spans 13 documents: six local factual, four
table/numeric, four summary/analytical, three cross-language, three
no-answer/conflict, four conversation turns, and two quoted explanations.

Results: route 25/26 (96.2%), retrieval necessity 25/25 (100%), acceptable
answer 19/26 (73.1%), false refusal 1/23 (4.35%), citation validity/document
23/24 (95.8%), strict page 7/24 (29.2%), conversation resolution 2/2,
summary section coverage 0.9000, key-claim recall 0.6250, conclusion 1/2,
strict GTS 7/26 (26.9%), latency p50 7129.5 ms and p95 23733.3 ms. The real
false refusal is `d14148-quote-explain`.

Per-route deterministic breakdown:

| Expected route | Count | Route | Retrieval | Answer | Strict page | GTS |
|---|---:|---:|---:|---:|---:|---:|
| analytical | 2 | 2/2 | 2/2 | 1/2 | 0/2 | 0/2 |
| comprehensive summary | 2 | 2/2 | 2/2 | 1/2 | 0/2 | 0/2 |
| conversational follow-up | 2 | 2/2 | 2/2 | 2/2 | not required | 0/2 |
| focused RAG | 20 | 19/20 | 20/20 | 15/20 | 9/20 | 7/20 |

Per-document breakdown:

| Document | Tasks | Route | Answer | Strict page | GTS |
|---|---:|---:|---:|---:|---:|
| doh-13-66.pdf | 5 | 4/5 | 2/5 | 0/5 | 0/5 |
| doh-13-75.pdf | 1 | 1/1 | 1/1 | 1/1 | 0/1 |
| doh-14-148.pdf | 1 | 1/1 | 0/1 | 0/1 | 0/1 |
| doh-14-5.pdf | 4 | 4/4 | 4/4 | 0/4 | 0/4 |
| doh-14-54.pdf | 1 | 1/1 | 0/1 | 0/1 | 0/1 |
| doh-14-83.pdf | 3 | 3/3 | 3/3 | 2/3 | 2/3 |
| doh-14-99.pdf | 1 | 1/1 | 1/1 | 1/1 | 1/1 |
| doh-16-334.pdf | 2 | 2/2 | 1/2 | 0/2 | 0/2 |
| doh-16-434.pdf | 2 | 2/2 | 2/2 | 1/2 | 1/2 |
| doh-16-450.pdf | 1 | 1/1 | 1/1 | 0/1 | 0/1 |
| doh-16-456.pdf | 2 | 2/2 | 1/2 | 1/2 | 1/2 |
| conflicting-retention fixture | 1 | 1/1 | 1/1 | 1/1 | 1/1 |
| repeated-header fixture | 2 | 2/2 | 2/2 | 2/2 | 1/2 |

DeepEval diagnostics on all 26 saved responses: composite mean 0.8923, 25/26
passes; answer correctness 0.9231, faithfulness 0.9615, relevance 1.0000,
citation support 0.5769, refusal correctness 1.0000. The only judge failure
was `d1366-cross-conclusion`. The contrast between high semantic scores and
low strict page/GTS scores confirms that the judge cannot replace page-level
release gates.

## Final UI gates

The final Persian six-turn conversation passed: direct whole-document summary,
zero-document-operation clarification, TOPSIS explanation, rank 1, rank 2,
and explicit false-premise correction. The table answers cite physical page 9.
The EPR three-turn conversation passed with a theoretical schema, preserved
central argument, zero-document-operation clarification, and Persian-to-English
evidence lookup for the reality criterion.

Additional gates passed:

- intentional no-answer: the policy has no overtime rule (page 3);
- ambiguous follow-up: “منظورتان پروژه آلفاست یا بتا؟” with zero document
  operations;
- quoted explanation: initial response time differs from full resolution and
  unresolved cases escalate to level two (pages 2–3);
- real table: three financial-component indicators from table 5 (page 11).

No final trace contains `برنامه پاسخ انتخاب شد...`. There were no console,
page, HTTP, or backend errors in the clean Persian run. EPR and additional
diagnostics contained only a browser-cancelled Next.js RSC prefetch, not an
HTTP failure. Screenshots and sanitized traces are retained under
`tmp/rag-quality-goal/goal3/final-ui/20260723-1730/`.

All six exact uploaded assets were removed by asset ID, their exact Qdrant
points and storage directories were verified absent, and the E2E account and
authentication state were retained. The production collection itself was not
recreated or broadly deleted.

## Cost

| Phase | Requests | Input/output tokens | Cost (USD) |
|---|---:|---:|---:|
| unchanged 15 production | 28 | 183900 / 13901 | 0.17143964 |
| judge calibration (12 completed + timeout reserve) | 13 budgeted | 2881 / 892 completed | 0.00287960 |
| expanded 26 production | 57 | 226458 / 16182 | 0.16028049 |
| valid saved-output judges | 41 | 119019 / 4124 | 0.04368440 |
| invalid v1 judge configuration, retained in ledger | 41 | 101110 / 3650 | 0.04628400 |
| final UI and generalization gates | 25 | 73592 / 8840 | 0.05054808 |
| **Goal 3 total** | — | — | **0.47511621** |

The invalid judge v1 used empty expected-page data for citation support; its
results were rejected but its cost was not hidden. Cumulative Goals 1–3 cost is
`$0.80850752`, below both the `$1.60` Goal 3 cap and `$2.00` program cap.

## Known limitations

- The unchanged-15 strict page target is 10/13 versus 11/13 required.
- Deterministic Recall@5, Recall@10, MRR, and nDCG@10 remain below target.
- Provider-dependent unchanged-15 p95 is 35.6 seconds versus 25 seconds.
- Expanded strict page accuracy, summary key-claim recall, conclusion coverage,
  and strict GTS show limited generalization; `d14148-quote-explain` still
  false-refuses.
- Summary citations are grounded but not always the Gold Set's smallest
  sufficient page set. Conversation citations inherited from a previous
  summary can likewise be broader than the strict expected set.
- The Development Set is a controlled engineering benchmark, not evidence of
  universal production readiness.

Detailed scorer, failure-matrix, production, expanded, judge, UI, cleanup, and
cost artifacts remain ignored under `tmp/rag-quality-goal/goal3/`.
