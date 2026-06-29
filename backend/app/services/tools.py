from copy import deepcopy


TEXT_TOOLS = [
    {
        "id": "summary",
        "title": "خلاصه‌سازی",
        "category": "documents",
        "description": "خلاصه دقیق از متن یا منابع انتخاب‌شده تولید می‌کند.",
        "requires_assets": False,
        "output_type": "chat_markdown",
        "params_schema": [
            {
                "id": "length",
                "label": "طول خلاصه",
                "type": "select",
                "required": True,
                "default": "medium",
                "options": [
                    {"value": "short", "label": "کوتاه"},
                    {"value": "medium", "label": "متوسط"},
                    {"value": "detailed", "label": "تفصیلی"},
                ],
            },
            {
                "id": "format",
                "label": "فرمت",
                "type": "select",
                "required": True,
                "default": "bullets",
                "options": [
                    {"value": "bullets", "label": "بولت‌پوینت"},
                    {"value": "paragraph", "label": "پاراگرافی"},
                ],
            },
        ],
    },
    {
        "id": "key_points",
        "title": "استخراج نکات کلیدی",
        "category": "documents",
        "description": "مهم‌ترین نکات، اصطلاحات و تصمیم‌های قابل اقدام را استخراج می‌کند.",
        "requires_assets": False,
        "output_type": "chat_markdown",
        "params_schema": [
            {"id": "count", "label": "تعداد نکات", "type": "number", "required": True, "default": 8, "min": 3, "max": 30},
            {"id": "focus", "label": "تمرکز اختیاری", "type": "text", "required": False, "placeholder": "مثلاً نکات حقوقی یا نکات امتحانی"},
        ],
    },
    {
        "id": "compare_documents",
        "title": "مقایسه اسناد",
        "category": "documents",
        "description": "شباهت‌ها، تفاوت‌ها و تعارض‌های منابع انتخاب‌شده را مقایسه می‌کند.",
        "requires_assets": True,
        "output_type": "chat_markdown",
        "params_schema": [
            {"id": "focus", "label": "محور مقایسه", "type": "text", "required": False, "placeholder": "مثلاً تعهدات، تاریخ‌ها یا ادعاها"},
        ],
    },
    {
        "id": "exam_generation",
        "title": "طراحی آزمون",
        "category": "education",
        "description": "از متن یا منابع انتخاب‌شده آزمون قابل استفاده تولید می‌کند.",
        "requires_assets": True,
        "output_type": "structured_markdown",
        "params_schema": [
            {"id": "question_count", "label": "تعداد سؤال", "type": "number", "required": True, "default": 10, "min": 1, "max": 60},
            {"id": "multiple_choice_count", "label": "تعداد سؤال تستی", "type": "number", "required": True, "default": 5, "min": 0, "max": 60},
            {"id": "descriptive_count", "label": "تعداد سؤال تشریحی", "type": "number", "required": True, "default": 5, "min": 0, "max": 60},
            {"id": "total_score", "label": "نمره کل آزمون", "type": "number", "required": True, "default": 20, "min": 1, "max": 100},
            {"id": "duration_minutes", "label": "زمان آزمون (دقیقه)", "type": "number", "required": True, "default": 20, "min": 1, "max": 240},
            {
                "id": "difficulty",
                "label": "سطح سختی",
                "type": "select",
                "required": True,
                "default": "medium",
                "options": [
                    {"value": "easy", "label": "آسان"},
                    {"value": "medium", "label": "متوسط"},
                    {"value": "hard", "label": "سخت"},
                ],
            },
            {
                "id": "answer_key",
                "label": "پاسخنامه",
                "type": "select",
                "required": True,
                "default": "end",
                "options": [
                    {"value": "end", "label": "آخر آزمون"},
                    {"value": "after_each", "label": "بعد از هر سؤال"},
                    {"value": "none", "label": "بدون پاسخنامه"},
                ],
            },
        ],
    },
    {
        "id": "flashcards",
        "title": "فلش‌کارت",
        "category": "education",
        "description": "فلش‌کارت‌های پرسش و پاسخ برای مرور سریع می‌سازد.",
        "requires_assets": False,
        "output_type": "structured_markdown",
        "params_schema": [
            {"id": "card_count", "label": "تعداد کارت", "type": "number", "required": True, "default": 12, "min": 3, "max": 80},
            {
                "id": "level",
                "label": "سطح",
                "type": "select",
                "required": True,
                "default": "medium",
                "options": [
                    {"value": "basic", "label": "پایه"},
                    {"value": "medium", "label": "متوسط"},
                    {"value": "advanced", "label": "پیشرفته"},
                ],
            },
        ],
    },
    {
        "id": "article_draft",
        "title": "پیش‌نویس مقاله",
        "category": "writing",
        "description": "پیش‌نویس مقاله ساختارمند با تیترها و بدنه منسجم تولید می‌کند.",
        "requires_assets": False,
        "output_type": "structured_markdown",
        "params_schema": [
            {"id": "audience", "label": "مخاطب", "type": "text", "required": False, "placeholder": "مثلاً دانشجویان یا مدیران"},
            {
                "id": "tone",
                "label": "لحن",
                "type": "select",
                "required": True,
                "default": "formal",
                "options": [
                    {"value": "formal", "label": "رسمی"},
                    {"value": "academic", "label": "دانشگاهی"},
                    {"value": "friendly", "label": "صمیمی"},
                ],
            },
            {
                "id": "length",
                "label": "طول متن",
                "type": "select",
                "required": True,
                "default": "medium",
                "options": [
                    {"value": "short", "label": "کوتاه"},
                    {"value": "medium", "label": "متوسط"},
                    {"value": "long", "label": "بلند"},
                ],
            },
        ],
    },
    {
        "id": "legal_pleading",
        "title": "لایحه‌نویسی",
        "category": "legal",
        "description": "پیش‌نویس اولیه لایحه با ساختار حقوقی تولید می‌کند.",
        "requires_assets": False,
        "output_type": "structured_markdown",
        "params_schema": [
            {"id": "pleading_type", "label": "نوع لایحه", "type": "text", "required": True, "placeholder": "مثلاً دفاعیه یا تجدیدنظرخواهی"},
            {"id": "court", "label": "مرجع رسیدگی", "type": "text", "required": False, "placeholder": "مثلاً دادگاه عمومی حقوقی"},
            {
                "id": "tone",
                "label": "لحن",
                "type": "select",
                "required": True,
                "default": "formal",
                "options": [
                    {"value": "formal", "label": "رسمی"},
                    {"value": "firm", "label": "قاطع"},
                    {"value": "concise", "label": "مختصر"},
                ],
            },
        ],
    },
    {
        "id": "legal_review",
        "title": "بررسی حقوقی",
        "category": "legal",
        "description": "ایرادهای ساختاری، نگارشی و استنادی متن حقوقی را گزارش می‌کند.",
        "requires_assets": False,
        "output_type": "structured_markdown",
        "params_schema": [
            {
                "id": "review_focus",
                "label": "تمرکز بررسی",
                "type": "select",
                "required": True,
                "default": "full",
                "options": [
                    {"value": "full", "label": "کامل"},
                    {"value": "structure", "label": "ساختار"},
                    {"value": "citations", "label": "استنادها"},
                    {"value": "language", "label": "نگارش"},
                ],
            },
        ],
    },
    {
        "id": "rewrite",
        "title": "بازنویسی",
        "category": "writing",
        "description": "متن را با لحن و طول مورد نظر بازنویسی می‌کند.",
        "requires_assets": False,
        "output_type": "chat_markdown",
        "params_schema": [
            {
                "id": "tone",
                "label": "لحن",
                "type": "select",
                "required": True,
                "default": "clear",
                "options": [
                    {"value": "clear", "label": "شفاف"},
                    {"value": "formal", "label": "رسمی"},
                    {"value": "friendly", "label": "صمیمی"},
                    {"value": "persuasive", "label": "اقناعی"},
                ],
            },
            {
                "id": "length",
                "label": "طول",
                "type": "select",
                "required": True,
                "default": "same",
                "options": [
                    {"value": "shorter", "label": "کوتاه‌تر"},
                    {"value": "same", "label": "تقریباً برابر"},
                    {"value": "longer", "label": "مفصل‌تر"},
                ],
            },
        ],
    },
]


