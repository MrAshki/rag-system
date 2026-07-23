# خط پایه کیفیت RAG - Development Set

این گزارش یک **خط پایه Development Set** است، نه benchmark تولید و نه ادعای
اطمینان آماری در مقیاس production. هیچ منطق RAG در این هدف بهینه یا اصلاح نشده
است؛ شکست‌ها فقط اندازه‌گیری و ثبت شده‌اند.

## Gold Set و روش راستی‌آزمایی

- اسناد: 20 PDF و 223 صفحه
- تک‌نوبتی: 65
- مکالمه: 10 با 25 نوبت
- همهٔ هش‌های SHA-256 و شمار صفحه‌ها از بایت‌های واقعی PDF دوباره محاسبه شدند.
- متن همهٔ صفحات با `pypdf` بررسی شد؛ صفحه‌های layout-sensitive با
  `pypdfium2` رندر شدند. جدول ۴ سند `doh-16-381.pdf` در صفحه فیزیکی ۹ به‌صورت
  بصری تأیید شد.
- برچسب no-answer با جست‌وجوی کل سند و forbidden-claim guard ثبت شد.

توزیع دسته‌ها:

- `analytical`: 7
- `comprehensive_summary`: 6
- `cross_language`: 6
- `local_factual`: 18
- `no_answer_or_conflict`: 6
- `page_specific`: 9
- `quoted_document_explanation`: 5
- `table_or_numerical`: 8

محدودیت داده: سند انگلیسی‌فقط، PDF تماماً اسکن/OCR، معادله و استدلال چندسندی
در این مجموعه وجود ندارد. `doh-14-54.pdf` لایهٔ متن به‌شدت مخدوش دارد و فقط
sliceهای دستیِ تأییدشده trusted هستند.

## معماری و اجرای ارزیابی

اعتبارسنج ingestion، schema، هش و صفحه کاملاً محلی است. یک index صفحه‌ای
ایزوله و deterministic از متن PDF با BM25 برای zero-cost sanity baseline ساخته
شد. خط پایه production فقط از endpoint واقعی زیر اجرا شد:

`POST http://127.0.0.1:5000/api/ask/stream`

تعداد درخواست endpoint: 15. subset متوازن:

`d16381-summary`, `conv-d381-summary-clarify:t2`, `d16381-table4`, `d16381-fact-economic`, `fx004-fact-leave`, `fx003-fact-rollback`, `fx005-fact-alpha`, `d16395-num-method`, `d16345-summary`, `fx004-noanswer-overtime`, `fx001-conflict`, `fx003-cross-threshold`, `fx004-cross`, `conv-fx005-ambiguous:t1`, `conv-fx005-ambiguous:t2`

دستورها:

```powershell
D:\rag-system\venv\Scripts\python.exe evaluation\runners\evaluate_ingestion.py
D:\rag-system\venv\Scripts\python.exe evaluation\runners\evaluate_retrieval.py --output <ignored-json>
D:\rag-system\venv\Scripts\python.exe evaluation\runners\evaluate_production_baseline.py run --run-dir <ignored-run-dir>
D:\rag-system\venv\Scripts\python.exe evaluation\runners\generate_report.py --production <ignored-json> --isolated-retrieval <ignored-json> --output docs\rag-quality-baseline.md
```

## تعریف معیارها

Retrieval شامل Recall/Precision/Hit Rate@K، MRR، MAP، nDCG، expected-page،
expected-document و evidence-set recall است. معیارهای routing، generation،
summary، citation و conversation به‌صورت deterministic از gold labels محاسبه
می‌شوند. هر نسبت با صورت، مخرج و Wilson 95% گزارش می‌شود.

Grounded Task Success فقط وقتی ۱ است که تمام شرط‌های زیر هم‌زمان برقرار باشند:
route صحیح، شاهد موجود، پاسخ صحیح، پوشش مفاهیم لازم، grounded بودن، citation
صحیح، خروجی کامل و عدم افشای پیام داخلی. این معیار میانگین fuzzy نیست.

## Retrieval

Zero-cost isolated page-index (64 پرسش دارای qrel):

- Recall@1: 42.2%
- Recall@5: 66.7%
- Recall@10: 74.9%
- Precision@5: 24.7%
- Hit Rate@5: 79.7%
- MRR: 0.6881
- MAP: 0.6041
- nDCG@10: 0.6191
- expected-page recall: 74.9%
- expected-document recall: 96.9%
- evidence-set recall: 74.9%

Production subset (citation/source order as observable endpoint evidence):

- Recall@1: 0.0%
- Recall@5: 0.0%
- Recall@10: 0.0%
- Precision@5: 0.0%
- Hit Rate@5: 0.0%
- MRR: 0.0000
- MAP: 0.0000
- nDCG@10: 0.0000

## Routing

| معیار | صورت/مخرج | درصد | Wilson 95% |
|---|---:|---:|---:|
| intent_classification_accuracy | 9/15 | 60.0% | 35.7% تا 80.2% |
| route_selection_accuracy | 9/15 | 60.0% | 35.7% تا 80.2% |
| retrieval_necessity_accuracy | 6/15 | 40.0% | 19.8% تا 64.3% |
| unnecessary_retrieval_rate | 2/2 | 100.0% | 34.2% تا 100.0% |
| missing_retrieval_rate | 7/13 | 53.8% | 29.1% تا 76.8% |
| rewrite_correctness | 14/15 | 93.3% | 70.2% تا 98.8% |
| reranker_call_correctness | 8/15 | 53.3% | 30.1% تا 75.2% |

## Generation

