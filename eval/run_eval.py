"""Baseline benchmark runner for the local RAG pipeline (Step 1: measurement only).

Loads eval/golden_set.json, calls the EXISTING rag.py functions exactly as the
app does today (no changes to rag.py / app.py), and reports approximate
Recall@5, Recall@10, MRR, source/keyword grounding, false-refusal flags, and an
LLM-judge faithfulness/correctness pass (a separate ollama call made only from
this script, not from the pipeline itself).

Usage (PowerShell, from the project venv):
    .\\venv\\Scripts\\python.exe eval\\run_eval.py
    .\\venv\\Scripts\\python.exe eval\\run_eval.py --no-judge
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import ollama  # noqa: E402  (same dependency rag.py already uses)
import rag  # noqa: E402  (existing pipeline, not modified)

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:12b")

REFUSAL_MARKERS = (
    "اطلاعات کافی در اسناد موجود برای پاسخ به این سؤال وجود ندارد",
    "در سند انتخاب‌شده اطلاعات کافی برای پاسخ وجود ندارد",
)


def is_refusal(answer: str) -> bool:
    return any(marker in (answer or "") for marker in REFUSAL_MARKERS)


def keyword_hit_ranks(chunks, keywords):
    if not keywords:
        return []
    lowered_kw = [k.lower() for k in keywords]
    ranks = []
    for i, c in enumerate(chunks, start=1):
        text = (c.get("text") or "").lower()
        if any(kw in text for kw in lowered_kw):
            ranks.append(i)
    return ranks


def source_hit_ranks(chunks, expected_filename):
    if not expected_filename:
        return []
    return [i for i, c in enumerate(chunks, start=1) if c.get("source") == expected_filename]


def judge_with_llm(question_fa, expected_answer_fa, produced_answer, context_text):
    """Ask the same local Ollama model to grade correctness/faithfulness.
    Best-effort JSON parsing; never raises -- returns a dict with an 'error' key on failure."""
    prompt = (
        "You are grading a Persian-language RAG answer. Respond with ONLY a compact JSON object, "
        "no extra text, no markdown fences.\n"
        'Schema: {"correctness": "correct"|"partial"|"incorrect", '
        '"faithful": "yes"|"partial"|"no", "reason": "<short Persian or English reason>"}\n\n'
        f"Question: {question_fa}\n\n"
        f"Expected answer (reference): {expected_answer_fa}\n\n"
        f"Produced answer: {produced_answer}\n\n"
        f"Retrieved context (what the model was allowed to use):\n{context_text[:4000]}\n\n"
        "correctness = how well the produced answer matches the reference answer's meaning. "
        "faithful = whether the produced answer's claims are actually supported by the retrieved context "
        "(not the reference answer)."
    )
    try:
        resp = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0, "num_ctx": 4096},
        )
        raw = resp["message"]["content"].strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            raw = raw[start:end + 1]
        parsed = json.loads(raw)
        return {
            "correctness": parsed.get("correctness", "unparsed"),
            "faithful": parsed.get("faithful", "unparsed"),
            "reason": parsed.get("reason", ""),
        }
    except Exception as e:
        return {"correctness": "judge_error", "faithful": "judge_error", "reason": str(e)}


def run(golden_path, out_json_path, out_txt_path, n_results, use_judge):
    with open(golden_path, "r", encoding="utf-8") as f:
        golden = json.load(f)

    items = golden["items"]
    results = []
    t0 = time.time()

    for idx, item in enumerate(items, start=1):
        qid = item["id"]
        question = item["question_fa"]
        print(f"[{idx}/{len(items)}] {qid} ...", flush=True)

        chunks = rag.query_documents(question, n_results=n_results, document_id=None, user_id=None)
        top5 = chunks[:5]
        gen = rag.generate_response(question, top5, scope="all", selected_source=None)
        answer = gen.get("answer", "")
        sources = gen.get("sources", [])

        kw_ranks = keyword_hit_ranks(chunks, item.get("expected_keywords"))
        src_ranks = source_hit_ranks(chunks, item.get("filename"))
        first_kw_rank = min(kw_ranks) if kw_ranks else None

        refusal = is_refusal(answer)
        is_true_negative = bool(item.get("is_true_negative"))

        recall5 = recall10 = mrr = None
        false_refusal = False
        true_negative_correct = None

        if is_true_negative:
            true_negative_correct = refusal and not kw_ranks
        else:
            recall5 = 1 if (first_kw_rank is not None and first_kw_rank <= 5) else 0
            recall10 = 1 if first_kw_rank is not None else 0
            mrr = (1.0 / first_kw_rank) if first_kw_rank else 0.0
            false_refusal = refusal and recall10 == 1

        judge = None
        if use_judge and not is_true_negative:
            context_text = "\n\n".join((c.get("text") or "") for c in top5)
            judge = judge_with_llm(question, item.get("expected_answer_fa", ""), answer, context_text)

        results.append({
            "id": qid,
            "category": item.get("category"),
            "question_fa": question,
            "expected_filename": item.get("filename"),
            "expected_keywords": item.get("expected_keywords"),
            "expected_chapter_or_section": item.get("expected_chapter_or_section"),
            "is_true_negative": is_true_negative,
            "retrieved_top10_sources": [c["source"] for c in chunks],
            "keyword_hit_ranks": kw_ranks,
            "source_hit_ranks": src_ranks,
            "first_keyword_hit_rank": first_kw_rank,
            "recall_at_5": recall5,
            "recall_at_10": recall10,
            "mrr_contribution": mrr,
            "is_refusal": refusal,
            "false_refusal": false_refusal,
            "true_negative_correct": true_negative_correct,
            "answer": answer,
            "sources": sources,
            "llm_judge": judge,
        })

    elapsed = time.time() - t0

    positive = [r for r in results if not r["is_true_negative"]]
    neg = [r for r in results if r["is_true_negative"]]

    n_pos = len(positive)
    agg = {
        "n_items_total": len(results),
        "n_positive_items": n_pos,
        "n_true_negative_items": len(neg),
        "recall_at_5": (sum(r["recall_at_5"] for r in positive) / n_pos) if n_pos else None,
        "recall_at_10": (sum(r["recall_at_10"] for r in positive) / n_pos) if n_pos else None,
        "mrr": (sum(r["mrr_contribution"] for r in positive) / n_pos) if n_pos else None,
        "false_refusal_count": sum(1 for r in positive if r["false_refusal"]),
        "true_negative_correct_count": sum(1 for r in neg if r["true_negative_correct"]),
        "true_negative_hallucination_count": sum(1 for r in neg if r["true_negative_correct"] is False),
        "elapsed_seconds": round(elapsed, 1),
        "ollama_model": OLLAMA_MODEL,
        "embedding_model": os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        "n_results_fetched": n_results,
        "llm_judge_enabled": use_judge,
    }
    if use_judge:
        judged = [r for r in positive if r["llm_judge"] and r["llm_judge"].get("correctness") not in ("judge_error",)]
        agg["judge_correct_count"] = sum(1 for r in judged if r["llm_judge"]["correctness"] == "correct")
        agg["judge_partial_count"] = sum(1 for r in judged if r["llm_judge"]["correctness"] == "partial")
        agg["judge_incorrect_count"] = sum(1 for r in judged if r["llm_judge"]["correctness"] == "incorrect")
        agg["judge_faithful_yes_count"] = sum(1 for r in judged if r["llm_judge"]["faithful"] == "yes")
        agg["judge_faithful_no_count"] = sum(1 for r in judged if r["llm_judge"]["faithful"] == "no")
        agg["judge_unparsed_or_error_count"] = len(positive) - len(judged)

    report = {"aggregate": agg, "items": results}

    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    write_text_report(out_txt_path, agg, results)

    print(f"\nDone in {elapsed:.1f}s. JSON: {out_json_path}  TXT: {out_txt_path}")
    return report


def write_text_report(path, agg, results):
    lines = []
    lines.append("BASELINE RAG BENCHMARK REPORT")
    lines.append(f"items total: {agg['n_items_total']}  positive: {agg['n_positive_items']}  true_negative: {agg['n_true_negative_items']}")
    lines.append(f"embedding_model: {agg['embedding_model']}  ollama_model: {agg['ollama_model']}  n_results_fetched: {agg['n_results_fetched']}")
    lines.append(f"elapsed_seconds: {agg['elapsed_seconds']}")
    lines.append("")
    lines.append("AGGREGATE METRICS (positive items only, approximate via keyword matching)")
    lines.append(f"Recall@5:  {fmt_pct(agg['recall_at_5'])}")
    lines.append(f"Recall@10: {fmt_pct(agg['recall_at_10'])}")
    lines.append(f"MRR:       {fmt_num(agg['mrr'])}")
    lines.append(f"False refusals (right info retrieved, model still refused): {agg['false_refusal_count']} / {agg['n_positive_items']}")
    lines.append("")
    lines.append("TRUE-NEGATIVE CONTROL ITEMS")
    lines.append(f"Correctly refused: {agg['true_negative_correct_count']} / {agg['n_true_negative_items']}")
    lines.append(f"Hallucinated an answer instead of refusing: {agg['true_negative_hallucination_count']} / {agg['n_true_negative_items']}")
    if "judge_correct_count" in agg:
        lines.append("")
        lines.append("LLM-JUDGE METRICS (positive items, gemma3-graded; treat as indicative, not ground truth)")
        lines.append(f"correct: {agg['judge_correct_count']}  partial: {agg['judge_partial_count']}  incorrect: {agg['judge_incorrect_count']}  unparsed/error: {agg['judge_unparsed_or_error_count']}")
        lines.append(f"faithful=yes: {agg['judge_faithful_yes_count']}  faithful=no: {agg['judge_faithful_no_count']}")
    lines.append("")
    lines.append("PER-ITEM DETAIL")
    for r in results:
        lines.append("-" * 70)
        lines.append(f"id: {r['id']}  category: {r['category']}  true_negative: {r['is_true_negative']}")
        lines.append(f"question_fa: {r['question_fa']}")
        lines.append(f"expected_filename: {r['expected_filename']}  expected_section: {r['expected_chapter_or_section']}")
        lines.append(f"retrieved_sources(top10): {r['retrieved_top10_sources']}")
        lines.append(f"keyword_hit_ranks: {r['keyword_hit_ranks']}  first_hit_rank: {r['first_keyword_hit_rank']}")
        if not r["is_true_negative"]:
            lines.append(f"recall@5: {r['recall_at_5']}  recall@10: {r['recall_at_10']}  mrr_contrib: {fmt_num(r['mrr_contribution'])}")
            lines.append(f"is_refusal: {r['is_refusal']}  false_refusal: {r['false_refusal']}")
        else:
            lines.append(f"is_refusal: {r['is_refusal']}  true_negative_correct: {r['true_negative_correct']}")
        if r["llm_judge"]:
            lines.append(f"llm_judge: correctness={r['llm_judge']['correctness']}  faithful={r['llm_judge']['faithful']}  reason={r['llm_judge']['reason']}")
        lines.append(f"answer: {r['answer']}")
        lines.append(f"sources: {r['sources']}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def fmt_pct(v):
    return "n/a" if v is None else f"{v * 100:.1f}%"


def fmt_num(v):
    return "n/a" if v is None else f"{v:.3f}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baseline RAG benchmark runner (read-only, no pipeline changes)")
    here = os.path.dirname(os.path.abspath(__file__))
    parser.add_argument("--golden", default=os.path.join(here, "golden_set.json"))
    parser.add_argument("--out-json", default=os.path.join(here, "baseline_report.json"))
    parser.add_argument("--out-txt", default=os.path.join(here, "baseline_report.txt"))
    parser.add_argument("--n-results", type=int, default=10, help="chunks fetched per query for recall@10 measurement")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM-judge correctness/faithfulness pass")
    args = parser.parse_args()

    run(args.golden, args.out_json, args.out_txt, args.n_results, use_judge=not args.no_judge)
