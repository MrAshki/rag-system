import os
import re
import random
from datetime import datetime
from functools import wraps
from flask import session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

import db

OTP_TTL_SECONDS = 120
OTP_MIN_INTERVAL_SECONDS = 60
OTP_MAX_PER_HOUR = 5
MIN_PASSWORD_LEN = 6

PHONE_RE = re.compile(r"^09\d{9}$")
# Deliberately loose: we don't verify email yet, so this only rejects obviously
# malformed input (must look like local@domain.tld), not deliverability.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_phone(phone: str) -> str:
    return (phone or "").strip().replace(" ", "")


def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(phone))


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or ""))


def parse_iso_date(s: str):
    """Parse a 'YYYY-MM-DD' string (Gregorian, already converted from Jalali on the
    client) into a date, or None if missing/malformed. Birth date is optional."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


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


# ---- registration (phone OTP first, then profile) ----

def verify_registration_otp(phone: str, code: str):
    """Step 2 of the register flow: confirm the SMS code WITHOUT logging in or
    finalizing the account. On success we stash the verified phone in the session
    so complete_registration() can trust it; the profile fields are collected next.
    Returns (ok, error_message_or_None)."""
    if not is_valid_phone(phone):
        return False, "شماره موبایل نامعتبر است"
    existing = db.get_user_by_phone(phone)
    if existing and existing["password_hash"]:
        return False, "این شماره قبلاً ثبت‌نام کرده است. لطفاً وارد شوید."
    if not db.verify_and_consume_otp(phone, code):
        return False, "کد نامعتبر یا منقضی‌شده است"
    session["reg_verified_phone"] = phone
    return True, None


def complete_registration(phone, first_name, last_name, email, birth_date, password):
    """Step 3 of the register flow: store the profile + password and log the user
    in. Guarded by the session marker set in verify_registration_otp() so a profile
    can only be created for a phone whose OTP was actually verified in this session.
    Returns (user_row, None) on success or (None, error_message)."""
    if session.get("reg_verified_phone") != phone:
        return None, "ابتدا شماره موبایل خود را تأیید کنید"

    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    email = normalize_email(email)
    password = password or ""

    if not first_name or not last_name:
        return None, "نام و نام خانوادگی را وارد کنید"
    if not is_valid_email(email):
        return None, "ایمیل نامعتبر است"
    if len(password) < MIN_PASSWORD_LEN:
        return None, f"رمز عبور باید حداقل {MIN_PASSWORD_LEN} کاراکتر باشد"

    taken = db.get_user_by_email(email)
    if taken and taken["phone"] != phone:
        return None, "این ایمیل قبلاً استفاده شده است"

    user = db.complete_user_registration(
        phone, first_name, last_name, email, birth_date,
        generate_password_hash(password),
    )
    session.pop("reg_verified_phone", None)
    session["user_id"] = user["id"]
    session["phone"] = phone
    return user, None


# ---- email + password login (alternate to phone OTP) ----

def login_with_email(email: str, password: str):
    """Returns (ok, error_message_or_None). Same generic error for unknown email,
    no-password account, and wrong password so the form doesn't leak which emails
    exist or which accounts have a password set."""
    email = normalize_email(email)
    user = db.get_user_by_email(email)
    if not user or not user["password_hash"] or not check_password_hash(user["password_hash"], password or ""):
        return False, "ایمیل یا رمز عبور نادرست است"
    session["user_id"] = user["id"]
    session["phone"] = user["phone"]
    return True, None


# ---- profile self-service edit ----

def update_profile(user_id, first_name, last_name, email, birth_date, password=None):
    """Validate and apply profile edits from the profile page. `password` is
    optional: a non-empty value changes the login password, empty leaves it as-is.
    Returns (ok, error_message_or_None)."""
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    email = normalize_email(email)
    password = password or ""

    if not first_name or not last_name:
        return False, "نام و نام خانوادگی را وارد کنید"
    if not is_valid_email(email):
        return False, "ایمیل نامعتبر است"
    if password and len(password) < MIN_PASSWORD_LEN:
        return False, f"رمز عبور باید حداقل {MIN_PASSWORD_LEN} کاراکتر باشد"

    taken = db.get_user_by_email(email)
    if taken and taken["id"] != user_id:
        return False, "این ایمیل قبلاً استفاده شده است"

    db.update_user_profile(user_id, first_name, last_name, email, birth_date)
    if password:
        db.set_user_password(user_id, generate_password_hash(password))
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
