import json

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse

import db
import rag
from backend.app.api.responses import error_response
from backend.app.dependencies import enforce_rate_limit, require_subscription
from backend.app.services.serializers import (
    conversation_to_json,
    message_to_json,
    selected_assets_from_payload,
)

router = APIRouter()


def _prepare_ask(user, data: dict):
    question = data.get("question", "").strip()
    scope = data.get("scope", "all")
    document_id = data.get("document_id")
    document_name = data.get("document_name")
    chat_provider = data.get("chat_provider")
    chat_model = data.get("chat_model")
    conversation_id = data.get("conversation_id")
    asset_ids, selected_asset_names, asset_error = selected_assets_from_payload(user["id"], data)

    if not question:
        return None, error_response("سوال خالی است")
    if asset_error:
        return None, error_response(asset_error)
    if scope == "selected" and not document_id and not asset_ids:
        return None, error_response("برای این حالت باید یک سند انتخاب شود")
    if asset_ids:
        scope = "selected"
        document_id = None
        document_name = "، ".join(selected_asset_names)

    return {
        "question": question,
        "scope": scope,
        "document_id": document_id,
        "document_name": document_name,
        "chat_provider": chat_provider,
        "chat_model": chat_model,
        "conversation_id": conversation_id,
        "asset_ids": asset_ids,
    }, None


def _rate_limit_ask(request: Request, data: dict):
    conversation_id = data.get("conversation_id") or "new"
    enforce_rate_limit(
        f"ask:{request.session.get('user_id')}:{conversation_id}",
        min_interval_seconds=1,
        max_per_window=60,
        window_seconds=600,
    )


def _ensure_conversation(user_id: int, payload: dict):
    chat_provider = payload["chat_provider"]
    chat_model = payload["chat_model"]
    conversation_id = payload["conversation_id"]

    if conversation_id:
        conversation = db.get_conversation(user_id, conversation_id)
        if not conversation:
            return None, None, None, error_response("گفتگو پیدا نشد", status_code=404)
        if chat_provider or chat_model:
            conversation = db.update_conversation(
                user_id,
                conversation_id,
                chat_provider=chat_provider or conversation["chat_provider"],
                chat_model=chat_model or conversation["chat_model"],
            )
        chat_provider = chat_provider or conversation["chat_provider"]
        chat_model = chat_model or conversation["chat_model"]
    else:
        conversation = db.create_conversation(
            user_id,
            chat_provider=chat_provider,
            chat_model=chat_model,
        )
        conversation_id = conversation["id"]

    return conversation, conversation_id, (chat_provider, chat_model), None


@router.post("/api/ask")
def ask(request: Request, data: dict = Body(default_factory=dict), user=Depends(require_subscription)):
    _rate_limit_ask(request, data)
    payload, error = _prepare_ask(user, data)
    if error:
        return error

    conversation, conversation_id, model_pair, error = _ensure_conversation(user["id"], payload)
    if error:
        return error
    chat_provider, chat_model = model_pair

    db.create_conversation_message(conversation_id, "user", payload["question"])
    if conversation["title"] == "گفتگوی جدید":
        conversation = db.update_conversation(user["id"], conversation_id, title=payload["question"][:42])

    try:
        result = rag.answer_request(
            payload["question"],
            scope=payload["scope"],
            document_id=payload["document_id"],
            asset_ids=payload["asset_ids"],
            user_id=user["id"],
            selected_source=payload["document_name"],
            chat_provider_name=chat_provider,
            chat_model=chat_model,
        )
        db.create_conversation_message(
            conversation_id,
            "assistant",
            result.get("answer", ""),
            sources=result.get("sources", []),
            status="complete",
        )
    except Exception:
        db.create_conversation_message(
            conversation_id,
            "assistant",
            "خطا در تولید پاسخ.",
            status="error",
        )
        raise
    result["conversation"] = conversation_to_json(conversation)
    return result


@router.post("/api/ask/stream")
def ask_stream(request: Request, data: dict = Body(default_factory=dict), user=Depends(require_subscription)):
    _rate_limit_ask(request, data)
    payload, error = _prepare_ask(user, data)
    if error:
        return error

    user_id = user["id"]
    conversation, conversation_id, model_pair, error = _ensure_conversation(user_id, payload)
    if error:
        return error
    chat_provider, chat_model = model_pair

    user_message = db.create_conversation_message(conversation_id, "user", payload["question"])
    if conversation["title"] == "گفتگوی جدید":
        conversation = db.update_conversation(user_id, conversation_id, title=payload["question"][:42])
    assistant_message = db.create_conversation_message(
        conversation_id,
        "assistant",
        "",
        status="streaming",
        stream_status="در حال آماده‌سازی...",
    )

    def event_stream():
        answer_text = ""
        final_sources = []
        done_sent = False
        try:
            yield json.dumps({
                "type": "conversation",
                "conversation": conversation_to_json(conversation),
                "user_message": message_to_json(user_message),
                "assistant_message": message_to_json(assistant_message),
            }, ensure_ascii=False) + "\n"
            for event in rag.answer_request_stream(
                payload["question"],
                scope=payload["scope"],
                document_id=payload["document_id"],
                asset_ids=payload["asset_ids"],
                user_id=user_id,
                selected_source=payload["document_name"],
                chat_provider_name=chat_provider,
                chat_model=chat_model,
            ):
                if event.get("type") == "token":
                    answer_text += event.get("delta") or ""
                elif event.get("type") == "final":
                    if not answer_text and event.get("answer"):
                        answer_text = event["answer"]
                    final_sources = event.get("sources") or []
                    db.update_conversation_message(
                        conversation_id,
                        assistant_message["id"],
                        content=answer_text,
                        sources=final_sources,
                        status="complete",
                    )
                elif event.get("type") == "error":
                    db.update_conversation_message(
                        conversation_id,
                        assistant_message["id"],
                        content=event.get("error") or "خطا در تولید پاسخ.",
                        status="error",
                    )
                elif event.get("type") == "done":
                    done_sent = True
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as e:
            print(f"ask_stream: unhandled error ({e})", flush=True)
            db.update_conversation_message(
                conversation_id,
                assistant_message["id"],
                content="خطا در تولید پاسخ.",
                status="error",
            )
            yield json.dumps({"type": "error", "error": "خطا در تولید پاسخ."}, ensure_ascii=False) + "\n"
        finally:
            if answer_text:
                db.update_conversation_message(
                    conversation_id,
                    assistant_message["id"],
                    content=answer_text,
                    sources=final_sources,
                    status="complete",
                )
            if not done_sent:
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
