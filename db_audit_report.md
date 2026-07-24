# Database & Usage Audit Report

## خلاصه مدیریتی

این audit روی branch فعلی `feature/database-updates-20260630` و با رویکرد read-only انجام شد. تنها فایل نوشته‌شده همین گزارش است.

وضعیت کلی:

- دیتابیس اصلی پروژه PostgreSQL + pgvector است. کانتینر فعال: `rag_postgres_pgvector`، فایل مرجع: `docker-compose.yml`.
- schema runtime تا migration `20260629_0005` جلو رفته است. شواهد: جدول `alembic_version` در PostgreSQL.
- pgvector واقعاً فعال است. extensionهای runtime: `plpgsql` و `vector`.
- در کد فعلی SQLite فعال پیدا نشد. جستجو فقط policy ignore برای `app_data.sqlite3` در `.gitignore` و اشاره‌های تاریخی/مستنداتی نشان داد.
- Chroma در مسیر فعلی runtime فعال نیست. `backend/app/vector/factory.py` فقط `pgvector` را پیاده‌سازی‌شده می‌داند و `chroma_persistent_storage/` در workspace فعلی وجود ندارد.
- LiteLLM سرویس جدا دارد، اما طبق `infra/litellm/docker-compose.yml` دیتابیس جداگانه برای LiteLLM تعریف نشده است؛ فقط `GEMINI_API_KEY` و `LITELLM_MASTER_KEY` به کانتینر داده می‌شود.
- storage فایل‌ها در `storage/` فعال است. این مسیر فایل اصلی upload، `normalized.md`، `metadata.json` و artifacts مربوط به OCR را نگه می‌دارد. فایل مرجع: `storage.py`.
- چت آزاد conversation و messageها را ذخیره می‌کند؛ system prompt/context ذخیره نمی‌شود. مسیر اصلی: `backend/app/api/routes/ask.py` و `db.py`.
- token usage فقط برای callهایی که از `LiteLLMChatProvider` عبور می‌کنند در `usage_events` ثبت می‌شود. providerهای مستقیم `ollama`، `gemini` و `deepseek` در کد فعلی usage DB را ثبت نمی‌کنند.
- hardware/compute usage در جدول `compute_usage_events` ذخیره می‌شود و در کد فعلی برای embedding و reranking محلی ثبت می‌شود؛ monitoring دوره‌ای CPU/GPU وجود ندارد.

Runtime counts خوانده‌شده از PostgreSQL:

| جدول | تعداد رکورد |
|---|---:|
| users | 11 |
| otp_codes | 7 |
| plans | 1 |
| subscriptions | 5 |
| payments | 0 |
| assets | 3 |
| conversations | 31 |
| conversation_messages | 59 |
| generated_outputs | 14 |
| usage_events | 27 |
| compute_usage_events | 2 |
| document_chunks | 170 |
| alembic_version | 1 |

## دیتابیس‌ها و storageهای فعال

### PostgreSQL / pgvector

- فعال است و کانتینر `rag_postgres_pgvector` در زمان audit بالا بود.
- تعریف سرویس در `docker-compose.yml`.
- schema در `backend/app/db/models.py` و migrationها در `backend/app/db/migrations/versions/`.
- اتصال SQLAlchemy در `backend/app/core/config.py` و `backend/app/db/session.py`.
- compatibility layer قدیمی‌تر در `db.py` همچنان مسیر اصلی بیشتر read/writeهای اپ است.
- extension `vector` فعال است و جدول `document_chunks.embedding` از نوع `vector` دارد.

### SQLite

در کد فعلی شواهدی از استفاده فعال SQLite پیدا نشد. `.gitignore` فقط `app_data.sqlite3` را برای جلوگیری از برگشت legacy SQLite ignore کرده است.

### LiteLLM database

در `infra/litellm/docker-compose.yml` برای LiteLLM هیچ `DATABASE_URL`، volume دیتابیس، یا service دیتابیس جدا تعریف نشده است. در `infra/litellm/config.yaml` فقط aliasهای مدل و `master_key` تنظیم شده‌اند. بنابراین در وضعیت فعلی شواهدی از دیتابیس جداگانه LiteLLM پیدا نشد.

### Local file storage

- مسیر اصلی: `storage.py` با `STORAGE_ROOT=./storage` به صورت پیش‌فرض.
- layout: `storage/{user_id}/{category}/{asset_id}/`.
- فایل‌های ذخیره‌شده: `original.{ext}`، برای متن‌ها `normalized.md` و `metadata.json`، و در صورت OCR مسیر `ocr/`.
- در runtime فعلی `storage/` وجود دارد و شامل فایل‌های `.md`، `.json`، `.txt`، `.pdf` و تعدادی `.png` مربوط به artifacts است.
- `docs/` و `converted/` و `chroma_persistent_storage/` در workspace فعلی وجود ندارند.

### Logs/cache/models

