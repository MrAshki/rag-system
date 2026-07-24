# Database Risk Mitigation Plan

## خلاصه مدیریتی

این برنامه بر اساس `db_audit_report.md` نوشته شده و هدفش تبدیل ریسک‌های فعلی دیتابیس، storage، usage tracking و privacy به یک مسیر اجرایی کم‌ریسک است. وضعیت فعلی پروژه قابل ادامه برای development است، اما برای production چند نقطه باید قبل از رشد محصول تمیز شود: یکپارچه‌سازی schema management با Alembic، تعیین policy حذف و retention، کامل کردن data integrity، و روشن کردن اینکه usage tracking از مسیر LiteLLM source of truth باشد یا providerهای مستقیم هم پشتیبانی شوند.

اصل پیشنهادی این پلن:

- ابتدا کارهای کم‌ریسک و بدون data migration انجام شود: پاک‌سازی legacy comments، مستندسازی source of truth، افزودن reportهای read-only و تست‌های migration.
- سپس migrationهای کوچک integrity انجام شود: FK برای `generated_output_id` و تبدیل JSON text به `jsonb` بعد از backup.
- بعد مسیر deletion و retention با policy روشن پیاده شود، چون اشتباه در این بخش می‌تواند باعث از دست رفتن داده شود.
- در نهایت hardening production مثل backup/restore، privacy controls و monitoring واقعی اضافه شود.

## جدول اولویت‌بندی ریسک‌ها

| ریسک | شدت | احتمال | اولویت | پیچیدگی | پیشنهاد کوتاه |
|---|---|---|---|---|---|
| `db.py` بزرگ و legacy | متوسط | زیاد | مهم ولی غیر فوری | زیاد | تدریجی به repository/serviceهای کوچک منتقل شود |
| Drift بین Alembic و schema دستی `db.py` | زیاد | متوسط | فوری | متوسط | Alembic را source of truth کنید و `SCHEMA` را حذف/غیرفعال کنید |
| commentهای legacy Chroma | کم | زیاد | فوری | کم | commentها و docs قدیمی اصلاح شوند |
| JSON-likeها به صورت `text` | متوسط | متوسط | مهم ولی غیر فوری | متوسط | با migration امن به `jsonb` تبدیل شوند |
| نبود FK برای `conversation_messages.generated_output_id` | متوسط | متوسط | فوری | کم | FK با `ON DELETE SET NULL` اضافه شود |
| نبود cleanup برای `otp_codes` | زیاد | زیاد | فوری | کم | cleanup job/endpoint داخلی و index مناسب اضافه شود |
| نبود retention برای usage/compute | متوسط | زیاد | مهم ولی غیر فوری | متوسط | retention policy و aggregate strategy تعریف شود |
| نبود route حذف کامل asset/document | زیاد | متوسط | فوری | متوسط | service و endpoint حذف asset طراحی شود |
| حذف asset باید DB/chunk/file را هماهنگ پاک کند | زیاد | متوسط | فوری | زیاد | حذف transactional + filesystem cleanup با rollback-aware design |
| providerهای مستقیم usage را ثبت نمی‌کنند | زیاد | متوسط | فوری | متوسط | یا LiteLLM-only policy یا instrumentation مشترک |
| فقط LiteLLM در `usage_events` track می‌شود | زیاد | متوسط | فوری | متوسط | source of truth usage مشخص شود |
| `llm_normalize.py` مستقیم Ollama را صدا می‌زند | متوسط | کم | مهم ولی غیر فوری | متوسط | از model gateway یا usage wrapper عبور کند |
| hardware tracking فقط operation-level است | متوسط | متوسط | بعداً | متوسط | compute events حفظ شود، monitoring واقعی جدا اضافه شود |
| `assets.user_id` بدون cascade | متوسط | متوسط | مهم ولی غیر فوری | متوسط | delete policy user/asset روشن شود |
| payments/subscriptions بدون cascade/retention | زیاد | متوسط | مهم ولی غیر فوری | متوسط | retain-by-default و anonymization policy |
| نگهداری داده حساس | زیاد | زیاد | فوری | زیاد | classification, retention, redaction/encryption policy |
| نبود route/report usage/compute | متوسط | زیاد | مهم ولی غیر فوری | متوسط | admin read-only usage dashboard/API |
| نبود backup/restore strategy | زیاد | متوسط | فقط production-grade | متوسط | بکاپ PostgreSQL volume و `storage/` با restore drill |
| نبود CI/smoke test migration | زیاد | متوسط | فوری | متوسط | Alembic head + model/schema validation در CI |
| multi-user isolation باید harden شود | زیاد | متوسط | فوری | زیاد | تست‌های isolation و review همه queryها |

## پلن دقیق برای هر ریسک

### ریسک: `db.py` بزرگ و legacy است و هنوز compatibility SQL layer دارد

**وضعیت فعلی:**  
در audit آمده که `db.py` شامل compatibility layer، SQL دستی، توابع auth/payments/assets/conversations/usage و رشته `SCHEMA` است. مسیرهای اصلی هنوز از همین فایل استفاده می‌کنند: `backend/app/api/routes/ask.py`, `gallery.py`, `auth.py`, `payments.py`, `outputs.py`.

**چرا مشکل‌ساز است:**  
نگهداری سخت می‌شود، تغییر یک جدول می‌تواند چند feature را بشکند، و تست کردن behaviorها granular نیست. در production، این شکل monolithic احتمال regression را بالا می‌برد.

**راهکار پیشنهادی:**  
refactor تدریجی، نه big-bang. ابتدا هیچ behavior را تغییر ندهید؛ فقط توابع را به ماژول‌های کوچک repository منتقل کنید:

- `backend/app/repositories/users.py`
- `backend/app/repositories/assets.py`
- `backend/app/repositories/conversations.py`
- `backend/app/repositories/usage.py`
- `backend/app/repositories/billing.py`

`db.py` در فاز اول فقط facade باقی بماند و به repositoryها delegate کند. بعد routeها آرام‌آرام مستقیم repository/service را استفاده کنند.

**گزینه‌های ممکن:**  
- گزینه A: big-bang حذف `db.py`. سریع ولی پرریسک.
- گزینه B: facade تدریجی. کندتر ولی امن‌تر.
- گزینه C: نگه داشتن `db.py` و فقط comment زدن. کم‌هزینه ولی مشکل واقعی را حل نمی‌کند.

**پیشنهاد نهایی تو:**  
گزینه B. پروژه هنوز در حال رشد است و مسیرهای زیادی به `db.py` وابسته‌اند؛ refactor تدریجی کم‌ریسک‌تر است.

**تغییرات لازم در دیتابیس:**  
هیچ migration لازم نیست. فقط refactor کد است.

**تغییرات لازم در کد:**  
- `db.py`
- `backend/app/db/session.py`
- routeهای `backend/app/api/routes/*.py`
- سرویس‌های `backend/app/services/usage_tracking.py`, `tool_runner.py`

**تست‌های لازم:**  
- unit test برای هر repository.
- integration test برای auth، upload، conversation، ask stream، output grade.
- smoke test که APIهای فعلی همان response قبلی را بدهند.

**ریسک اجرای راهکار:**  
اگر facade درست نگه داشته نشود، routeهای فعلی می‌شکنند.

**اولویت:**  
مهم ولی غیر فوری

**تخمین پیچیدگی:**  
زیاد

**پیش‌نیاز تصمیم‌گیری:**  
آیا می‌خواهی در کوتاه‌مدت `db.py` facade باقی بماند یا سریع‌تر routeها را مستقیم به repositoryها وصل کنیم؟

### ریسک: Alembic و schema دستی در `db.py` ممکن است باعث drift شوند

