import uuid

from fastapi import APIRouter, Body, Depends

from backend.app.api.responses import error_response
from backend.app.dependencies import require_login
from backend.app.services.usage_tracking import usage_context
from model_gateway.registry import get_chat_provider


router = APIRouter()


@router.post("/api/litellm/chat-free")
def litellm_chat_free(data: dict = Body(default_factory=dict), user=Depends(require_login)):
    question = (data.get("question") or "").strip()
    if not question:
        return error_response("سوال خالی است")

    provider = get_chat_provider("litellm", "chat_free")
    with usage_context(
        request_id=uuid.uuid4().hex,
        user_id=user["id"],
        feature="chat_free",
        operation_type="chat_completion",
        metadata={"route": "/api/litellm/chat-free"},
    ):
        answer = provider.chat(
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Answer briefly."},
                {"role": "user", "content": question},
            ],
            options={"temperature": 0.2},
        ).strip()

    return {
        "answer": answer,
        "provider": provider.name,
        "model": provider.model,
    }