- `models/` وجود دارد و برای embedding/reranker/Ollama local models استفاده می‌شود. مسیرها در `.env` و `rag.py` و `backend/app/vector/embeddings.py`.
- `*.log` در `.gitignore` ignore شده است.
- cache اپلیکیشنی دیتابیس‌مانند در کد فعلی پیدا نشد. cacheهای npm فقط وابستگی frontend هستند و در scope دیتابیس محصول نیستند.

## نقشه کلی data flow

### شروع اپ

- `backend/app/main.py` در lifespan ابتدا `db.init_db()` را صدا می‌زند.
- `db.init_db()` در `db.py` وجود schema را با `plans` چک می‌کند و اگر plan اولیه وجود نداشته باشد، plan پایه را اضافه می‌کند.
- سپس `scan_worker.start()` اجرا می‌شود و assetهای stuck در status `scanning` را با `db.requeue_stuck_scanning()` به `uploaded` برمی‌گرداند.

### Upload و indexing سند

1. `backend/app/api/routes/gallery.py::gallery_upload`
   - فایل را در `storage.original_path(...)` می‌نویسد.
   - رکورد `assets` را با `db.create_asset(...)` می‌سازد.
   - `scan_worker.notify()` را صدا می‌زند.
2. `scan_worker.py`
   - `db.claim_next_uploaded_asset()` یک asset را atomically به `scanning` تبدیل می‌کند.
   - برای text assetها، `document_pipeline/ingest.py::normalize_document` را اجرا می‌کند.
   - خروجی normalized را با `document_pipeline/ingest.py::write_normalized` در `storage/` می‌نویسد.
   - chunkها را با `document_pipeline/chunker.py::parse_markdown_to_chunks` می‌سازد.
   - `rag.py::index_chunks` و سپس `backend/app/vector/pgvector_store.py::PGVectorStore.add_chunks` متن chunk و embedding را در `document_chunks` upsert می‌کنند.
   - وضعیت asset با `db.update_asset_status(...)` به `scanned` یا `failed` تغییر می‌کند.

### چت / RAG / ابزار

- endpoint اصلی: `backend/app/api/routes/ask.py`.
- `_prepare_ask` حالت را تعیین می‌کند:
  - بدون source/tool: `free_chat`
  - با source: `grounded_chat`
  - با tool: `template_workflow`
- `_ensure_conversation` conversation را می‌سازد یا آپدیت می‌کند.
- user message با `db.create_conversation_message(...)` ذخیره می‌شود.
- در streaming، assistant message ابتدا با content خالی و status `streaming` ساخته و بعد با `db.update_conversation_message(...)` کامل می‌شود.
- RAG در `rag.py::answer_request` و `rag.py::answer_request_stream` اجرا می‌شود.
- toolها در `backend/app/services/tool_runner.py::run_tool` و `run_tool_stream` اجرا می‌شوند.
- خروجی structured ابزار با `db.create_generated_output(...)` در `generated_outputs` ذخیره می‌شود.

## جدول‌ها و کاربرد هرکدام

### alembic_version

- ستون‌ها: `version_num varchar primary key`.
- کاربرد: نگه‌داری revision فعلی Alembic.
- خواندن/نوشتن: Alembic؛ migration env در `backend/app/db/migrations/env.py`.
- وضعیت runtime: `20260629_0005`.
- sensitive: خیر.
- production: مناسب، استاندارد Alembic.

### users

- ستون‌ها: `id int PK`, `phone text unique not null`, `is_verified bool`, `is_admin bool`, `created_at timestamptz`, `first_name text`, `last_name text`, `email text`, `birth_date date`, `password_hash text`.
- indexها: `users_pkey`, `users_phone_key`, `idx_users_email unique`.
- کاربرد: هویت کاربر، profile، admin flag و login.
- writes:
  - `db.get_or_create_user`
  - `db.mark_user_verified`
  - `db.complete_user_registration`
  - `db.update_user_profile`
  - `db.set_user_password`
  - `backend/app/api/routes/auth.py`
  - `backend/app/api/routes/profile.py`
  - `backend/app/api/routes/admin.py`
- reads:
  - `db.get_user_by_phone`, `db.get_user_by_id`, `db.get_user_by_email`, `db.list_users`
  - `backend/app/dependencies.py` از طریق current user flow
  - auth/profile/admin/payment routes
- sensitive: بله؛ phone، email، birth_date، password_hash.
- production: نیازمند retention/security policy، جلوگیری از log شدن PII، و احتمالاً hardening برای password policy.

### otp_codes

- ستون‌ها: `id int PK`, `phone text`, `code text`, `expires_at timestamptz`, `consumed bool`, `created_at timestamptz`.
- indexها: `idx_otp_phone(phone, created_at)`.
- کاربرد: OTP login/register.
- writes: `db.create_otp`, `db.verify_and_consume_otp`.
- reads: `db.recent_otp_count`, `db.verify_and_consume_otp`.
- callerها: `backend/app/services/auth_service.py::request_otp`, `backend/app/api/routes/auth.py`.
- sensitive: بله؛ OTP code و phone.
- production: نیاز به retention/cleanup برای OTPهای قدیمی دارد. الان cleanup دوره‌ای در کد پیدا نشد.

### plans