**وضعیت فعلی:**  
schema اصلی در `backend/app/db/migrations/versions/` و `backend/app/db/models.py` است، اما `db.py` هنوز `SCHEMA` دستی دارد. `db.init_db()` دیگر schema نمی‌سازد و فقط وجود `plans` را چک می‌کند، اما schema دستی همچنان در کد باقی است.

**چرا مشکل‌ساز است:**  
دو source of truth باعث drift می‌شود. توسعه‌دهنده ممکن است ستون را در مدل/Alembic تغییر دهد ولی `SCHEMA` را فراموش کند، یا برعکس. برای production و migration قابل اعتماد خطرناک است.

**راهکار پیشنهادی:**  
Alembic تنها source of truth شود. `SCHEMA` از `db.py` حذف یا به فایل legacy docs منتقل شود. `db.init_db()` فقط sanity check کند که `alembic_version` در head است و seedهای ضروری مثل plan اولیه را idempotent انجام دهد.

**گزینه‌های ممکن:**  
- گزینه A: حذف کامل `SCHEMA`.
- گزینه B: نگه داشتن `SCHEMA` فقط در یک doc/legacy فایل غیر اجرایی.
- گزینه C: نگه داشتن هر دو و اضافه کردن تست مقایسه. پیچیده و غیرضروری.

**پیشنهاد نهایی تو:**  
گزینه A یا B. برای این پروژه، B در یک commit کم‌ریسک‌تر است چون historical reference از بین نمی‌رود، اما runtime source فقط Alembic باشد.

**تغییرات لازم در دیتابیس:**  
Migration لازم نیست. فقط code cleanup.  
ریسک migration ندارد. Rollback با revert commit ممکن است.

**تغییرات لازم در کد:**  
- `db.py`: حذف/انتقال `SCHEMA`.
- `db.init_db()`: چک Alembic head و seed plan.
- احتمالاً `README.md`: توضیح اینکه migration فقط Alembic است.

**تست‌های لازم:**  
- test که `db.init_db()` بدون اجرای schema دستی کار می‌کند.
- smoke test روی دیتابیس تازه: `alembic upgrade head` سپس start backend.
- test که revision head برابر expected است.

**ریسک اجرای راهکار:**  
اگر جایی پنهانی به `SCHEMA` وابسته باشد، start app ممکن است fail شود. audit شواهدی از استفاده فعال نداده، ولی باید با `rg "SCHEMA"` قبل اجرا تایید شود.

**اولویت:**  
فوری

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
آیا می‌خواهی `SCHEMA` کاملاً حذف شود یا به یک فایل legacy/reference منتقل شود؟

### ریسک: commentها و اشاره‌های legacy به Chroma هنوز در کد وجود دارد

**وضعیت فعلی:**  
Audit نشان داد runtime فعلی pgvector است و Chroma فعال نیست، اما commentهای قدیمی در `rag.py`, `storage.py`, `db.py`, `document_pipeline/chunker.py` باقی مانده‌اند.

**چرا مشکل‌ساز است:**  
برای maintenance گمراه‌کننده است. ممکن است تصمیم‌های بعدی بر اساس تصور غلط گرفته شود که Chroma هنوز بخشی از مسیر عادی است.

**راهکار پیشنهادی:**  
فقط comment/docs را اصلاح کن. هیچ behavior تغییر نکند. هرجا نوشته Chroma، به pgvector یا legacy migration note تبدیل شود.

**گزینه‌های ممکن:**  
- گزینه A: اصلاح commentها در کد.
- گزینه B: اصلاح commentها + README/architecture docs.
- گزینه C: حذف همه اشاره‌های تاریخی. ممکن است context مهاجرت از بین برود.

**پیشنهاد نهایی تو:**  
گزینه B. هم کد تمیز می‌شود، هم مستندات آینده درست می‌ماند.

**تغییرات لازم در دیتابیس:**  
هیچ.

**تغییرات لازم در کد:**  
- `rag.py`
- `storage.py`
- `db.py`
- `document_pipeline/chunker.py`
- احتمالا `README.md` و `architecture/model-interactions.md`

**تست‌های لازم:**  
نیازی به unit test ندارد؛ فقط `rg -n "Chroma|chromadb|chroma"` و lint.

**ریسک اجرای راهکار:**  
تقریباً کم؛ فقط مراقب باش commentهای مرتبط با ابزار migration قدیمی حذف اشتباه نشوند.

**اولویت:**  
فوری

**تخمین پیچیدگی:**  
کم

**پیش‌نیاز تصمیم‌گیری:**  
آیا اشاره‌های historical migration را نگه داریم یا تمام نام Chroma را از کد محصول حذف کنیم؟

### ریسک: بعضی ستون‌های JSON-like به صورت `text` ذخیره شده‌اند، نه `jsonb`

**وضعیت فعلی:**  
طبق audit، ستون‌های `generated_outputs.content_json`, `source_asset_ids_json`, `template_params_json`, `conversation_messages.sources_json`, `tool_params_json` از نوع `text` هستند. در مقابل `usage_events.metadata_json` و `document_chunks.metadata` از نوع `jsonb` هستند.

**چرا مشکل‌ساز است:**  
query/reporting سخت‌تر می‌شود، validation دیتابیس نداریم، indexهای GIN ممکن نیست، و داده خراب JSON فقط در زمان parse کشف می‌شود.

**راهکار پیشنهادی:**  
Migration مرحله‌ای:

1. قبل از migration، query validation روی رکوردهای موجود اجرا شود که همه مقدارهای non-null JSON معتبر باشند.
2. ستون‌های JSON-like به `jsonb` تبدیل شوند با `USING column::jsonb`.
3. مدل SQLAlchemy و serializers/db access مطابق `jsonb` آپدیت شوند.
4. اگر نیاز به query روی keys هست، index GIN انتخابی اضافه شود، نه برای همه ستون‌ها.

**گزینه‌های ممکن:**  
- گزینه A: تبدیل همه JSON-likeها به `jsonb`.
- گزینه B: فقط ستون‌هایی که واقعاً query می‌شوند را `jsonb` کنیم.
- گزینه C: حفظ `text` و اضافه کردن validation در کد. integrity کامل نمی‌دهد.

**پیشنهاد نهایی تو:**  
گزینه A برای ستون‌های واضح JSON، اما GIN index فقط جایی که query واقعی داریم. حجم داده فعلی کم است و فرصت خوبی برای درست کردن foundation است.

**تغییرات لازم در دیتابیس:**  
- migration برای alter type:
  - `conversation_messages.sources_json -> jsonb`
  - `conversation_messages.tool_params_json -> jsonb`
  - `generated_outputs.content_json -> jsonb`
  - `generated_outputs.source_asset_ids_json -> jsonb`
  - `generated_outputs.template_params_json -> jsonb`
- data migration لازم است: cast از text به jsonb.
- ریسک migration: اگر حتی یک مقدار invalid JSON باشد migration fail می‌شود.
- rollback: alter back to text با `column::text` ممکن است، ولی formatting JSON تغییر می‌کند.

**تغییرات لازم در کد:**  
- `backend/app/db/models.py`
- `db.py` در insert/update/read مسیرهای JSON
- `backend/app/services/serializers.py`
- `backend/app/api/routes/ask.py`
- `backend/app/api/routes/outputs.py`

**تست‌های لازم:**  
- migration test روی DB sample.
- test برای serializer پیام و generated output.
- test برای create/read tool output.
- test invalid legacy JSON detection قبل migration.

**ریسک اجرای راهکار:**  
خرابی migration به خاطر JSON نامعتبر یا تغییر نوع برگشتی rowها در serializers.

