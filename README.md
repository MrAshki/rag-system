<div dir="rtl" align="right">

# دستیار اسناد | Persian RAG System

دستیار اسناد یک محصول RAG فارسی‌محور برای بارگذاری، پردازش، جست‌وجو و گفت‌وگو با اسناد است. پروژه از یک فرانت‌اند Next.js، یک API مبتنی بر FastAPI، پایگاه داده PostgreSQL/pgvector، مدل‌های embedding محلی و یک model gateway برای اتصال به Ollama، LiteLLM، Gemini و DeepSeek تشکیل شده است.

این README بر اساس فایل‌های همین مخزن نوشته شده و تلاش می‌کند تصویر عملی پروژه را نشان بدهد: از مسیر کاربر و ابزارهای محصول تا راه‌اندازی محلی، APIها، متغیرهای محیطی و مدل داده.

## تصاویر محصول

برای اینکه طبق خواسته پروژه، فایل جدیدی خارج از `README.md` اضافه نشود، نماهای محصول زیر به‌صورت SVG داخل همین فایل تعبیه شده‌اند. تصویر معماری نیز از فایل موجود پروژه استفاده می‌کند.

### نمای چت، منابع و ابزارها

<svg width="100%" viewBox="0 0 1180 620" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="نمای چت دستیار اسناد">
  <rect width="1180" height="620" rx="18" fill="#f7f3ea"/>
  <rect x="28" y="28" width="1124" height="564" rx="16" fill="#ffffff" stroke="#d7cebd"/>
  <rect x="930" y="28" width="222" height="564" rx="16" fill="#1f2933"/>
  <text x="1118" y="70" fill="#ffffff" font-size="24" font-family="Tahoma" text-anchor="end">دستیار اسناد</text>
  <rect x="956" y="98" width="168" height="38" rx="10" fill="#334155"/>
  <text x="1102" y="123" fill="#dbe4ee" font-size="15" font-family="Tahoma" text-anchor="end">گفتگوی جدید</text>
  <rect x="956" y="158" width="168" height="54" rx="10" fill="#0f766e"/>
  <text x="1102" y="181" fill="#ffffff" font-size="14" font-family="Tahoma" text-anchor="end">سند قرارداد</text>
  <text x="1102" y="199" fill="#ccfbf1" font-size="11" font-family="Tahoma" text-anchor="end">آخرین گفتگو</text>
  <rect x="956" y="226" width="168" height="54" rx="10" fill="#334155"/>
  <text x="1102" y="250" fill="#dbe4ee" font-size="14" font-family="Tahoma" text-anchor="end">طراحی آزمون</text>
  <text x="1102" y="268" fill="#94a3b8" font-size="11" font-family="Tahoma" text-anchor="end">ابزار آموزشی</text>
  <rect x="72" y="66" width="790" height="76" rx="14" fill="#f8fafc" stroke="#e2e8f0"/>
  <text x="830" y="96" fill="#111827" font-size="22" font-family="Tahoma" text-anchor="end">از کجا شروع کنیم؟</text>
  <text x="830" y="121" fill="#64748b" font-size="15" font-family="Tahoma" text-anchor="end">سؤال بپرسید، منبع انتخاب کنید یا یک ابزار را از داخل همین چت اجرا کنید.</text>
  <rect x="250" y="180" width="612" height="68" rx="15" fill="#ecfeff" stroke="#99f6e4"/>
  <text x="834" y="209" fill="#115e59" font-size="15" font-family="Tahoma" text-anchor="end">کاربر</text>
  <text x="834" y="230" fill="#134e4a" font-size="16" font-family="Tahoma" text-anchor="end">تعهدات اصلی این قرارداد را خلاصه کن.</text>
  <rect x="72" y="276" width="664" height="132" rx="15" fill="#f9fafb" stroke="#e5e7eb"/>
  <text x="704" y="305" fill="#111827" font-size="15" font-family="Tahoma" text-anchor="end">پاسخ دستیار</text>
  <text x="704" y="333" fill="#374151" font-size="15" font-family="Tahoma" text-anchor="end">۱. طرفین باید طبق بندهای مالی عمل کنند. [S1]</text>
  <text x="704" y="360" fill="#374151" font-size="15" font-family="Tahoma" text-anchor="end">۲. تعهد تحویل در بازه زمانی مشخص ذکر شده است. [S2]</text>
  <text x="704" y="387" fill="#374151" font-size="15" font-family="Tahoma" text-anchor="end">۳. در صورت نقض، ضمانت اجرا در متن آمده است. [S3]</text>
  <rect x="72" y="450" width="790" height="92" rx="18" fill="#ffffff" stroke="#cbd5e1"/>
  <text x="830" y="486" fill="#94a3b8" font-size="16" font-family="Tahoma" text-anchor="end">پیام خود را بنویسید...</text>
  <rect x="730" y="504" width="112" height="28" rx="9" fill="#0f766e"/>
  <text x="786" y="523" fill="#ffffff" font-size="13" font-family="Tahoma" text-anchor="middle">ارسال</text>
  <rect x="586" y="504" width="126" height="28" rx="9" fill="#f1f5f9"/>
  <text x="649" y="523" fill="#334155" font-size="12" font-family="Tahoma" text-anchor="middle">انتخاب منبع</text>
  <rect x="446" y="504" width="122" height="28" rx="9" fill="#f1f5f9"/>
  <text x="507" y="523" fill="#334155" font-size="12" font-family="Tahoma" text-anchor="middle">انتخاب ابزار</text>