- ستون‌ها: `id int PK`, `name text`, `price_toman bigint`, `duration_days int`, `active bool`.
- indexها: فقط PK.
- کاربرد: پلن‌های اشتراک.
- writes: migration اولیه و `db.init_db`.
- reads: `db.list_active_plans`, `db.get_plan`, payment/admin routes.
- sensitive: خیر.
- production: قابل قبول؛ اگر تعداد پلن کم باشد index اضافه لازم نیست.

### subscriptions

- ستون‌ها: `id int PK`, `user_id int FK users(id)`, `plan_id int FK plans(id)`, `starts_at timestamptz`, `expires_at timestamptz`, `status text`, `created_at timestamptz`.
- indexها: `idx_sub_user(user_id, status, expires_at)`.
- کاربرد: دسترسی subscription.
- writes: `db.create_subscription`, `db.revoke_subscription`.
- reads: `db.get_active_subscription`, `db.list_subscriptions_for_admin`, auth/admin dependencies/routes.
- sensitive: نسبتاً؛ subscription وضعیت مالی/دسترسی کاربر است.
- production: FKها cascade ندارند؛ حذف user ممکن است با subscriptions مانع شود یا نیاز به policy داشته باشد.

### payments

- ستون‌ها: `id int PK`, `user_id int FK users(id)`, `plan_id int FK plans(id)`, `amount_toman bigint`, `authority text`, `ref_id text`, `status text`, `created_at timestamptz`, `paid_at timestamptz`.
- indexها: `idx_pay_authority(authority)`.
- کاربرد: پرداخت‌های Zarinpal-like.
- writes: `db.create_payment`, `db.set_payment_authority`, `db.mark_payment_paid`, `db.mark_payment_failed`.
- reads: `db.get_payment_by_authority`, `db.list_payments_for_user`, `db.list_payments_for_admin`.
- callerها: `backend/app/api/routes/payments.py`, `backend/app/api/routes/profile.py`, `backend/app/api/routes/admin.py`.
- sensitive: بله؛ payment authority/ref_id و history مالی.
- production: نیاز به auditability و retention مشخص دارد؛ FKها cascade ندارند.

### assets

- ستون‌ها: `id text PK`, `user_id int FK users(id)`, `category text`, `original_filename text`, `file_ext text`, `size_bytes bigint`, `status text`, `scan_error text`, `chunk_count int`, `original_path text`, `normalized_md_path text`, `extraction_warning text`, `created_at timestamptz`, `scanned_at timestamptz`.
- indexها: `idx_assets_user(user_id, category, created_at)`, `idx_assets_status(status)`.
- کاربرد: source of truth برای فایل‌های کاربر و lifecycle scan.
- writes: `db.create_asset`, `db.update_asset_status`, `db.claim_next_uploaded_asset`, `db.requeue_stuck_scanning`.
- reads: `db.get_asset`, `db.list_assets`, `db.list_assets_by_ids`, `gallery.py`, `serializers.py`.
- sensitive: بله؛ filenames، local paths، scan errors.
- production: نیاز به delete route/cleanup policy دارد؛ در کد فعلی endpoint حذف asset پیدا نشد.

### conversations

- ستون‌ها: `id text PK`, `user_id int FK users(id) ON DELETE CASCADE`, `title text`, `chat_provider text`, `chat_model text`, `created_at timestamptz`, `updated_at timestamptz`.
- indexها: `idx_conversations_user_updated(user_id, updated_at)`.
- کاربرد: session/conversation chat.
- writes: `db.create_conversation`, `db.update_conversation`, `db.delete_conversation`.
- reads: `db.list_conversations`, `db.get_conversation`, conversation/ask routes.
- sensitive: بله؛ title معمولاً از سوال کاربر ساخته می‌شود.
- production: cascade روی messages درست است، اما usage/outputها روی حذف conversation به `SET NULL` می‌روند و history usage باقی می‌ماند.

### conversation_messages

- ستون‌ها: `id text PK`, `conversation_id text FK conversations(id) ON DELETE CASCADE`, `role text`, `content text`, `sources_json text`, `status text`, `stream_status text`, `created_at timestamptz`, `mode text`, `tool_id text`, `tool_title text`, `tool_params_json text`, `generated_output_id text`.
- indexها: `idx_conversation_messages_conversation_created(conversation_id, created_at)`.
- کاربرد: ذخیره پیام user/assistant، status streaming/error، metadata ابزار و citations.
- writes: `db.create_conversation_message`, `db.update_conversation_message`, `ask.py`.
- reads: `db.list_conversation_messages`, `db.get_message_for_generated_output`, conversation/output routes.
- sensitive: بله؛ متن کامل پیام کاربر و پاسخ مدل.
- production: `generated_output_id` FK ندارد؛ فقط text است. اگر output حذف شود، integrity دیتابیس enforce نمی‌شود.

### generated_outputs

