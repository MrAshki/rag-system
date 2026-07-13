# RAG System

> [!IMPORTANT]
> **This project is under active development.** APIs, database schemas, configuration keys, model routing, and user-facing workflows may change without backward compatibility. It is not ready for production use yet.

RAG System is a document intelligence platform for uploading, processing, searching, and chatting with private documents. It combines a Next.js workspace with a FastAPI backend, PostgreSQL/pgvector retrieval, local multilingual embedding and reranking models, and a configurable LLM gateway.

The product is designed around a Persian-first user experience while keeping the retrieval and model infrastructure multilingual. Users can ask grounded questions, inspect cited sources, generate structured learning or writing artifacts, and manage their document library from one interface.

## Product Overview

| Area | What it provides |
|---|---|
| Document library | Private uploads, per-user storage, processing status, categorization, and source selection |
| Grounded chat | Retrieval-augmented answers based on selected documents with source citations |
| General chat | Model-based answers when no document source is selected |
| Document tools | Summaries, key points, document comparison, exams, flashcards, article drafts, legal drafts, legal reviews, and rewriting |
| Structured outputs | Dedicated output canvas for exams, flashcards, articles, and other generated artifacts |
| Conversations | Persistent chat history, model selection, renaming, continuation, and deletion |
| Administration | User, subscription, payment, and usage visibility for administrators |
| Model routing | Ollama, LiteLLM, Gemini, and DeepSeek providers behind a shared gateway |

## System Architecture

The diagram below replaces the previous model-only image and shows the complete product path, from the browser to document ingestion, retrieval, generation, and persistence.

```mermaid
flowchart TB
    User["User or Administrator"] --> Web["Next.js Web Application"]
    Web --> API["FastAPI Application"]

    API --> Accounts["Authentication, Profiles, and Admin"]
    API --> Chat["Chat and Document Tools"]
    API --> Gallery["Document Gallery"]
    API --> Payments["Plans and Zarinpal Payments"]

    Gallery --> Storage["Per-user File Storage"]
    Gallery --> Worker["Background Scan Worker"]
    Worker --> Normalize["Normalize TXT, PDF, and DOCX"]
    Normalize --> OCR["Optional OCR"]
    OCR --> Chunk["Structure-aware Chunking"]
    Chunk --> Embed["BGE-M3 Embeddings"]
    Embed --> VectorDB["PostgreSQL with pgvector"]

    Chat --> Search["User-isolated Vector Search"]
    Search --> VectorDB
    Search --> Rerank["BGE Reranker"]
    Rerank --> Context["Grounded Context and Citations"]
    Context --> Gateway["Model Gateway"]
    Gateway --> Models["Ollama, LiteLLM, Gemini, or DeepSeek"]

    Accounts --> Database["PostgreSQL Application Data"]
    Chat --> Database
    Payments --> Database
```

### Request Flow

| Step | Component | Result |
|---:|---|---|
| 1 | Next.js application | Authenticates the user and sends a question with optional document IDs and tool metadata |
| 2 | FastAPI | Validates the session, loads the conversation, and chooses chat or tool execution |
| 3 | pgvector | Finds candidate chunks belonging only to the current user |
| 4 | Reranker | Reorders candidates and keeps the strongest evidence |
| 5 | Model gateway | Sends the question and grounded context to the selected provider |
| 6 | Streaming API | Returns trace, token, final, and completion events as NDJSON |
| 7 | PostgreSQL | Persists the conversation, messages, generated outputs, and usage records |

## Technology Stack

| Layer | Technology | Responsibility |
|---|---|---|
| Web | Next.js 16, React 19, TypeScript | Chat workspace, authentication, gallery, profile, admin console, and output canvas |
| API | FastAPI, Uvicorn, Starlette | Authentication, chat, tools, documents, conversations, payments, administration, and health APIs |
| Data | PostgreSQL, SQLAlchemy, Alembic | Application data, conversations, assets, generated outputs, payments, and usage events |
| Retrieval | pgvector | User-isolated embedding storage and similarity search |
| Embeddings | `BAAI/bge-m3` through Sentence Transformers | Local multilingual document and query embeddings |
| Reranking | `BAAI/bge-reranker-v2-m3` through CrossEncoder | Second-stage relevance ranking before generation |
| Model gateway | Ollama, LiteLLM, Gemini, DeepSeek | Shared interface for chat completion and tool workloads |
| Storage | Local per-user directories | Original files, normalized Markdown, OCR artifacts, and metadata |
| Processing | Internal FastAPI worker | Claims uploaded assets and moves them through the ingestion pipeline |

