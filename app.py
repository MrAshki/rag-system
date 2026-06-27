import os
import json
import uuid
from datetime import datetime, date
from flask import Flask, request, jsonify, redirect, session, Response, stream_with_context
from flask.json.provider import DefaultJSONProvider

import rag
import db
import auth
import storage
import scan_worker
import payments
from ratelimit import rate_limited


class ISOJSONProvider(DefaultJSONProvider):
    """Serialize datetime/date as ISO 8601 (YYYY-MM-DD...) so the frontend's
    date handling (e.g. .slice(0,10)) works consistently."""
    def default(self, o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
MAX_UPLOAD_MB = 25


def fa_number(n: int) -> str:
    return str(n).translate(PERSIAN_DIGITS)


db.init_db()

app = Flask(__name__, static_folder="webapp", static_url_path="")
app.json = ISOJSONProvider(app)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY is not set. Add a long random value to .env before running "
        "(e.g. python -c \"import secrets; print(secrets.token_hex(32))\")."
    )
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Only require HTTPS-only cookies once actually served over HTTPS (set PUBLIC_BASE_URL
# to an https:// URL in production). Forcing this on for local http testing would
# break login entirely.
app.config["SESSION_COOKIE_SECURE"] = os.getenv("PUBLIC_BASE_URL", "").startswith("https://")

# Start the background scan worker exactly once, at import time, so it runs no
# matter how the app is launched -- `python app.py` (dev) OR `python serve.py`
# (waitress/production), since serve.py just imports `app` and never hits this
# file's __main__ block. start() is idempotent. Under the Werkzeug debug reloader
# the parent process re-execs itself and only the child (WERKZEUG_RUN_MAIN=="true")
# serves requests, so in debug mode we start the worker only in that child to
# avoid two workers racing on the same queue.
_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
if not _DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    scan_worker.start()


# ---------------------------------------------------------------------------
# Static pages
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    """Unauthenticated, non-sensitive: lets us confirm which answer-prompt version a
    running server actually loaded (a stale server keeps old code until restarted)."""
    return jsonify({
        "status": "ok",
        "answer_prompt_version": rag.ANSWER_PROMPT_VERSION,
        "chat_provider": rag.CHAT_PROVIDER.name,
        "chat_model": rag.CHAT_PROVIDER.model,
        "ollama_model": rag.OLLAMA_MODEL,
        "ollama_num_ctx": rag.OLLAMA_NUM_CTX,
        "embedding_model": rag.EMBEDDING_MODEL,
        "reranker_enabled": rag.ENABLE_RERANKER,
        "reranker_model": rag.RERANKER_MODEL,
        "retrieve_k": rag.RETRIEVE_K,
        "rerank_top_k": rag.RERANK_TOP_K,
        "indexed_chunks": rag.collection.count(),
    })


@app.route("/api/chat/models", methods=["GET"])
@auth.login_required
def chat_models():
    return jsonify({"models": rag.chat_model_options()})


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/login.html")
def login_page():
    return app.send_static_file("login.html")


@app.route("/register.html")
def register_page():
    return app.send_static_file("register.html")


@app.route("/profile.html")
def profile_page():
    return app.send_static_file("profile.html")


@app.route("/admin.html")
def admin_page():
    return app.send_static_file("admin.html")


@app.route("/gallery.html")
def gallery_page():
    return app.send_static_file("gallery.html")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route("/api/auth/request-otp", methods=["POST"])
@rate_limited(lambda: f"otp:{request.remote_addr}", min_interval_seconds=2, max_per_window=10, window_seconds=600)
def auth_request_otp():
    data = request.get_json(silent=True) or {}
    phone = auth.normalize_phone(data.get("phone", ""))
    ok, error = auth.request_otp(phone)
    if not ok:
        return jsonify({"error": error}), 400
    return jsonify({"status": "ok"})


@app.route("/api/auth/verify-otp", methods=["POST"])
def auth_verify_otp():
    data = request.get_json(silent=True) or {}
    phone = auth.normalize_phone(data.get("phone", ""))
    code = (data.get("code") or "").strip()
    ok, error = auth.verify_otp_and_login(phone, code)
    if not ok:
        return jsonify({"error": error}), 400
    user = auth.current_user()
    return jsonify({"status": "ok", "is_admin": bool(user["is_admin"])})


@app.route("/api/auth/register/send-otp", methods=["POST"])
@rate_limited(lambda: f"otp:{request.remote_addr}", min_interval_seconds=2, max_per_window=10, window_seconds=600)
def auth_register_send_otp():
    """Send the registration SMS code. Same OTP machinery as login, but rejects a
    phone that already has a finished account so people don't accidentally try to
    re-register instead of logging in."""
    data = request.get_json(silent=True) or {}
    phone = auth.normalize_phone(data.get("phone", ""))
    existing = db.get_user_by_phone(phone) if auth.is_valid_phone(phone) else None
    if existing and existing["password_hash"]:
        return jsonify({"error": "این شماره قبلاً ثبت‌نام کرده است. لطفاً وارد شوید."}), 400
    ok, error = auth.request_otp(phone)
    if not ok:
        return jsonify({"error": error}), 400
    return jsonify({"status": "ok"})


@app.route("/api/auth/register/verify-otp", methods=["POST"])
def auth_register_verify_otp():
    data = request.get_json(silent=True) or {}
    phone = auth.normalize_phone(data.get("phone", ""))
    code = (data.get("code") or "").strip()
    ok, error = auth.verify_registration_otp(phone, code)
    if not ok:
        return jsonify({"error": error}), 400
    return jsonify({"status": "ok"})


@app.route("/api/auth/register/complete", methods=["POST"])
def auth_register_complete():
    data = request.get_json(silent=True) or {}
    phone = auth.normalize_phone(data.get("phone", ""))
    user, error = auth.complete_registration(
        phone,
        data.get("first_name"),
        data.get("last_name"),
        data.get("email"),
        auth.parse_iso_date(data.get("birth_date")),
        data.get("password"),
    )
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"status": "ok", "is_admin": bool(user["is_admin"])})