- ستون‌ها: `id text PK`, `user_id int FK users(id) ON DELETE CASCADE`, `conversation_id text FK conversations(id) ON DELETE SET NULL`, `type text`, `title text`, `content_json text`, `content_markdown text`, `source_asset_ids_json text`, `template_id text`, `template_params_json text`, `created_at timestamptz`, `updated_at timestamptz`.
- indexها: `idx_generated_outputs_user_updated(user_id, updated_at)`, `idx_generated_outputs_conversation(conversation_id, updated_at)`.
- کاربرد: خروجی‌های structured مثل exam/canvas/tool output.
- writes: `db.create_generated_output`, `ask.py::_create_tool_output`.
- reads: `db.get_generated_output`, `db.get_message_for_generated_output`, `outputs.py`.
- sensitive: بله؛ محتوای تولیدی، پاسخنامه/آزمون، source asset ids.
- production: `content_json` به صورت `text` ذخیره شده نه `jsonb`؛ برای query/reporting آینده محدودیت دارد.

### usage_events

- ستون‌ها: `id text PK`, `request_id text`, `user_id int FK users ON DELETE SET NULL`, `conversation_id text FK conversations ON DELETE SET NULL`, `message_id text FK conversation_messages ON DELETE SET NULL`, `tool_run_id text`, `output_id text FK generated_outputs ON DELETE SET NULL`, `feature text`, `operation_type text`, `provider text`, `model text`, `input_tokens int`, `output_tokens int`, `total_tokens int`, `estimated_cost_usd numeric`, `latency_ms int`, `status text`, `error_type text`, `metadata_json jsonb`, `created_at timestamptz`.
- indexها: created، user+created، feature+created، provider+model+created، request_id، conversation_id، GIN روی metadata.
- کاربرد: token/cost/latency tracking برای model calls.
- writes:
  - `backend/app/services/usage_tracking.py::record_usage_event`
  - در کد فعلی فقط `model_gateway/providers/litellm_provider.py` این تابع را صدا می‌زند.
- reads: در کد اپ route/report خواندن usage پیدا نشد؛ فقط tests و audit runtime.
- sensitive: متوسط تا زیاد؛ user/conversation/message linkage، model route، error type و metadata.
- production: برای retention، aggregation و dashboard نیاز به policy دارد. اگر provider مستقیم غیر LiteLLM استفاده شود، coverage ناقص است.

### compute_usage_events

- ستون‌ها: `id text PK`, `request_id text`, `user_id int FK users ON DELETE SET NULL`, `conversation_id text FK conversations ON DELETE SET NULL`, `message_id text FK conversation_messages ON DELETE SET NULL`, `output_id text FK generated_outputs ON DELETE SET NULL`, `feature text`, `operation_type text`, `provider text`, `model text`, `device text`, `latency_ms int`, `input_count int`, `input_chars int`, `chunk_count int`, `pair_count int`, `query_count int`, `batch_size int`, `status text`, `error_type text`, `metadata_json jsonb`, `created_at timestamptz`.
- indexها: created، user+created، feature+created، operation_type+created، request_id، conversation_id، GIN metadata.
- کاربرد: compute tracking محلی برای embedding و reranking.
- writes:
  - `backend/app/services/usage_tracking.py::record_compute_usage_event`
  - `backend/app/vector/embeddings.py::embed_texts`
  - `rag.py::rerank`
- reads: route خواندن در کد فعلی پیدا نشد.
- sensitive: متوسط؛ به user/conversation/message وصل می‌شود و metadata ممکن است context فنی داشته باشد.
- production: tracking فعلی append-only است و monitoring دوره‌ای hardware نیست.

### document_chunks

- ستون‌ها: `id bigint PK`, `chunk_id text unique`, `user_id int FK users ON DELETE CASCADE`, `document_id text FK assets ON DELETE CASCADE`, `source text`, `chunk_index int`, `text text`, `metadata jsonb`, `embedding_model text`, `embedding vector`, `created_at timestamptz`.
- unique: `chunk_id`, و `uq_document_chunks_document_chunk_index(document_id, chunk_index)`.
- indexها: `idx_document_chunks_user_document`, `idx_document_chunks_metadata_gin`, `idx_document_chunks_embedding_cosine` با HNSW cosine.
- کاربرد: متن chunk، metadata و embedding برای RAG.
- writes: `backend/app/vector/pgvector_store.py::PGVectorStore.add_chunks`.
- reads: `PGVectorStore.search`, `rag.py::list_documents`, `PGVectorStore.count`.
- sensitive: بله؛ متن استخراج‌شده کامل/بخشی از اسناد و embeddings.
- production: index vector مناسب است؛ retention/delete مسیر API کامل برای asset deletion در کد فعلی پیدا نشد.

## چت آزاد چه چیزی ذخیره می‌کند؟

برای endpointهای `/api/ask` و `/api/ask/stream`:

