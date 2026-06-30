import logging
import uuid

from fastapi import APIRouter, Body, Depends

import db
from backend.app.api.responses import error_response
from backend.app.dependencies import require_subscription
from backend.app.services.exam_grader import grade_exam
from backend.app.services.serializers import generated_output_to_json
from backend.app.services.usage_tracking import usage_context

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
    request_id = uuid.uuid4().hex
    try:
        source_message = db.get_message_for_generated_output(output["id"])
        conversation_id = (source_message["conversation_id"] if source_message else None) or row["conversation_id"]
        message_id = source_message["id"] if source_message else None
        with usage_context(
            request_id=request_id,
            user_id=user["id"],
            conversation_id=conversation_id,
            message_id=message_id,
            output_id=output["id"],
            feature="exam_grading_descriptive",
            operation_type="chat_completion",
            metadata={
                "route": f"/api/outputs/{output_id}/grade",
                "chat_provider": chat_provider,
                "chat_model": chat_model,
            },
        ):
            grade = grade_exam(output["content_json"], answers, provider_name=chat_provider, model=chat_model)
        db.update_usage_events_context(
            request_id,
            user_id=user["id"],
            conversation_id=conversation_id,
            message_id=message_id,
            output_id=output["id"],
        )
        return {"grade": grade}
    except Exception:
        logger.exception("Failed to grade generated output %s", output_id)
        return error_response("تصحیح آزمون ناموفق بود. لطفاً بک‌اند و Ollama را بررسی کنید.", status_code=500)