| معیار | صورت/مخرج | درصد | Wilson 95% |
|---|---:|---:|---:|
| normalized_answer_match | 0/15 | 0.0% | 0.0% تا 20.4% |
| acceptable_answer_match | 0/15 | 0.0% | 0.0% تا 20.4% |
| forbidden_claim_rate | 0/15 | 0.0% | 0.0% تا 20.4% |
| generic_failure_rate | 0/15 | 0.0% | 0.0% تا 20.4% |
| false_refusal_rate | 7/12 | 58.3% | 32.0% تا 80.7% |
| truncation_rate | 0/15 | 0.0% | 0.0% تا 20.4% |

- میانگین پوشش required concepts: 0.0%

## Summary

- تعداد: 2
- substantive-section coverage: 0.0%
- key-claim recall: 0.0%
- contamination rate: 0.0%
- page-range diversity: 0.0%
- comprehensive-summary pass:

| معیار | صورت/مخرج | درصد | Wilson 95% |
|---|---:|---:|---:|
| conclusion coverage | 0/2 | 0.0% | 0.0% تا 65.8% |
| comprehensive-summary pass | 0/2 | 0.0% | 0.0% تا 65.8% |

## Citations

| معیار | صورت/مخرج | درصد | Wilson 95% |
|---|---:|---:|---:|
| citation_validity | 0/13 | 0.0% | 0.0% تا 22.8% |
| citation_document_accuracy | 0/13 | 0.0% | 0.0% تا 22.8% |
| citation_page_accuracy | 0/13 | 0.0% | 0.0% تا 22.8% |
| citation_recall | 0/13 | 0.0% | 0.0% تا 22.8% |
| unsupported_numeric_citation_failure | 0/6 | 0.0% | 0.0% تا 39.0% |
| metadata_only_citation_failure | 0/13 | 0.0% | 0.0% تا 22.8% |

## Conversation

| معیار | صورت/مخرج | درصد | Wilson 95% |
|---|---:|---:|---:|
| followup_resolution_accuracy | 0/2 | 0.0% | 0.0% تا 65.8% |
| history_use_accuracy | 0/2 | 0.0% | 0.0% تا 65.8% |
| unnecessary_retrieval_rate | 2/2 | 100.0% | 34.2% تا 100.0% |
| selected_asset_persistence | 2/2 | 100.0% | 34.2% تا 100.0% |
| conversation_id_persistence | 2/2 | 100.0% | 34.2% تا 100.0% |

## Grounded Task Success

| route | صورت/مخرج | درصد | Wilson 95% |
|---|---:|---:|---:|
| analytical | 0/1 | 0.0% | 0.0% تا 79.3% |
| comprehensive_summary | 0/2 | 0.0% | 0.0% تا 65.8% |
| conversational_followup | 0/2 | 0.0% | 0.0% تا 65.8% |
| focused_rag | 0/9 | 0.0% | 0.0% تا 29.9% |
| specific_section | 0/1 | 0.0% | 0.0% تا 79.3% |

Overall:

| معیار | صورت/مخرج | درصد | Wilson 95% |
|---|---:|---:|---:|
| Development subset GTS | 0/15 | 0.0% | 0.0% تا 20.4% |

## Latency و هزینه

- latency p50: 3573 ms
- latency p95: 35211 ms
- endpoint requests: 15
- endpoint attempts (including local HTTP 429 attempts): 25
- provider requests ثبت‌شده: 21
- input tokens: 48288
- output tokens: 8882
- exact recorded API cost: `$0.04927749`
- hard cap `$0.35`: رعایت شد

## شکست‌های نماینده

- `d16381-summary`: evidence_available، answer_correct، required_concepts_covered، grounded، citations_correct
- `conv-d381-summary-clarify:t2`: answer_correct، required_concepts_covered، grounded، citations_correct
- `d16381-table4`: answer_correct، required_concepts_covered، grounded، citations_correct
- `d16381-fact-economic`: answer_correct، required_concepts_covered، grounded، citations_correct
- `fx004-fact-leave`: route_correct، evidence_available، answer_correct، required_concepts_covered، grounded، citations_correct، output_complete
- `fx003-fact-rollback`: route_correct، evidence_available، answer_correct، required_concepts_covered، grounded، citations_correct
- `fx005-fact-alpha`: answer_correct، required_concepts_covered، grounded، citations_correct
- `d16395-num-method`: route_correct، evidence_available، answer_correct، required_concepts_covered، grounded، citations_correct

بدترین sliceها فقط بر اساس اندازه‌گیری بالا شناسایی می‌شوند؛ این گزارش پیشنهاد
تغییر معماری نمی‌دهد.

## معیارهای ناممکن/اندازه‌گیری‌نشده

- provider-backed GTS برای هر ۶۵ task، به دلیل سقف هزینه، اجرا نشد.
- confidence تولیدی از این Development Set کوچک قابل استنتاج نیست.
- OCR تمام‌صفحه، سند انگلیسی‌فقط، equation retrieval و multi-document reasoning
  در داده حاضر قابل اندازه‌گیری نیستند.
- کیفیت semantic index تولید برای کل ۲۰ سند فقط در subset endpoint سنجیده شد؛
  zero-cost BM25 یک sanity baseline ایزوله است و جای production index را نمی‌گیرد.

## اعتبارسنجی

- تست معیارها: 21 passed in 2.18s
- pytest کامل: 96 passed, 4 failed in 6.67s (existing RAG tests; not modified in Goal 1)
- pip check: No broken requirements found
- git diff --check: passed (only LF/CRLF warning for .gitignore)

هیچ مدل اصلی، fallback یا embedding تغییر نکرد؛ هیچ parser، chunker، retrieval،
reranker، prompt، citation logic، UI، auth، PostgreSQL schema یا Qdrant schema
تغییر نکرد. هیچ commit، stage، push، tag یا PR ساخته نشد.
