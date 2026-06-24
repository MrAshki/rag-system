import os
import re
import random
from functools import wraps
from flask import session, jsonify

import db

OTP_TTL_SECONDS = 120
OTP_MIN_INTERVAL_SECONDS = 60
OTP_MAX_PER_HOUR = 5

PHONE_RE = re.compile(r"^09\d{9}$")


def normalize_phone(phone: str) -> str:
    return (phone or "").strip().replace(" ", "")


def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(phone))


def generate_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def send_otp(phone: str, code: str):
    """Pluggable OTP sender. No real SMS provider is wired in yet (see SMS_PROVIDER
    decision pending) — for now this logs the code so the flow is fully testable.
    Swap this function's body for a real provider (Kavenegar/sms.ir/ippanel, etc.)
    once an account/API key is available."""
    provider = os.getenv("SMS_PROVIDER", "console")
    if provider == "console":
        print(f"[OTP] phone={phone} code={code} (no real SMS provider configured)", flush=True)
    else:
        raise NotImplementedError(f"SMS provider '{provider}' is not implemented yet")


def request_otp(phone: str):
    """Returns (ok, error_message_or_None)."""
    if not is_valid_phone(phone):
        return False, "شماره موبایل نامعتبر است (فرمت صحیح: 09xxxxxxxxx)"

    if db.recent_otp_count(phone, OTP_MIN_INTERVAL_SECONDS) > 0:
        return False, "لطفاً کمی صبر کنید و دوباره تلاش کنید"
    if db.recent_otp_count(phone, 3600) >= OTP_MAX_PER_HOUR:
        return False, "تعداد درخواست‌های شما در این ساعت زیاد بوده، بعداً تلاش کنید"

    code = generate_code()
    db.create_otp(phone, code, ttl_seconds=OTP_TTL_SECONDS)
    send_otp(phone, code)
    return True, None


def verify_otp_and_login(phone: str, code: str):
    """Returns (ok, error_message_or_None)."""
    if not db.verify_and_consume_otp(phone, code):
        return False, "کد نامعتبر یا منقضی‌شده است"
    user = db.get_or_create_user(phone)
    db.mark_user_verified(phone)
    session["user_id"] = user["id"]
    session["phone"] = phone
    return True, None


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.get_user_by_id(user_id)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return jsonify({"error": "ابتدا وارد شوید"}), 401
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or not user["is_admin"]:
            return jsonify({"error": "دسترسی غیرمجاز"}), 403
        return view(*args, **kwargs)
    return wrapped


def subscription_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "ابتدا وارد شوید"}), 401
        if user["is_admin"]:
            return view(*args, **kwargs)
        if not db.get_active_subscription(user["id"]):
            return jsonify({"error": "اشتراک فعال ندارید", "code": "no_subscription"}), 402
        return view(*args, **kwargs)
    return wrapped