</svg>

### نمای خروجی آزمون

<svg width="100%" viewBox="0 0 1180 560" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="نمای خروجی آزمون">
  <rect width="1180" height="560" rx="18" fill="#f8fafc"/>
  <rect x="32" y="32" width="1116" height="496" rx="16" fill="#ffffff" stroke="#d6dee8"/>
  <rect x="36" y="32" width="330" height="496" rx="16" fill="#0f172a"/>
  <text x="330" y="82" fill="#ffffff" font-size="24" font-family="Tahoma" text-anchor="end">محیط آزمون</text>
  <text x="330" y="112" fill="#cbd5e1" font-size="14" font-family="Tahoma" text-anchor="end">زمان‌سنج، پاسخ‌ها و تصحیح تشریحی</text>
  <rect x="72" y="156" width="258" height="80" rx="14" fill="#1e293b"/>
  <text x="300" y="186" fill="#94a3b8" font-size="14" font-family="Tahoma" text-anchor="end">زمان باقی‌مانده</text>
  <text x="300" y="216" fill="#ffffff" font-size="28" font-family="Tahoma" text-anchor="end">۱۸:۴۲</text>
  <rect x="72" y="260" width="258" height="80" rx="14" fill="#1e293b"/>
  <text x="300" y="290" fill="#94a3b8" font-size="14" font-family="Tahoma" text-anchor="end">پاسخ داده‌شده</text>
  <text x="300" y="320" fill="#ffffff" font-size="28" font-family="Tahoma" text-anchor="end">۷ / ۱۰</text>
  <rect x="72" y="378" width="258" height="44" rx="10" fill="#0f766e"/>
  <text x="201" y="406" fill="#ffffff" font-size="15" font-family="Tahoma" text-anchor="middle">تکمیل آزمون</text>
  <text x="1108" y="82" fill="#111827" font-size="24" font-family="Tahoma" text-anchor="end">آزمون تولیدشده از منابع انتخابی</text>
  <rect x="428" y="122" width="680" height="96" rx="14" fill="#f9fafb" stroke="#e5e7eb"/>
  <text x="1078" y="153" fill="#111827" font-size="16" font-family="Tahoma" text-anchor="end">۱. کدام گزینه مفهوم اصلی بخش اول را بهتر بیان می‌کند؟</text>
  <rect x="986" y="175" width="92" height="28" rx="8" fill="#ecfdf5"/>
  <text x="1032" y="194" fill="#047857" font-size="12" font-family="Tahoma" text-anchor="middle">تستی</text>
  <text x="1078" y="205" fill="#64748b" font-size="13" font-family="Tahoma" text-anchor="end">گزینه‌ها بعد از ارسال با پاسخ صحیح مقایسه می‌شوند.</text>
  <rect x="428" y="242" width="680" height="128" rx="14" fill="#f9fafb" stroke="#e5e7eb"/>
  <text x="1078" y="274" fill="#111827" font-size="16" font-family="Tahoma" text-anchor="end">۲. ارتباط بندهای قرارداد و ضمانت اجرا را توضیح دهید.</text>
  <rect x="958" y="296" width="120" height="28" rx="8" fill="#eff6ff"/>
  <text x="1018" y="315" fill="#1d4ed8" font-size="12" font-family="Tahoma" text-anchor="middle">تشریحی</text>
  <rect x="460" y="322" width="584" height="30" rx="8" fill="#ffffff" stroke="#cbd5e1"/>
  <text x="1024" y="342" fill="#94a3b8" font-size="13" font-family="Tahoma" text-anchor="end">پاسخ تشریحی خود را بنویسید...</text>
  <rect x="428" y="394" width="680" height="78" rx="14" fill="#f0fdf4" stroke="#bbf7d0"/>
  <text x="1078" y="425" fill="#166534" font-size="16" font-family="Tahoma" text-anchor="end">نتیجه تصحیح</text>
  <text x="1078" y="454" fill="#166534" font-size="14" font-family="Tahoma" text-anchor="end">نمره کل، بازخورد تستی و بازخورد تشریحی با مدل انتخاب‌شده تولید می‌شود.</text>
