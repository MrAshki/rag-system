import json
import re
from typing import Iterable

import rag
from backend.app.services.tools import prepare_tool_search_query
from model_gateway.registry import get_chat_provider


def _label(chunk: dict) -> str:
    return rag._citation_label(chunk)


def _context(chunks: list[dict]) -> str:
    return "\n\n".join(
        f"[S{i}: {_label(chunk)}]\n{chunk['text']}"
        for i, chunk in enumerate(chunks, start=1)
    )


def _param_text(tool: dict, params: dict) -> str:
    fields = {field["id"]: field for field in tool.get("params_schema", [])}
    lines = []
    for key, value in (params or {}).items():
        field = fields.get(key, {})
        label = field.get("label", key)
        if field.get("type") == "select":
            option = next((item for item in field.get("options", []) if item["value"] == value), None)
            value = option["label"] if option else value
        lines.append(f"- {label}: {value}")
    return "\n".join(lines) if lines else "- بدون پارامتر"


def _language_instruction(question: str) -> str:
    return (
        "زبان خروجی باید فارسی روان و طبیعی باشد."
        if rag._question_language(question) == "fa"
        else "Write the output in fluent English."
    )


def _summary_system(params: dict) -> str:
    format_rule = (
        "خروجی را فقط به صورت bullet list بنویس."
        if params.get("format") == "bullets"
        else "خروجی را به صورت چند پاراگراف منسجم بنویس."
    )
    length_rule = {
        "short": "خیلی کوتاه و فشرده بنویس.",
        "medium": "در اندازه متوسط بنویس.",
        "detailed": "تفصیلی‌تر بنویس اما از متن خارج نشو.",
    }.get(params.get("length"), "در اندازه متوسط بنویس.")
    return (
        "تو ابزار خلاصه‌سازی هستی، نه چت عمومی. فقط خروجی خلاصه تولید کن.\n"
        "از منابع انتخاب‌شده خارج نشو. اگر context کافی نیست، صریح بگو اطلاعات کافی در منابع نیست.\n"
        f"{format_rule}\n{length_rule}\n"
        "هر bullet یا جمله factual باید citation همان جمله را با [S1]، [S2] و مانند آن داشته باشد.\n"
        "عنوان، مقدمه طولانی، توضیح درباره کار خودت، و لیست منابع انتهایی ننویس."
    )


def _exam_system(params: dict) -> str:
    count = int(params.get("question_count") or 10)
    multiple_choice_count = int(params.get("multiple_choice_count") or 0)
    descriptive_count = int(params.get("descriptive_count") or 0)
    total_score = float(params.get("total_score") or 20)
    answer_key = params.get("answer_key")
    answer_rule = {
        "end": "پاسخنامه را فقط در انتهای آزمون بیاور.",
        "after_each": "پاسخ صحیح و توضیح کوتاه را بعد از هر سؤال بیاور.",
        "none": "پاسخنامه ننویس.",
    }.get(answer_key, "پاسخنامه را فقط در انتهای آزمون بیاور.")
    difficulty = {
        "easy": "سطح سؤال‌ها آسان باشد.",
        "medium": "سطح سؤال‌ها متوسط باشد.",
        "hard": "سطح سؤال‌ها سخت و مفهومی‌تر باشد.",
    }.get(params.get("difficulty"), "سطح سؤال‌ها متوسط باشد.")
    return (
        "تو ابزار طراحی آزمون هستی، نه چت عمومی و نه ابزار خلاصه‌سازی.\n"
        "وظیفه تو فقط تولید آزمون استاندارد و قابل اجراست. توضیح آموزشی، خلاصه متن، تحلیل موضوعی یا پاسخ به سؤال کاربر ننویس.\n"
        "از context انتخاب‌شده سؤال بساز و از دانسته بیرونی استفاده نکن.\n"
        f"دقیقاً {count} سؤال تولید کن: {multiple_choice_count} تستی چهارگزینه‌ای و {descriptive_count} تشریحی. {difficulty} {answer_rule}\n"
        f"نمره کل آزمون {total_score:g} باشد و برای هر سؤال نمره جدا تعیین کن؛ معمولاً سؤال تشریحی نمره بیشتری از تستی دارد.\n"
        "سؤال‌ها نباید سطحی، حفظی یا بسیار بدیهی باشند؛ از مفهوم، رابطه علت و معلول، مقایسه، کاربرد و استنباط سؤال بساز.\n"
        "فرمت خروجی:\n"
        "# آزمون\n"
        "## سؤال‌ها\n"
        "1. متن سؤال ... [S1]\n"
        "   - الف) ...\n"
        "   - ب) ...\n"
        "   - ج) ...\n"
        "   - د) ...\n"
        "## پاسخنامه\n"
        "1. گزینه/پاسخ صحیح: ... — توضیح کوتاه ... [S1]\n"
        "برای سؤال تشریحی rubric کوتاه اضافه کن.\n"
        "هر سؤال باید citation داشته باشد. اگر context کافی نیست، تعداد سؤال کمتر نساز؛ سؤال‌های کافی از بخش‌های موجود بساز."
    )


