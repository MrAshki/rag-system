# دستیار اسناد — Persian RAG SaaS

A local, Persian-first Retrieval-Augmented Generation (RAG) product. Users sign in
with their phone number, buy a subscription, upload documents (TXT/PDF/DOCX), and ask
questions answered strictly from their own documents. Includes an admin panel.

## Architecture

| Layer | Tech |
|------|------|
| Frontend | Next.js app in `apps/web` |
| API | FastAPI (`backend/app/main.py`), served by Uvicorn (`serve.py` or `python -m backend.run`) |
| Auth | Phone + OTP, Starlette signed sessions (`backend/app/services/auth_service.py`) |
| Billing | ZarinPal payment gateway (`payments.py`) |
| Data | PostgreSQL + SQLAlchemy for users, billing, conversations, files, chunks, and metadata |
| Migrations | Alembic (`backend/app/db/migrations`) |
| Vector store | pgvector behind `backend/app/vector/VectorStore`; Qdrant adapter is a future swap-in |
| Embeddings | `bge-m3` (multilingual) via sentence-transformers, GPU when available |
| LLM | Gemma (`gemma3:12b`) via Ollama |

## Local setup

```bash
python -m venv venv
venv\Scripts\activate            # Windows
pip install -r requirements.txt
# Install a matching PyTorch build (see note in requirements.txt)

cp .env.example .env             # then fill in the values
python -c "import secrets; print(secrets.token_hex(32))"   # -> SESSION_SECRET_KEY

# Make sure Ollama is running and the model is pulled:
ollama pull gemma3:12b

python make_admin.py 09xxxxxxxxx  # create your admin account
python serve.py                   # backend API server
```

In another terminal, start the frontend:

```bash
cd apps/web
npm install
npm run dev
```

Open http://127.0.0.1:3000. API requests under `/api/*` are proxied from Next.js to FastAPI.

## Environment variables (`.env`)

| Var | Purpose |
|-----|---------|
| `SESSION_SECRET_KEY` | **Required.** Session signing key. `FLASK_SECRET_KEY` is still accepted as a temporary fallback. |
| `OLLAMA_MODEL` | LLM model name (default `gemma3:12b`). |
| `EMBEDDING_MODEL` | Path/name of the embedding model. |
| `EMBEDDING_MODEL_PATH` | Preferred embedding model path for the new vector layer. Defaults to `EMBEDDING_MODEL`. |
| `EMBEDDING_DIM` | Embedding dimension, default `1024` for BGE-M3. |
| `VECTOR_BACKEND` | Current value: `pgvector`. `qdrant` is reserved for a future adapter. |
| `DATABASE_URL` | PostgreSQL URL, preferably `postgresql+psycopg://...`. |
| `PUBLIC_BASE_URL` | Public URL; used for ZarinPal callback + secure cookies. Use `https://` in production. |
| `SMS_PROVIDER` | `console` logs OTP for testing; swap for a real provider. |
| `ZARINPAL_MERCHANT_ID` | Your ZarinPal merchant id. |
| `ZARINPAL_SANDBOX` | `true` for sandbox testing, `false` for live. |
| `HOST` / `PORT` | Bind address for `serve.py`. |
| `BACKEND_URL` | Used by the Next.js frontend proxy, defaults to `http://127.0.0.1:5000`. |

## Database and vector setup

### Docker PostgreSQL + pgvector

Local development uses Docker PostgreSQL with pgvector:

```yaml
services:
  postgres_pgvector:
    image: pgvector/pgvector:pg18-trixie
    container_name: rag_postgres_pgvector
    restart: unless-stopped
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: 123
      POSTGRES_DB: rag_system
    ports:
      - "5433:5432"
    volumes:
      - rag_pgvector_data:/var/lib/postgresql

volumes:
  rag_pgvector_data:
```

Important for PostgreSQL 18: mount the volume at `/var/lib/postgresql`, not
`/var/lib/postgresql/data`.

This machine's Docker Desktop data location is:

```text
D:\DockerData\DockerDesktopWSL
```

The local project database URL is:

```env
DATABASE_URL=postgresql+psycopg://postgres:123@127.0.0.1:5433/rag_system
```

Verify pgvector inside the container:

```powershell
docker exec rag_postgres_pgvector psql -U postgres -d rag_system -c "SELECT extname FROM pg_extension ORDER BY extname;"
```

Expected output includes:

```text
plpgsql
vector
```

The backend loads `.env` with override enabled, so stale PowerShell session
variables do not silently redirect the app to the old Windows PostgreSQL on
port 5432.

For a normal schema migration:

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

For a clean local reset when test data can be discarded:

```powershell
.\venv\Scripts\python.exe scripts\reset_postgres_schema.py
```

The initial migration enables PostgreSQL's `vector` extension and creates
`document_chunks` with `VECTOR(1024)` by default.

Chroma is no longer part of the normal RAG path. To preserve and disable an old
local Chroma directory:

```powershell
.\venv\Scripts\python.exe scripts\backup_and_disable_chroma.py
```

If old Chroma chunks must be exported later, install the legacy Chroma dependency
and run:

```powershell
.\venv\Scripts\python.exe scripts\migrate_chroma_to_pgvector.py
```

That export script explicitly uses the local BGE-M3 embedding function so Chroma
does not fall back to a downloadable default embedding model.

## Integration points still requiring real credentials

- **SMS/OTP**: implement a real provider in `backend/app/services/auth_service.py`.
- **Payments**: set a real `ZARINPAL_MERCHANT_ID`; verify a full sandbox payment
  (especially whether `Amount` is Toman or Rial for your account) before going live.

## Production notes

- Run FastAPI with `python serve.py` or `python -m backend.run`.
- Run/build the frontend from `apps/web`.
- Put nginx/Caddy in front for HTTPS; route the frontend to Next.js and `/api/*` to FastAPI or keep the Next.js proxy.
- PostgreSQL and `storage/` hold live user data; back them up.

## Experiments

`experiments/` holds early standalone scripts (`cag.py`, `rac.py`) kept for reference.
They are not part of the product and must not be run against the production vector store.