</svg>

### تصویر معماری مدل‌ها

![نمودار تعامل مدل‌ها](architecture/model-interactions.svg)

## خلاصه امکانات

| حوزه | قابلیت | فایل‌ها و مسیرهای اصلی |
|---|---|---|
| احراز هویت | ورود با ایمیل/رمز عبور، ورود با موبایل و OTP، ثبت‌نام چندمرحله‌ای | `backend/app/api/routes/auth.py`, `apps/web/src/app/login/page.tsx`, `apps/web/src/app/register/page.tsx` |
| نشست کاربر | Session cookie امضاشده با Starlette، اعتبارسنجی کاربر در سمت سرور | `backend/app/main.py`, `backend/app/dependencies.py`, `apps/web/src/lib/server-auth.ts` |
| مدیریت پروفایل | مشاهده و به‌روزرسانی نام، ایمیل، تاریخ تولد، رمز عبور و پرداخت‌ها | `backend/app/api/routes/profile.py`, `apps/web/src/app/profile/page.tsx` |
| بارگذاری فایل | دریافت فایل، تشخیص دسته فایل، ذخیره در مسیر اختصاصی هر کاربر | `backend/app/api/routes/gallery.py`, `storage.py` |
| پردازش سند | نرمال‌سازی TXT/PDF/DOCX به Markdown، OCR اختیاری، metadata، chunking ساختارمند | `document_pipeline/ingest.py`, `document_pipeline/chunker.py`, `scan_worker.py` |
| RAG فارسی | جست‌وجوی برداری با BGE-M3، rerank با cross-encoder، پاسخ grounded با citation | `rag.py`, `backend/app/vector/pgvector_store.py` |
| چت آزاد | اگر منبعی انتخاب نشود، پاسخ عمومی از مدل انتخابی گرفته می‌شود | `rag.py`, `backend/app/api/routes/ask.py` |
| جریان پاسخ | پاسخ streaming با رویدادهای NDJSON شامل trace، token، final، done | `backend/app/api/routes/ask.py`, `apps/web/src/features/chat/utils/stream.ts` |
| ابزارهای متنی | خلاصه‌سازی، نکات کلیدی، مقایسه اسناد، آزمون‌سازی، فلش‌کارت، مقاله، لایحه، بازنویسی | `backend/app/services/tools.py`, `backend/app/services/tool_runner.py` |
| خروجی ساختاریافته | ذخیره خروجی ابزارها، نمایش در canvas، تصحیح آزمون | `backend/app/api/routes/outputs.py`, `apps/web/src/features/chat/components/OutputCanvas.tsx` |
| مدیریت مکالمه | ساخت، تغییر نام، حذف و ادامه مکالمه با مدل انتخابی | `backend/app/api/routes/conversations.py`, `apps/web/src/features/chat/components/UnifiedChatSidebar.tsx` |
| پنل مدیریت | آمار کاربران، اشتراک‌ها، پرداخت‌ها، اعطای دستی اشتراک | `backend/app/api/routes/admin.py`, `apps/web/src/features/admin/components/AdminClient.tsx` |
| پرداخت | اتصال به زرین‌پال، callback، ثبت پرداخت و ساخت اشتراک | `payments.py`, `backend/app/api/routes/payments.py` |
| ثبت مصرف | ثبت usage مدل‌ها و مصرف compute برای embedding/reranking/grading | `backend/app/services/usage_tracking.py`, `backend/app/db/models.py` |
| model gateway | انتخاب provider بین Ollama، LiteLLM، Gemini و DeepSeek | `model_gateway/registry.py`, `model_gateway/providers/*` |

