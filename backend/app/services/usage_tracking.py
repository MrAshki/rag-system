from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


_usage_context = ContextVar("usage_context", default={})


@contextmanager
def usage_context(**fields):
    current = dict(_usage_context.get() or {})
    metadata = dict(current.get("metadata") or {})
    metadata.update(fields.pop("metadata", {}) or {})
    next_context = {
        **current,
        **{key: value for key, value in fields.items() if value is not None},
    }
    if metadata:
        next_context["metadata"] = metadata
    token = _usage_context.set(next_context)
    try:
        yield
    finally:
        _usage_context.reset(token)


def current_usage_context() -> dict[str, Any]:
    return dict(_usage_context.get() or {})


def estimate_tokens_from_text(text: str) -> int:
    text = text or ""
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def estimate_tokens_from_messages(messages: list[dict]) -> int:
    # Conservative fallback only. LiteLLM should normally return provider usage.
    return sum(estimate_tokens_from_text(message.get("content") or "") for message in messages or [])


def record_usage_event(
    *,
    feature: str = None,
    operation_type: str = None,
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    estimated_cost_usd=0,
    latency_ms: int = None,
    status: str = "success",
    error_type: str = None,
    metadata: dict[str, Any] | None = None,
):
    context = current_usage_context()
    event_metadata = dict(context.get("metadata") or {})
    event_metadata.update(metadata or {})

    try:
        import db

        return db.create_usage_event(
            request_id=context.get("request_id"),
            user_id=context.get("user_id"),
            conversation_id=context.get("conversation_id"),
            message_id=context.get("message_id"),
            tool_run_id=context.get("tool_run_id"),
            output_id=context.get("output_id"),
            feature=feature or context.get("feature") or "unknown",
            operation_type=operation_type or context.get("operation_type") or "chat_completion",
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd or 0,
            latency_ms=latency_ms,
            status=status,
            error_type=error_type,
            metadata=event_metadata,
        )
    except Exception as exc:  # noqa: BLE001 - usage logging must never break chat.
        print(f"[usage] failed to record usage event: {exc}", flush=True)
        return None


def record_compute_usage_event(
    *,
    feature: str = None,
    operation_type: str,
    provider: str,
    model: str = None,
    device: str = None,
    latency_ms: int = None,
    input_count: int = 0,
    input_chars: int = 0,
    chunk_count: int = 0,
    pair_count: int = 0,
    query_count: int = 0,
    batch_size: int = 0,
    status: str = "success",
    error_type: str = None,
    metadata: dict[str, Any] | None = None,
):
    context = current_usage_context()
    event_metadata = dict(context.get("metadata") or {})
    event_metadata.update(metadata or {})

    try:
        import db

        return db.create_compute_usage_event(
            request_id=context.get("request_id"),
            user_id=context.get("user_id"),
            conversation_id=context.get("conversation_id"),
            message_id=context.get("message_id"),
            output_id=context.get("output_id"),
            feature=feature or context.get("feature") or "unknown",
            operation_type=operation_type,
            provider=provider,
            model=model,
            device=device,
            latency_ms=latency_ms,
            input_count=input_count,
            input_chars=input_chars,
            chunk_count=chunk_count,
            pair_count=pair_count,
            query_count=query_count,
            batch_size=batch_size,
            status=status,
            error_type=error_type,
            metadata=event_metadata,
        )
    except Exception as exc:  # noqa: BLE001 - compute logging must never break work.
        print(f"[usage] failed to record compute usage event: {exc}", flush=True)
        return None
