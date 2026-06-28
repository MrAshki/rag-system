from fastapi import APIRouter, Body, Depends

import db
from backend.app.api.responses import error_response
from backend.app.dependencies import require_login
from backend.app.services import auth_service as auth

router = APIRouter()


@router.get("/api/profile")
def get_profile(user=Depends(require_login)):
    return {
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "email": user["email"],
        "phone": user["phone"],
        "birth_date": user["birth_date"],
        "created_at": user["created_at"],
        "has_password": bool(user["password_hash"]),
    }


@router.post("/api/profile")
def update_profile(data: dict = Body(default_factory=dict), user=Depends(require_login)):
    ok, error = auth.update_profile(
        user["id"],
        data.get("first_name"),
        data.get("last_name"),
        data.get("email"),
        auth.parse_iso_date(data.get("birth_date")),
        data.get("password"),
    )
    if not ok:
        return error_response(error)
    return {"status": "ok"}


@router.get("/api/profile/payments")
def profile_payments(user=Depends(require_login)):
    rows = db.list_payments_for_user(user["id"])
    return {"payments": [dict(p) for p in rows]}
