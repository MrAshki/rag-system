"""Background scan worker (in-process, Option A).

A single daemon thread, started by the FastAPI app, drains the `assets` queue: it claims
each 'uploaded' asset and runs the existing text pipeline on it
(normalize -> chunk -> embed/index), flipping its status to 'scanned' (text) or
'stored' (media, which has no pipeline yet), or 'failed' on error.

Why in-process: the whole pipeline (ingest, chunker, rag) and the loaded
embedding model + pgvector store already live in the backend process, so the thread
just calls them directly -- no Redis/Celery/second process. See the plan's
"اسکن پس‌زمینه: دو حالت" section for the trade-offs vs. a separate queue.
"""
import io
import threading

import db
import storage
import rag
from document_pipeline import chunker, document_map, ingest, profiling

# How long the loop sleeps when the queue is empty before re-polling. The upload
# route calls notify() to wake it immediately, so this is just a safety net.
IDLE_POLL_SECONDS = 10.0

_wake = threading.Event()
_thread = None
_started = False
_lock = threading.Lock()


def notify():
    """Wake the worker now (called by the upload route after enqueuing assets)."""
    _wake.set()


def _ocr_failure_message(meta) -> str:
    """A clear, actionable Persian message for when a PDF needed OCR but it
    couldn't run -- shown on the asset's 'failed' badge."""
    status = meta.get("ocr_status")
    err = meta.get("ocr_error") or ""
    if status == "unavailable":
        return ("این PDF لایه‌ی متنیِ سالم ندارد و برای استخراج به OCR نیاز دارد، "
                "ولی موتور OCR در دسترس نیست: " + err)
    if status == "disabled":
        return "این PDF به OCR نیاز دارد ولی OCR غیرفعال است (ENABLE_OCR_FALLBACK=false)."
    if status == "failed":
        return "اجرای OCR روی این PDF ناموفق بود: " + err
    return "استخراج متن این PDF ناموفق بود؛ به OCR نیاز دارد."


def _process_text_asset(asset):
    """Run the full text pipeline for one asset and mark it scanned/failed."""
    asset_id = asset["id"]
    user_id = asset["user_id"]
    ext = asset["file_ext"]
    filename = asset["original_filename"]

    with open(asset["original_path"], "rb") as f:
        raw_bytes = f.read()

    # OCR (if needed) renders page images into the asset's own ocr/ folder.
    ocr_artifact_dir = storage.ocr_dir(user_id, "text", asset_id)
    normalized = ingest.normalize_document(
        filename, io.BytesIO(raw_bytes), ext, ocr_artifact_dir=ocr_artifact_dir,
    )
    meta = normalized["meta"]
    markdown_text = normalized["markdown_text"]

    profile = profiling.profile_document(markdown_text, meta, filename=filename)

    # If the PDF's text layer was garbled/missing, OCR was required. When OCR
    # didn't actually run (backend missing, disabled, or it errored), refuse to
    # index the bad text -- fail with a clear message instead of storing mojibake.
    if meta.get("ocr_required") and meta.get(
        "ocr_blocking",
        meta.get("ocr_status") != "applied",
    ):
        db.update_asset_status(asset_id, "failed", scan_error=_ocr_failure_message(meta))
        return

    if not markdown_text.strip():
        db.update_asset_status(
            asset_id, "failed",
            scan_error="متنی از فایل استخراج نشد (ممکن است اسکن‌شده باشد).",
        )
        return

    if not profile.quality.indexable:
        db.update_asset_status(
            asset_id,
            "failed",
            scan_error="کیفیت متن استخراج‌شده برای جست‌وجوی قابل اعتماد کافی نیست.",
            document_profile=profile.to_dict(),
            quality_status=profile.quality.status,
            quality_score=profile.quality.score,
            content_hash=profile.content_hash,
        )
        return

    md_path = storage.normalized_md_path(user_id, "text", asset_id)
    map_path = storage.document_map_path(user_id, "text", asset_id)
    doc_map = document_map.build_document_map(markdown_text, profile)
    metadata = {
        "document_id": asset_id,
        "original_filename": filename,
        "source_file_type": ext.lstrip("."),
        "original_upload_path": asset["original_path"],
        "normalized_md_path": md_path,
        "user_id": user_id,
        "created_at": ingest.now_iso(),
        "normalization_version": ingest.NORMALIZATION_VERSION,
        "document_profile": profile.to_dict(),
        "document_map_path": map_path,
        **meta,
    }
    ingest.write_normalized(user_id, asset_id, markdown_text, metadata, category="text")
    document_map.write_document_map(map_path, doc_map)

    chunks = chunker.parse_markdown_to_chunks(markdown_text)
    document_map.assign_chunks_to_units(chunks, doc_map)
    result = rag.index_chunks(
        filename=filename,
        chunks=chunks,
        document_id=asset_id,
        user_id=user_id,
        source_file_type=ext.lstrip("."),
        normalized_md_path=md_path,
        document_language=profile.language,
    )

    db.update_asset_status(
        asset_id, "scanned",
        chunk_count=result["chunks"],
        normalized_md_path=md_path,
        extraction_warning=meta.get("extraction_quality_warning"),
        document_profile=profile.to_dict(),
        document_map_path=map_path,
        processing_version=f"{ingest.NORMALIZATION_VERSION}:{profile.version}:{doc_map['version']}",
        content_hash=profile.content_hash,
        quality_status=profile.quality.status,
        quality_score=profile.quality.score,
        set_scanned_at=True,
    )


