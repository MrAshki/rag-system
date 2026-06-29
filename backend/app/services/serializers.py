import json


def _row_get(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def asset_to_json(a) -> dict:
    return {
        "id": a["id"],
        "filename": a["original_filename"],
        "category": a["category"],
        "ext": a["file_ext"],
        "size_bytes": a["size_bytes"],
        "status": a["status"],
        "chunk_count": a["chunk_count"],
        "scan_error": a["scan_error"],
        "warning": a["extraction_warning"],
        "created_at": a["created_at"],
    }


def conversation_to_json(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "chat_provider": row["chat_provider"],
        "chat_model": row["chat_model"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def message_to_json(row) -> dict:
    try:
        sources = json.loads(_row_get(row, "sources_json") or "[]")
    except Exception:
        sources = []
    try:
        tool_params = json.loads(_row_get(row, "tool_params_json") or "{}")
    except Exception:
        tool_params = {}
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "sources": sources,
        "status": row["status"],
        "streamStatus": row["stream_status"],
        "mode": _row_get(row, "mode"),
        "tool_id": _row_get(row, "tool_id"),
        "tool_title": _row_get(row, "tool_title"),
        "tool_params": tool_params,
        "generated_output_id": _row_get(row, "generated_output_id"),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def generated_output_to_json(row) -> dict:
    try:
        content_json = json.loads(_row_get(row, "content_json") or "{}")
    except Exception:
        content_json = {}
    try:
        source_asset_ids = json.loads(_row_get(row, "source_asset_ids_json") or "[]")
    except Exception:
        source_asset_ids = []
    try:
        template_params = json.loads(_row_get(row, "template_params_json") or "{}")
    except Exception:
        template_params = {}
    return {
        "id": row["id"],
        "type": row["type"],
        "title": row["title"],
        "content_json": content_json,
        "content_markdown": row["content_markdown"],
        "source_asset_ids": source_asset_ids,
        "template_id": row["template_id"],
        "template_params": template_params,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def clean_title(value: str) -> str:
    title = (value or "").strip()
    return (title or "گفتگوی جدید")[:160]


def selected_assets_from_payload(user_id: int, data: dict):
    import db

    raw_ids = data.get("asset_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    asset_ids = []
    seen = set()
    for raw_id in raw_ids:
        asset_id = str(raw_id or "").strip()
        if asset_id and asset_id not in seen:
            seen.add(asset_id)
            asset_ids.append(asset_id)

    if not asset_ids:
        return [], [], None

    rows = db.list_assets_by_ids(user_id, asset_ids)
    by_id = {row["id"]: row for row in rows}
    missing = [asset_id for asset_id in asset_ids if asset_id not in by_id]
    if missing:
        return None, None, "برخی منابع انتخاب‌شده پیدا نشدند."

    invalid = [row for row in rows if row["category"] != "text" or row["status"] != "scanned"]
    if invalid:
        return None, None, "فعلاً فقط فایل‌های متنی آماده قابل استفاده در چت هستند."

    selected_rows = [by_id[asset_id] for asset_id in asset_ids]
    selected_names = [row["original_filename"] for row in selected_rows]
    return asset_ids, selected_names, None