**اولویت:**  
مهم ولی غیر فوری

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
آیا می‌خواهی همه JSON-likeها الان تبدیل شوند یا فقط ستون‌های خروجی ابزارها؟

### ریسک: `conversation_messages.generated_output_id` foreign key ندارد

**وضعیت فعلی:**  
طبق audit، `conversation_messages.generated_output_id` فقط `text` است و FK به `generated_outputs.id` ندارد. در `db.create_conversation_message` و `db.update_conversation_message` مقدار آن ثبت می‌شود. `db.get_message_for_generated_output` هم بر اساس همین ستون جستجو می‌کند.

**چرا مشکل‌ساز است:**  
اگر output حذف یا خراب شود، message می‌تواند به خروجی ناموجود اشاره کند. data integrity enforce نمی‌شود.

**راهکار پیشنهادی:**  
FK nullable با `ON DELETE SET NULL` اضافه شود. قبل از migration، orphan check اجرا شود.

**گزینه‌های ممکن:**  
- گزینه A: FK با `ON DELETE SET NULL`.
- گزینه B: FK با `ON DELETE CASCADE`.
- گزینه C: بدون FK و فقط validation در کد.

**پیشنهاد نهایی تو:**  
گزینه A. چون message history باید باقی بماند حتی اگر output حذف شود.

**تغییرات لازم در دیتابیس:**  
- migration:
  - orphanهای احتمالی را report یا null کند.
  - `ALTER TABLE conversation_messages ADD CONSTRAINT ... FOREIGN KEY (generated_output_id) REFERENCES generated_outputs(id) ON DELETE SET NULL`.
- data migration: فقط اگر orphan وجود داشته باشد باید null شوند.
- rollback: drop constraint.

**تغییرات لازم در کد:**  
کد زیادی لازم نیست، اما test اضافه شود:
- `backend/app/db/models.py` FK را reflect کند.
- `db.py` همان مقدار را می‌نویسد.

**تست‌های لازم:**  
- migration orphan precheck.
- test حذف generated_output و null شدن message reference.
- test `outputs_get` و `get_message_for_generated_output`.

**ریسک اجرای راهکار:**  
اگر orphan وجود داشته باشد migration fail می‌شود مگر قبلش تمیز شود.

**اولویت:**  
فوری

**تخمین پیچیدگی:**  
کم

**پیش‌نیاز تصمیم‌گیری:**  
اگر orphan پیدا شد، آیا null شود یا migration متوقف و دستی بررسی شود؟

### ریسک: `otp_codes` cleanup/retention ندارد

**وضعیت فعلی:**  
`otp_codes` شامل `phone`, `code`, `expires_at`, `consumed`, `created_at` است. تولید و مصرف در `backend/app/services/auth_service.py` و `db.py` انجام می‌شود. audit cleanup دوره‌ای پیدا نکرد.

**چرا مشکل‌ساز است:**  
OTP و شماره موبایل sensitive هستند. جدول بی‌نهایت رشد می‌کند و retention نامشخص privacy risk ایجاد می‌کند.

**راهکار پیشنهادی:**  
cleanup ساده و امن:

- TTL مثلاً ۲۴ یا ۷۲ ساعت برای OTPهای expired/consumed.
- تابع `delete_expired_otp_codes(before)` در repository/auth service.
- اجرای cleanup در startup یا background lightweight job. برای dev می‌تواند startup باشد؛ برای production بهتر است scheduled job.

**گزینه‌های ممکن:**  
- گزینه A: cleanup در startup backend.
- گزینه B: scheduled job خارجی/cron.
- گزینه C: PostgreSQL job extension. وابستگی اضافه می‌کند.

**پیشنهاد نهایی تو:**  
برای این پروژه گزینه A در کوتاه‌مدت، و گزینه B برای production.

**تغییرات لازم در دیتابیس:**  
- migration اختیاری برای index بهتر: `otp_codes(expires_at)` یا `(consumed, expires_at)`.
- data migration: حذف داده‌های قدیمی فقط بعد از تایید owner.
- rollback: اگر data حذف شود rollback واقعی ممکن نیست. هشدار: deletion irreversible است.

**تغییرات لازم در کد:**  
- `db.py` یا repository auth جدید
- `backend/app/services/auth_service.py`
- `backend/app/main.py` یا background maintenance service

**تست‌های لازم:**  
- unit test حذف فقط expired/old OTP.
- test که OTP معتبر حذف نمی‌شود.
- smoke login/register.

**ریسک اجرای راهکار:**  
اگر window اشتباه باشد، OTPهای معتبر حذف می‌شوند و login/register مختل می‌شود.

**اولویت:**  
فوری

**تخمین پیچیدگی:**  
کم

**پیش‌نیاز تصمیم‌گیری:**  
OTPهای expired را بعد از چند ساعت/روز نگه داریم؟

### ریسک: `usage_events` و `compute_usage_events` retention ندارند

**وضعیت فعلی:**  
هر دو جدول append-only هستند. `usage_events` توسط `LiteLLMChatProvider` و `compute_usage_events` توسط embedding/reranking پر می‌شود. audit route خواندن یا retention پیدا نکرد.

**چرا مشکل‌ساز است:**  
رشد بی‌پایان، هزینه storage، privacy risk و کند شدن reportها. این جدول‌ها به user/conversation/message وصل‌اند.

**راهکار پیشنهادی:**  
policy دو لایه:

- raw events برای مدت محدود، مثلاً ۹۰ روز.
- aggregate روزانه/ماهانه برای analytics بلندمدت، بدون message_id و با PII کمتر.

**گزینه‌های ممکن:**  
- گزینه A: فقط حذف raw قدیمی.
- گزینه B: aggregate سپس حذف raw.
- گزینه C: partitioning monthly + retention. production-gradeتر است.

**پیشنهاد نهایی تو:**  
گزینه B برای مرحله بعد، گزینه C وقتی حجم بالا رفت.

**تغییرات لازم در دیتابیس:**  
- احتمالی: جدول aggregate مثل `usage_daily_rollups` و `compute_daily_rollups`.
- indexها فعلاً مناسب‌اند؛ در حجم بالا partitioning لازم می‌شود.
- data deletion irreversible است؛ قبلش backup بگیرید.
- rollback aggregate ممکن است، اما raw حذف‌شده برنمی‌گردد.

**تغییرات لازم در کد:**  
- `backend/app/services/usage_tracking.py`
- maintenance job جدید
- admin report route جدید

**تست‌های لازم:**  
- test aggregation correctness.
- test retention cutoff.
- test عدم حذف داده جدید.

**ریسک اجرای راهکار:**  
از دست رفتن داده usage خام برای debugging یا billing اگر cutoff اشتباه باشد.

**اولویت:**  
مهم ولی غیر فوری

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
raw usage چند روز باید نگه داشته شود و آیا billing دقیق به raw events نیاز دارد؟

### ریسک: مسیر حذف کامل asset/document از API مشخص یا کامل نیست

**وضعیت فعلی:**  
`gallery.py` upload/list دارد، اما audit endpoint حذف asset پیدا نکرد. `PGVectorStore.delete_document` وجود دارد اما از API استفاده نشده است.

**چرا مشکل‌ساز است:**  
کاربر نمی‌تواند سند را کامل حذف کند. برای privacy و storage management مشکل جدی است.

**راهکار پیشنهادی:**  
یک service حذف asset بسازید:

- validate مالکیت asset.
- اگر status در حال `scanning` است، یا delete را block کند یا state `deleting` اضافه کند.
- حذف DB و فایل‌ها را هماهنگ انجام دهد.
- endpoint: `DELETE /api/gallery/assets/{asset_id}`.