@app.route("/api/auth/login-email", methods=["POST"])
@rate_limited(lambda: f"login-email:{request.remote_addr}", min_interval_seconds=1, max_per_window=20, window_seconds=600)
def auth_login_email():
    data = request.get_json(silent=True) or {}
    ok, error = auth.login_with_email(data.get("email", ""), data.get("password", ""))
    if not ok:
        return jsonify({"error": error}), 400
    user = auth.current_user()
    return jsonify({"status": "ok", "is_admin": bool(user["is_admin"])})


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"status": "ok"})


@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    user = auth.current_user()
    if not user:
        return jsonify({"logged_in": False})
    sub = db.get_active_subscription(user["id"])
    full_name = " ".join(p for p in (user["first_name"], user["last_name"]) if p).strip()
    return jsonify({
        "logged_in": True,
        "phone": user["phone"],
        "name": full_name or None,
        "is_admin": bool(user["is_admin"]),
        "has_subscription": bool(user["is_admin"] or sub),
        "subscription_expires_at": sub["expires_at"] if sub else None,
    })


# ---------------------------------------------------------------------------
# Profile (self-service account page)
# ---------------------------------------------------------------------------

@app.route("/api/profile", methods=["GET"])
@auth.login_required
def get_profile():
    user = auth.current_user()
    return jsonify({
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "email": user["email"],
        "phone": user["phone"],
        "birth_date": user["birth_date"],   # ISO date via ISOJSONProvider, or null
        "created_at": user["created_at"],
        "has_password": bool(user["password_hash"]),
    })


@app.route("/api/profile", methods=["POST"])
@auth.login_required
def update_profile():
    user = auth.current_user()
    data = request.get_json(silent=True) or {}
    ok, error = auth.update_profile(
        user["id"],
        data.get("first_name"),
        data.get("last_name"),
        data.get("email"),
        auth.parse_iso_date(data.get("birth_date")),
        data.get("password"),
    )
    if not ok:
        return jsonify({"error": error}), 400
    return jsonify({"status": "ok"})


