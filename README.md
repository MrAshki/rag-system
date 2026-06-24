# دستیار اسناد — Persian RAG SaaS

A local, Persian-first Retrieval-Augmented Generation (RAG) product. Users sign in
with their phone number, buy a subscription, upload documents (TXT/PDF/DOCX), and ask
questions answered strictly from their own documents. Includes an admin panel.

## Architecture

| Layer | Tech |
|------|------|
| Web / API | Flask (`app.py`), served by waitress in production (`serve.py`) |
| Auth | Phone + OTP, server-side sessions (`auth.py`) |
| Billing | ZarinPal payment gateway (`payments.py`) |
| Data | SQLite for users/plans/subscriptions/payments (`db.py`) |
| Vector store | ChromaDB, per-user isolation via `user_id` metadata |
| Embeddings | `bge-m3` (multilingual) via sentence-transformers, GPU when available |
| LLM | Gemma (`gemma3:12b`) via Ollama |
| Frontend | Vanilla HTML/CSS/JS (`webapp/`), shared design system in `styles.css` |

## Local setup

```bash
python -m venv venv
venv\Scripts\activate            # Windows
pip install -r requirements.txt
# Install a matching PyTorch build (see note in requirements.txt)

cp .env.example .env             # then fill in the values
python -c "import secrets; print(secrets.token_hex(32))"   # -> FLASK_SECRET_KEY

# Make sure Ollama is running and the model is pulled:
ollama pull gemma3:12b

python make_admin.py 09xxxxxxxxx  # create your admin account
python serve.py                   # production server (or `python app.py` for dev)
```

Open http://127.0.0.1:5000

## Environment variables (`.env`)

| Var | Purpose |
|-----|---------|
| `FLASK_SECRET_KEY` | **Required.** Session signing key. |
| `OLLAMA_MODEL` | LLM model name (default `gemma3:12b`). |
| `EMBEDDING_MODEL` | Path/name of the embedding model. |
| `PUBLIC_BASE_URL` | Public URL; used for ZarinPal callback + secure cookies. Use `https://` in production. |
| `SMS_PROVIDER` | `console` logs OTP for testing; swap for a real provider. |
| `ZARINPAL_MERCHANT_ID` | Your ZarinPal merchant id. |
| `ZARINPAL_SANDBOX` | `true` for sandbox testing, `false` for live. |
| `HOST` / `PORT` | Bind address for `serve.py`. |

## Integration points still requiring real credentials

- **SMS/OTP**: implement a real provider in `auth.py:send_otp()`.
- **Payments**: set a real `ZARINPAL_MERCHANT_ID`; verify a full sandbox payment
  (especially whether `Amount` is Toman or Rial for your account) before going live.

## Production notes

- Run with `python serve.py` (waitress), never the Flask dev server.
- Put nginx/Caddy in front for HTTPS; set `PUBLIC_BASE_URL` to the https URL.
- `app_data.sqlite3`, `chroma_persistent_storage/`, and `docs/` hold live user data —
  back them up; they are gitignored.

## Experiments

`experiments/` holds early standalone scripts (`cag.py`, `rac.py`) kept for reference.
They are not part of the product and must not be run against the production vector store.
