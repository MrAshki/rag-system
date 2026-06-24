"""Grounding regression run through the ACTUAL Flask /api/ask route.

Unlike check_grounding.py (which calls rag.generate_response directly), this drives
the real backend path: the /api/ask view, its split_questions() handling, and the
per-user query_documents(user_id=...) retrieval filter -- exactly what the browser
hits. It uses Flask's in-process test_client with a real logged-in session, so only
the OTP/network login step is bypassed (that step cannot affect answer generation).

READ-ONLY: only queries Chroma + calls local Ollama. No writes, no reindex.

Usage (PowerShell, project root, project venv):
    .\\venv\\Scripts\\python.exe scripts\\check_grounding_api.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import rag      # noqa: E402
import db       # noqa: E402
import app as appmod  # noqa: E402

BOOK_OWNER_PHONE = "09391324913"

ENTITY_VARIANTS = ["محمد اشکریز", "اشکریز", "اشكريز", "mohammad ashkriz", "ashkriz"]

CASES = [
    ("A", "اراده آزاد از نظر محمد اشکریز چیه؟",
     "Persian; must say محمد اشکریز not found; must NOT attribute a view to him; then explain topic."),
    ("B", "کتاب درباره اراده آزاد چی میگه؟",
     "Persian grounded answer; no unnecessary 'entity missing' warning."),
    ("C", "این کتاب درباره رژیم کتو چی میگه؟",
     "Exact unsupported/refusal; no fake keto explanation."),
    ("D", "What does the book say about free will?",
     "English grounded answer."),
    ("E", "نظر رابرت ساپولسکی درباره اراده آزاد چیه؟",
     "If Sapolsky in retrieved text -> may attribute carefully; if not -> say not found then explain topic."),
]


def detect_lang(text):
    fa = len(re.findall(r"[؀-ۿ]", text or ""))
    en = len(re.findall(r"[A-Za-z]", text or ""))
    return "fa" if fa >= en and fa > 0 else ("en" if en else "unknown")


def pick_user():
    u = db.get_user_by_phone(BOOK_OWNER_PHONE)
    if u and (u["is_admin"] or db.get_active_subscription(u["id"])):
        return u
    for u in db.list_users():
        if u["is_admin"] or db.get_active_subscription(u["id"]):
            return u
    return u  # fall back (route may 402, which we'll report)


def main():
    print(f"[proof] rag module     : {os.path.abspath(rag.__file__)}")
    print(f"[proof] prompt version : {rag.ANSWER_PROMPT_VERSION}")
    print(f"[proof] OLLAMA_MODEL    : {rag.OLLAMA_MODEL}")
    print(f"[proof] OLLAMA_NUM_CTX  : {rag.OLLAMA_NUM_CTX}")
    print(f"[proof] EMBEDDING_MODEL : {rag.EMBEDDING_MODEL}")
    print(f"[proof] app uses rag id : {id(appmod.rag)} (same module: {appmod.rag is rag})")
    print(f"[proof] collection count: {rag.collection.count()}\n")

    user = pick_user()
    print(f"Logged-in test user: id={user['id']} phone={user.get('phone')} "
          f"is_admin={user['is_admin']} active_sub={bool(db.get_active_subscription(user['id']))}\n")

    flask_app = appmod.app
    flask_app.config["TESTING"] = True
    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["phone"] = user.get("phone")

    for tag, q, expect in CASES:
        print("=" * 80)
        print(f"CASE {tag}: {q}")
        print(f"Expected: {expect}")

        # show retrieval the route will use (same user_id, same call)
        chunks = rag.query_documents(q, user_id=user["id"])
        joined = "\n".join(c["text"] for c in chunks).lower()
        labels = [rag._citation_label(c) for c in chunks]
        print("Retrieved source labels:")
        for l in labels:
            print(f"  - {l}")
        hits = sorted({v for v in ENTITY_VARIANTS if v.lower() in joined})
        print(f"Entity variants in retrieved text: {hits if hits else 'NONE'}")

        resp = client.post("/api/ask", json={"question": q, "scope": "all"})
        data = resp.get_json() or {}
        ans = data.get("answer", f"<no answer; status={resp.status_code} body={data}>")
        print(f"HTTP {resp.status_code} | answer language: {detect_lang(ans)} "
              f"(question: {detect_lang(q)}) | sources: {len(data.get('sources', []))}")
        print(f"ANSWER:\n{ans}\n")


if __name__ == "__main__":
    main()