@app.route("/api/profile/payments", methods=["GET"])
@auth.login_required
def profile_payments():
    user = auth.current_user()
    rows = db.list_payments_for_user(user["id"])
    return jsonify({"payments": [dict(p) for p in rows]})


# ---------------------------------------------------------------------------
# Plans & payment
# ---------------------------------------------------------------------------

@app.route("/api/plans", methods=["GET"])
def get_plans():
    plans = db.list_active_plans()
    return jsonify({"plans": [dict(p) for p in plans]})


@app.route("/api/subscribe", methods=["POST"])
@auth.login_required
def subscribe():
    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan_id")
    plan = db.get_plan(plan_id) if plan_id else None
    if not plan:
        return jsonify({"error": "پلن نامعتبر است"}), 400

    user = auth.current_user()
    payment_id = db.create_payment(user["id"], plan["id"], plan["price_toman"])

    base_url = os.getenv("PUBLIC_BASE_URL", request.url_root.rstrip("/"))
    callback_url = f"{base_url}/api/payment/callback?payment_id={payment_id}"

    try:
        authority = payments.request_payment(
            amount_toman=plan["price_toman"],
            callback_url=callback_url,
            description=f"خرید {plan['name']}",
            mobile=user["phone"],
        )
    except payments.PaymentError as e:
        db.mark_payment_failed(payment_id)
        return jsonify({"error": str(e)}), 502

    db.set_payment_authority(payment_id, authority)
    return jsonify({"redirect_url": payments.get_startpay_url(authority)})


@app.route("/api/payment/callback", methods=["GET"])
def payment_callback():
    payment_id = request.args.get("payment_id")
    authority = request.args.get("Authority")
    status = request.args.get("Status")

    payment = None
    try:
        payment = db.get_payment_by_authority(authority) if authority else None
    except Exception:
        payment = None

    if not payment or str(payment["id"]) != str(payment_id) or status != "OK":
        if payment:
            db.mark_payment_failed(payment["id"])
        return redirect("/?payment=failed")

    try:
        payments.verify_payment(authority, payment["amount_toman"])
    except payments.PaymentError:
        db.mark_payment_failed(payment["id"])
        return redirect("/?payment=failed")

    plan = db.get_plan(payment["plan_id"])
    db.mark_payment_paid(payment["id"], ref_id=authority)
    db.create_subscription(payment["user_id"], plan["id"], plan["duration_days"])
    return redirect("/?payment=success")


# ---------------------------------------------------------------------------
# Documents / RAG (scoped per logged-in user)
# ---------------------------------------------------------------------------

@app.route("/api/documents", methods=["GET"])
@auth.login_required
def list_documents():
    """Documents available to the Q&A tool: the user's text assets that have
    finished scanning. Backed by the assets registry (single source of truth)
    rather than scraping Chroma metadata; asset id == Chroma document_id."""
    user = auth.current_user()
    docs = [
        {"document_id": a["id"], "source": a["original_filename"]}
        for a in db.list_assets(user["id"], category="text", status="scanned")
    ]
    return jsonify({"documents": docs})


# ---------------------------------------------------------------------------
# Gallery (per-user file store + async scan)
# ---------------------------------------------------------------------------

def _asset_to_json(a) -> dict:
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


