from fastapi import APIRouter, Body, Depends

import db
from backend.app.api.responses import error_response
from backend.app.dependencies import require_subscription
from backend.app.services.serializers import clean_title, conversation_to_json, message_to_json

router = APIRouter()


@router.get("/api/conversations")
def conversations_list(user=Depends(require_subscription)):
    rows = db.list_conversations(user["id"])
    return {"conversations": [conversation_to_json(row) for row in rows]}


@router.post("/api/conversations", status_code=201)
def conversations_create(data: dict = Body(default_factory=dict), user=Depends(require_subscription)):
    conversation = db.create_conversation(
        user["id"],
        title=clean_title(data.get("title")),
        chat_provider=data.get("chat_provider"),
        chat_model=data.get("chat_model"),
    )
    return {"conversation": conversation_to_json(conversation)}


@router.patch("/api/conversations/{conversation_id}")
def conversations_update(conversation_id: str, data: dict = Body(default_factory=dict), user=Depends(require_subscription)):
    conversation = db.get_conversation(user["id"], conversation_id)
    if not conversation:
        return error_response("گفتگو پیدا نشد", status_code=404)

    updated = db.update_conversation(
        user["id"],
        conversation_id,
        title=clean_title(data.get("title")) if "title" in data else None,
        chat_provider=data.get("chat_provider") if "chat_provider" in data else None,
        chat_model=data.get("chat_model") if "chat_model" in data else None,
    )
    return {"conversation": conversation_to_json(updated)}


@router.delete("/api/conversations/{conversation_id}")
def conversations_delete(conversation_id: str, user=Depends(require_subscription)):
    if not db.delete_conversation(user["id"], conversation_id):
        return error_response("گفتگو پیدا نشد", status_code=404)
    return {"status": "ok"}


@router.get("/api/conversations/{conversation_id}/messages")
def conversations_messages(conversation_id: str, user=Depends(require_subscription)):
    conversation = db.get_conversation(user["id"], conversation_id)
    if not conversation:
        return error_response("گفتگو پیدا نشد", status_code=404)
    rows = db.list_conversation_messages(user["id"], conversation_id)
    return {
        "conversation": conversation_to_json(conversation),
        "messages": [message_to_json(row) for row in rows],
    }