TOOL_INSTRUCTIONS = {
    "summary": "خلاصه‌ای دقیق و وفادار تولید کن. نکات مهم را حذف نکن و از افزودن ادعای ناموجود پرهیز کن.",
    "key_points": "نکات کلیدی را استخراج کن. خروجی را کوتاه، قابل اسکن و اولویت‌بندی‌شده بنویس.",
    "compare_documents": "منابع انتخاب‌شده را مقایسه کن. شباهت‌ها، تفاوت‌ها، تعارض‌ها و نکات نیازمند بررسی را جدا کن.",
    "exam_generation": "یک آزمون استاندارد تولید کن. صورت سؤال‌ها واضح باشند و اگر پاسخنامه خواسته شده، پاسخ صحیح و توضیح کوتاه بده.",
    "flashcards": "فلش‌کارت‌های کاربردی با قالب پرسش/پاسخ بساز. هر کارت باید یک مفهوم مشخص را پوشش دهد.",
    "article_draft": "یک پیش‌نویس مقاله ساختارمند با تیتر، مقدمه، بدنه و جمع‌بندی تولید کن.",
    "legal_pleading": "پیش‌نویس حقوقی منظم تولید کن. لحن رسمی، ساختار روشن و احتیاط در ادعاهای حقوقی را رعایت کن.",
    "legal_review": "متن را از نظر ساختار، استناد، نگارش و ابهام بررسی کن و پیشنهاد اصلاح بده.",
    "rewrite": "متن را با حفظ معنا و رعایت پارامترهای خواسته‌شده بازنویسی کن.",
}


def list_tools() -> list[dict]:
    return deepcopy(TEXT_TOOLS)


def get_tool(tool_id: str) -> dict | None:
    clean_id = str(tool_id or "").strip()
    for tool in TEXT_TOOLS:
        if tool["id"] == clean_id:
            return deepcopy(tool)
    return None


