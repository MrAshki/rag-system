# معماری نهایی گفت‌وگو با سند

## دامنه و اصل ایمنی

این مسیر برای پاسخ grounded روی PDF/DOCX/TXT طراحی شده است. متن قابل‌نمایش فقط پس از پایان تولید ساخت‌یافته، اعتبارسنجی schema، بررسی citation، کنترل پشتیبانی ادعاهای عددی/نقل‌قولی، و در خلاصهٔ جامع کنترل پوشش همهٔ بخش‌ها منتشر می‌شود. mapهای میانی، پاسخ truncation‌شده، خطای provider و متن خام fallback هرگز به کاربر داده نمی‌شوند.

## جریان داده

1. `document_pipeline.ingest` فایل را بدون تغییر اصل آن normalize می‌کند. PDF با تحلیل layout، font/position، header/footer تکراری، metadata و ترتیب صفحه پردازش می‌شود؛ DOCX پاراگراف و جدول را در ترتیب خواندن حفظ می‌کند.
2. `profiling` نوع، زبان، عنوان، نویسندگان، کیفیت و بخش‌های واقعی را تعیین می‌کند.
3. `document_map` واحدهای پایدار parent را با نقش‌های abstract، introduction، section، conclusion و references می‌سازد.
4. chunkها همراه `document_id`، `user_id`، صفحه، parent و نقش با Nemotron Embed در Qdrant ثبت می‌شوند.
5. router درخواست را به focused، specific-section/page، analytical، comprehensive-summary، conversational-followup یا free-chat می‌فرستد.
6. focused/analytical از R2 استفاده می‌کنند: lexical + dense، یک rewrite فقط برای cross-language، fusion و دقیقاً یک rerank. analytical سپس parentهای seed را کامل گسترش می‌دهد.
7. specific-section/page مستقیم از canonical map می‌خواند. follow-up کوتاه ابتدا صفحه‌های citationشده در پاسخ قبلی را بازاستفاده می‌کند و retrieval نامرتبط اجرا نمی‌کند.
8. Gemini 2.5 Flash پاسخ اولیهٔ JSON را می‌سازد. فقط در timeout/خطای retryable یا شکست قرارداد ساختاری، citation، truncation یا coverage، GLM 5.2 دقیقاً یک بار با همان prompt/context hash اجرا می‌شود.

## خلاصهٔ جامع

- سندهای زیر ۴۰٬۰۰۰ نویسه: همهٔ chunkهای هر واحد به یک evidence بخشی در ترتیب canonical ادغام می‌شوند؛ هیچ متن منبعی حذف نمی‌شود.
- سندهای بزرگ‌تر: هر بخش کامل به یک evidence تبدیل، به خلاصهٔ ۲۰۰–۳۵۰ واژه‌ای validated تبدیل و با hash محتوا cache می‌شود. retry فقط بخش شکست‌خورده و بخش‌های بعدی را اجرا می‌کند.
- reduce نهایی یک نگاشت صریح `coverage key -> evidence IDs` می‌گیرد و برای هر بخش یک پاراگراف ۶۰–۱۰۰ واژه‌ای تولید می‌کند.
- پوشش بعد از parse و support filtering سنجیده می‌شود. metadata شامل بخش‌های کشف‌شده/پوشش‌داده‌شده/جاافتاده، صفحات درنظرگرفته‌شده، بازهٔ منبع، راهبرد و telemetry مدل است.
- اگر یک map، reduce یا پوشش نهایی شکست بخورد، فقط پیام کنترل‌شده و بدون output میانی برگردانده می‌شود.

## دو fixture واقعی و خطاهای پایه

| سند | پایه | نهایی |
|---|---|---|
| EPR، ۴ صفحه | عنوان غلط، متن مقالهٔ لانتانوم قبل از عنوان، ۹ heading کاذب، ۱۳ chunk | عنوان واقعی، research article، Abstract/Section I/Section 2، ۱۰ chunk، صفحات ۱–۴ |
| مقالهٔ فارسی، ۱۸ صفحه | عنوان `Shinakht`، ۴۱ heading کاذب، header/ISSN داخل استدلال، فاصله‌گذاری خراب، ۵۶ chunk | عنوان واقعی فارسی، ۸ واحد واقعی (references خارج از خلاصه)، ۳۳ chunk، بدون header/ISSN |

OCR برای هیچ‌یک لازم نبود. تصاویر embedded عمدتاً metadata/لوگو بودند و جدول محتوایی واقعی وجود نداشت؛ بنابراین سناریوی OCR و سؤال از جدول برای این دو fixture «نامربوط» ثبت شد، نه اینکه ساختگی ارزیابی شود.

## ارزیابی معماری

مقایسهٔ offline شامل baseline legacy، hierarchy/parent expansion و graph سبک term/section بود. hierarchy میانگین recall صفحهٔ مورد انتظار `0.586` و graph سبک `0.486` داشت؛ بنابراین graph به production اضافه نشد. گراف فقط زمانی ارزشمند است که edgeهای رابطه‌ای با gold set مستقل، citation attribution و هزینهٔ نگه‌داری سنجیده شوند.

در E2E واقعی، هر دو سند با نسخهٔ `v4:v2:v2` و ۴۳ point ایزوله index شدند. سناریوهای factual، numeric، exact extraction، section/conclusion، analytical comparison، cross-language، unanswerable، quoted statement، follow-up و full-document coverage اجرا شدند. خلاصهٔ نهایی EPR سه واحد و صفحات ۱–۴ را پوشاند؛ خلاصهٔ نهایی فارسی همهٔ هفت coverage key و صفحات ۱–۱۷ را پوشاند.

هزینهٔ تجمعی همهٔ اجراهای واقعی، شامل تلاش‌های تشخیصی شکست‌خورده، `0.23533053 USD` بود. embedding و rerank مدل‌های free بودند. هیچ فراخوانی پولی پس از رسیدن به پاسخ معتبر دو خلاصه انجام نشد.

## فرمان‌های بازتولید

```powershell
.\venv\Scripts\python.exe scripts\validate_document_quality.py --fixture-dir "C:\Users\ashkriz\Downloads\New folder"
.\venv\Scripts\python.exe -m unittest discover -s tests -t . -v
.\venv\Scripts\python.exe scripts\run_real_rag_evaluation.py setup
.\venv\Scripts\python.exe scripts\run_real_rag_evaluation.py stage1
.\venv\Scripts\python.exe scripts\run_real_rag_evaluation.py stage2
.\venv\Scripts\python.exe scripts\run_real_rag_evaluation.py cleanup
```

recheckهای تشخیصی فقط برای توسعه‌اند: `recheck-global` و `recheck-fa-global`. runner شناسه‌های کاربر/asset/request را ثبت می‌کند و cleanup فقط همان Qdrant pointها، cacheها، usageها، assetها، کاربر و فایل‌های runtime ایزوله را حذف می‌کند.

## پیشنهادهای آزمون آینده

- PDF چندستونه با caption واقعی، جدول چندصفحه‌ای و footnote پیچیده.
- PDF اسکن‌شدهٔ فارسی/انگلیسی با OCR و صفحهٔ چرخیده.
- DOCX با جدول تو‌در‌تو، header/footer و tracked changes.
- سند بلندتر از context با ۳۰+ بخش و شکست عمدی map برای اثبات resume cache.
- مقایسهٔ چندسندی که هر سوی ادعا citation مستقل داشته باشد.
- gold set جدا برای تصمیم دوباره دربارهٔ graph retrieval، با هزینه، latency و attribution.