**گزینه‌های ممکن:**  
- گزینه A: حذف فقط DB با cascade chunkها.
- گزینه B: حذف DB + فایل storage در یک service.
- گزینه C: soft delete و cleanup async.

**پیشنهاد نهایی تو:**  
گزینه C برای production بهتر است، اما برای پروژه فعلی گزینه B با transaction و error handling کافی است. اگر worker concurrency مهم است، C را انتخاب کنید.

**تغییرات لازم در دیتابیس:**  
- ممکن است ستون `assets.deleted_at` و status `deleting/deleted` لازم شود اگر soft delete انتخاب شود.
- اگر hard delete انتخاب شود migration لازم نیست.
- ریسک: hard delete irreversible است.

**تغییرات لازم در کد:**  
- `backend/app/api/routes/gallery.py`
- `storage.py`
- `db.py` یا repository assets
- `backend/app/vector/pgvector_store.py`
- `scan_worker.py` برای جلوگیری از race با scanning

**تست‌های لازم:**  
- test حذف asset متعلق به خود کاربر.
- test ممنوع بودن حذف asset کاربر دیگر.
- test حذف chunkها/embeddingها.
- test حذف فایل‌های storage.
- test رفتار asset در حال scanning.

**ریسک اجرای راهکار:**  
حذف اشتباه فایل یا داده کاربر دیگر. این بخش باید با دقت و تست isolation اجرا شود.

**اولویت:**  
فوری

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
حذف سند باید hard delete باشد یا soft delete با امکان بازیابی کوتاه‌مدت؟

### ریسک: حذف asset باید دیتابیس، chunkها، embeddingها و فایل‌های `storage/` را هماهنگ پاک کند

**وضعیت فعلی:**  
`document_chunks.document_id` به `assets.id ON DELETE CASCADE` وصل است، پس حذف asset از DB chunkها را پاک می‌کند. اما فایل‌های `storage/` خارج از DB هستند و endpoint/service کامل حذف پیدا نشد.

**چرا مشکل‌ساز است:**  
ممکن است DB پاک شود اما فایل روی دیسک بماند، یا فایل پاک شود و DB بماند. هر دو حالت privacy و integrity را خراب می‌کند.

**راهکار پیشنهادی:**  
delete orchestration با ترتیب امن:

1. asset را با lock یا status `deleting` claim کنید.
2. مسیر asset folder را از DB بخوانید و validate کنید داخل `STORAGE_ROOT` است.
3. در transaction رکورد asset را حذف کنید تا chunkها cascade شوند.
4. بعد از commit، folder را حذف کنید.
5. اگر فایل delete fail شد، job retry بسازید یا asset deletion tombstone نگه دارید.

**گزینه‌های ممکن:**  
- گزینه A: DB first, filesystem after commit.
- گزینه B: filesystem first, DB later.
- گزینه C: soft delete + async cleanup.

**پیشنهاد نهایی تو:**  
گزینه C بهترین است؛ اگر عجله داریم، گزینه A با retry log. هیچ‌وقت filesystem first پیشنهاد نمی‌شود چون DB به فایل حذف‌شده اشاره خواهد کرد.

**تغییرات لازم در دیتابیس:**  
- برای C: ستون‌های `deleted_at`, `delete_error`, status `deleting/deleted`.
- برای A: migration لازم نیست.
- rollback: hard delete قابل rollback نیست؛ soft delete قابل برگشت است تا cleanup انجام نشده.

**تغییرات لازم در کد:**  
- `storage.py`: تابع safe remove برای asset folder.
- `backend/app/api/routes/gallery.py`
- `db.py`/repository assets
- `scan_worker.py`

**تست‌های لازم:**  
- integration test با فایل واقعی temp.
- test جلوگیری از path traversal.
- test retry وقتی فایل حذف نشود.
- test cascade chunkها.

**ریسک اجرای راهکار:**  
اشتباه path validation می‌تواند فایل خارج از storage را پاک کند. باید absolute path و prefix check اجباری باشد.

**اولویت:**  
فوری

**تخمین پیچیدگی:**  
زیاد

**پیش‌نیاز تصمیم‌گیری:**  
برای حذف فایل‌ها، آیا نیاز به recycle/soft delete چندروزه داری یا حذف فوری کافی است؟

### ریسک: providerهای مستقیم مثل Ollama/Gemini/DeepSeek token usage را در DB ثبت نمی‌کنند

**وضعیت فعلی:**  
`model_gateway/providers/litellm_provider.py` usage ثبت می‌کند، اما `ollama_provider.py`, `gemini_provider.py`, `deepseek_provider.py` در audit usage DB ثبت نمی‌کنند.

**چرا مشکل‌ساز است:**  
اگر کاربر یا config provider مستقیم انتخاب کند، cost/token/latency ناقص می‌شود. برای billing، quota و debug قابل اتکا نیست.

**راهکار پیشنهادی:**  
دو مسیر روشن وجود دارد:

- production policy: فقط LiteLLM مجاز باشد و direct providerها dev-only شوند.
- instrumentation مشترک: wrapper در base provider که همه providerها success/error را record کنند.

**گزینه‌های ممکن:**  
- گزینه A: enforce LiteLLM-only.
- گزینه B: instrument تمام providerهای مستقیم.
- گزینه C: هر دو، یعنی production LiteLLM-only و direct providerها هم best-effort tracking.

**پیشنهاد نهایی تو:**  
گزینه C. برای محصول واقعی، LiteLLM مسیر اصلی باشد؛ ولی چون direct providerها در کد باقی می‌مانند، نباید silently untracked باشند.

**تغییرات لازم در دیتابیس:**  
Migration لازم نیست. `usage_events` همین داده را پشتیبانی می‌کند.

**تغییرات لازم در کد:**  
- `model_gateway/providers/ollama_provider.py`
- `model_gateway/providers/gemini_provider.py`
- `model_gateway/providers/deepseek_provider.py`
- شاید `model_gateway/base.py` برای helper مشترک
- `backend/app/services/usage_tracking.py`

**تست‌های لازم:**  
- mock provider response و assert `record_usage_event`.
- streaming success/error برای هر provider.
- fallback token estimation برای providerهایی که usage واقعی نمی‌دهند.

**ریسک اجرای راهکار:**  
instrumentation اشتباه می‌تواند duplicate usage event بسازد یا streaming را کند کند.

**اولویت:**  
فوری

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
آیا در production اجازه می‌دهی کاربر از provider مستقیم غیر LiteLLM استفاده کند؟

### ریسک: فقط requestهای عبوری از LiteLLM در `usage_events` track می‌شوند

**وضعیت فعلی:**  
default provider در `model_gateway/registry.py` fallback به `litellm` دارد و `infra/litellm/config.yaml` aliasهای ابزار را تعریف می‌کند. اما `ask.py` provider/model را از payload/conversation/default می‌گیرد، پس اگر provider مستقیم باشد LiteLLM آن call را نمی‌بیند.

**چرا مشکل‌ساز است:**  
گزارش usage/cost در پروژه کامل نیست و ممکن است تصمیم‌های billing/quota اشتباه شود.

**راهکار پیشنهادی:**  
یک policy رسمی برای routing:

- `production`: فقط LiteLLM.
- `development`: direct providers allowed، اما با warning و best-effort tracking.
- UI model picker هم فقط گزینه‌های مجاز محیط را نشان دهد.

**گزینه‌های ممکن:**  
- گزینه A: حذف direct providers از UI.
- گزینه B: نگه داشتن direct providers ولی badge "untracked/estimated".
- گزینه C: همه routeها را forcibly به LiteLLM map کنید.

**پیشنهاد نهایی تو:**  
گزینه A برای production و B برای dev. حذف کامل direct code فعلاً لازم نیست.

