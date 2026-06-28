import os
import random
import re
from datetime import datetime

import db

OTP_TTL_SECONDS = 120
OTP_MIN_INTERVAL_SECONDS = 60
OTP_MAX_PER_HOUR = 5
MIN_PASSWORD_LEN = 6

PHONE_RE = re.compile(r"^09\d{9}$")
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
    provider = os.getenv("SMS_PROVIDER", "console")
    if provider == "console":
        print(f"[OTP] phone={phone} code={code} (no real SMS provider configured)", flush=True)
    else:
        raise NotImplementedError(f"SMS provider '{provider}' is not implemented yet")


def request_otp(phone: str):
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


def update_profile(user_id, first_name, last_name, email, birth_date, password=None):
    from werkzeug.security import generate_password_hash

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