def default_params(tool: dict) -> dict:
    params = {}
    for field in tool.get("params_schema", []):
        if "default" in field:
            params[field["id"]] = field["default"]
    return params


def validate_tool_params(tool: dict, raw_params) -> tuple[dict | None, str | None]:
    raw_params = raw_params if isinstance(raw_params, dict) else {}
    params = default_params(tool)

    for field in tool.get("params_schema", []):
        field_id = field["id"]
        value = raw_params.get(field_id, params.get(field_id))
        if field.get("required") and (value is None or str(value).strip() == ""):
            return None, f"پارامتر «{field['label']}» الزامی است."

        if value is None or value == "":
            continue

        if field["type"] == "number":
            try:
                number = int(value)
            except (TypeError, ValueError):
                return None, f"پارامتر «{field['label']}» باید عدد باشد."
            if "min" in field and number < field["min"]:
                return None, f"پارامتر «{field['label']}» کمتر از حد مجاز است."
            if "max" in field and number > field["max"]:
                return None, f"پارامتر «{field['label']}» بیشتر از حد مجاز است."
            params[field_id] = number
        elif field["type"] == "select":
            allowed = {option["value"] for option in field.get("options", [])}
            if value not in allowed:
                return None, f"گزینه انتخاب‌شده برای «{field['label']}» نامعتبر است."
            params[field_id] = value
        elif field["type"] == "boolean":
            params[field_id] = bool(value)
        else:
            params[field_id] = str(value).strip()

    if tool.get("id") == "exam_generation":
        total = int(params.get("question_count") or 0)
        multiple_choice = int(params.get("multiple_choice_count") or 0)
        descriptive = int(params.get("descriptive_count") or 0)
        if multiple_choice + descriptive != total:
            return None, "جمع تعداد سؤال‌های تستی و تشریحی باید با تعداد کل سؤال برابر باشد."
        if total <= 0:
            return None, "تعداد سؤال باید بیشتر از صفر باشد."

    return params, None


def prepare_tool_request(question: str, tool: dict | None, params: dict | None, has_assets: bool) -> str:
    if not tool:
        return question

    grounded_policy = (
        "اگر منابع انتخاب شده‌اند، فقط از همان منابع برای بخش‌های factual استفاده کن و اگر پاسخ در منابع نبود، صریح بگو کافی نیست. "
        "اگر منبعی انتخاب نشده، از متن درخواست کاربر و دانش عمومی مجاز استفاده کن."
    )
    if has_assets:
        grounded_policy = "فقط از منابع انتخاب‌شده استفاده کن. اگر اطلاعات لازم در منابع نبود، صریح بگو در منابع پیدا نشد."

    param_lines = []
    field_by_id = {field["id"]: field for field in tool.get("params_schema", [])}
    for key, value in (params or {}).items():
        label = field_by_id.get(key, {}).get("label", key)
        param_lines.append(f"- {label}: {value}")
    params_text = "\n".join(param_lines) if param_lines else "- بدون پارامتر اضافی"

    return (
        f"ابزار فعال: {tool['title']}\n"
        f"دستور ابزار: {TOOL_INSTRUCTIONS.get(tool['id'], tool['description'])}\n"
        f"سیاست زمینه: {grounded_policy}\n"
        f"پارامترها:\n{params_text}\n\n"
        f"درخواست کاربر:\n{question}"
    )


def default_tool_request(tool: dict | None) -> str:
    if not tool:
        return ""
    return f"{tool['title']} را با تنظیمات انتخاب‌شده انجام بده."


def prepare_tool_search_query(question: str, tool: dict | None, params: dict | None) -> str:
    if not tool:
        return question

    question = (question or "").strip()
    generic_requests = {
        "انجام بده",
        "انجامش بده",
        "کارتو انجام بده",
        "کارت رو انجام بده",
        "انجام بده کارتو",
        "انجام بده کارت رو",
        "شروع کن",
        "اجرا کن",
        "اوکی",
        "تایید",
    }
    if question in generic_requests or len(question) < 8:
        question = ""

    defaults = {
        "summary": "نکات اصلی، موضوعات مهم و جمع‌بندی کلی متن",
        "key_points": "نکات کلیدی، مفاهیم مهم و موارد قابل اقدام",
        "compare_documents": "شباهت‌ها، تفاوت‌ها و تعارض‌های اصلی اسناد",
        "exam_generation": "مفاهیم مهم، نکات آموزشی و مطالب قابل سؤال",
        "flashcards": "تعاریف، مفاهیم مهم، پرسش و پاسخ‌های آموزشی",
        "article_draft": "موضوعات اصلی، استدلال‌ها و نکات قابل استفاده برای مقاله",
        "legal_pleading": "وقایع، ادعاها، استدلال‌ها و نکات حقوقی مهم",
        "legal_review": "ایرادهای ساختاری، استنادی، نگارشی و ابهام‌های حقوقی",
        "rewrite": "متن اصلی و نکات لازم برای بازنویسی",
    }
    base = defaults.get(tool["id"], tool["description"])
    return f"{base}\n{question}".strip()