## Core Features

### Authentication and Accounts

- Email and password authentication
- Mobile OTP login and multi-step registration
- Signed cookie-based sessions
- User profile and password management
- Role-based administrator access

### Document Processing

- TXT, PDF, and DOCX normalization to canonical Markdown
- Optional OCR fallback for scanned or malformed PDFs
- Heading-aware chunking with page, section, and offset metadata
- Local BGE-M3 embedding generation
- pgvector indexing isolated by user ID
- Background states: `uploaded`, `scanning`, `scanned`, and `failed`

### Retrieval and Chat

- Dense vector retrieval followed by optional cross-encoder reranking
- Grounded prompts with inline source references
- Free-form chat when no source is selected
- Selectable model providers and logical model names
- Streaming responses over newline-delimited JSON
- Persistent conversations and messages

### Product Tools

| Tool | Identifier | Source required | Output |
|---|---|:---:|---|
| Summary | `summary` | No | Markdown response |
| Key points | `key_points` | No | Markdown response |
| Compare documents | `compare_documents` | Yes | Grounded comparison |
| Exam generation | `exam_generation` | Yes | Structured exam canvas with grading |
| Flashcards | `flashcards` | No | Structured flashcard set |
| Article draft | `article_draft` | No | Structured writing output |
| Legal pleading | `legal_pleading` | No | Structured legal draft |
| Legal review | `legal_review` | No | Structured review output |
| Rewrite | `rewrite` | No | Rewritten Markdown |

## Repository Layout

| Path | Purpose |
|---|---|
| `apps/web` | Next.js frontend |
| `backend/app` | FastAPI routes, services, database models, and vector store |
| `document_pipeline` | Normalization, OCR, LLM-assisted labeling, and chunking |
| `model_gateway` | Provider registry and model adapters |
| `infra/litellm` | Optional LiteLLM service and routing configuration |
| `architecture` | Architecture notes and legacy diagrams |
| `models` | Local embedding and reranking model files |
| `storage` | Runtime user uploads and generated processing artifacts |
| `tests` | Usage, grading context, and preprocessing tests |
| `alembic` | Database migrations |

## Prerequisites

| Requirement | Notes |
|---|---|
| Python | A version compatible with the pinned packages in `requirements.txt` |
| Node.js and npm | Required for the Next.js application |
| Docker Desktop | Recommended for PostgreSQL/pgvector and optional LiteLLM |
| Ollama | Required when using the local model provider |
| Local model files | `models/bge-m3` and, when enabled, `models/bge-reranker-v2-m3` |
| Tesseract OCR | Optional; required for OCR fallback on scanned PDFs |

## Local Development

### 1. Install Backend Dependencies

Run the following commands from the repository root:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

PyTorch installation is environment-specific. For a CPU-only environment:

```powershell
pip install torch
```

For GPU acceleration, install the PyTorch wheel matching your CUDA runtime and driver.

### 2. Configure the Environment

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Place the generated value in `SESSION_SECRET_KEY` or `FLASK_SECRET_KEY`, then review at least these settings:

```env
DATABASE_URL=postgresql+psycopg://postgres:CHANGE_ME@127.0.0.1:5432/rag_system
SESSION_SECRET_KEY=CHANGE_ME
VECTOR_BACKEND=pgvector
EMBEDDING_MODEL=./models/bge-m3
EMBEDDING_MODEL_PATH=./models/bge-m3
OLLAMA_MODEL=gemma3:12b
```

Do not use example secrets in a shared or production environment.

### 3. Start PostgreSQL and pgvector

```powershell
docker compose up -d
```

The current Compose file exposes PostgreSQL on `127.0.0.1:5432`. If that port is already occupied, update both the Compose port mapping and `DATABASE_URL`.

