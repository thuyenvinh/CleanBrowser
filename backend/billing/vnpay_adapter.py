"""VNPay (Vietnam payment gateway) adapter.
Configure via env: VNPAY_TMN_CODE, VNPAY_HASH_SECRET, VNPAY_URL, VNPAY_RETURN_URL.

VNPay flow (sandbox + production):
- POST checkout: build query string with vnp_* params, sign with HMAC SHA512.
- User redirected to vnp_PaymentUrl.
- Callback: verify signature, check vnp_ResponseCode == '00' (success).
- One-time payment per cycle (VNPay does not support recurring native).
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone as tz
from urllib.parse import quote_plus, urlencode


def is_configured() -> bool:
    return bool(os.environ.get("VNPAY_TMN_CODE") and os.environ.get("VNPAY_HASH_SECRET"))


def _config():
    return {
        "tmn_code": os.environ["VNPAY_TMN_CODE"],
        "hash_secret": os.environ["VNPAY_HASH_SECRET"],
        "url": os.environ.get(
            "VNPAY_URL", "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"
        ),
    }


def _sign(params: dict, secret: str) -> str:
    # VNPay spec: sort params alphabetically, urlencode, then HMAC SHA512
    sorted_items = sorted(params.items())
    query = "&".join(f"{k}={quote_plus(str(v))}" for k, v in sorted_items)
    return hmac.new(secret.encode(), query.encode(), hashlib.sha512).hexdigest()


def build_checkout_url(
    *,
    tenant_id: str,
    plan_id: str,
    amount_vnd: int,  # in VND (no division by 100; VNPay uses x100 internally — see vnp_Amount)
    order_info: str,
    return_url: str,
    client_ip: str = "127.0.0.1",
    order_id: str | None = None,
) -> dict:
    """Returns {url, vnp_TxnRef}."""
    if not is_configured():
        raise RuntimeError("VNPay not configured")
    cfg = _config()
    txn_ref = order_id or f"{tenant_id[:8]}-{int(datetime.now(tz.utc).timestamp())}"
    now = datetime.now(tz.utc).strftime("%Y%m%d%H%M%S")

    params = {
        "vnp_Version": "2.1.0",
        "vnp_Command": "pay",
        "vnp_TmnCode": cfg["tmn_code"],
        "vnp_Amount": str(amount_vnd * 100),
        "vnp_CurrCode": "VND",
        "vnp_TxnRef": txn_ref,
        "vnp_OrderInfo": order_info,
        "vnp_OrderType": "billpayment",
        "vnp_Locale": "vn",
        "vnp_ReturnUrl": return_url,
        "vnp_IpAddr": client_ip,
        "vnp_CreateDate": now,
        "vnp_BankCode": "",
    }
    # Remove empty params (VNPay sigs only on non-empty)
    params = {k: v for k, v in params.items() if v != ""}
    sig = _sign(params, cfg["hash_secret"])
    params["vnp_SecureHash"] = sig
    url = f"{cfg['url']}?{urlencode(params, quote_via=quote_plus)}"
    return {"url": url, "vnp_TxnRef": txn_ref}


def verify_callback(params: dict) -> tuple[bool, str]:
    """Verify VNPay return callback.
    Returns (success, txn_ref). success=True iff signature valid AND vnp_ResponseCode == '00'."""
    if not is_configured():
        return False, ""
    cfg = _config()
    received_sig = params.pop("vnp_SecureHash", "")
    params.pop("vnp_SecureHashType", None)
    expected = _sign(params, cfg["hash_secret"])
    if not hmac.compare_digest(received_sig.lower(), expected.lower()):
        return False, params.get("vnp_TxnRef", "")
    if params.get("vnp_ResponseCode") != "00":
        return False, params.get("vnp_TxnRef", "")
    return True, params.get("vnp_TxnRef", "")