def _exam_json_system(params: dict) -> str:
    count = int(params.get("question_count") or 10)
    multiple_choice_count = int(params.get("multiple_choice_count") or 0)
    descriptive_count = int(params.get("descriptive_count") or 0)
    total_score = float(params.get("total_score") or 20)
    duration = int(params.get("duration_minutes") or 20)
    difficulty = params.get("difficulty") or "medium"
    return (
        "You generate a structured exam from retrieved document context. Return ONLY valid JSON, no markdown.\n"
        "Use Persian for all user-facing text.\n"
        "Do not summarize the document. Do not explain your process. Generate an actual exam.\n"
        "Use only the provided context. Every question must include citations like ['S1'].\n"
        "Questions must be conceptual and useful, not shallow recall. Use application, inference, comparison, and cause/effect where possible.\n"
        f"Generate exactly {count} questions: {multiple_choice_count} multiple_choice and {descriptive_count} descriptive.\n"
        f"difficulty={difficulty}. duration_minutes={duration}. total_score={total_score:g}.\n"
        "Every multiple_choice question must have exactly four choices, answer_index 0-3, and answer_key one of a,b,c,d.\n"
        "Every descriptive question must have rubric and sample_answer.\n"
        "Assign a numeric points value to every question based on difficulty and effort. Descriptive questions usually receive more points than multiple_choice questions.\n"
        f"The sum of all points must be exactly {total_score:g}.\n"
        "JSON schema:\n"
        "{"
        "\"kind\":\"exam\","
        "\"title\":\"...\","
        "\"duration_minutes\":20,"
        "\"total_score\":20,"
        "\"questions\":["
        "{"
        "\"id\":\"q1\","
        "\"type\":\"multiple_choice|descriptive\","
        "\"points\":2,"
        "\"prompt\":\"...\","
        "\"choices\":[\"...\",\"...\",\"...\",\"...\"],"
        "\"answer_index\":0,"
        "\"answer_key\":\"a\","
        "\"sample_answer\":\"...\","
        "\"rubric\":[\"...\"],"
        "\"explanation\":\"...\","
        "\"citations\":[\"S1\"]"
        "}"
        "]"
        "}"
    )


def _generic_system(tool: dict, params: dict) -> str:
    return (
        f"تو ابزار «{tool['title']}» هستی. فقط خروجی همین ابزار را تولید کن، نه گفتگوی عمومی.\n"
        "از context انتخاب‌شده خارج نشو و اگر context کافی نیست، صریح بگو اطلاعات کافی نیست.\n"
        "هر ادعای factual باید citation داشته باشد.\n"
        f"پارامترها:\n{_param_text(tool, params)}"
    )