- user message ذخیره می‌شود: بله، با `db.create_conversation_message(...)` در `ask.py`.
- assistant response ذخیره می‌شود: بله. در non-stream بعد از تولید پاسخ ساخته می‌شود؛ در stream ابتدا placeholder ساخته می‌شود و بعد با `db.update_conversation_message(...)` کامل می‌شود.
- conversation/session ذخیره می‌شود: بله، با `db.create_conversation(...)` یا `db.get_conversation(...)`.
- provider/model ذخیره می‌شود: در سطح conversation، ستون‌های `chat_provider` و `chat_model`. اگر payload مقدار بدهد یا conversation قبلی داشته باشد ذخیره/آپدیت می‌شود. اگر مقدار null بماند، provider/model واقعی default فقط در usage event دیده می‌شود، نه لزوماً در conversation.
- system prompt ذخیره می‌شود: خیر. `rag.py::_build_free_chat_messages` system prompt را runtime می‌سازد ولی در DB ذخیره نمی‌کند.
- context ذخیره می‌شود: برای چت آزاد context سند وجود ندارد. prompt runtime ذخیره نمی‌شود.
- فایل/source/chunk/citation ذخیره می‌شود: در چت آزاد `sources` خالی است و `sources_json` معمولاً `[]` می‌شود.
- tool call ذخیره می‌شود: در چت آزاد خیر؛ `tool_id/tool_title/tool_params_json` null هستند.
- error ذخیره می‌شود: اگر exception در `ask.py` رخ دهد، یک assistant message با content عمومی `خطا در تولید پاسخ.` و status `error` ذخیره می‌شود. جزئیات exception در message ذخیره نمی‌شود. اگر provider LiteLLM باشد، `usage_events.error_type` هم ثبت می‌شود.
- token usage: اگر provider آزاد LiteLLM باشد، در `usage_events` ثبت می‌شود. اگر provider مستقیم Ollama/Gemini/DeepSeek باشد، در کد فعلی usage DB ثبت نمی‌شود.

## RAG چه چیزی ذخیره می‌کند؟

### Document/RAG storage

- اسناد اصلی: `storage/{user_id}/{category}/{asset_id}/original.{ext}`، فایل مرجع `storage.py`.
- متن استخراج‌شده: `normalized.md` در همان asset folder، توسط `document_pipeline/ingest.py::write_normalized`.
- metadata extraction: `metadata.json` در همان asset folder، توسط `write_normalized`.
- chunkها: جدول `document_chunks.text`.
- embeddingها: جدول `document_chunks.embedding` با نوع `vector`.
- metadata هر chunk: `document_id`, `source`, `chunk`, `user_id`, `source_file_type`, `normalized_md_path`, `chapter`, `section`, `subsection`, `page`, `char_start`, `char_end`. ساخته‌شده در `rag.py::index_chunks` و تکمیل‌شده در `PGVectorStore.add_chunks`.
- document_id: در upload با `uuid.uuid4().hex` به عنوان `asset_id` ساخته می‌شود؛ برای text asset همان id به عنوان `document_id` chunkها استفاده می‌شود. مسیرها: `gallery.py::gallery_upload`, `scan_worker.py::_process_text_asset`, `rag.py::index_chunks`.
- pgvector فعال است: `backend/app/vector/factory.py` فقط `PGVectorStore` را برای `VECTOR_BACKEND=pgvector` می‌سازد.
- Chroma فعال نیست: مسیر فعلی Chroma وجود ندارد و factory adapter Chroma ندارد؛ فقط commentهای قدیمی در `rag.py`, `storage.py`, `db.py`, `chunker.py` باقی مانده‌اند.

### RAG chat storage

- سوال user در `conversation_messages.content`.
- پاسخ assistant در `conversation_messages.content`.
- citations/source labels در `conversation_messages.sources_json`.
- retrieved chunk متن کامل دوباره داخل message ذخیره نمی‌شود؛ chunkها قبلاً در `document_chunks` هستند.
- query understanding output ذخیره نمی‌شود، فقط در جریان runtime استفاده می‌شود.
- system prompt و context assembled در `rag.py::_build_answer_messages` ذخیره نمی‌شوند.

### حذف سند و orphan data

- در کد فعلی `PGVectorStore.delete_document` و `delete_user_data` وجود دارد، اما endpoint حذف asset/document پیدا نشد.
- FK جدول `document_chunks.document_id` به `assets.id ON DELETE CASCADE` است؛ اگر asset از DB حذف شود، chunkها هم cascade می‌شوند.
- چون route حذف asset وجود ندارد، cleanup عملی فایل‌های `storage/` و asset/chunk از مسیر UI/API فعلی شواهد کافی ندارد.
- runtime orphan check فعلی: chunk بدون asset صفر، message بدون conversation صفر، output بدون user صفر، usage/compute با message حذف‌شده صفر.

## Token Usage Tracking

### منبع اصلی ثبت

- `backend/app/services/usage_tracking.py::record_usage_event` رکورد را در `db.create_usage_event(...)` می‌سازد.
- در کد فعلی `record_usage_event` فقط از `model_gateway/providers/litellm_provider.py` صدا زده می‌شود.
- `LiteLLMChatProvider.chat` و `LiteLLMChatProvider.stream_chat` بعد از success `_record_success` و هنگام exception `_record_error` را اجرا می‌کنند.
- اگر response usage داشته باشد، `prompt_tokens`, `completion_tokens`, `total_tokens` استفاده می‌شود.
- اگر usage نباشد، fallback تخمینی با `estimate_tokens_from_messages` و `estimate_tokens_from_text` ثبت می‌شود.
- cost از headerهای LiteLLM مثل `x-litellm-response-cost` خوانده می‌شود؛ اگر نباشد صفر.

