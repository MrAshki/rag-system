from fastapi import APIRouter, Body, Depends, Request
from werkzeug.security import check_password_hash, generate_password_hash

import db
from backend.app.dependencies import client_host, current_user, enforce_rate_limit
from backend.app.api.responses import error_response
from backend.app.services import auth_service as auth

router = APIRouter()


@router.post("/api/auth/request-otp")
def request_otp(request: Request, data: dict = Body(default_factory=dict)):
    enforce_rate_limit(
        f"otp:{client_host(request)}",
        min_interval_seconds=2,
        max_per_window=10,
        window_seconds=600,
    )
    phone = auth.normalize_phone(data.get("phone", ""))
    ok, error = auth.request_otp(phone)
    if not ok:
        return error_response(error)
    return {"status": "ok"}


@router.post("/api/auth/verify-otp")
def verify_otp(request: Request, data: dict = Body(default_factory=dict)):
    phone = auth.normalize_phone(data.get("phone", ""))
    code = (data.get("code") or "").strip()
    if not db.verify_and_consume_otp(phone, code):
        return error_response("کد نامعتبر یا منقضی‌شده است")
    user = db.get_or_create_user(phone)
    db.mark_user_verified(phone)
    request.session["user_id"] = user["id"]
    request.session["phone"] = phone
    return {"status": "ok", "is_admin": bool(user["is_admin"])}


@router.post("/api/auth/register/send-otp")
def register_send_otp(request: Request, data: dict = Body(default_factory=dict)):
    enforce_rate_limit(
        f"otp:{client_host(request)}",
        min_interval_seconds=2,
        max_per_window=10,
        window_seconds=600,
    )
    phone = auth.normalize_phone(data.get("phone", ""))
    existing = db.get_user_by_phone(phone) if auth.is_valid_phone(phone) else None
    if existing and existing["password_hash"]:
        return error_response("این شماره قبلاً ثبت‌نام کرده است. لطفاً وارد شوید.")
    ok, error = auth.request_otp(phone)
    if not ok:
        return error_response(error)
    return {"status": "ok"}


@router.post("/api/auth/register/verify-otp")
def register_verify_otp(request: Request, data: dict = Body(default_factory=dict)):
    phone = auth.normalize_phone(data.get("phone", ""))
    code = (data.get("code") or "").strip()
    if not auth.is_valid_phone(phone):
        return error_response("شماره موبایل نامعتبر است")
    existing = db.get_user_by_phone(phone)
    if existing and existing["password_hash"]:
        return error_response("این شماره قبلاً ثبت‌نام کرده است. لطفاً وارد شوید.")
    if not db.verify_and_consume_otp(phone, code):
        return error_response("کد نامعتبر یا منقضی‌شده است")
    request.session["reg_verified_phone"] = phone
    return {"status": "ok"}


@router.post("/api/auth/register/complete")
def register_complete(request: Request, data: dict = Body(default_factory=dict)):
    phone = auth.normalize_phone(data.get("phone", ""))
    if request.session.get("reg_verified_phone") != phone:
        return error_response("ابتدا شماره موبایل خود را تأیید کنید")

    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    email = auth.normalize_email(data.get("email"))
    password = data.get("password") or ""

    if not first_name or not last_name:
        return error_response("نام و نام خانوادگی را وارد کنید")
    if not auth.is_valid_email(email):
        return error_response("ایمیل نامعتبر است")
    if len(password) < auth.MIN_PASSWORD_LEN:
        return error_response(f"رمز عبور باید حداقل {auth.MIN_PASSWORD_LEN} کاراکتر باشد")

    taken = db.get_user_by_email(email)
    if taken and taken["phone"] != phone:
        return error_response("این ایمیل قبلاً استفاده شده است")

    user = db.complete_user_registration(
        phone,
        first_name,
        last_name,
        email,
        auth.parse_iso_date(data.get("birth_date")),
        generate_password_hash(password),
    )
    request.session.pop("reg_verified_phone", None)
    request.session["user_id"] = user["id"]
    request.session["phone"] = phone
    return {"status": "ok", "is_admin": bool(user["is_admin"])}


@router.post("/api/auth/login-email")
def login_email(request: Request, data: dict = Body(default_factory=dict)):
    enforce_rate_limit(
        f"login-email:{client_host(request)}",
        min_interval_seconds=1,
        max_per_window=20,
        window_seconds=600,
    )
    email = auth.normalize_email(data.get("email", ""))
    user = db.get_user_by_email(email)
    if not user or not user["password_hash"] or not check_password_hash(user["password_hash"], data.get("password") or ""):
        return error_response("ایمیل یا رمز عبور نادرست است")
    request.session["user_id"] = user["id"]
    request.session["phone"] = user["phone"]
    return {"status": "ok", "is_admin": bool(user["is_admin"])}


@router.post("/api/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}


@router.get("/api/auth/me")
def me(user=Depends(current_user)):
    if not user:
        return {"logged_in": False}
    sub = db.get_active_subscription(user["id"])
    full_name = " ".join(p for p in (user["first_name"], user["last_name"]) if p).strip()
    return {
        "logged_in": True,
        "phone": user["phone"],
        "name": full_name or None,
        "is_admin": bool(user["is_admin"]),
        "has_subscription": True,
        "subscription_expires_at": sub["expires_at"] if sub else None,
    }
