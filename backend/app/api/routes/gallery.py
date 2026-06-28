import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse

import db
import scan_worker
import storage
from backend.app.api.responses import error_response
from backend.app.dependencies import require_login, require_subscription
from backend.app.services.serializers import asset_to_json

router = APIRouter()


@router.get("/api/documents")
def list_documents(user=Depends(require_login)):
    docs = [
        {"document_id": a["id"], "source": a["original_filename"]}
        for a in db.list_assets(user["id"], category="text", status="scanned")
    ]
    return {"documents": docs}


@router.post("/api/gallery/upload")
async def gallery_upload(
    files: Optional[List[UploadFile]] = File(default=None),
    file: Optional[UploadFile] = File(default=None),
    user=Depends(require_subscription),
):
    incoming = list(files or [])
    if file:
        incoming.append(file)
    incoming = [f for f in incoming if f and f.filename]
    if not incoming:
        return error_response("فایلی انتخاب نشده است")

    created, rejected = [], []
    for upload in incoming:
        ext = os.path.splitext(upload.filename)[1].lower()
        category = storage.category_for_ext(ext)
        if not category:
            rejected.append({"filename": upload.filename, "error": "این فرمت پشتیبانی نمی‌شود"})
            continue
        raw_bytes = await upload.read()
        if not raw_bytes:
            rejected.append({"filename": upload.filename, "error": "فایل خالی است"})
            continue

        asset_id = uuid.uuid4().hex
        dest = storage.original_path(user["id"], category, asset_id, ext)
        with open(dest, "wb") as f:
            f.write(raw_bytes)
        db.create_asset(
            asset_id=asset_id,
            user_id=user["id"],
            category=category,
            original_filename=upload.filename,
            file_ext=ext,
            size_bytes=len(raw_bytes),
            original_path=dest,
            status="uploaded",
        )
        created.append({
            "id": asset_id,
            "filename": upload.filename,
            "category": category,
            "status": "uploaded",
        })

    if created:
        scan_worker.notify()
    return JSONResponse(
        {"created": created, "rejected": rejected},
        status_code=200 if created else 400,
    )


@router.get("/api/gallery/assets")
def gallery_assets(category: str = None, user=Depends(require_subscription)):
    if category in ("all", ""):
        category = None

    all_rows = db.list_assets(user["id"])
    counts = {}
    for a in all_rows:
        counts[a["category"]] = counts.get(a["category"], 0) + 1
    rows = all_rows if category is None else [a for a in all_rows if a["category"] == category]
    return {
        "assets": [asset_to_json(a) for a in rows],
        "counts": counts,
        "total": len(all_rows),
    }