### context اتصال usage به user/session/message

- `backend/app/api/routes/ask.py` اطراف RAG/tool callها `usage_context(...)` یا در streaming `set_usage_context(...)` می‌گذارد.
- context شامل `request_id`, `user_id`, `conversation_id`, `message_id`, `feature`, `operation_type`, metadata است.
- بعد از ساخته‌شدن assistant message یا output، `db.update_usage_events_context(...)` message/output را backfill می‌کند.
- `outputs.py::outputs_grade` برای تصحیح آزمون هم `usage_context(...)` تنظیم می‌کند.
- route آزمایشی `litellm.py::litellm_chat_free` هم usage context دارد.

### آیا token usage در دیتابیس پروژه ذخیره می‌شود؟

بله، در `usage_events`، اما فقط برای callهایی که از `LiteLLMChatProvider` رد می‌شوند.

### آیا از LiteLLM usage/cost tracking خود LiteLLM استفاده شده؟

به صورت partial:

- requestها از LiteLLM proxy می‌گذرند و metadata headers مثل `x-litellm-spend-logs-metadata` ارسال می‌شود.
- `infra/litellm/config.yaml` `always_include_stream_usage: true` دارد.
- اما برای LiteLLM دیتابیس جدا/virtual key/spend tracking DB در Compose فعلی تعریف نشده است. بنابراین source of truth عملی برای پروژه جدول `usage_events` خود پروژه است.

### coverage مسیرها

- چت آزاد: اگر default/current provider = LiteLLM باشد، usage دارد. اگر direct provider انتخاب شود، usage DB ندارد.
- RAG answer generation: با `get_chat_provider(... feature="chat_grounded")` انجام می‌شود. اگر provider LiteLLM باشد track می‌شود؛ direct provider نه.
- query understanding/query rewriting: `rag.py::understand_query` از همان provider RAG استفاده می‌کند. اگر provider LiteLLM باشد، این call هم usage event می‌سازد؛ اگر direct باشد نه.
- reranker: token usage LLM ندارد؛ compute usage در `compute_usage_events` ثبت می‌شود و فقط `estimated_input_tokens` در metadata reranking می‌آید.
- embedding: token usage ندارد؛ compute usage در `compute_usage_events` ثبت می‌شود.
- tool calls: `tool_runner.py::run_tool` و `run_tool_stream` provider را با feature همان tool می‌گیرند. اگر LiteLLM باشد، هم retrieval compute و هم generation usage ثبت می‌شود.
- exam grading: `outputs.py` و `exam_grader.py` با feature `exam_grading_descriptive` provider می‌گیرند؛ اگر LiteLLM باشد usage ثبت می‌شود.
- optional LLM normalization در `document_pipeline/llm_normalize.py` مستقیم `ollama.chat` را صدا می‌زند و در کد فعلی usage tracking ندارد. این مسیر فقط وقتی `ENABLE_LLM_NORMALIZATION=true` باشد فعال می‌شود.

### نکته runtime

در داده‌های فعلی `usage_events` چند رکورد با providerهای local مثل `local_gpu` و `local_cpu` دیده شد. در کد فعلی compute usage باید در `compute_usage_events` برود؛ بنابراین این رکوردها احتمالاً historical/قبل از جداسازی compute tracking هستند یا از اجرای قبلی به‌جا مانده‌اند. شواهد کد فعلی برای نوشتن compute به `usage_events` پیدا نشد.

## LiteLLM Routing Analysis

- default provider در `model_gateway/registry.py::_default_provider` برابر `DEFAULT_CHAT_PROVIDER` یا `CHAT_PROVIDER` یا fallback `litellm` است.
- default LiteLLM model در `_litellm_model_for_feature` از feature-specific env، سپس `DEFAULT_CHAT_MODEL`، سپس `LITELLM_MODEL`، سپس `chat_free` می‌آید.
- list مدل UI از `LITELLM_CHAT_MODEL_OPTIONS` خوانده می‌شود تا aliasهای ابزار مثل `summary` وارد picker چت نشوند.
- `infra/litellm/config.yaml` aliasهای `chat_free`, `summary`, `flashcards`, `rewrite`, `exam_generation`, `exam_grading_descriptive` را به مدل Gemini پشت LiteLLM map می‌کند.
- `backend/app/api/routes/litellm.py` یک route مستقیم `/api/litellm/chat-free` دارد که همیشه `get_chat_provider("litellm", "chat_free")` را استفاده می‌کند.
- مسیرهای عادی `/api/ask` و `/api/ask/stream` provider/model را از payload/conversation/default می‌گیرند. بنابراین LiteLLM همه callها را فقط وقتی می‌بیند که provider انتخاب‌شده LiteLLM باشد.

## Hardware Usage Tracking