## معماری پروژه

| لایه | تکنولوژی | نقش |
|---|---|---|
| Frontend | Next.js 16، React 19، TypeScript | رابط چت، ورود/ثبت‌نام، گالری منابع، پنل ادمین و canvas خروجی |
| Backend API | FastAPI، Uvicorn، Starlette SessionMiddleware | API احراز هویت، اسناد، مکالمه، ابزارها، پرداخت، ادمین و سلامت سیستم |
| Database | PostgreSQL، SQLAlchemy، Alembic | کاربران، OTP، پلن‌ها، پرداخت‌ها، فایل‌ها، مکالمه‌ها، خروجی‌ها و usage |
| Vector Store | pgvector | ذخیره embedding چانک‌ها و جست‌وجوی similarity |
| Embedding | `sentence-transformers` با مدل `bge-m3` | embedding چندزبانه محلی، با GPU در صورت دسترس |
| Reranker | `bge-reranker-v2-m3` با CrossEncoder | بازچینی نتایج جست‌وجوی برداری قبل از تولید پاسخ |
| LLM Gateway | Ollama، LiteLLM، Gemini، DeepSeek | تولید پاسخ، فهم پرسش، ابزارهای متنی و تصحیح تشریحی |
| File Storage | مسیر `storage/{user_id}/{category}/{asset_id}` | نگهداری فایل اصلی، Markdown نرمال‌شده، metadata و خروجی OCR |
| Worker | Thread داخلی در FastAPI | پردازش صف فایل‌های `uploaded` و تبدیل آن‌ها به `scanned` یا `failed` |
| Tests | pytest-style tests | تست usage tracking، grading context و preprocessing |

## جریان پردازش سند

| مرحله | ورودی | خروجی | توضیح |
|---|---|---|---|
| ۱. Upload | `txt`, `pdf`, `docx` و همچنین mediaهای ذخیره‌شونده | ردیف `assets` با وضعیت `uploaded` | مسیر `/api/gallery/upload` فایل را در پوشه اختصاصی کاربر ذخیره می‌کند. |
| ۲. Claim | asset با وضعیت `uploaded` | وضعیت `scanning` | `scan_worker` فایل بعدی را از دیتابیس claim می‌کند. |
| ۳. Normalize | فایل اصلی | `normalized.md` و `metadata.json` | TXT/PDF/DOCX به Markdown canonical تبدیل می‌شوند؛ PDF می‌تواند OCR fallback داشته باشد. |
| ۴. Chunk | Markdown ساختارمند | چانک‌های heading-aware | چانک‌ها chapter/section/page/offset دارند و overlap کنترل‌شده می‌گیرند. |
| ۵. Embed | متن چانک‌ها | vector با ابعاد `EMBEDDING_DIM` | embedding با BGE-M3 ساخته می‌شود. |
| ۶. Index | vector و metadata | ردیف‌های `document_chunks` | در pgvector ذخیره می‌شود و با `user_id` ایزوله است. |
| ۷. Retrieve | پرسش کاربر | چانک‌های مرتبط | ابتدا جست‌وجوی dense، سپس rerank اختیاری. |
| ۸. Generate | پرسش + context | پاسخ با citation | پاسخ factual فقط از context مجاز ساخته می‌شود. |

