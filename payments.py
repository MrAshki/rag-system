import os
import requests

# NOTE on verification status: I could not reach zarinpal.com's live docs from this
# environment to triple-check field names against the current API version. The
# field names below (MerchantID/Amount/CallbackURL/Authority/Status/RefID) match
# ZarinPal's long-standing REST gateway as used in multiple independent real
# integrations (PHP/C# SDKs). Test a full payment in the SANDBOX before accepting
# real money — in particular confirm whether `Amount` should be Toman or Rial for
# your merchant account; this is the single most likely thing to be off by 10x.

ZARINPAL_MERCHANT_ID = os.getenv("ZARINPAL_MERCHANT_ID", "")
ZARINPAL_SANDBOX = os.getenv("ZARINPAL_SANDBOX", "true").lower() == "true"

_HOST = "sandbox.zarinpal.com" if ZARINPAL_SANDBOX else "www.zarinpal.com"
REQUEST_URL = f"https://{_HOST}/pg/rest/WebGate/PaymentRequest.json"
VERIFY_URL = f"https://{_HOST}/pg/rest/WebGate/PaymentVerification.json"
STARTPAY_URL = f"https://{_HOST}/pg/StartPay/{{authority}}"


class PaymentError(Exception):
    pass


def request_payment(amount_toman: int, callback_url: str, description: str, mobile: str = None) -> str:
    """Starts a ZarinPal payment and returns the Authority token."""
    if not ZARINPAL_MERCHANT_ID:
        raise PaymentError("ZARINPAL_MERCHANT_ID تنظیم نشده است")

    payload = {
        "MerchantID": ZARINPAL_MERCHANT_ID,
        "Amount": amount_toman,
        "CallbackURL": callback_url,
        "Description": description,
    }
    if mobile:
        payload["Mobile"] = mobile

    resp = requests.post(REQUEST_URL, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if int(data.get("Status", -1)) != 100:
        raise PaymentError(f"خطا در شروع پرداخت (status={data.get('Status')})")
    return data["Authority"]


def get_startpay_url(authority: str) -> str:
    return STARTPAY_URL.format(authority=authority)


def verify_payment(authority: str, amount_toman: int) -> str:
    """Verifies a completed payment. Returns the RefID on success, raises PaymentError otherwise."""
    payload = {
        "MerchantID": ZARINPAL_MERCHANT_ID,
        "Authority": authority,
        "Amount": amount_toman,
    }
    resp = requests.post(VERIFY_URL, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    status = int(data.get("Status", -1))
    if status not in (100, 101):
        raise PaymentError(f"تأیید پرداخت ناموفق بود (status={status})")
    return str(data.get("RefID", ""))