**تغییرات لازم در دیتابیس:**  
هیچ migration لازم نیست.

**تغییرات لازم در کد:**  
- `model_gateway/registry.py`
- `apps/web/src/features/chat/components/ChatComposer.tsx`
- `backend/app/api/routes/ask.py` برای validation provider مجاز
- `.env.example` فقط در مرحله اجرا، نه در این پلن

**تست‌های لازم:**  
- test validation provider در backend.
- UI test/model options filtering.
- integration test chat_free با LiteLLM.

**ریسک اجرای راهکار:**  
اگر LiteLLM down باشد، چت production قطع می‌شود مگر fallback صریح داشته باشید.

**اولویت:**  
فوری

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
آیا availability مهم‌تر است یا tracking کامل؟ یعنی fallback direct در production مجاز باشد یا نه؟

### ریسک: optional `llm_normalize.py` مستقیم Ollama را صدا می‌زند و usage tracking ندارد

**وضعیت فعلی:**  
`document_pipeline/llm_normalize.py::call_ollama` مستقیم `ollama.chat` را صدا می‌زند. این مسیر فقط وقتی `ENABLE_LLM_NORMALIZATION=true` باشد فعال می‌شود. متن تولیدی مدل وارد سند نمی‌شود، فقط label ساختاری استفاده می‌شود.

**چرا مشکل‌ساز است:**  
اگر این feature فعال شود، usage/cost/latency آن در `usage_events` دیده نمی‌شود و LiteLLM آن را نمی‌بیند.

**راهکار پیشنهادی:**  
این مسیر از `model_gateway.get_chat_provider(... feature="document_normalization")` عبور کند و داخل `usage_context` مناسب scan asset اجرا شود.

**گزینه‌های ممکن:**  
- گزینه A: همچنان direct Ollama ولی با record_usage_event تخمینی دستی.
- گزینه B: عبور از model_gateway.
- گزینه C: غیرفعال نگه داشتن دائمی و حذف feature.

**پیشنهاد نهایی تو:**  
گزینه B اگر feature لازم است. اگر در محصول فعلاً نیاز نیست، feature را off نگه دارید و فقط issue/decision ثبت کنید.

**تغییرات لازم در دیتابیس:**  
Migration لازم نیست. شاید feature جدید `document_normalization` در metadata ثبت شود.

**تغییرات لازم در کد:**  
- `document_pipeline/llm_normalize.py`
- `document_pipeline/ingest.py`
- `scan_worker.py` برای usage context شامل asset/user
- `model_gateway/registry.py` برای feature model alias اگر LiteLLM route لازم شود

**تست‌های لازم:**  
- test با mock provider که labels parse شود.
- test usage context برای normalization.
- test اینکه متن مدل وارد document content نمی‌شود.

**ریسک اجرای راهکار:**  
تغییر در normalization pipeline می‌تواند ingestion را کند یا brittle کند.

**اولویت:**  
مهم ولی غیر فوری

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
آیا LLM-assisted normalization واقعاً در v1 فعال خواهد شد؟

### ریسک: hardware usage فعلی monitoring واقعی CPU/GPU/VRAM نیست و فقط embedding/reranking operation را ثبت می‌کند

**وضعیت فعلی:**  
`compute_usage_events` در `backend/app/vector/embeddings.py::embed_texts` و `rag.py::rerank` پر می‌شود. ستون‌ها operation-level هستند، نه metrics دوره‌ای hardware. audit monitoring عمومی CPU/GPU/VRAM پیدا نکرد.

**چرا مشکل‌ساز است:**  
برای capacity planning، debugging performance و production monitoring کافی نیست.

**راهکار پیشنهادی:**  
compute events را نگه دارید، اما monitoring واقعی را جدا طراحی کنید:

- table یا external metrics برای نمونه‌های دوره‌ای.
- ترجیح production: Prometheus/Grafana یا exporter، نه پر کردن DB اصلی با هر ثانیه metric.
- اگر DB داخلی لازم است، جدول جدا مثل `hardware_metric_samples`.

**گزینه‌های ممکن:**  
- گزینه A: فقط همین compute events را ادامه دهیم.
- گزینه B: table داخلی samples.
- گزینه C: ابزار monitoring خارجی.

**پیشنهاد نهایی تو:**  
گزینه A برای dev و C برای production. گزینه B فقط اگر dashboard داخلی ساده می‌خواهی.

**تغییرات لازم در دیتابیس:**  
- برای C: هیچ.
- برای B: جدول `hardware_metric_samples` با timestamp, host/container, cpu, memory, gpu, vram.
- ریسک: حجم زیاد اگر sampling کنترل نشود.

**تغییرات لازم در کد:**  
- برای monitoring خارجی: config/deploy docs.
- برای table داخلی: service collector جدا، نه داخل request path.

**تست‌های لازم:**  
- اگر داخلی شد: test sampling interval و retention.
- اگر external شد: smoke dashboard/exporter.

**ریسک اجرای راهکار:**  
sampling زیاد می‌تواند DB را پر کند یا performance را خراب کند.

**اولویت:**  
بعداً

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
برای production monitoring، ابزار خارجی مثل Prometheus قابل قبول است یا dashboard داخل محصول می‌خواهی؟

### ریسک: جدول `assets` به `users` بدون `ON DELETE CASCADE` وصل است و delete policy باید شفاف شود

**وضعیت فعلی:**  
`assets.user_id` به `users.id` FK دارد اما طبق audit بدون cascade است. `document_chunks.user_id` و `document_chunks.document_id` cascade دارند.

**چرا مشکل‌ساز است:**  
حذف user ممکن است fail شود یا داده‌های وابسته باقی بماند. از طرف دیگر cascade کور ممکن است اسناد و فایل‌ها را ناخواسته حذف کند.

**راهکار پیشنهادی:**  
قبل از migration، policy حذف user را تعریف کنید:

- در product معمولاً حذف user باید به صورت soft delete/anonymize باشد، نه cascade فوری.
- assetها باید یا حذف شوند، یا ownership anonymized شود، بسته به privacy و legal retention.

**گزینه‌های ممکن:**  
- گزینه A: `ON DELETE CASCADE` برای assets.
- گزینه B: `ON DELETE RESTRICT` و user deletion service.
- گزینه C: soft delete user + async data deletion/anonymization.

**پیشنهاد نهایی تو:**  
گزینه C. چون assets فایل‌های واقعی و حساس دارند و حذف باید با storage هماهنگ باشد.

**تغییرات لازم در دیتابیس:**  
- شاید ستون‌های `users.deleted_at`, `assets.deleted_at`.
- تغییر FK به cascade فقط اگر hard delete policy تایید شود.
- data migration: nullable/anonymization columns ممکن است لازم شود.
- rollback: hard deletion قابل برگشت نیست.

**تغییرات لازم در کد:**  
- `backend/app/api/routes/profile.py` یا admin route حذف user
- `db.py`/repositories users/assets
- `storage.py`
- `scan_worker.py`

**تست‌های لازم:**  
- user deletion/anonymization flow.
- asset ownership isolation.
- storage cleanup.

**ریسک اجرای راهکار:**  
از دست رفتن اسناد یا باقی ماندن فایل‌های حساس اگر policy و orchestration غلط باشد.

**اولویت:**  
مهم ولی غیر فوری

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
وقتی user حذف حساب می‌زند، آیا همه اسناد و چت‌ها باید حذف شوند یا برای audit/payment بخشی نگه داشته شود؟

### ریسک: `payments` و `subscriptions` cascade ندارند و retention/delete policy لازم دارند