## مسیرهای مهم Frontend

| مسیر | کاربرد | نیاز به ورود |
|---|---|---|
| `/` | برنامه اصلی چت، انتخاب منبع، ابزارها و canvas خروجی | بله |
| `/login` | ورود با ایمیل/رمز عبور یا موبایل/OTP | خیر |
| `/register` | ثبت‌نام با OTP، اطلاعات فردی و تقویم شمسی | خیر |
| `/gallery` | مشاهده فایل‌ها و وضعیت پردازش | بله |
| `/profile` | پروفایل و تاریخچه پرداخت‌ها | بله |
| `/admin` | آمار، کاربران، اشتراک‌ها و پرداخت‌ها | مدیر |

## APIهای اصلی

| گروه | Endpoint | متد | توضیح |
|---|---|---|---|
| Health | `/api/health` | GET | وضعیت سیستم، مدل‌ها، reranker، تعداد چانک‌ها |
| Auth | `/api/auth/request-otp` | POST | ارسال OTP ورود |
| Auth | `/api/auth/verify-otp` | POST | تأیید OTP و ساخت نشست |
| Auth | `/api/auth/register/send-otp` | POST | OTP ثبت‌نام |
| Auth | `/api/auth/register/complete` | POST | تکمیل ثبت‌نام |
| Auth | `/api/auth/login-email` | POST | ورود با ایمیل و رمز عبور |
| Auth | `/api/auth/me` | GET | وضعیت کاربر فعلی |
| Gallery | `/api/gallery/upload` | POST | بارگذاری فایل |
| Gallery | `/api/gallery/assets` | GET | فهرست assetها و شمارش دسته‌ها |
| Documents | `/api/documents` | GET | اسناد text اسکن‌شده برای انتخاب |
| Chat | `/api/chat/models` | GET | مدل‌های قابل انتخاب در UI |
| Chat | `/api/ask` | POST | پاسخ غیر streaming |
| Chat | `/api/ask/stream` | POST | پاسخ streaming با NDJSON |
| Conversations | `/api/conversations` | GET/POST | فهرست و ساخت مکالمه |
| Conversations | `/api/conversations/{id}` | PATCH/DELETE | تغییر نام/مدل یا حذف مکالمه |
| Conversations | `/api/conversations/{id}/messages` | GET | پیام‌های یک مکالمه |
| Tools | `/api/tools` | GET | ابزارهای قابل اجرا در چت |
| Outputs | `/api/outputs/{id}` | GET | دریافت خروجی ذخیره‌شده ابزار |
| Outputs | `/api/outputs/{id}/grade` | POST | تصحیح آزمون تولیدشده |
| Payments | `/api/plans` | GET | پلن‌های فعال |
| Payments | `/api/subscribe` | POST | شروع پرداخت زرین‌پال |
| Payments | `/api/payment/callback` | GET | callback پرداخت |
| Admin | `/api/admin/*` | GET/POST | مدیریت کاربران، اشتراک‌ها و پرداخت‌ها |

## ابزارهای محصول

| ابزار | شناسه | نیاز به منبع | خروجی |
|---|---|---|---|
| خلاصه‌سازی | `summary` | خیر | Markdown در چت |
| استخراج نکات کلیدی | `key_points` | خیر | Markdown در چت |
| مقایسه اسناد | `compare_documents` | بله | Markdown در چت |
| طراحی آزمون | `exam_generation` | بله | خروجی ساختاریافته، canvas آزمون و امکان تصحیح |
| فلش‌کارت | `flashcards` | خیر | خروجی ساختاریافته |
| پیش‌نویس مقاله | `article_draft` | خیر | خروجی ساختاریافته |
| لایحه‌نویسی | `legal_pleading` | خیر | خروجی ساختاریافته |
| بررسی حقوقی | `legal_review` | خیر | خروجی ساختاریافته |
| بازنویسی | `rewrite` | خیر | Markdown در چت |