جدول فعلی: `compute_usage_events`.

این جدول چه track می‌کند:

- `feature`: feature یا tool مرتبط، از usage context یا `unknown`.
- `operation_type`: مثل `embedding` یا `reranking`.
- `provider`: `local_cpu` یا `local_gpu`.
- `model`: مسیر مدل local مثل embedding/reranker.
- `device`: `cpu` یا `cuda`.
- `latency_ms`: مدت اجرای operation.
- `input_count`: تعداد متن‌ها یا pairها.
- `input_chars`: تعداد کاراکترهای ورودی.
- `chunk_count`: تعداد chunkهای rerank شده.
- `pair_count`: تعداد pairهای query/chunk در reranker.
- `query_count`: تعداد query.
- `batch_size`: اندازه batch.
- `status` و `error_type`: success/error.
- `metadata_json`: جزئیات مثل `embedding_dim`, `top_k`, `returned`, `estimated_input_tokens`.

چه زمانی ثبت می‌شود:

- embedding: در `backend/app/vector/embeddings.py::embed_texts` هنگام encode کردن متن‌ها.
- reranking: در `rag.py::rerank` هنگام predict کردن CrossEncoder.

به ازای request یا aggregate:

- append-only per operation است، نه aggregate.
- اگر usage context فعال باشد، به `request_id`, `user_id`, `conversation_id`, `message_id`, `output_id` وصل می‌شود.
- اگر خارج از request اجرا شود، برخی ستون‌ها null می‌مانند یا feature `unknown` می‌شود.

کامل است یا بخشی:

- فقط embedding و reranking را پوشش می‌دهد.
- monitoring دوره‌ای CPU/GPU، memory، VRAM، utilization، disk IO یا container metrics وجود ندارد.
- برای LLMهای remote hardware usage محاسبه نمی‌شود.

## مشکلات و ریسک‌ها

- `db.py` هنوز compatibility SQL layer بزرگ دارد و schema SQL دستی داخل `SCHEMA` با Alembic coexist می‌کند. `init_db()` دیگر schema نمی‌سازد ولی وجود این SQL legacy ریسک drift ذهنی و maintenance ایجاد می‌کند.
- در commentها هنوز Chroma ذکر شده، در حالی که runtime فعلی pgvector است. این می‌تواند برای نگهداری گمراه‌کننده باشد.
- `generated_outputs.content_json`, `source_asset_ids_json`, `template_params_json`, `conversation_messages.sources_json`, `tool_params_json` به صورت `text` ذخیره می‌شوند نه `jsonb`.
- `conversation_messages.generated_output_id` foreign key ندارد.
- OTPها cleanup/retention ندارند.
- usage/compute events retention ندارند و append-only هستند.
- مسیر حذف سند در API پیدا نشد؛ اگر asset حذف عملیاتی لازم شود، باید فایل‌های `storage/`، رکورد `assets` و chunkها هماهنگ حذف شوند.
- providerهای مستقیم `ollama/gemini/deepseek` usage tracking DB ندارند؛ فقط LiteLLM provider instrument شده است.
- optional `llm_normalize.py` مستقیم Ollama را صدا می‌زند و usage tracking ندارد.
- جدول `assets` به `users` بدون `ON DELETE CASCADE` وصل است، اما `document_chunks.user_id/document_id` cascade دارد. delete policy کاربر/asset باید شفاف‌تر شود.
- `payments` و `subscriptions` FK cascade ندارند؛ برای production ممکن است مطلوب باشد، اما باید policy حذف/retention تعریف شود.
- پیام‌ها و chunkها متن کامل حساس را نگه می‌دارند؛ encryption/retention/redaction در کد فعلی دیده نشد.

## پیشنهادهای بهینه‌سازی

- یک migration برای تبدیل JSON text ستون‌های JSON-like به `jsonb`، اگر query/reporting روی آن‌ها لازم است.
- افزودن FK برای `conversation_messages.generated_output_id -> generated_outputs(id) ON DELETE SET NULL`.
- تعریف retention policy برای `otp_codes`, `usage_events`, `compute_usage_events`, logs و شاید conversation history.
- ساخت route/service حذف asset که هم DB و هم فایل‌های `storage/` را پاک کند.
- یکسان‌سازی مسیر schema management: Alembic source of truth باشد و `db.py::SCHEMA` legacy حذف یا محدود شود.
- اضافه کردن usage instrumentation برای providerهای مستقیم یا enforce کردن LiteLLM به عنوان تنها provider production.
- اضافه کردن read/report endpoint برای usage و compute اگر dashboard لازم است.
- پاک‌سازی commentهای legacy Chroma.
- تعریف policy برای حذف user و cascade/retain داده‌های payment/subscription.
- بررسی encryption at rest یا حداقل data classification برای message/chunk/payment/OTP.

## اولویت‌بندی کارهای بعدی

### کارهای فوری

- تصمیم روشن: production provider فقط LiteLLM باشد یا direct providerها هم مجاز باشند.
- retention/cleanup برای `otp_codes`.
- تعیین تکلیف `conversation_messages.generated_output_id` بدون FK.
- مستندسازی اینکه LiteLLM دیتابیس جدا ندارد و source of truth usage جدول `usage_events` پروژه است.

