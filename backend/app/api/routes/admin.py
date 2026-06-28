from fastapi import APIRouter, Body, Depends

import db
from backend.app.api.responses import error_response
from backend.app.dependencies import require_admin
from backend.app.services import auth_service as auth

router = APIRouter()


@router.get("/api/admin/users")
def admin_users(_user=Depends(require_admin)):
    users = [dict(u) for u in db.list_users()]
    for u in users:
        sub = db.get_active_subscription(u["id"])
        u["has_subscription"] = bool(sub)
        u["subscription_expires_at"] = sub["expires_at"] if sub else None
    return {"users": users}


@router.post("/api/admin/grant")
def admin_grant(data: dict = Body(default_factory=dict), _user=Depends(require_admin)):
    phone = auth.normalize_phone(data.get("phone", ""))
    plan_id = data.get("plan_id")
    plan = db.get_plan(plan_id) if plan_id else None
    if not auth.is_valid_phone(phone) or not plan:
        return error_response("ورودی نامعتبر است")
    user = db.get_or_create_user(phone)
    db.create_subscription(user["id"], plan["id"], plan["duration_days"])
    return {"status": "ok"}


@router.get("/api/admin/subscriptions")
def admin_subscriptions(_user=Depends(require_admin)):
    return {"subscriptions": [dict(s) for s in db.list_subscriptions_for_admin()]}


@router.post("/api/admin/revoke")
def admin_revoke(data: dict = Body(default_factory=dict), _user=Depends(require_admin)):
    subscription_id = data.get("subscription_id")
    if not subscription_id:
        return error_response("ورودی نامعتبر است")
    db.revoke_subscription(subscription_id)
    return {"status": "ok"}


@router.get("/api/admin/payments")
def admin_payments(_user=Depends(require_admin)):
    return {"payments": [dict(p) for p in db.list_payments_for_admin()]}


@router.get("/api/admin/stats")
def admin_stats(_user=Depends(require_admin)):
    users = db.list_users()
    active_subs = sum(1 for u in users if db.get_active_subscription(u["id"]))
    return {
        "total_users": len(users),
        "active_subscriptions": active_subs,
    }