## مدل داده

| جدول | نقش |
|---|---|
| `users` | اطلاعات حساب، نقش مدیر، وضعیت تأیید، ایمیل و رمز |
| `otp_codes` | کدهای OTP با انقضا و وضعیت مصرف |
| `plans` | پلن‌های اشتراک |
| `subscriptions` | اشتراک‌های کاربران |
| `payments` | پرداخت‌ها، authority، ref_id و وضعیت |
| `assets` | فایل‌های آپلودشده، وضعیت اسکن، مسیر فایل و metadata |
| `document_chunks` | چانک‌های سند همراه embedding، metadata و ایزولاسیون کاربر |
| `conversations` | مکالمه‌ها و مدل انتخاب‌شده |
| `conversation_messages` | پیام‌ها، منابع، وضعیت stream و metadata ابزار |
| `generated_outputs` | خروجی‌های ابزارها مثل آزمون، فلش‌کارت و مقاله |
| `usage_events` | مصرف مدل‌های chat completion |
| `compute_usage_events` | مصرف عملیات compute مثل reranking |

## پیش‌نیازها

| ابزار | نسخه/توضیح |
|---|---|
| Python | نسخه سازگار با dependencyهای پروژه |
| Node.js و npm | برای Next.js frontend |
| Docker Desktop | برای PostgreSQL/pgvector و در صورت نیاز LiteLLM |
| Ollama | برای provider محلی و مدل پیش‌فرض `gemma3:12b` |
| مدل‌های محلی | `models/bge-m3` و در صورت فعال بودن reranker، `models/bge-reranker-v2-m3` |
| Tesseract OCR | اختیاری؛ برای PDFهای اسکن‌شده یا دارای text layer خراب |

## راه‌اندازی سریع Backend

از ریشه پروژه:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

نصب PyTorch جداست، چون buildهای CUDA روی PyPI عمومی نیستند. برای CPU:

```powershell
pip install torch
```

برای GPU باید wheel متناسب با کارت و درایور خود را نصب کنید؛ نمونه:

```powershell
pip install torch==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
```

فایل محیطی را بسازید:

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

مقدار تولیدشده را در `SESSION_SECRET_KEY` یا `FLASK_SECRET_KEY` قرار دهید. سپس حداقل این مقدارها را بررسی کنید:

```env
DATABASE_URL=postgresql+psycopg://postgres:CHANGE_ME@127.0.0.1:5432/rag_system
OLLAMA_MODEL=gemma3:12b
EMBEDDING_MODEL=./models/bge-m3
EMBEDDING_MODEL_PATH=./models/bge-m3
VECTOR_BACKEND=pgvector
```

PostgreSQL/pgvector را اجرا کنید:

```powershell
docker compose up -d
```

مهاجرت‌های دیتابیس را اجرا کنید:

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

مدل Ollama را آماده کنید:

```powershell
ollama pull gemma3:12b
```

در صورت نیاز یک مدیر بسازید:

```powershell
.\venv\Scripts\python.exe make_admin.py 09123456789
```

Backend را اجرا کنید:

```powershell
.\venv\Scripts\python.exe serve.py
```

آدرس پیش‌فرض API:

```text
http://127.0.0.1:5000
```

## راه‌اندازی Frontend

در ترمینال جدا:

```powershell
cd apps\web
npm install
npm run dev
```

آدرس پیش‌فرض فرانت:

```text
http://127.0.0.1:3000
```

Next.js درخواست‌های `/api/*` را با مقدار `BACKEND_URL` به FastAPI proxy می‌کند. مقدار پیش‌فرض:

```env
BACKEND_URL=http://127.0.0.1:5000
```

## اجرای LiteLLM اختیاری

پروژه به‌صورت پیش‌فرض می‌تواند `DEFAULT_CHAT_PROVIDER=litellm` داشته باشد. سرویس LiteLLM در مسیر `infra/litellm` تعریف شده و پورت `4000` را باز می‌کند.

```powershell
cd infra\litellm
docker compose up -d
```