**وضعیت فعلی:**  
`payments.user_id`, `payments.plan_id`, `subscriptions.user_id`, `subscriptions.plan_id` FK دارند اما cascade ندارند. routeها: `backend/app/api/routes/payments.py`, `profile.py`, `admin.py`.

**چرا مشکل‌ساز است:**  
داده مالی باید معمولاً retention قانونی داشته باشد و نباید با حذف user کور حذف شود. ولی privacy/anonymization هم لازم است.

**راهکار پیشنهادی:**  
retain-by-default برای payment/subscription، با anonymization user PII در صورت حذف حساب. FKها بدون cascade می‌توانند عمدی باشند، اما باید policy و code flow شفاف شود.

**گزینه‌های ممکن:**  
- گزینه A: cascade delete. برای مالی خطرناک.
- گزینه B: restrict و جلوگیری از حذف user.
- گزینه C: soft delete/anonymize user، retain financial records.

**پیشنهاد نهایی تو:**  
گزینه C.

**تغییرات لازم در دیتابیس:**  
- شاید `users.deleted_at`, `users.anonymized_at`.
- شاید snapshot fields در payments مثل masked phone/plan name برای historical report.
- migration FK لازم نیست مگر policy تغییر کند.

**تغییرات لازم در کد:**  
- `backend/app/api/routes/payments.py`
- `backend/app/api/routes/admin.py`
- `db.py`/billing repository
- auth/profile deletion flow

**تست‌های لازم:**  
- payment history بعد از anonymization.
- admin reports.
- user deletion cannot remove payment data unexpectedly.

**ریسک اجرای راهکار:**  
ناسازگاری قانونی/حسابداری اگر payment حذف شود، یا privacy risk اگر PII زیاد نگه داشته شود.

**اولویت:**  
مهم ولی غیر فوری

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
دوره نگهداری اطلاعات پرداخت و اشتراک از نظر کسب‌وکار/قانون چقدر است؟

### ریسک: پیام‌ها، chunkها، OTPها و payment data داده‌های حساس نگه می‌دارند

**وضعیت فعلی:**  
audit جدول‌های sensitive را مشخص کرده: `users`, `otp_codes`, `payments`, `conversation_messages`, `document_chunks`, `generated_outputs`, `assets`, `usage_events`.

**چرا مشکل‌ساز است:**  
نشت دیتابیس یا backup می‌تواند متن کامل اسناد، چت‌ها، شماره موبایل، ایمیل، OTP و پرداخت را افشا کند. برای production باید حداقل retention و access control روشن باشد.

**راهکار پیشنهادی:**  
data classification و controls:

- classification ستون‌ها: PII, secret-like, user content, billing, telemetry.
- retention برای هر دسته.
- redaction در logs.
- encryption at rest در سطح volume/cloud و در صورت نیاز column-level برای OTP/payment identifiers.
- admin access محدود و audited.

**گزینه‌های ممکن:**  
- گزینه A: فقط retention و log hygiene.
- گزینه B: retention + encryption at rest.
- گزینه C: column-level encryption برای چند ستون حساس.

**پیشنهاد نهایی تو:**  
برای الان B، برای production خاص/حساس C فقط پس از طراحی key management.

**تغییرات لازم در دیتابیس:**  
- ممکن است ستون‌های `deleted_at`, `purged_at`, audit metadata لازم شود.
- column encryption migration پیچیده و پرریسک است.
- حذف داده irreversible است.

**تغییرات لازم در کد:**  
- auth/payment/logging layers
- `backend/app/api/routes/admin.py`
- `backend/app/services/serializers.py`
- retention maintenance job

**تست‌های لازم:**  
- test عدم نمایش data حساس در APIهای admin/user.
- test retention.
- security review logs.

**ریسک اجرای راهکار:**  
پیاده‌سازی ناقص encryption می‌تواند data recovery را سخت کند یا app را بشکند.

**اولویت:**  
فوری

**تخمین پیچیدگی:**  
زیاد

**پیش‌نیاز تصمیم‌گیری:**  
سطح حساسیت محصول و الزامات privacy/legal برای ذخیره متن اسناد و چت‌ها چیست؟

### ریسک: route/report مناسب برای دیدن usage و compute usage وجود ندارد

**وضعیت فعلی:**  
audit route read/report برای `usage_events` و `compute_usage_events` پیدا نکرد. فقط نوشتن event وجود دارد.

**چرا مشکل‌ساز است:**  
بدون گزارش، tracking قابل استفاده نیست. نمی‌توان cost، خطاها، latency و مصرف featureها را دید.

**راهکار پیشنهادی:**  
افزودن admin-only read API:

- summary per day/provider/model/feature.
- error counts.
- token/cost totals.
- compute operation summary.
- pagination برای raw events محدود.

**گزینه‌های ممکن:**  
- گزینه A: SQL admin endpoint ساده.
- گزینه B: materialized/aggregate table.
- گزینه C: dashboard خارجی.

**پیشنهاد نهایی تو:**  
گزینه A برای شروع، بعد B وقتی retention/aggregate اضافه شد.

**تغییرات لازم در دیتابیس:**  
Migration لازم نیست برای read ساده. برای aggregate بعداً جدول لازم است.

**تغییرات لازم در کد:**  
- `backend/app/api/routes/admin.py` یا route جدید `usage.py`
- `db.py`/usage repository
- frontend admin در آینده

**تست‌های لازم:**  
- admin permission test.
- aggregation query test.
- pagination/filter test.

**ریسک اجرای راهکار:**  
اگر endpoint raw events بدون محدودیت باشد، اطلاعات sensitive و بار DB ایجاد می‌کند.

**اولویت:**  
مهم ولی غیر فوری

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
گزارش usage فقط برای admin داخلی است یا بعداً کاربر هم usage خودش را ببیند؟

### ریسک: برای production backup/restore strategy برای PostgreSQL volume و `storage/` لازم است

**وضعیت فعلی:**  
داده‌ها بین PostgreSQL volume `rag_pgvector_data` و filesystem `storage/` تقسیم شده‌اند. audit backup/restore strategy پیدا نکرد.

**چرا مشکل‌ساز است:**  
backup فقط DB بدون storage ناقص است، چون `assets.original_path` و `normalized_md_path` به فایل‌ها اشاره می‌کنند. backup فقط storage بدون DB هم قابل استفاده نیست.

**راهکار پیشنهادی:**  
backup هماهنگ:

- DB dump یا volume snapshot.
- archive از `storage/`.
- metadata شامل timestamp و commit/migration version.
- restore drill منظم روی محیط جدا.

**گزینه‌های ممکن:**  
- گزینه A: script ساده `pg_dump` + zip storage.
- گزینه B: volume snapshot هماهنگ.
- گزینه C: managed Postgres + object storage versioning.

**پیشنهاد نهایی تو:**  
برای dev/early production گزینه A، برای production جدی گزینه C.

**تغییرات لازم در دیتابیس:**  
Migration لازم نیست.

**تغییرات لازم در کد:**  
کد app لازم نیست؛ scripts/deployment docs لازم است.

**تست‌های لازم:**  
- restore drill.
- check count assets vs files after restore.
- Alembic version validation after restore.

**ریسک اجرای راهکار:**  
backup ناهماهنگ DB/storage می‌تواند orphan file یا orphan asset بسازد.

**اولویت:**  
فقط production-grade

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
محیط production قرار است local Docker باشد یا managed services/cloud؟

### ریسک: برای migrationها باید CI یا smoke test وجود داشته باشد که Alembic head و مدل‌ها را validate کند

**وضعیت فعلی:**  
audit پیشنهاد داده migration policy با CI لازم است. schema در Alembic و مدل‌ها در `backend/app/db/models.py` هستند. runtime head `20260629_0005` بود.

