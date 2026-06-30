import json
import logging
import re

from model_gateway.registry import get_chat_provider


logger = logging.getLogger(__name__)

BAD_ANSWER_RE = re.compile(
    r"(نمی\s*دونم|نمیدونم|نمی\s*دانم|چرت|الکی|خاستگاری|خواستگاری|برو\s*بریم)",
    re.I,
)


def _normalize(text: str) -> str:
    return (
        str(text or "")
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("ۀ", "ه")
        .replace("ة", "ه")
        .replace("\u200c", " ")
        .strip()
        .lower()
    )


def _json_loads(content: str):
    content = (content or "").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise


def _is_non_answer(answer: str, prompt: str) -> bool:
    answer_norm = _normalize(answer)
    prompt_norm = _normalize(prompt)
    if len(answer_norm) < 18:
        return True
    if BAD_ANSWER_RE.search(answer_norm):
        return True
    # Copying the prompt is not an answer.
    if prompt_norm and (answer_norm in prompt_norm or prompt_norm in answer_norm):
        return True
    return False


def _points(question: dict, default: float) -> float:
    try:
        value = float(question.get("points"))
    except (TypeError, ValueError):
        value = default
    return max(0, value)


def _grade_descriptive(question: dict, answer: str, provider=None) -> dict:
    max_score = _points(question, 5)
    if _is_non_answer(answer, question.get("prompt", "")):
        return {
            "score": 0,
            "max_score": max_score,
            "feedback": "پاسخ معتبر یا مرتبطی ارائه نشده است.",
        }

    if provider is None:
        return {
            "score": 0,
            "max_score": max_score,
            "feedback": "تصحیح هوشمند در دسترس نیست؛ این پاسخ نمره‌ای دریافت نکرد.",
        }

    prompt = (
        "You grade a Persian descriptive exam answer. Return ONLY valid JSON.\n"
        "Grade strictly using the rubric and sample answer. Do not be generous.\n"
        "If the student copied the question, wrote irrelevant text, or gave a vague non-answer, score 0.\n"
        f"Score is a number from 0 to {max_score:g}, can be decimal by 0.5.\n"
        f"JSON schema: {{\"score\": 0, \"max_score\": {max_score:g}, \"feedback\": \"...\"}}\n\n"
        f"Question:\n{question.get('prompt', '')}\n\n"
        f"Rubric:\n{json.dumps(question.get('rubric') or [], ensure_ascii=False)}\n\n"
        f"Sample answer:\n{question.get('sample_answer') or ''}\n\n"
        f"Student answer:\n{answer}"
    )
    try:
        data = _json_loads(
            provider.chat(
                messages=[
                    {"role": "system", "content": "You are a strict exam grader."},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.0},
                response_format="json",
            )
        )
        score = float(data.get("score", 0))
        score = max(0, min(max_score, round(score * 2) / 2))
        return {
            "score": score,
            "max_score": max_score,
            "feedback": str(data.get("feedback") or "تصحیح انجام شد."),
        }
    except Exception:
        logger.exception("Failed to grade descriptive exam answer")
        return {
            "score": 0,
            "max_score": max_score,
            "feedback": "تصحیح هوشمند ناموفق بود؛ این پاسخ نمره‌ای دریافت نکرد.",
        }