فایل `infra/litellm/config.yaml` مدل‌های منطقی زیر را به Gemini نگاشت می‌کند:

| نام منطقی | کاربرد |
|---|---|
| `chat_free` | چت آزاد |
| `summary` | خلاصه‌سازی |
| `flashcards` | فلش‌کارت |
| `rewrite` | بازنویسی |
| `exam_generation` | تولید آزمون |
| `exam_grading_descriptive` | تصحیح تشریحی |

## متغیرهای محیطی مهم

| متغیر | مقدار نمونه | توضیح |
|---|---|---|
| `SESSION_SECRET_KEY` / `FLASK_SECRET_KEY` | مقدار تصادفی بلند | کلید امضای session؛ بدون آن backend بالا نمی‌آید. |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:5000` | برای callback زرین‌پال و secure cookie در production. |
| `FRONTEND_URL` | `http://127.0.0.1:3000` | آدرس فرانت در پاسخ ریشه API. |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | bind address برای Uvicorn. |
| `DATABASE_URL` | `postgresql+psycopg://...` | اتصال SQLAlchemy به PostgreSQL. |
| `VECTOR_BACKEND` | `pgvector` | تنها backend پیاده‌سازی‌شده فعلی؛ Qdrant رزرو شده است. |
| `EMBEDDING_MODEL` | `./models/bge-m3` | مدل embedding مورد انتظار RAG. |
| `EMBEDDING_MODEL_PATH` | `./models/bge-m3` | مسیر ترجیحی لایه vector. |
| `EMBEDDING_DIM` | `1024` | ابعاد embedding برای BGE-M3 و ستون pgvector. |
| `OLLAMA_MODEL` | `gemma3:12b` | مدل پیش‌فرض Ollama. |
| `OLLAMA_NUM_CTX` | `8192` | context window برای callهای اصلی RAG. |
| `DEFAULT_CHAT_PROVIDER` / `CHAT_PROVIDER` | `litellm` | provider پیش‌فرض مدل chat. |
| `CHAT_MODEL` | خالی یا نام مدل | مدل عمومی در صورت override. |
| `LITELLM_BASE_URL` | `http://127.0.0.1:4000` | آدرس LiteLLM. |
| `LITELLM_MODEL` | `chat_free` | مدل منطقی پیش‌فرض در LiteLLM. |
| `LITELLM_CHAT_MODEL_OPTIONS` | `chat_free` | مدل‌هایی که در UI نمایش داده می‌شوند. |
| `LITELLM_MASTER_KEY` | `sk-local-litellm-test-key` | کلید دسترسی LiteLLM. |
| `GEMINI_API_KEY` | خالی | برای provider مستقیم Gemini یا LiteLLM با Gemini. |
| `DEEPSEEK_API_KEY` | خالی | برای provider مستقیم DeepSeek. |
| `ENABLE_RERANKER` | `true` | فعال‌سازی reranker مرحله دوم retrieval. |
| `RERANKER_MODEL` | `./models/bge-reranker-v2-m3` | مدل reranker. |
| `RERANKER_DEVICE` | `cpu` | دستگاه reranker؛ پیش‌فرض CPU برای کاهش فشار GPU. |
| `RETRIEVE_K` | `30` | تعداد نتایج dense قبل از rerank. |
| `RERANK_TOP_K` | `5` | تعداد چانک‌های نهایی برای تولید پاسخ. |
| `ENABLE_OCR_FALLBACK` | `false` در example | OCR fallback برای PDFهای مشکل‌دار. در کد ingest اگر unset باشد پیش‌فرض `true` دارد. |
| `ENABLE_LLM_NORMALIZATION` | `false` | فعال‌سازی relabel ساختار سند با LLM. |
| `SMS_PROVIDER` | `console` | در توسعه OTP در log چاپ می‌شود. |
| `ZARINPAL_MERCHANT_ID` | خالی | merchant id زرین‌پال. |
| `ZARINPAL_SANDBOX` | `true` | حالت sandbox پرداخت. |

## پایگاه داده و مهاجرت‌ها