**چرا مشکل‌ساز است:**  
بدون smoke test ممکن است migration تازه روی DB خالی یا DB موجود fail شود، یا مدل SQLAlchemy با schema drift کند.

**راهکار پیشنهادی:**  
CI/smoke local:

- create DB خالی test.
- `alembic upgrade head`.
- import backend app/models.
- run minimal queries.
- optionally compare tables/columns expected.

**گزینه‌های ممکن:**  
- گزینه A: local script فقط دستی.
- گزینه B: GitHub Actions با Postgres service.
- گزینه C: هر دو.

**پیشنهاد نهایی تو:**  
گزینه C. اول script، بعد CI.

**تغییرات لازم در دیتابیس:**  
هیچ. فقط test DB موقت.

**تغییرات لازم در کد:**  
- test یا script مثل `tests/db/test_migrations.py`
- CI workflow
- شاید `alembic.ini` env handling

**تست‌های لازم:**  
خود این ریسک درباره تست است:
- migrate empty DB.
- migrate from previous revision snapshot، اگر fixture دارید.
- verify `alembic_version`.

**ریسک اجرای راهکار:**  
CI config اشتباه ممکن است کند یا flaky شود.

**اولویت:**  
فوری

**تخمین پیچیدگی:**  
متوسط

**پیش‌نیاز تصمیم‌گیری:**  
CI روی GitHub Actions کافی است یا فقط local scripts می‌خواهی؟

### ریسک: multi-user بودن و data isolation باید بررسی و harden شود

**وضعیت فعلی:**  
بسیاری از queryها user-scoped هستند: `db.get_conversation(user_id, conversation_id)`, `db.list_assets(user_id)`, `PGVectorStore.search` با filter `user_id`. با این حال audit فقط پوشش کد را گزارش کرده؛ تست جامع isolation ذکر نشده است.

**چرا مشکل‌ساز است:**  
یک query بدون user filter می‌تواند سند، پیام یا خروجی کاربر دیگر را نمایش دهد. این از بزرگ‌ترین ریسک‌های privacy است.

**راهکار پیشنهادی:**  
تست و hardening سراسری:

- inventory همه endpointهای user-facing.
- برای هر endpoint تست user A/B.
- repositoryها امضای تابع را طوری طراحی کنند که user_id required باشد.
- admin routes جدا و explicit باشند.

**گزینه‌های ممکن:**  
- گزینه A: فقط review دستی.
- گزینه B: integration tests برای همه endpointها.
- گزینه C: DB-level RLS. پیچیده‌تر.

**پیشنهاد نهایی تو:**  
گزینه B الان، گزینه C فقط اگر production چندکاربره حساس و تیم آماده RLS است.

**تغییرات لازم در دیتابیس:**  
برای B هیچ. برای C باید Row Level Security policies اضافه شود؛ پیچیدگی زیاد دارد.

**تغییرات لازم در کد:**  
- `backend/app/api/routes/gallery.py`
- `conversations.py`
- `outputs.py`
- `ask.py`
- `backend/app/vector/pgvector_store.py`
- repositoryهای جدید

**تست‌های لازم:**  
- user A cannot read/delete asset B.
- user A cannot access conversation/messages/output B.
- RAG retrieval فقط chunkهای user A را برگرداند.
- usage report user-facing اگر اضافه شد scoped باشد.

**ریسک اجرای راهکار:**  
تغییر queryها ممکن است endpointهای admin یا internal worker را بشکند اگر admin/internal path جدا نشود.

**اولویت:**  
فوری

**تخمین پیچیدگی:**  
زیاد

**پیش‌نیاز تصمیم‌گیری:**  
آیا می‌خواهی در این مرحله فقط تست isolation اضافه شود یا DB-level RLS هم در roadmap production بیاید؟

## تغییرات پیشنهادی در schema و migrationها

پیشنهادهای migration به ترتیب کم‌ریسک‌تر:

1. افزودن FK:
   - `conversation_messages.generated_output_id -> generated_outputs(id) ON DELETE SET NULL`
   - precheck: orphanها را پیدا کن.
   - rollback: drop constraint.

2. index برای cleanup OTP:
   - `otp_codes(expires_at)` یا `(consumed, expires_at)`.
   - data deletion فقط بعد از تصمیم retention.

3. تبدیل JSON text به `jsonb`:
   - `conversation_messages.sources_json`
   - `conversation_messages.tool_params_json`
   - `generated_outputs.content_json`
   - `generated_outputs.source_asset_ids_json`
   - `generated_outputs.template_params_json`
   - precheck: همه JSONها valid باشند.
   - rollback ممکن است ولی formatting تغییر می‌کند.

4. soft delete/retention columns، فقط بعد از تصمیم مالک:
   - `assets.deleted_at`, `assets.delete_error`
   - احتمالا `users.deleted_at`, `users.anonymized_at`
   - شاید aggregate tables برای usage.

5. production-only:
   - partitioning برای `usage_events` و `compute_usage_events`.
   - `hardware_metric_samples` فقط اگر monitoring داخلی لازم شد.

## تغییرات پیشنهادی در backend/service layer

- `db.py` مرحله‌ای به facade تبدیل شود و repositoryهای کوچک اضافه شوند.
- `db.init_db()` فقط Alembic/schema sanity check و seed idempotent انجام دهد.
- asset deletion service اضافه شود:
  - validation مالکیت
  - state/race handling با scan worker
  - DB cleanup
  - filesystem cleanup امن
- maintenance service اضافه شود:
  - cleanup OTP
  - retention usage/compute
  - در آینده cleanup soft-deleted assets
- admin usage report read-only اضافه شود.
- routeها user isolation test داشته باشند.

## تغییرات پیشنهادی برای LiteLLM و token usage tracking

- تصمیم product: production LiteLLM-only یا direct provider مجاز.
- اگر LiteLLM-only:
  - backend provider validation اضافه شود.
  - UI فقط LiteLLM modelها را نشان دهد.
  - fallback direct فقط در dev.
- اگر direct providerها مجازند:
  - `OllamaChatProvider`, `GeminiChatProvider`, `DeepSeekChatProvider` هم `record_usage_event` داشته باشند.
  - token usage برای direct providerها estimated یا واقعی اگر response usage داد.
- `llm_normalize.py` اگر فعال می‌شود، از model gateway عبور کند یا usage تخمینی ثبت کند.
- source of truth usage فعلاً `usage_events` پروژه است؛ LiteLLM DB جدا در Compose فعلی وجود ندارد.

## تغییرات پیشنهادی برای hardware/compute usage tracking

- `compute_usage_events` فعلی برای operation-level tracking حفظ شود.
- برای monitoring واقعی CPU/GPU/VRAM، آن را با `compute_usage_events` قاطی نکنید.
- production پیشنهاد: exporter خارجی مثل Prometheus/Grafana.
- اگر dashboard داخلی می‌خواهید، جدول جدا با sampling interval و retention کوتاه طراحی شود.
- usage report باید فرق `operation-level compute` و `hardware metrics` را واضح نشان دهد.

## تغییرات پیشنهادی برای RAG/document storage

- pgvector مسیر اصلی است؛ commentهای Chroma اصلاح شوند.
- asset deletion flow باید شامل:
  - `assets`
  - `document_chunks`
  - embeddingها
  - `storage/{user_id}/{category}/{asset_id}`
  - generated output references در صورت نیاز
- برای حذف hard، هشدار irreversible لازم است.
- برای soft delete، scan/retrieval باید `deleted_at IS NULL` را رعایت کند.
- `storage.py` باید safe path validation برای حذف داشته باشد.

## تغییرات پیشنهادی برای security/privacy/retention

