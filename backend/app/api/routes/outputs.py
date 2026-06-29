import logging

from fastapi import APIRouter, Body, Depends

import db
from backend.app.api.responses import error_response
from backend.app.dependencies import require_subscription
from backend.app.services.exam_grader import grade_exam
from backend.app.services.serializers import generated_output_to_json

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/outputs/{output_id}")
def outputs_get(output_id: str, user=Depends(require_subscription)):
    row = db.get_generated_output(user["id"], output_id)
    if not row:
        return error_response("خروجی پیدا نشد", status_code=404)
    return {"output": generated_output_to_json(row)}


@router.post("/api/outputs/{output_id}/grade")
def outputs_grade(output_id: str, data: dict = Body(default_factory=dict), user=Depends(require_subscription)):
    row = db.get_generated_output(user["id"], output_id)
    if not row:
        return error_response("خروجی پیدا نشد", status_code=404)
    output = generated_output_to_json(row)
    if output["type"] != "exam_generation" or output["content_json"].get("kind") != "exam":
        return error_response("این خروجی آزمون قابل تصحیح نیست", status_code=400)
    answers = data.get("answers") or {}
    if not isinstance(answers, dict):
        return error_response("پاسخ‌ها نامعتبر هستند", status_code=400)
    chat_provider = data.get("chat_provider")
    chat_model = data.get("chat_model")
    try:
        return {"grade": grade_exam(output["content_json"], answers, provider_name=chat_provider, model=chat_model)}
    except Exception:
        logger.exception("Failed to grade generated output %s", output_id)
        return error_response("تصحیح آزمون ناموفق بود. لطفاً بک‌اند و Ollama را بررسی کنید.", status_code=500)