### 4. Apply Database Migrations

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

### 5. Prepare the Local Chat Model

```powershell
ollama pull gemma3:12b
```

### 6. Start the Backend

```powershell
.\venv\Scripts\python.exe serve.py
```

The API is available at `http://127.0.0.1:5000` by default.

### 7. Start the Frontend

In a separate terminal:

```powershell
cd apps\web
npm install
npm run dev
```

The web application is available at `http://127.0.0.1:3000`. Requests under `/api/*` are proxied to `BACKEND_URL`, which defaults to `http://127.0.0.1:5000`.

### 8. Create an Administrator

```powershell
.\venv\Scripts\python.exe make_admin.py 09123456789
```

Replace the example phone number with the registered account that should receive administrator access.

## Optional LiteLLM Gateway

LiteLLM is configured separately and exposes port `4000`:

```powershell
cd infra\litellm
docker compose up -d
```

`infra/litellm/config.yaml` currently maps logical product models such as `chat_free`, `summary`, `flashcards`, `rewrite`, `exam_generation`, and `exam_grading_descriptive` to Gemini. A valid provider key must be configured before these routes can succeed.

## Environment Reference

| Variable | Example | Purpose |
|---|---|---|
| `SESSION_SECRET_KEY` | Random secret | Signs application sessions; the backend will not start without a valid secret |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:5000` | Public backend URL and payment callback base |
| `FRONTEND_URL` | `http://127.0.0.1:3000` | Frontend URL exposed by the API |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Uvicorn bind address |
| `DATABASE_URL` | `postgresql+psycopg://...` | SQLAlchemy PostgreSQL connection |
| `VECTOR_BACKEND` | `pgvector` | Vector backend; pgvector is the implemented option |
| `EMBEDDING_MODEL_PATH` | `./models/bge-m3` | Local embedding model directory |
| `EMBEDDING_DIM` | `1024` | Embedding dimension used by BGE-M3 and the vector column |
| `ENABLE_RERANKER` | `true` | Enables second-stage reranking |
| `RERANKER_MODEL` | `./models/bge-reranker-v2-m3` | Local reranker model directory |
| `RERANKER_DEVICE` | `cpu` | Reranker execution device |
| `RETRIEVE_K` | `30` | Dense candidates retrieved before reranking |
| `RERANK_TOP_K` | `5` | Final chunks supplied to generation |
| `DEFAULT_CHAT_PROVIDER` | `litellm` | Default model provider |
| `OLLAMA_MODEL` | `gemma3:12b` | Default Ollama model |
| `LITELLM_BASE_URL` | `http://127.0.0.1:4000` | LiteLLM endpoint |
| `LITELLM_MODEL` | `chat_free` | Default LiteLLM logical model |
| `GEMINI_API_KEY` | Provider secret | Enables direct Gemini or LiteLLM-to-Gemini calls |
| `DEEPSEEK_API_KEY` | Provider secret | Enables the direct DeepSeek provider |
| `ENABLE_OCR_FALLBACK` | `false` | Enables OCR fallback during PDF ingestion |
| `SMS_PROVIDER` | `console` | Sends OTP messages through the selected provider; console is for development |
| `ZARINPAL_MERCHANT_ID` | Provider identifier | Enables Zarinpal payment requests |
| `ZARINPAL_SANDBOX` | `true` | Uses the payment sandbox |

See `.env.example` and `backend/app/core/config.py` for the complete configuration surface.

## Main API Endpoints