- جدول data classification بسازید: PII، user content، billing، telemetry.
- retention پیشنهادی اولیه:
  - OTP: ۲۴ تا ۷۲ ساعت بعد از expiry/consume.
  - usage raw: ۹۰ روز، سپس aggregate.
  - compute raw: ۳۰ تا ۹۰ روز.
  - chat/document: تصمیم محصول لازم دارد.
  - payment/subscription: retain/anonymize طبق policy کسب‌وکار.
- log redaction برای phone/email/payment identifiers.
- admin routeها باید permission و pagination و filtering داشته باشند.
- backupها هم sensitive هستند؛ retention و encryption برای backup لازم است.

## تست‌هایی که باید نوشته یا اجرا شوند

- migration smoke:
  - empty DB -> `alembic upgrade head`.
  - verify `alembic_version`.
  - import `backend.app.db.models`.

- data integrity:
  - FK `generated_output_id`.
  - JSON migration precheck.
  - orphan checks برای assets/chunks/messages/usage.

- asset deletion:
  - حذف asset خود کاربر.
  - ممنوعیت حذف asset کاربر دیگر.
  - حذف chunkها و فایل‌های storage.
  - race با `scan_worker`.

- retention:
  - OTP cleanup.
  - usage/compute cleanup یا aggregate.

- usage tracking:
  - LiteLLM chat success/error/stream.
  - direct provider estimated tracking اگر اضافه شد.
  - `llm_normalize` usage اگر فعال شد.

- multi-user isolation:
  - gallery/conversation/output/RAG retrieval.
  - admin-only routes.

- backup/restore:
  - restore DB + storage در محیط جدا.
  - count consistency بین assets و folders.

## ترتیب اجرای پیشنهادی

### فاز 1: تمیزکاری فوری و کم‌ریسک

هدف فاز چیست:

- کاهش ابهام و جلوگیری از drift آینده بدون دست زدن به داده‌های production.

چه کارهایی داخلش انجام می‌شود:

- پاک‌سازی commentهای Chroma.
- مستندسازی Alembic به عنوان source of truth.
- حذف/انتقال `db.py::SCHEMA` به legacy reference.
- اضافه کردن migration smoke script.
- تصمیم‌گیری مکتوب درباره LiteLLM-only یا direct providers.

چه تست‌هایی باید پاس شوند:

- backend import/start smoke.
- `alembic upgrade head` روی DB خالی test.
- lint/unitهای موجود.

چه چیزی نباید در آن فاز دست بخورد:

- data deletion.
- تغییر نوع ستون‌ها.
- تغییر FKهای حساس.
- تغییر storage layout.

### فاز 2: data integrity و migrationهای ضروری

هدف فاز چیست:

- enforce کردن integrity بدون تغییر behavior محصول.

چه کارهایی داخلش انجام می‌شود:

- FK برای `conversation_messages.generated_output_id`.
- index cleanup OTP.
- precheck JSON validity.
- migration تبدیل JSON text به `jsonb` اگر precheck پاک بود.

چه تست‌هایی باید پاس شوند:

- migration up/down در DB test.
- serializers و output/message tests.
- orphan checks.

چه چیزی نباید در آن فاز دست بخورد:

- حذف asset/document.
- retention delete واقعی.
- تغییر provider routing.

### فاز 3: usage tracking کامل

هدف فاز چیست:

- مشخص شدن coverage usage برای همه callهای مدل.

چه کارهایی داخلش انجام می‌شود:

- enforce یا validate LiteLLM routing.
- instrumentation providerهای مستقیم اگر مجاز باشند.
- پوشش `llm_normalize.py` اگر feature قرار است فعال باشد.
- admin usage/compute report read-only.

چه تست‌هایی باید پاس شوند:

- chat_free/grounded/tool/exam grading usage tests.
- streaming usage tests.
- direct provider mock tests.
- admin permission tests.

چه چیزی نباید در آن فاز دست بخورد:

- retention delete.
- payment/subscription policy.
- asset deletion hard.

### فاز 4: retention/security

هدف فاز چیست:

- کاهش ریسک privacy و رشد بی‌پایان داده‌ها.

چه کارهایی داخلش انجام می‌شود:

- OTP cleanup.
- usage/compute retention یا aggregate.
- data classification.
- log redaction.
- user/account deletion/anonymization policy طراحی شود.

چه تست‌هایی باید پاس شوند:

- retention cutoff tests.
- عدم حذف داده جدید.
- privacy/API exposure tests.

چه چیزی نباید در آن فاز دست بخورد:

- migrationهای بزرگ همزمان با deletion.
- hard delete user بدون تصمیم retention billing.

### فاز 5: production hardening

هدف فاز چیست:

- آماده شدن برای داده واقعی و failure واقعی.

چه کارهایی داخلش انجام می‌شود:

- backup/restore strategy برای PostgreSQL و `storage/`.
- restore drill.
- monitoring واقعی CPU/GPU/VRAM با ابزار خارجی یا جدول جدا.
- partitioning/aggregate برای usage در صورت رشد.
- multi-user isolation hardening کامل، احتمالاً RLS فقط بعد از بررسی.

چه تست‌هایی باید پاس شوند:

- restore drill.
- load/smoke tests.
- isolation suite.
- backup consistency checks.

چه چیزی نباید در آن فاز دست بخورد:

- تغییر بنیادی schema بدون backup و rollback plan.
- حذف raw historical data بدون archive/decision.

## کارهایی که فعلاً نباید انجام شوند

- حذف hard داده‌های user/chat/document/payment بدون policy تاییدشده.
- تغییر cascade روی `users`، `assets`، `payments` یا `subscriptions` بدون تصمیم مالک.
- فعال کردن monitoring samples داخل DB با interval کوتاه بدون retention.
- حذف direct providerها از کد قبل از تصمیم availability/fallback.
- تبدیل JSON text به `jsonb` بدون precheck validity و backup.
- اضافه کردن LiteLLM DB جدا تا وقتی source of truth usage مشخص نشده است.
- اجرای RLS در PostgreSQL بدون test suite کامل isolation.

## سوال‌های باز و تصمیم‌هایی که مالک پروژه باید بگیرد

- آیا production باید LiteLLM-only باشد یا fallback/direct provider هم مجاز است؟
- حذف سند hard delete باشد یا soft delete با امکان بازیابی کوتاه‌مدت؟
- OTPهای expired چند ساعت/روز نگه داشته شوند؟
- raw usage و compute events چند روز نگه داشته شوند؟
- پیام‌ها و اسناد کاربر retention مشخص دارند یا تا وقتی کاربر حذف نکرده نگه می‌مانند؟
- با حذف حساب کاربر، payment/subscription history باید retained/anonymized شود یا حذف؟
- آیا usage report فقط admin داخلی است یا کاربر هم مصرف خودش را می‌بیند؟
- production روی Docker local می‌ماند یا managed PostgreSQL/object storage استفاده می‌شود؟
- آیا LLM-assisted normalization در v1 فعال خواهد شد؟
- آیا برای multi-user hardening فقط تست application-level کافی است یا RLS هم باید وارد roadmap شود؟

## تصمیم‌هایی که باید از مالک پروژه بپرسم

- Production را LiteLLM-only می‌خواهی یا direct provider fallback هم مجاز باشد؟
- حذف سند و حذف حساب کاربر hard delete باشد یا soft delete/anonymization؟
- retention عددی برای OTP، usage، compute، chat و document چقدر باشد؟
- payment/subscription data بعد از حذف کاربر چطور نگه‌داری یا anonymize شود؟
- برای monitoring production ابزار خارجی قابل قبول است یا گزارش داخل خود محصول می‌خواهی؟