def process_asset(asset):
    """Process one claimed asset (already flipped to 'scanning'). Text assets go
    through the pipeline; media is just marked 'stored' (no pipeline yet)."""
    asset_id = asset["id"]
    try:
        if storage.is_processable(asset["category"]):
            _process_text_asset(asset)
        else:
            # image / audio / video: stored verbatim, awaiting a future pipeline.
            db.update_asset_status(asset_id, "stored", set_scanned_at=True)
    except Exception as e:  # noqa: BLE001 -- never let one bad file kill the worker
        print(f"[scan_worker] asset {asset_id} failed: {e}", flush=True)
        try:
            removed = rag.delete_document_index(asset_id, user_id=asset.get("user_id"))
            if removed:
                print(f"[scan_worker] removed {removed} indexed chunk(s) for failed asset {asset_id}", flush=True)
        except Exception as e2:  # noqa: BLE001
            print(f"[scan_worker] could not clean vector index for failed asset {asset_id}: {e2}", flush=True)
        try:
            db.update_asset_status(asset_id, "failed", scan_error=str(e))
        except Exception as e2:  # noqa: BLE001
            print(f"[scan_worker] could not mark asset {asset_id} failed: {e2}", flush=True)


def _run_loop():
    print("[scan_worker] started", flush=True)
    while True:
        try:
            asset = db.claim_next_uploaded_asset()
        except Exception as e:  # noqa: BLE001 -- DB hiccup: back off and retry
            print(f"[scan_worker] claim error: {e}", flush=True)
            _wake.wait(timeout=IDLE_POLL_SECONDS)
            _wake.clear()
            continue
        if asset is None:
            # Queue empty: sleep until notify() or the idle timeout, then re-poll.
            _wake.wait(timeout=IDLE_POLL_SECONDS)
            _wake.clear()
            continue
        print(f"[scan_worker] scanning asset {asset['id']} "
              f"({asset['category']}, {asset['original_filename']})", flush=True)
        process_asset(asset)


def start():
    """Idempotently start the worker thread and requeue any 'scanning' assets
    stranded by a previous crash/restart. Call once after db.init_db()."""
    global _thread, _started
    with _lock:
        if _started:
            return
        _started = True
    try:
        requeued = db.requeue_stuck_scanning()
        if requeued:
            print(f"[scan_worker] requeued {requeued} stuck 'scanning' asset(s)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[scan_worker] requeue on startup failed: {e}", flush=True)
    _thread = threading.Thread(target=_run_loop, name="scan-worker", daemon=True)
    _thread.start()