`docker-compose.yml` فعلی سرویس `postgres_pgvector` را با تصویر `pgvector/pgvector:pg18-trixie` اجرا می‌کند و پورت `5432` کانتینر را روی `5432` میزبان publish می‌کند.

```yaml
services:
  postgres_pgvector:
    image: pgvector/pgvector:pg18-trixie
    container_name: rag_postgres_pgvector
    ports:
      - "5432:5432"
```

اگر روی سیستم شما PostgreSQL دیگری روی `5432` فعال است، پورت compose و مقدار `DATABASE_URL` را با هم تغییر دهید.

مهاجرت‌های موجود:

| فایل | نقش |
|---|---|
| `20260628_0001_initial_pgvector.py` | schema اولیه و pgvector |
| `20260629_0002_message_tool_metadata.py` | metadata ابزار در پیام‌ها |
| `20260629_0003_generated_outputs.py` | خروجی‌های تولیدشده |
| `20260629_0004_usage_events.py` | usage رویدادهای مدل |
| `20260629_0005_compute_usage_events.py` | usage عملیات compute |

## تست‌ها

تست‌های موجود در مسیر `tests/` روی usage context، تصحیح خروجی‌ها و preprocessing تمرکز دارند. در صورت نصب بودن pytest:

```powershell
.\venv\Scripts\python.exe -m pytest tests
```

برای تست‌های preprocessing:

```powershell
.\venv\Scripts\python.exe tests\preprocessing\run_preprocessing_tests.py
```

## نکات عملیاتی

| موضوع | توصیه |
|---|---|
| امنیت session | در production فقط از `https://` برای `PUBLIC_BASE_URL` استفاده کنید تا cookie امن شود. |
| داده‌های زنده | PostgreSQL و پوشه `storage/` داده اصلی کاربران هستند و باید backup شوند. |
| OCR | اگر کاربران PDF اسکن‌شده بارگذاری می‌کنند، Tesseract و زبان فارسی را نصب کنید. |
| مدل‌های محلی | پروژه با `HF_HUB_OFFLINE=1` و `TRANSFORMERS_OFFLINE=1` از دانلود ناخواسته مدل جلوگیری می‌کند. |
| اشتراک | dependency با نام `require_subscription` فعلاً فقط login را enforce می‌کند؛ در `backend/app/dependencies.py` کامنت توسعه محصول وجود دارد. |
| پرداخت | قبل از production مقدار واقعی `ZARINPAL_MERCHANT_ID`، واحد مبلغ و callback را در sandbox تست کنید. |
| LiteLLM | اگر `DEFAULT_CHAT_PROVIDER=litellm` است، سرویس LiteLLM و کلید provider مقصد باید آماده باشد. |

## ساختار پوشه‌ها

| مسیر | توضیح |
|---|---|
| `apps/web` | فرانت‌اند Next.js |
| `backend/app` | FastAPI، routeها، schema دیتابیس، vector store و سرویس‌ها |
| `document_pipeline` | نرمال‌سازی، OCR، LLM normalization و chunking |
| `model_gateway` | abstraction مدل‌های chat و providerها |
| `infra/litellm` | compose و config سرویس LiteLLM |
| `architecture` | اسناد و نمودار معماری |
| `models` | مدل‌های local مثل BGE-M3 |
| `storage` | فایل‌ها و artifactهای کاربران |
| `tests` | تست‌های usage و preprocessing |
| `manual_test_inputs` | ورودی‌های تست دستی |

## فرمان‌های پرکاربرد

| کار | فرمان |
|---|---|
| اجرای دیتابیس | `docker compose up -d` |
| اجرای migration | `.\venv\Scripts\python.exe -m alembic upgrade head` |
| اجرای backend | `.\venv\Scripts\python.exe serve.py` |
| اجرای frontend | `cd apps\web; npm run dev` |
| ساخت مدیر | `.\venv\Scripts\python.exe make_admin.py 09123456789` |
| دریافت مدل Ollama | `ollama pull gemma3:12b` |
| اجرای LiteLLM | `cd infra\litellm; docker compose up -d` |

</div>
