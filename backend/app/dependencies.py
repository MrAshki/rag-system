from typing import Optional

from fastapi import HTTPException, Request

import db
from ratelimit import check_rate_limit


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get_user_by_id(user_id)


def require_login(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="ابتدا وارد شوید")
    return user


def require_admin(request: Request):
    user = current_user(request)
    if not user or not user["is_admin"]:
        raise HTTPException(status_code=403, detail="دسترسی غیرمجاز")
    return user


def require_subscription(request: Request):
    # Subscriptions are intentionally disabled during product development.
    # Keep the dependency name so existing routes stay stable, but only require login.
    return require_login(request)


def enforce_rate_limit(
    key: str,
    min_interval_seconds: float = 2,
    max_per_window: int = 30,
    window_seconds: int = 600,
):
    error = check_rate_limit(key, min_interval_seconds, max_per_window, window_seconds)
    if error:
        raise HTTPException(status_code=429, detail=error)


def client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def session_user_id(request: Request) -> Optional[int]:
    return request.session.get("user_id")