| Group | Endpoint | Method | Purpose |
|---|---|---|---|
| Health | `/api/health` | `GET` | Reports service, model, reranker, and index status |
| Auth | `/api/auth/request-otp` | `POST` | Requests a login OTP |
| Auth | `/api/auth/verify-otp` | `POST` | Verifies an OTP and creates a session |
| Auth | `/api/auth/login-email` | `POST` | Authenticates with email and password |
| Auth | `/api/auth/me` | `GET` | Returns the current account |
| Gallery | `/api/gallery/upload` | `POST` | Uploads a document or supported asset |
| Gallery | `/api/gallery/assets` | `GET` | Lists the current user's assets and status counts |
| Documents | `/api/documents` | `GET` | Lists processed text documents available as sources |
| Chat | `/api/chat/models` | `GET` | Lists selectable chat models |
| Chat | `/api/ask` | `POST` | Returns a non-streaming answer |
| Chat | `/api/ask/stream` | `POST` | Streams an answer as NDJSON events |
| Conversations | `/api/conversations` | `GET`, `POST` | Lists or creates conversations |
| Conversations | `/api/conversations/{id}` | `PATCH`, `DELETE` | Updates or deletes a conversation |
| Tools | `/api/tools` | `GET` | Lists chat tools available to the user |
| Outputs | `/api/outputs/{id}` | `GET` | Loads a structured generated output |
| Outputs | `/api/outputs/{id}/grade` | `POST` | Grades a generated exam |
| Payments | `/api/plans` | `GET` | Lists active subscription plans |
| Payments | `/api/subscribe` | `POST` | Starts a Zarinpal payment |
| Admin | `/api/admin/*` | `GET`, `POST` | Provides administrative operations |

## Data Model

| Table | Stored data |
|---|---|
| `users` | Accounts, roles, verification state, email, and password hashes |
| `otp_codes` | Expiring and consumed OTP records |
| `plans` | Subscription plan definitions |
| `subscriptions` | User subscription periods and state |
| `payments` | Payment authority, reference, amount, and status |
| `assets` | Uploaded files, scan state, storage paths, and metadata |
| `document_chunks` | Text chunks, embeddings, source metadata, and user ownership |
| `conversations` | Conversation titles and selected models |
| `conversation_messages` | Messages, sources, stream state, and tool metadata |
| `generated_outputs` | Structured exams, flashcards, articles, and other artifacts |
| `usage_events` | Chat model usage events |
| `compute_usage_events` | Embedding, reranking, grading, and other compute usage |

## Testing

Run the test suite from the repository root:

```powershell
.\venv\Scripts\python.exe -m pytest tests
```

Run the preprocessing checks directly when working on ingestion:

```powershell
.\venv\Scripts\python.exe tests\preprocessing\run_preprocessing_tests.py
```

Test coverage currently focuses on usage tracking, grading context, and document preprocessing. Broader integration, browser, payment, and end-to-end coverage is still needed.

## Current Development Status

This repository is an evolving development build. The main workflows are implemented, but several areas still require hardening before a production release.

| Area | Current state |
|---|---|
| Subscription enforcement | `require_subscription` currently enforces authentication only; subscription checks are intentionally disabled during product development |
| Payments | Zarinpal integration exists but must be validated end to end with real deployment URLs and production credentials |
| OTP delivery | The `console` provider is intended only for local development |
| File processing | Processing runs in an internal application thread rather than an independently scalable worker service |
| Storage | Local disk storage requires a backup, retention, and multi-instance strategy for production |
| Model availability | Local models and external provider credentials must be provisioned manually |
| API stability | Routes and schemas may change while product workflows are being refined |
| Security | Secrets, HTTPS, cookie policy, upload limits, rate limiting, and deployment boundaries require a production review |
| Testing | Integration and end-to-end coverage is incomplete |

Do not treat the current configuration defaults as production recommendations. Before deployment, rotate all secrets, use HTTPS, validate payment callbacks, configure a real SMS provider, back up PostgreSQL and `storage/`, and review access control and resource limits.

## Useful Commands

| Task | Command |
|---|---|
| Start PostgreSQL | `docker compose up -d` |
| Apply migrations | `.\venv\Scripts\python.exe -m alembic upgrade head` |
| Start the backend | `.\venv\Scripts\python.exe serve.py` |
| Start the frontend | `cd apps\web; npm run dev` |
| Create an administrator | `.\venv\Scripts\python.exe make_admin.py <phone>` |
| Pull the default Ollama model | `ollama pull gemma3:12b` |
| Start LiteLLM | `cd infra\litellm; docker compose up -d` |
| Run tests | `.\venv\Scripts\python.exe -m pytest tests` |

---

**Development notice:** this project is still under active development and should be evaluated as a work in progress, not as a stable production release.
