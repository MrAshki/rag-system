import json
import uuid

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse

import db
import rag
from backend.app.api.responses import error_response
from backend.app.dependencies import enforce_rate_limit, require_subscription
from backend.app.services.serializers import (
    conversation_to_json,
    generated_output_to_json,
    message_to_json,
    selected_assets_from_payload,
)
from backend.app.services.tool_runner import run_tool, run_tool_stream
from backend.app.services.tools import (
    default_tool_request,
    get_tool,
    prepare_tool_request,
    prepare_tool_search_query,
    validate_tool_params,
)
from backend.app.services.usage_tracking import reset_usage_context, set_usage_context, usage_context

router = APIRouter()


def _create_tool_output(user_id: int, conversation_id: str, payload: dict, answer: str, content_json=None):
    if not payload.get("tool"):
        return None
    row = db.create_generated_output(
        user_id,
        conversation_id,
        output_type=payload["tool_id"],
        title=payload["tool_title"] or payload["tool"]["title"],
        content_markdown=answer,
        content_json=content_json or {"markdown": answer},
        source_asset_ids=payload["asset_ids"],
        template_id=payload["tool_id"],
        template_params=payload["tool_params"],
    )
    return generated_output_to_json(row)


def _prepare_ask(user, data: dict):
    question = data.get("question", "").strip()
    scope = data.get("scope", "all")
    document_id = data.get("document_id")
    document_name = data.get("document_name")
    chat_provider = None
    chat_model = None
    conversation_id = data.get("conversation_id")
    tool_id = data.get("tool_id")
    tool_params = data.get("tool_params")
    asset_ids, selected_asset_names, asset_error = selected_assets_from_payload(user["id"], data)

    if asset_error:
        return None, error_response(asset_error)
    if scope == "selected" and not document_id and not asset_ids:
        return None, error_response("برای این حالت باید یک سند انتخاب شود")
    if asset_ids:
        scope = "selected"
        document_id = None
        document_name = "، ".join(selected_asset_names)

    tool = None
    clean_tool_id = str(tool_id or "").strip()
    if clean_tool_id:
        tool = get_tool(clean_tool_id)
        if not tool:
            return None, error_response("ابزار انتخاب‌شده نامعتبر است")
        if tool.get("requires_assets") and not asset_ids and not document_id:
            return None, error_response("این ابزار به انتخاب منبع نیاز دارد.")
        tool_params, params_error = validate_tool_params(tool, tool_params)
        if params_error:
            return None, error_response(params_error)

    if not question:
        if not tool:
            return None, error_response("سوال خالی است")
        question = default_tool_request(tool)

    mode = "template_workflow" if tool else ("grounded_chat" if asset_ids or document_id else "free_chat")
    runtime_question = prepare_tool_request(question, tool, tool_params, bool(asset_ids or document_id))
    search_question = prepare_tool_search_query(question, tool, tool_params)

    return {
        "question": question,
        "runtime_question": runtime_question,
        "search_question": search_question,
        "mode": mode,
        "scope": scope,
        "document_id": document_id,
        "document_name": document_name,
        "chat_provider": chat_provider,
        "chat_model": chat_model,
        "conversation_id": conversation_id,
        "asset_ids": asset_ids,
        "tool": tool,
        "tool_id": tool["id"] if tool else None,
        "tool_title": tool["title"] if tool else None,
        "tool_params": tool_params if tool else None,
    }, None


def _rate_limit_ask(request: Request, data: dict):
    conversation_id = data.get("conversation_id") or "new"
    enforce_rate_limit(
        f"ask:{request.session.get('user_id')}:{conversation_id}",
        min_interval_seconds=1,
        max_per_window=60,
        window_seconds=600,
    )


def _usage_feature(payload: dict) -> str:
    if payload.get("tool_id"):
        return payload["tool_id"]
    if payload.get("mode") == "grounded_chat":
        return "chat_grounded"
    return "chat_free"


