import io
import os
import uuid
from datetime import datetime, date
from flask import Flask, request, jsonify, redirect, session
from flask.json.provider import DefaultJSONProvider

import rag
import db
import auth
from document_pipeline import ingest, chunker
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
ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}
MAX_UPLOAD_MB = 25


def fa_number(n: int) -> str:
    return str(n).translate(PERSIAN_DIGITS)


DOCS_DIR = "./docs"
os.makedirs(DOCS_DIR, exist_ok=True)

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
        "ollama_model": rag.OLLAMA_MODEL,
        "ollama_num_ctx": rag.OLLAMA_NUM_CTX,
        "embedding_model": rag.EMBEDDING_MODEL,
        "reranker_enabled": rag.ENABLE_RERANKER,
        "reranker_model": rag.RERANKER_MODEL,
        "retrieve_k": rag.RETRIEVE_K,
        "rerank_top_k": rag.RERANK_TOP_K,
        "indexed_chunks": rag.collection.count(),
    })


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/login.html")
def login_page():
    return app.send_static_file("login.html")


@app.route("/admin.html")
def admin_page():
    return app.send_static_file("admin.html")


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
    return jsonify({
        "logged_in": True,
        "phone": user["phone"],
        "is_admin": bool(user["is_admin"]),
        "has_subscription": bool(user["is_admin"] or sub),
        "subscription_expires_at": sub["expires_at"] if sub else None,
    })


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
    user = auth.current_user()
    return jsonify({"documents": rag.list_documents(user_id=user["id"])})


@app.route("/api/upload", methods=["POST"])
@auth.subscription_required
@rate_limited(lambda: f"upload:{session.get('user_id')}", min_interval_seconds=3, max_per_window=20, window_seconds=600)
def upload():
    user = auth.current_user()
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "فایلی انتخاب نشده است"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": "فقط فایل‌های .txt، .pdf و .docx پشتیبانی می‌شوند"}), 400

    raw_bytes = file.stream.read()
    if not raw_bytes:
        return jsonify({"error": "فایلی انتخاب نشده است"}), 400

    document_id = uuid.uuid4().hex

    # Keep the original upload safely, alongside the normalized Markdown derived from it.
    original_path = os.path.join(DOCS_DIR, f"{document_id}{ext}")
    with open(original_path, "wb") as f:
        f.write(raw_bytes)

    try:
        normalized = ingest.normalize_document(file.filename, io.BytesIO(raw_bytes), ext)
    except Exception as e:
        return jsonify({"error": f"خطا در استخراج متن از فایل: {str(e)}"}), 400

    markdown_text = normalized["markdown_text"]
    if not markdown_text.strip():
        return jsonify({"error": "متنی از فایل استخراج نشد (ممکن است اسکن‌شده باشد)"}), 400

    md_path, _meta_path = ingest.paths_for(document_id)
    metadata = {
        "document_id": document_id,
        "original_filename": file.filename,
        "source_file_type": ext.lstrip("."),
        "original_upload_path": original_path,
        "normalized_md_path": md_path,
        "user_id": user["id"],
        "created_at": ingest.now_iso(),
        "normalization_version": ingest.NORMALIZATION_VERSION,
        **normalized["meta"],
    }
    ingest.write_normalized(document_id, markdown_text, metadata)

    chunks = chunker.parse_markdown_to_chunks(markdown_text)
    result = rag.index_chunks(
        filename=file.filename,
        chunks=chunks,
        document_id=document_id,
        user_id=user["id"],
        source_file_type=ext.lstrip("."),
        normalized_md_path=md_path,
    )

    response = {
        "status": "ok",
        "filename": file.filename,
        "document_id": document_id,
        "chunks": result["chunks"],
    }
    if metadata.get("extraction_quality_warning"):
        response["warning"] = metadata["extraction_quality_warning"]
    return jsonify(response)


@app.route("/api/ask", methods=["POST"])
@auth.subscription_required
@rate_limited(lambda: f"ask:{session.get('user_id')}", min_interval_seconds=1, max_per_window=60, window_seconds=600)
def ask():
    user = auth.current_user()
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    scope = data.get("scope", "all")
    document_id = data.get("document_id")
    document_name = data.get("document_name")

    if not question:
        return jsonify({"error": "سوال خالی است"}), 400
    if scope == "selected" and not document_id:
        return jsonify({"error": "برای این حالت باید یک سند انتخاب شود"}), 400

    # The full pipeline (understand the message -> per-question retrieve -> grounded
    # answer -> assemble) lives in rag.answer_request, so the web path and the offline
    # quality tests exercise exactly the same code. Semantic query understanding
    # replaced the old punctuation-based split_questions().
    result = rag.answer_request(
        question,
        scope=scope,
        document_id=document_id,
        user_id=user["id"],
        selected_source=document_name,
    )
    return jsonify(result)


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
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, port=5000)
