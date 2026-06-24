"""Lightweight, READ-ONLY grounding/language regression check.

Runs a fixed set of questions against the CURRENT live Chroma data and prints,
for each case: the retrieved source labels, whether the named entity appears in
the retrieved text, the generated answer, its detected language, and the cited
sources. It only calls collection.query() (read) + ollama.chat() (local Ollama) --
it never upserts, deletes, or otherwise modifies Chroma, and never reindexes.

Usage (PowerShell, from the project root, with the project venv):
    .\\venv\\Scripts\\python.exe scripts\\check_grounding.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import rag  # noqa: E402

# Variants of the user-mentioned name we want to confirm are NOT in the book.
ENTITY_VARIANTS = [
    "محمد اشکریز", "اشکریز", "اشكريز",
    "mohammad ashkriz", "ashkriz", "ashkooriz", "ashkoriz",
]

CASES = [
    {
        "name": "Persian, named person NOT in book (the reported bug)",
        "q": "اراده آزاد از نظر محمد اشکریز چیه؟",
        "entity": "محمد اشکریز",
        "expect": "Persian answer; must NOT attribute a free-will view to محمد اشکریز; "
                  "should state he is not mentioned in the retrieved text.",
    },
    {
        "name": "Persian, general grounded question",
        "q": "کتاب درباره اراده آزاد چی میگه؟",
        "entity": None,
        "expect": "Persian grounded answer drawn from the book.",
    },
    {
        "name": "Unsupported topic (keto diet)",
        "q": "این کتاب درباره رژیم کتو چی میگه؟",
        "entity": None,
        "expect": "Refusal / unsupported (exact no-info sentence).",
    },
    {
        "name": "English grounded question",
        "q": "What does the book say about free will?",
        "entity": None,
        "expect": "English grounded answer.",
    },
]


def detect_lang(text: str) -> str:
    return "fa" if re.search(r"[؀-ۿ]", text or "") else "en"


def main():
    print(f"Live collection count: {rag.collection.count()} (read-only; Chroma not modified)\n")
    for c in CASES:
        print("=" * 80)
        print(f"CASE: {c['name']}")
        print(f"Q   : {c['q']}")
        print(f"Want: {c['expect']}")

        chunks = rag.query_documents(c["q"], n_results=5, user_id=None)
        print(f"\nRetrieved {len(chunks)} chunk(s):")
        for ch in chunks:
            print(f"  - {rag._citation_label(ch)}")

        joined = "\n".join(ch["text"] for ch in chunks).lower()
        hits = sorted({v for v in ENTITY_VARIANTS if v.lower() in joined})
        print(f"\nEntity variants present in retrieved text: {hits if hits else 'NONE'}")

        result = rag.generate_response(c["q"], chunks, scope="all")
        ans = result["answer"]
        print(f"Answer language : {detect_lang(ans)} (question language: {detect_lang(c['q'])})")
        print(f"Sources cited   : {len(result['sources'])}")
        print(f"Answer:\n{ans}")

        if c["entity"]:
            mentions_entity = c["entity"] in ans
            disclaims = ("پیدا نکردم" in ans) or ("اشاره" in ans) or ("یافت نشد" in ans)
            wrongly_attributed = mentions_entity and not disclaims
            print(f"\n[CHECK] mentions entity: {mentions_entity} | "
                  f"disclaims-not-found: {disclaims} | "
                  f"WRONGLY ATTRIBUTES VIEW: {'YES (BAD)' if wrongly_attributed else 'no'}")
        print()


if __name__ == "__main__":
    main()