def _conversation_to_json(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "chat_provider": row["chat_provider"],
        "chat_model": row["chat_model"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def _message_to_json(row) -> dict:
    try:
        sources = json.loads(row["sources_json"] or "[]")
    except Exception:
        sources = []
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "sources": sources,
        "status": row["status"],
        "streamStatus": row["stream_status"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def _clean_title(value: str) -> str:
    title = (value or "").strip()
    return (title or "گفتگوی جدید")[:160]


def _selected_assets_from_request(user_id: int, data: dict):
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

    invalid = [
        row for row in rows
        if row["category"] != "text" or row["status"] != "scanned"
    ]
    if invalid:
        return None, None, "فعلاً فقط فایل‌های متنی آماده قابل استفاده در چت هستند."

    selected_rows = [by_id[asset_id] for asset_id in asset_ids]
    selected_names = [row["original_filename"] for row in selected_rows]
    return asset_ids, selected_names, None


def _ask_rate_key() -> str:
    data = request.get_json(silent=True) or {}
    conversation_id = data.get("conversation_id") or "new"
    return f"ask:{session.get('user_id')}:{conversation_id}"


@app.route("/api/gallery/upload", methods=["POST"])
@auth.subscription_required
@rate_limited(lambda: f"upload:{session.get('user_id')}", min_interval_seconds=3, max_per_window=20, window_seconds=600)
def gallery_upload():
    """Accept one or more files (drag-drop), store each under the user's
    per-category folder, register it as an asset, and hand off to the background
    scan worker. Returns immediately; the actual normalize/index happens async."""
    user = auth.current_user()
    files = request.files.getlist("files")
    if not files:
        single = request.files.get("file")  # Q&A dropzone sends a single 'file'
        if single:
            files = [single]
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({"error": "فایلی انتخاب نشده است"}), 400

    created, rejected = [], []
    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        category = storage.category_for_ext(ext)
        if not category:
            rejected.append({"filename": file.filename, "error": "این فرمت پشتیبانی نمی‌شود"})
            continue
        raw_bytes = file.stream.read()
        if not raw_bytes:
            rejected.append({"filename": file.filename, "error": "فایل خالی است"})
            continue

        asset_id = uuid.uuid4().hex
        dest = storage.original_path(user["id"], category, asset_id, ext)
        with open(dest, "wb") as f:
            f.write(raw_bytes)
        db.create_asset(
            asset_id=asset_id,
            user_id=user["id"],
            category=category,
            original_filename=file.filename,
            file_ext=ext,
            size_bytes=len(raw_bytes),
            original_path=dest,
            status="uploaded",
        )
        created.append({"id": asset_id, "filename": file.filename,
                        "category": category, "status": "uploaded"})

    if created:
        scan_worker.notify()  # wake the worker so it starts scanning right away
    return jsonify({"created": created, "rejected": rejected}), (200 if created else 400)


@app.route("/api/gallery/assets", methods=["GET"])
@auth.subscription_required
def gallery_assets():
    """List the user's assets (optionally filtered by ?category=) plus per-category
    counts for the sidebar. Polled by the gallery UI to track scan progress."""
    user = auth.current_user()
    category = request.args.get("category") or None
    if category in ("all", ""):
        category = None

    all_rows = db.list_assets(user["id"])
    counts = {}
    for a in all_rows:
        counts[a["category"]] = counts.get(a["category"], 0) + 1
    rows = all_rows if category is None else [a for a in all_rows if a["category"] == category]
    return jsonify({
        "assets": [_asset_to_json(a) for a in rows],
        "counts": counts,
        "total": len(all_rows),
    })


@app.route("/api/conversations", methods=["GET"])
@auth.subscription_required
def conversations_list():
    user = auth.current_user()
    rows = db.list_conversations(user["id"])
    return jsonify({"conversations": [_conversation_to_json(row) for row in rows]})


@app.route("/api/conversations", methods=["POST"])
@auth.subscription_required
def conversations_create():
    user = auth.current_user()
    data = request.get_json(silent=True) or {}
    conversation = db.create_conversation(
        user["id"],
        title=_clean_title(data.get("title")),
        chat_provider=data.get("chat_provider"),
        chat_model=data.get("chat_model"),
    )
    return jsonify({"conversation": _conversation_to_json(conversation)}), 201


@app.route("/api/conversations/<conversation_id>", methods=["PATCH"])
@auth.subscription_required
def conversations_update(conversation_id):
    user = auth.current_user()
    data = request.get_json(silent=True) or {}
    conversation = db.get_conversation(user["id"], conversation_id)
    if not conversation:
        return jsonify({"error": "گفتگو پیدا نشد"}), 404

    updated = db.update_conversation(
        user["id"],
        conversation_id,
        title=_clean_title(data.get("title")) if "title" in data else None,
        chat_provider=data.get("chat_provider") if "chat_provider" in data else None,
        chat_model=data.get("chat_model") if "chat_model" in data else None,
    )
    return jsonify({"conversation": _conversation_to_json(updated)})


@app.route("/api/conversations/<conversation_id>", methods=["DELETE"])
@auth.subscription_required
def conversations_delete(conversation_id):
    user = auth.current_user()
    if not db.delete_conversation(user["id"], conversation_id):
        return jsonify({"error": "گفتگو پیدا نشد"}), 404
    return jsonify({"status": "ok"})


@app.route("/api/conversations/<conversation_id>/messages", methods=["GET"])
@auth.subscription_required
def conversations_messages(conversation_id):
    user = auth.current_user()
    conversation = db.get_conversation(user["id"], conversation_id)
    if not conversation:
        return jsonify({"error": "گفتگو پیدا نشد"}), 404
    rows = db.list_conversation_messages(user["id"], conversation_id)
    return jsonify({
        "conversation": _conversation_to_json(conversation),
        "messages": [_message_to_json(row) for row in rows],
    })


@app.route("/api/ask", methods=["POST"])
@auth.subscription_required
@rate_limited(_ask_rate_key, min_interval_seconds=1, max_per_window=60, window_seconds=600)
def ask():
    user = auth.current_user()
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    scope = data.get("scope", "all")
    document_id = data.get("document_id")
    document_name = data.get("document_name")
    chat_provider = data.get("chat_provider")
    chat_model = data.get("chat_model")
    conversation_id = data.get("conversation_id")
    asset_ids, selected_asset_names, asset_error = _selected_assets_from_request(user["id"], data)

    if not question:
        return jsonify({"error": "سوال خالی است"}), 400
    if asset_error:
        return jsonify({"error": asset_error}), 400
    if scope == "selected" and not document_id and not asset_ids:
        return jsonify({"error": "برای این حالت باید یک سند انتخاب شود"}), 400
    if asset_ids:
        scope = "selected"
        document_id = None
        document_name = "، ".join(selected_asset_names)

    conversation = None
    if conversation_id:
        conversation = db.get_conversation(user["id"], conversation_id)
        if not conversation:
            return jsonify({"error": "گفتگو پیدا نشد"}), 404
        if chat_provider or chat_model:
            conversation = db.update_conversation(
                user["id"], conversation_id,
                chat_provider=chat_provider or conversation["chat_provider"],
                chat_model=chat_model or conversation["chat_model"],
            )
        chat_provider = chat_provider or conversation["chat_provider"]
        chat_model = chat_model or conversation["chat_model"]
    else:
        conversation = db.create_conversation(
            user["id"],
            chat_provider=chat_provider,
            chat_model=chat_model,
        )
        conversation_id = conversation["id"]

    db.create_conversation_message(conversation_id, "user", question)
    if conversation["title"] == "گفتگوی جدید":
        conversation = db.update_conversation(user["id"], conversation_id, title=question[:42])

    # The full pipeline (understand the message -> per-question retrieve -> grounded
    # answer -> assemble) lives in rag.answer_request, so the web path and the offline
    # quality tests exercise exactly the same code. Semantic query understanding
    # replaced the old punctuation-based split_questions().
    try:
        result = rag.answer_request(
            question,
            scope=scope,
            document_id=document_id,
            asset_ids=asset_ids,
            user_id=user["id"],
            selected_source=document_name,
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
    result["conversation"] = _conversation_to_json(conversation)
    return jsonify(result)


@app.route("/api/ask/stream", methods=["POST"])
@auth.subscription_required
@rate_limited(_ask_rate_key, min_interval_seconds=1, max_per_window=60, window_seconds=600)
def ask_stream():
    user = auth.current_user()
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    scope = data.get("scope", "all")
    document_id = data.get("document_id")
    document_name = data.get("document_name")
    chat_provider = data.get("chat_provider")
    chat_model = data.get("chat_model")
    conversation_id = data.get("conversation_id")
    asset_ids, selected_asset_names, asset_error = _selected_assets_from_request(user["id"], data)

    if not question:
        return jsonify({"error": "سوال خالی است"}), 400
    if asset_error:
        return jsonify({"error": asset_error}), 400
    if scope == "selected" and not document_id and not asset_ids:
        return jsonify({"error": "برای این حالت باید یک سند انتخاب شود"}), 400
    if asset_ids:
        scope = "selected"
        document_id = None
        document_name = "، ".join(selected_asset_names)

    user_id = user["id"]
    if conversation_id:
        conversation = db.get_conversation(user_id, conversation_id)
        if not conversation:
            return jsonify({"error": "گفتگو پیدا نشد"}), 404
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

    user_message = db.create_conversation_message(conversation_id, "user", question)
    if conversation["title"] == "گفتگوی جدید":
        conversation = db.update_conversation(user_id, conversation_id, title=question[:42])
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
        client_closed = False
        try:
            yield json.dumps({
                "type": "conversation",
                "conversation": _conversation_to_json(conversation),
                "user_message": _message_to_json(user_message),
                "assistant_message": _message_to_json(assistant_message),
            }, ensure_ascii=False) + "\n"
            for event in rag.answer_request_stream(
                question,
                scope=scope,
                document_id=document_id,
                asset_ids=asset_ids,
                user_id=user_id,
                selected_source=document_name,
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
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except GeneratorExit:
            client_closed = True
            raise
        except Exception as e:
            print(f"ask_stream: unhandled error ({e})", flush=True)
            db.update_conversation_message(
                conversation_id,
                assistant_message["id"],
                content="خطا در تولید پاسخ.",
                status="error",
            )
            yield json.dumps(
                {"type": "error", "error": "خطا در تولید پاسخ."},
                ensure_ascii=False,
            ) + "\n"
        finally:
            if answer_text:
                db.update_conversation_message(
                    conversation_id,
                    assistant_message["id"],
                    content=answer_text,
                    sources=final_sources,
                    status="complete",
                )
            if not client_closed:
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

    return Response(
        stream_with_context(event_stream()),
        content_type="application/x-ndjson; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@app.route("/api/admin/users", methods=["GET"])
@auth.admin_required
def admin_users():
    users = [dict(u) for u in db.list_users()]
    for u in users:
        sub = db.get_active_subscription(u["id"])
        u["has_subscription"] = bool(sub)
        u["subscription_expires_at"] = sub["expires_at"] if sub else None
    return jsonify({"users": users})


@app.route("/api/admin/grant", methods=["POST"])
@auth.admin_required
def admin_grant():
    data = request.get_json(silent=True) or {}
    phone = auth.normalize_phone(data.get("phone", ""))
    plan_id = data.get("plan_id")
    plan = db.get_plan(plan_id) if plan_id else None
    if not auth.is_valid_phone(phone) or not plan:
        return jsonify({"error": "ورودی نامعتبر است"}), 400
    user = db.get_or_create_user(phone)
    db.create_subscription(user["id"], plan["id"], plan["duration_days"])
    return jsonify({"status": "ok"})


@app.route("/api/admin/subscriptions", methods=["GET"])
@auth.admin_required
def admin_subscriptions():
    return jsonify({"subscriptions": [dict(s) for s in db.list_subscriptions_for_admin()]})


@app.route("/api/admin/revoke", methods=["POST"])
@auth.admin_required
def admin_revoke():
    data = request.get_json(silent=True) or {}
    subscription_id = data.get("subscription_id")
    if not subscription_id:
        return jsonify({"error": "ورودی نامعتبر است"}), 400
    db.revoke_subscription(subscription_id)
    return jsonify({"status": "ok"})


@app.route("/api/admin/payments", methods=["GET"])
@auth.admin_required
def admin_payments():
    return jsonify({"payments": [dict(p) for p in db.list_payments_for_admin()]})


@app.route("/api/admin/stats", methods=["GET"])
@auth.admin_required
def admin_stats():
    users = db.list_users()
    active_subs = sum(1 for u in users if db.get_active_subscription(u["id"]))
    return jsonify({
        "total_users": len(users),
        "active_subscriptions": active_subs,
    })


if __name__ == "__main__":
    # The scan worker is already started at import time above (so serve.py gets it
    # too); here we just run the dev server.
    app.run(debug=_DEBUG, port=5000)