def _system_prompt(tool: dict, params: dict) -> str:
    if tool["id"] == "summary":
        return _summary_system(params)
    if tool["id"] == "exam_generation":
        return _exam_system(params)
    return _generic_system(tool, params)


def _messages(tool: dict, params: dict, question: str, chunks: list[dict], selected_source: str = None) -> list[dict]:
    context = _context(chunks)
    source_line = f"منابع انتخاب‌شده: {selected_source}\n" if selected_source else ""
    return [
        {"role": "system", "content": f"{_system_prompt(tool, params)}\n{_language_instruction(question)}"},
        {
            "role": "user",
            "content": (
                f"{source_line}"
                f"Context:\n{context}\n\n"
                f"درخواست کاربر:\n{question}\n\n"
                "فقط خروجی ابزار را تولید کن."
            ),
        },
    ]


def _exam_json_messages(tool: dict, params: dict, question: str, chunks: list[dict], selected_source: str = None) -> list[dict]:
    context = _context(chunks)
    source_line = f"منابع انتخاب‌شده: {selected_source}\n" if selected_source else ""
    return [
        {"role": "system", "content": _exam_json_system(params)},
        {
            "role": "user",
            "content": (
                f"{source_line}"
                f"Context:\n{context}\n\n"
                f"User request:\n{question}\n"
            ),
        },
    ]


def _retrieve(tool: dict, params: dict, question: str, document_id: str = None,
              asset_ids: list[str] = None, user_id: int = None) -> list[dict]:
    query = prepare_tool_search_query(question, tool, params)
    top_k = 12 if tool["id"] in {"exam_generation", "flashcards"} else None
    return rag.retrieve(
        query,
        document_id=document_id,
        document_ids=asset_ids or None,
        user_id=user_id,
        top_k=top_k,
    )


def _json_loads(content: str) -> dict:
    content = (content or "").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise


def _coerce_answer_index(raw: dict) -> int:
    key = raw.get("answer_key")
    value = raw.get("answer_index")
    aliases = {
        "a": 0, "b": 1, "c": 2, "d": 3,
        "A": 0, "B": 1, "C": 2, "D": 3,
        "الف": 0, "ا": 0, "أ": 0,
        "ب": 1,
        "ج": 2,
        "د": 3,
        "گزینه الف": 0, "گزینه ا": 0,
        "گزینه ب": 1,
        "گزینه ج": 2,
        "گزینه د": 3,
    }
    for candidate in (key, value):
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text in aliases:
            return aliases[text]
        lowered = text.lower()
        if lowered in aliases:
            return aliases[lowered]
        match = re.search(r"[abcd]", lowered)
        if match:
            return aliases[match.group(0)]
        persian_match = re.search(r"(الف|گزینه\s*الف|ب|ج|د)", text)
        if persian_match:
            return aliases[persian_match.group(1).replace("گزینه ", "")]

    try:
        number = int(value)
    except (TypeError, ValueError):
        return -1
    # Models often ignore the 0-based instruction and return 1..4.
    if 1 <= number <= 4:
        return number - 1
    if 0 <= number <= 3:
        return number
    return -1


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _exam_target_counts(params: dict) -> tuple[int, int, int]:
    total = int(params.get("question_count") or 10)
    multiple_choice = int(params.get("multiple_choice_count") or 0)
    descriptive = int(params.get("descriptive_count") or 0)
    if multiple_choice + descriptive != total:
        # Backward-compatible fallback for older requests.
        if params.get("exam_type") == "multiple_choice":
            multiple_choice, descriptive = total, 0
        elif params.get("exam_type") == "descriptive":
            multiple_choice, descriptive = 0, total
        else:
            multiple_choice = max(0, total // 2)
            descriptive = max(0, total - multiple_choice)
    return total, multiple_choice, descriptive


def _normalize_points(questions: list[dict], total_score: float) -> list[dict]:
    if not questions:
        return questions
    total_units = max(1, int(round(total_score * 2)))
    weights = []
    for question in questions:
        raw_points = _number(question.get("points"), 0)
        if raw_points > 0:
            weights.append(raw_points)
        else:
            weights.append(3.0 if question.get("type") == "descriptive" else 1.0)

    weight_sum = sum(weights) or len(weights)
    exact_units = [(weight / weight_sum) * total_units for weight in weights]
    units = [int(value) for value in exact_units]

    if total_units >= len(units):
        units = [max(1, value) for value in units]

    diff = total_units - sum(units)
    if diff > 0:
        order = sorted(range(len(units)), key=lambda i: exact_units[i] - int(exact_units[i]), reverse=True)
        for index in range(diff):
            units[order[index % len(order)]] += 1
    elif diff < 0:
        order = sorted(range(len(units)), key=lambda i: exact_units[i] - int(exact_units[i]))
        remaining = -diff
        for item_index in order:
            floor = 1 if total_units >= len(units) else 0
            removable = max(0, units[item_index] - floor)
            take = min(removable, remaining)
            units[item_index] -= take
            remaining -= take
            if remaining == 0:
                break

    for question, unit in zip(questions, units):
        question["points"] = unit / 2
    return questions


def _normalize_exam(data: dict, params: dict) -> dict:
    questions = []
    total_count, target_multiple_choice, target_descriptive = _exam_target_counts(params)
    used_multiple_choice = 0
    used_descriptive = 0
    for index, raw in enumerate(data.get("questions") or [], start=1):
        if len(questions) >= total_count:
            break
        qtype = raw.get("type") if raw.get("type") in {"multiple_choice", "descriptive"} else "multiple_choice"
        if used_multiple_choice >= target_multiple_choice and used_descriptive < target_descriptive:
            qtype = "descriptive"
        elif used_descriptive >= target_descriptive and used_multiple_choice < target_multiple_choice:
            qtype = "multiple_choice"
        choices = [str(choice).strip() for choice in (raw.get("choices") or []) if str(choice).strip()]
        if qtype == "multiple_choice":
            choices = (choices + ["", "", "", ""])[:4]
            answer_index = _coerce_answer_index(raw)
            used_multiple_choice += 1
        else:
            choices = []
            answer_index = None
            used_descriptive += 1
        questions.append({
            "id": str(raw.get("id") or f"q{index}"),
            "type": qtype,
            "points": _number(raw.get("points"), 0),
            "prompt": str(raw.get("prompt") or "").strip(),
            "choices": choices,
            "answer_index": answer_index,
            "answer_key": ["a", "b", "c", "d"][answer_index] if isinstance(answer_index, int) and 0 <= answer_index <= 3 else None,
            "sample_answer": str(raw.get("sample_answer") or "").strip(),
            "rubric": [str(item).strip() for item in (raw.get("rubric") or []) if str(item).strip()],
            "explanation": str(raw.get("explanation") or "").strip(),
            "citations": [str(item).strip() for item in (raw.get("citations") or []) if str(item).strip()],
        })
    total_score = _number(data.get("total_score"), _number(params.get("total_score"), 20))
    questions = _normalize_points(questions, total_score)
    return {
        "kind": "exam",
        "title": str(data.get("title") or "آزمون").strip(),
        "duration_minutes": int(data.get("duration_minutes") or params.get("duration_minutes") or 20),
        "total_score": total_score,
        "questions": questions,
    }


def _exam_student_markdown(exam: dict) -> str:
    lines = [f"# {exam.get('title') or 'آزمون'}", ""]
    lines.append(f"زمان آزمون: {exam.get('duration_minutes')} دقیقه")
    lines.append(f"نمره کل: {exam.get('total_score')}")
    lines.append("")
    for index, question in enumerate(exam.get("questions") or [], start=1):
        citations = "".join(f"[{citation}]" for citation in question.get("citations") or [])
        points = question.get("points")
        lines.append(f"{index}. ({points} نمره) {question.get('prompt', '')} {citations}".strip())
        if question.get("type") == "multiple_choice":
            for label, choice in zip(["الف", "ب", "ج", "د"], question.get("choices") or []):
                lines.append(f"   - {label}) {choice}")
        else:
            lines.append("   پاسخ تشریحی: ................................")
        lines.append("")
    return "\n".join(lines).strip()


def _run_exam_tool(provider, tool: dict, params: dict, question: str, chunks: list[dict], selected_source: str = None) -> dict:
    content = provider.chat(
        messages=_exam_json_messages(tool, params, question, chunks, selected_source=selected_source),
        options={"temperature": 0.0, "num_ctx": rag.OLLAMA_NUM_CTX},
        response_format="json",
    )
    exam = _normalize_exam(_json_loads(content), params)
    ready = (
        f"آزمون «{exam.get('title') or 'آزمون'}» آماده شد. "
        "برای شروع، آن را در Canvas باز کنید."
    )
    return {
        "answer": ready,
        "sources": [_label(chunk) for chunk in chunks],
        "content_json": exam,
    }


def run_tool(tool: dict, params: dict, question: str, document_id: str = None,
             asset_ids: list[str] = None, user_id: int = None, selected_source: str = None,
             chat_provider_name: str = None, chat_model: str = None) -> dict:
    provider = get_chat_provider(chat_provider_name, chat_model)
    chunks = _retrieve(tool, params, question, document_id=document_id, asset_ids=asset_ids, user_id=user_id)
    if (asset_ids or document_id) and not chunks:
        return {"answer": "در منابع انتخاب‌شده اطلاعات کافی برای اجرای این ابزار پیدا نشد.", "sources": []}
    if tool["id"] == "exam_generation":
        return _run_exam_tool(provider, tool, params, question, chunks, selected_source=selected_source)
    answer = provider.chat(
        messages=_messages(tool, params, question, chunks, selected_source=selected_source),
        options={"temperature": 0.0, "num_ctx": rag.OLLAMA_NUM_CTX},
    ).strip()
    return {"answer": answer, "sources": [_label(chunk) for chunk in chunks], "content_json": {"markdown": answer}}


def run_tool_stream(tool: dict, params: dict, question: str, document_id: str = None,
                    asset_ids: list[str] = None, user_id: int = None, selected_source: str = None,
                    chat_provider_name: str = None, chat_model: str = None) -> Iterable[dict]:
    provider = get_chat_provider(chat_provider_name, chat_model)
    yield {"type": "trace", "stage": "tool", "status": "started", "tool_id": tool["id"]}
    chunks = _retrieve(tool, params, question, document_id=document_id, asset_ids=asset_ids, user_id=user_id)
    yield {"type": "trace", "stage": "retrieve", "status": "done", "chunks": len(chunks)}
    if (asset_ids or document_id) and not chunks:
        answer = "در منابع انتخاب‌شده اطلاعات کافی برای اجرای این ابزار پیدا نشد."
        yield {"type": "token", "delta": answer}
        yield {"type": "final", "answer": answer, "sources": []}
        yield {"type": "done"}
        return

    if tool["id"] == "exam_generation":
        result = _run_exam_tool(provider, tool, params, question, chunks, selected_source=selected_source)
        yield {"type": "token", "delta": result["answer"]}
        yield {
            "type": "final",
            "answer": result["answer"],
            "sources": result["sources"],
            "content_json": result["content_json"],
        }
        yield {"type": "done"}
        return

    answer_parts = []
    for delta in provider.stream_chat(
        messages=_messages(tool, params, question, chunks, selected_source=selected_source),
        options={"temperature": 0.0, "num_ctx": rag.OLLAMA_NUM_CTX},
    ):
        answer_parts.append(delta)
        yield {"type": "token", "delta": delta}

    answer = "".join(answer_parts).strip()
    yield {"type": "final", "answer": answer, "sources": [_label(chunk) for chunk in chunks], "content_json": {"markdown": answer}}
    yield {"type": "done"}
