import os

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import RedirectResponse

import db
import payments
from backend.app.api.responses import error_response
from backend.app.dependencies import require_login

router = APIRouter()


@router.get("/api/plans")
def get_plans():
    plans = db.list_active_plans()
    return {"plans": [dict(p) for p in plans]}


@router.post("/api/subscribe")
def subscribe(request: Request, data: dict = Body(default_factory=dict), user=Depends(require_login)):
    plan_id = data.get("plan_id")
    plan = db.get_plan(plan_id) if plan_id else None
    if not plan:
        return error_response("پلن نامعتبر است")

    payment_id = db.create_payment(user["id"], plan["id"], plan["price_toman"])
    base_url = os.getenv("PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")
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
        return error_response(str(e), status_code=502)

    db.set_payment_authority(payment_id, authority)
    return {"redirect_url": payments.get_startpay_url(authority)}


@router.get("/api/payment/callback")
def payment_callback(payment_id: str = None, Authority: str = None, Status: str = None):
    payment = None
    try:
        payment = db.get_payment_by_authority(Authority) if Authority else None
    except Exception:
        payment = None

    if not payment or str(payment["id"]) != str(payment_id) or Status != "OK":
        if payment:
            db.mark_payment_failed(payment["id"])
        return RedirectResponse("/?payment=failed")

    try:
        payments.verify_payment(Authority, payment["amount_toman"])
    except payments.PaymentError:
        db.mark_payment_failed(payment["id"])
        return RedirectResponse("/?payment=failed")

    plan = db.get_plan(payment["plan_id"])
    db.mark_payment_paid(payment["id"], ref_id=Authority)
    db.create_subscription(payment["user_id"], plan["id"], plan["duration_days"])
    return RedirectResponse("/?payment=success")