def _grade_descriptive_batch(items: list[dict], provider=None) -> dict[str, dict]:
    if not items:
        return {}
    if provider is None:
        return {
            item["id"]: {
                "score": 0,
                "max_score": item["max_score"],
                "feedback": "تصحیح هوشمند در دسترس نیست؛ این پاسخ نمره‌ای دریافت نکرد.",
            }
            for item in items
        }

    prompt = (
        "You grade Persian descriptive exam answers. Return ONLY valid JSON.\n"
        "Compare each student answer with the question, sample_answer, and rubric.\n"
        "Grade strictly. Do not reward copied questions, vague text, irrelevant text, or empty answers.\n"
        "Each item has max_score. The score must be from 0 to that item's max_score and may use 0.5 increments.\n"
        "JSON schema: {\"grades\":[{\"id\":\"q1\",\"score\":0,\"max_score\":2.5,\"feedback\":\"...\"}]}\n\n"
        f"Items:\n{json.dumps(items, ensure_ascii=False)}"
    )
    try:
        data = _json_loads(
            provider.chat(
                messages=[
                    {"role": "system", "content": "You are a strict Persian exam grader."},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.0},
                response_format="json",
            )
        )
        results = {}
        for raw in data.get("grades") or []:
            qid = str(raw.get("id") or "")
            if not qid:
                continue
            item = next((row for row in items if row["id"] == qid), None)
            max_score = float((item or {}).get("max_score") or 5)
            score = float(raw.get("score", 0))
            score = max(0, min(max_score, round(score * 2) / 2))
            results[qid] = {
                "score": score,
                "max_score": max_score,
                "feedback": str(raw.get("feedback") or "تصحیح انجام شد."),
            }
        for item in items:
            results.setdefault(item["id"], {
                "score": 0,
                "max_score": item["max_score"],
                "feedback": "برای این پاسخ نتیجه تصحیح معتبری از مدل دریافت نشد.",
            })
        return results
    except Exception:
        logger.exception("Failed to batch grade descriptive exam answers")
        return {
            item["id"]: {
                "score": 0,
                "max_score": item["max_score"],
                "feedback": "تصحیح هوشمند ناموفق بود؛ این پاسخ نمره‌ای دریافت نکرد.",
            }
            for item in items
        }


def grade_exam(exam: dict, answers: dict, provider_name: str = None, model: str = None) -> dict:
    question_results = []
    descriptive_items = []
    objective_score = 0
    objective_max = 0
    descriptive_score = 0.0
    descriptive_max = 0

    for question in exam.get("questions") or []:
        qid = str(question.get("id"))
        answer = answers.get(qid)
        if question.get("type") == "multiple_choice":
            max_score = _points(question, 1)
            objective_max += max_score
            correct_index = question.get("answer_index")
            try:
                selected_index = int(answer)
            except (TypeError, ValueError):
                selected_index = None
            is_correct = isinstance(correct_index, int) and correct_index >= 0 and selected_index == correct_index
            if is_correct:
                objective_score += max_score
            question_results.append({
                "id": qid,
                "type": "multiple_choice",
                "score": max_score if is_correct else 0,
                "max_score": max_score,
                "correct": is_correct,
                "selected_index": selected_index,
                "answer_index": correct_index,
                "feedback": question.get("explanation") or "",
            })
        else:
            max_score = _points(question, 5)
            descriptive_max += max_score
            answer_text = str(answer or "")
            if _is_non_answer(answer_text, question.get("prompt", "")):
                graded = {
                    "score": 0,
                    "max_score": max_score,
                    "feedback": "پاسخ معتبر یا مرتبطی ارائه نشده است.",
                }
            else:
                graded = None
                descriptive_items.append({
                    "id": qid,
                    "question": question.get("prompt", ""),
                    "rubric": question.get("rubric") or [],
                    "sample_answer": question.get("sample_answer") or "",
                    "max_score": max_score,
                    "student_answer": answer_text,
                })
            row = {
                "id": qid,
                "type": "descriptive",
                **(graded or {"score": 0, "max_score": max_score, "feedback": "در انتظار تصحیح هوشمند."}),
                "sample_answer": question.get("sample_answer") or "",
                "rubric": question.get("rubric") or [],
            }
            question_results.append(row)

    if descriptive_items:
        try:
            provider = get_chat_provider(provider_name, model, feature="exam_grading_descriptive")
        except Exception:
            logger.exception("Failed to initialize chat provider for exam grading")
            provider = None
        batch_results = _grade_descriptive_batch(descriptive_items, provider)
        for row in question_results:
            if row["type"] != "descriptive" or row["id"] not in batch_results:
                continue
            row.update(batch_results[row["id"]])

    descriptive_score = sum(
        float(row.get("score") or 0)
        for row in question_results
        if row["type"] == "descriptive"
    )

    total_score = objective_score + descriptive_score
    total_max = objective_max + descriptive_max
    return {
        "total_score": total_score,
        "total_max": total_max,
        "objective_score": objective_score,
        "objective_max": objective_max,
        "descriptive_score": descriptive_score,
        "descriptive_max": descriptive_max,
        "questions": question_results,
    }
