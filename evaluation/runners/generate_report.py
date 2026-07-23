from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _prop(label: str, value: dict) -> str:
    interval = value.get("wilson_95", {})
    return (
        f"| {label} | {value.get('numerator', 0)}/{value.get('denominator', 0)} | "
        f"{value.get('percentage', 0):.1f}% | "
        f"{interval.get('low', 0) * 100:.1f}% تا {interval.get('high', 0) * 100:.1f}% |"
    )


def _metric_table(metrics: dict) -> str:
    lines = [
        "| معیار | صورت/مخرج | درصد | Wilson 95% |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(_prop(name, value) for name, value in metrics.items() if isinstance(value, dict) and "numerator" in value)
    return "\n".join(lines)


def render_report(data: dict) -> str:
    gold = data["goldset"]
    prod = data["production"]
    isolated = data["isolated_retrieval"]
    validation = data.get("validation", {})
    usage = prod["usage"]
    ranking = prod["retrieval"]
    failures = []
    conditions = [
        "route_correct", "evidence_available", "answer_correct",
        "required_concepts_covered", "grounded", "citations_correct",
        "output_complete", "no_internal_message_exposed",
    ]
    for row in prod.get("results", []):
        failed = [name for name in conditions if not row.get(name)]
        if failed:
            failures.append(f"- `{row['query_id']}`: " + "، ".join(failed))
    route_gts = prod["grounded_task_success"]["per_route"]
    route_lines = "\n".join(_prop(route, value) for route, value in route_gts.items())
    means = isolated["means"]
    prod_means = ranking["means"]
    category_lines = "\n".join(
        f"- `{name}`: {count}"
        for name, count in sorted(gold["categories"].items())
    )
    return f"""# خط پایه کیفیت RAG - Development Set

این گزارش یک **خط پایه Development Set** است، نه benchmark تولید و نه ادعای
اطمینان آماری در مقیاس production. هیچ منطق RAG در این هدف بهینه یا اصلاح نشده
است؛ شکست‌ها فقط اندازه‌گیری و ثبت شده‌اند.

## Gold Set و روش راستی‌آزمایی

- اسناد: {gold['documents']} PDF و {gold['pages']} صفحه
- تک‌نوبتی: {gold['tasks']}
- مکالمه: {gold['conversations']} با {gold['conversation_turns']} نوبت
- همهٔ هش‌های SHA-256 و شمار صفحه‌ها از بایت‌های واقعی PDF دوباره محاسبه شدند.
- متن همهٔ صفحات با `pypdf` بررسی شد؛ صفحه‌های layout-sensitive با
  `pypdfium2` رندر شدند. جدول ۴ سند `doh-16-381.pdf` در صفحه فیزیکی ۹ به‌صورت
  بصری تأیید شد.
- برچسب no-answer با جست‌وجوی کل سند و forbidden-claim guard ثبت شد.

توزیع دسته‌ها:

{category_lines}

محدودیت داده: سند انگلیسی‌فقط، PDF تماماً اسکن/OCR، معادله و استدلال چندسندی
در این مجموعه وجود ندارد. `doh-14-54.pdf` لایهٔ متن به‌شدت مخدوش دارد و فقط
sliceهای دستیِ تأییدشده trusted هستند.

## معماری و اجرای ارزیابی

اعتبارسنج ingestion، schema، هش و صفحه کاملاً محلی است. یک index صفحه‌ای
ایزوله و deterministic از متن PDF با BM25 برای zero-cost sanity baseline ساخته
شد. خط پایه production فقط از endpoint واقعی زیر اجرا شد:

`POST {prod['endpoint']}`

تعداد درخواست endpoint: {prod['endpoint_request_count']}. subset متوازن:

{', '.join(f'`{item}`' for item in prod['core_subset'])}

دستورها:

```powershell
D:\\rag-system\\venv\\Scripts\\python.exe evaluation\\runners\\evaluate_ingestion.py
D:\\rag-system\\venv\\Scripts\\python.exe evaluation\\runners\\evaluate_retrieval.py --output <ignored-json>
D:\\rag-system\\venv\\Scripts\\python.exe evaluation\\runners\\evaluate_production_baseline.py run --run-dir <ignored-run-dir>
D:\\rag-system\\venv\\Scripts\\python.exe evaluation\\runners\\generate_report.py --production <ignored-json> --isolated-retrieval <ignored-json> --output docs\\rag-quality-baseline.md
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

Zero-cost isolated page-index ({isolated['query_count']} پرسش دارای qrel):

- Recall@1: {_pct(means.get('recall@1', 0))}
- Recall@5: {_pct(means.get('recall@5', 0))}
- Recall@10: {_pct(means.get('recall@10', 0))}
- Precision@5: {_pct(means.get('precision@5', 0))}
- Hit Rate@5: {_pct(means.get('hit_rate@5', 0))}
- MRR: {means.get('mrr', 0):.4f}
- MAP: {means.get('ap', 0):.4f}
- nDCG@10: {means.get('ndcg@10', 0):.4f}
- expected-page recall: {_pct(means.get('expected_page_recall', 0))}
- expected-document recall: {_pct(means.get('expected_document_recall', 0))}
- evidence-set recall: {_pct(means.get('evidence_set_recall', 0))}

Production subset (citation/source order as observable endpoint evidence):

- Recall@1: {_pct(prod_means.get('recall@1', 0))}
- Recall@5: {_pct(prod_means.get('recall@5', 0))}
- Recall@10: {_pct(prod_means.get('recall@10', 0))}
- Precision@5: {_pct(prod_means.get('precision@5', 0))}
- Hit Rate@5: {_pct(prod_means.get('hit_rate@5', 0))}
- MRR: {prod_means.get('mrr', 0):.4f}
- MAP: {prod_means.get('ap', 0):.4f}
- nDCG@10: {prod_means.get('ndcg@10', 0):.4f}

## Routing

{_metric_table(prod['routing'])}

## Generation

{_metric_table({key: value for key, value in prod['generation'].items() if isinstance(value, dict)})}

- میانگین پوشش required concepts: {_pct(prod['generation'].get('required_concept_coverage_mean', 0))}

## Summary

- تعداد: {prod['summary']['task_count']}
- substantive-section coverage: {_pct(prod['summary']['substantive_section_coverage_mean'])}
- key-claim recall: {_pct(prod['summary']['key_claim_recall_mean'])}
- contamination rate: {_pct(prod['summary']['contamination_rate_mean'])}
- page-range diversity: {_pct(prod['summary']['page_range_diversity_mean'])}
- comprehensive-summary pass:

{_metric_table({'conclusion coverage': prod['summary']['conclusion_coverage'], 'comprehensive-summary pass': prod['summary']['comprehensive_summary_pass']})}

## Citations

{_metric_table(prod['citations'])}

## Conversation

{_metric_table(prod['conversations'])}

## Grounded Task Success

| route | صورت/مخرج | درصد | Wilson 95% |
|---|---:|---:|---:|
{route_lines}

Overall:

{_metric_table({'Development subset GTS': prod['grounded_task_success']['overall']})}

## Latency و هزینه

- latency p50: {prod['latency_ms']['p50']:.0f} ms
- latency p95: {prod['latency_ms']['p95']:.0f} ms
- endpoint requests: {prod['endpoint_request_count']}
- endpoint attempts (including local HTTP 429 attempts): {prod.get('endpoint_attempt_count', prod['endpoint_request_count'])}
- provider requests ثبت‌شده: {usage['provider_request_count']}
- input tokens: {usage['input_tokens']}
- output tokens: {usage['output_tokens']}
- exact recorded API cost: `${usage['cost_usd']:.8f}`
- hard cap `$0.35`: {'رعایت شد' if prod['hard_cap_respected'] else 'نقض شد'}

## شکست‌های نماینده

{chr(10).join(failures[:8]) if failures else '- شکست GTS در subset مشاهده نشد.'}

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

- تست معیارها: {validation.get('metric_tests', 'ثبت نشده')}
- pytest کامل: {validation.get('full_pytest', 'ثبت نشده')}
- pip check: {validation.get('pip_check', 'ثبت نشده')}
- git diff --check: {validation.get('diff_check', 'ثبت نشده')}

هیچ مدل اصلی، fallback یا embedding تغییر نکرد؛ هیچ parser، chunker، retrieval،
reranker، prompt، citation logic، UI، auth، PostgreSQL schema یا Qdrant schema
تغییر نکرد. هیچ commit، stage، push، tag یا PR ساخته نشد.
"""


def build_data(production: Path, isolated_retrieval: Path, validation: Path | None) -> dict:
    manifest = [
        json.loads(line)
        for line in (ROOT / "evaluation" / "dev_goldset" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tasks = [
        json.loads(line)
        for line in (ROOT / "evaluation" / "dev_goldset" / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    conversations = [
        json.loads(line)
        for line in (ROOT / "evaluation" / "dev_goldset" / "conversations.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {
        "goldset": {
            "documents": len(manifest),
            "pages": sum(row["page_count"] for row in manifest),
            "tasks": len(tasks),
            "conversations": len(conversations),
            "conversation_turns": sum(len(row["turns"]) for row in conversations),
            "categories": dict(Counter(row["task_type"] for row in tasks)),
        },
        "production": json.loads(production.read_text(encoding="utf-8")),
        "isolated_retrieval": json.loads(isolated_retrieval.read_text(encoding="utf-8")),
        "validation": json.loads(validation.read_text(encoding="utf-8-sig")) if validation else {},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", type=Path, required=True)
    parser.add_argument("--isolated-retrieval", type=Path, required=True)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "rag-quality-baseline.md")
    args = parser.parse_args()
    output = render_report(build_data(args.production, args.isolated_retrieval, args.validation))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