def _ensure_conversation(user_id: int, payload: dict):
    chat_provider = None
    chat_model = None
    conversation_id = payload["conversation_id"]

    if conversation_id:
        conversation = db.get_conversation(user_id, conversation_id)
        if not conversation:
            return None, None, None, error_response("گفتگو پیدا نشد", status_code=404)
    else:
        conversation = db.create_conversation(
            user_id,
            chat_provider=None,
            chat_model=None,
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
    conversation_history = [
        message_to_json(row)
        for row in db.list_conversation_messages(user["id"], conversation_id)[-8:]
    ]

    user_message = db.create_conversation_message(
        conversation_id,
        "user",
        payload["question"],
        tool_id=payload["tool_id"],
        tool_title=payload["tool_title"],
        tool_params=payload["tool_params"],
        mode=payload["mode"],
    )
    if conversation["title"] == "گفتگوی جدید":
        conversation = db.update_conversation(user["id"], conversation_id, title=payload["question"][:42])

    request_id = uuid.uuid4().hex
    try:
        with usage_context(
            request_id=request_id,
            user_id=user["id"],
            conversation_id=conversation_id,
            message_id=user_message["id"],
            feature=_usage_feature(payload),
            operation_type="chat_completion",
            metadata={
                "mode": payload["mode"],
                "tool_id": payload["tool_id"],
                "chat_provider": chat_provider,
                "chat_model": chat_model,
            },
        ):
            if payload["tool"]:
                result = run_tool(
                    payload["tool"],
                    payload["tool_params"],
                    payload["question"],
                    document_id=payload["document_id"],
                    asset_ids=payload["asset_ids"],
                    user_id=user["id"],
                    selected_source=payload["document_name"],
                    chat_provider_name=chat_provider,
                    chat_model=chat_model,
                )
            else:
                result = rag.answer_request(
                    payload["search_question"],
                    scope=payload["scope"],
                    document_id=payload["document_id"],
                    asset_ids=payload["asset_ids"],
                    user_id=user["id"],
                    selected_source=payload["document_name"],
                    chat_provider_name=chat_provider,
                    chat_model=chat_model,
                    generation_question=payload["runtime_question"],
                    conversation_history=conversation_history,
                    conversation_id=conversation_id,
                    request_id=request_id,
                )
        generated_output = _create_tool_output(
            user["id"],
            conversation_id,
            payload,
            result.get("answer", ""),
            content_json=result.get("content_json"),
        )
        assistant_message = db.create_conversation_message(
            conversation_id,
            "assistant",
            result.get("answer", ""),
            sources=result.get("sources", []),
            status="complete",
            mode=payload["mode"],
            tool_id=payload["tool_id"],
            tool_title=payload["tool_title"],
            tool_params=payload["tool_params"],
            generated_output_id=generated_output["id"] if generated_output else None,
        )
        db.update_usage_events_context(
            request_id,
            message_id=assistant_message["id"],
            output_id=generated_output["id"] if generated_output else None,
        )
        db.update_compute_usage_events_context(
            request_id,
            user_id=user["id"],
            conversation_id=conversation_id,
            message_id=assistant_message["id"],
            output_id=generated_output["id"] if generated_output else None,
        )
    except Exception:
        db.create_conversation_message(
            conversation_id,
            "assistant",
            "خطا در تولید پاسخ.",
            status="error",
            mode=payload["mode"],
            tool_id=payload["tool_id"],
            tool_title=payload["tool_title"],
            tool_params=payload["tool_params"],
        )
        raise
    result["conversation"] = conversation_to_json(conversation)
    if payload["tool"]:
        result["generated_output"] = generated_output
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
    conversation_history = [
        message_to_json(row)
        for row in db.list_conversation_messages(user_id, conversation_id)[-8:]
    ]

    user_message = db.create_conversation_message(
        conversation_id,
        "user",
        payload["question"],
        tool_id=payload["tool_id"],
        tool_title=payload["tool_title"],
        tool_params=payload["tool_params"],
        mode=payload["mode"],
    )
    if conversation["title"] == "گفتگوی جدید":
        conversation = db.update_conversation(user_id, conversation_id, title=payload["question"][:42])
    assistant_message = db.create_conversation_message(
        conversation_id,
        "assistant",
        "",
        status="streaming",
        stream_status="در حال آماده‌سازی...",
        mode=payload["mode"],
        tool_id=payload["tool_id"],
        tool_title=payload["tool_title"],
        tool_params=payload["tool_params"],
    )
    request_id = uuid.uuid4().hex

    def event_stream():
        answer_text = ""
        final_sources = []
        done_sent = False
        usage_fields = {
            "request_id": request_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": assistant_message["id"],
            "feature": _usage_feature(payload),
            "operation_type": "chat_completion",
            "metadata": {
                "mode": payload["mode"],
                "tool_id": payload["tool_id"],
                "chat_provider": chat_provider,
                "chat_model": chat_model,
                "stream": True,
            },
        }
        try:
            yield json.dumps({
                "type": "conversation",
                "conversation": conversation_to_json(conversation),
                "user_message": message_to_json(user_message),
                "assistant_message": message_to_json(assistant_message),
            }, ensure_ascii=False) + "\n"
            events = (
                run_tool_stream(
                    payload["tool"],
                    payload["tool_params"],
                    payload["question"],
                    document_id=payload["document_id"],
                    asset_ids=payload["asset_ids"],
                    user_id=user_id,
                    selected_source=payload["document_name"],
                    chat_provider_name=chat_provider,
                    chat_model=chat_model,
                )
                if payload["tool"]
                else rag.answer_request_stream(
                    payload["search_question"],
                    scope=payload["scope"],
                    document_id=payload["document_id"],
                    asset_ids=payload["asset_ids"],
                    user_id=user_id,
                    selected_source=payload["document_name"],
                    chat_provider_name=chat_provider,
                    chat_model=chat_model,
                    generation_question=payload["runtime_question"],
                    conversation_history=conversation_history,
                    conversation_id=conversation_id,
                    request_id=request_id,
                )
            )
            iterator = iter(events)
            while True:
                token = set_usage_context(**usage_fields)
                try:
                    event = next(iterator)
                except StopIteration:
                    reset_usage_context(token)
                    break
                except Exception:
                    reset_usage_context(token)
                    raise
                reset_usage_context(token)

                if event.get("type") == "token":
                    answer_text += event.get("delta") or ""
                elif event.get("type") == "final":
                    if not answer_text and event.get("answer"):
                        answer_text = event["answer"]
                    final_sources = event.get("sources") or []
                    generated_output = _create_tool_output(
                        user_id,
                        conversation_id,
                        payload,
                        answer_text,
                        content_json=event.get("content_json"),
                    )
                    if generated_output:
                        event["generated_output"] = generated_output
                    db.update_conversation_message(
                        conversation_id,
                        assistant_message["id"],
                        content=answer_text,
                        sources=final_sources,
                        status="complete",
                        generated_output_id=generated_output["id"] if generated_output else None,
                    )
                    db.update_usage_events_context(
                        request_id,
                        message_id=assistant_message["id"],
                        output_id=generated_output["id"] if generated_output else None,
                    )
                    db.update_compute_usage_events_context(
                        request_id,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_id=assistant_message["id"],
                        output_id=generated_output["id"] if generated_output else None,
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