### کارهای بهتر برای بعد

- تبدیل ستون‌های JSON text به `jsonb`.
- اضافه کردن asset delete flow و پاک‌سازی فایل‌های `storage/`.
- اضافه کردن route/report usage و compute.
- پاک‌سازی commentهای legacy Chroma.
- جداسازی لایه repository/service از `db.py` بزرگ.

### کارهای production-grade

- retention و archival policy برای chat/messages/chunks/usage.
- encryption یا redaction برای PII و متن سندها.
- audit log امنیتی برای auth/admin/payment.
- migration policy با CI که Alembic head و مدل‌ها را validate کند.
- monitoring واقعی container/hardware جدا از compute operation events.
- backup/restore strategy برای PostgreSQL volume و `storage/`.

## پاسخ مستقیم به سوال‌های مالک پروژه

### الان وضعیت کلی دیتابیس چیست؟

دیتابیس اصلی PostgreSQL + pgvector است، schema تا `20260629_0005` جلو رفته و ۱۳ جدول public دارد. pgvector فعال است. SQLite و Chroma در runtime فعلی فعال دیده نشدند. LiteLLM دیتابیس جدا ندارد.

### هر جدول چه چیزی ذخیره می‌کند و برای چه کاری است؟

- `users`: هویت، profile، admin، login.
- `otp_codes`: کدهای OTP.
- `plans`: پلن اشتراک.
- `subscriptions`: اشتراک فعال/لغوشده کاربران.
- `payments`: پرداخت‌ها و authority/ref id.
- `assets`: فایل‌های upload شده و وضعیت scan.
- `conversations`: sessionهای چت و provider/model conversation.
- `conversation_messages`: متن پیام‌های user/assistant، sources، status، tool metadata.
- `generated_outputs`: خروجی‌های structured مثل آزمون.
- `usage_events`: token/cost/latency برای model calls عبوری از LiteLLM provider.
- `compute_usage_events`: compute operationهای local مثل embedding/reranking.
- `document_chunks`: chunk text، metadata و embeddingهای pgvector.
- `alembic_version`: نسخه migration.

### usage توکن دقیقاً چطور track می‌شود؟

`LiteLLMChatProvider` بعد از هر `chat` یا `stream_chat` یک `usage_events` می‌سازد. اگر LiteLLM usage واقعی بدهد از آن استفاده می‌شود؛ اگر نه تخمین fallback ثبت می‌شود. context با `usage_context` از `ask.py`, `outputs.py`, `litellm.py` به event وصل می‌شود.

### آیا چت آزاد هم token tracking دارد یا فقط ابزارها؟

چت آزاد هم token tracking دارد، اما فقط وقتی provider آن LiteLLM باشد. در runtime فعلی `chat_free` رکوردهای `usage_events` دارد. اگر کاربر/provider مستقیم Ollama/Gemini/DeepSeek استفاده کند، در کد فعلی token usage در DB ثبت نمی‌شود.

### آیا LiteLLM همه‌ی callها را می‌بیند یا فقط بعضی مسیرها؟

LiteLLM فقط callهایی را می‌بیند که provider انتخاب‌شده `litellm` باشد. با default فعلی، مسیرهای چت/ابزار/RAG احتمالاً از LiteLLM عبور می‌کنند؛ ولی کد هنوز providerهای مستقیم را نگه داشته و اگر انتخاب شوند LiteLLM آن call را نمی‌بیند. optional `llm_normalize.py` هم مستقیم Ollama است.

### usage سخت‌افزار دقیقاً در همان جدول فعلی چطور track می‌شود؟

در `compute_usage_events` به صورت append-only per operation. `embed_texts` برای embedding و `rag.py::rerank` برای reranking event می‌سازند. ستون‌ها device/model/provider/latency/input_count/input_chars/chunk_count/pair_count/query_count/batch_size/status/error_type را نگه می‌دارند. monitoring عمومی CPU/GPU وجود ندارد.

### در چت آزاد دقیقاً چه داده‌هایی ذخیره می‌شوند؟

conversation، user message، assistant message، role/content/status/mode ذخیره می‌شود. provider/model در conversation ذخیره می‌شود اگر payload/conversation آن را داشته باشد. system prompt ذخیره نمی‌شود. source/chunk/citation ذخیره نمی‌شود. tool metadata ندارد. error فقط به شکل message عمومی و در صورت LiteLLM به شکل `usage_events.error_type` ذخیره می‌شود.

### چه چیزهایی باید تمیزتر، امن‌تر یا بهینه‌تر شوند؟

اولویت‌ها: retention برای OTP/usage/messages، FK برای `generated_output_id`، تبدیل JSON text به `jsonb`، delete flow کامل برای asset و storage، یکپارچه‌سازی Alembic به عنوان source of truth، پوشش usage برای direct providerها یا enforce LiteLLM، و data protection برای message/chunk/payment/OTP.
