"""환불 처리 자동화: 포트원에서 결제를 취소(환불)하면 해당 사용자의 크레딧을 자동으로 회수한다.

흐름
  1. 포트원이 웹훅(Transaction.Cancelled / Transaction.PartialCancelled)을 보낸다.
  2. 서버가 웹훅 서명을 검증하고, 결제 정보를 포트원 API 에서 다시 조회한다(웹훅 본문은 믿지 않는다).
  3. 결제 시 입력한 구매자 이메일로 사용자를 찾아, 누적 취소 금액에 해당하는 크레딧을 회수하고 내역을 남긴다.

회수 규칙 (환불정책과 같다)
  - 크레딧을 일부 사용한 뒤 환불하면 '사용분을 뺀 잔여 크레딧'이 소멸한다.
  - 환불액 = 결제금액 − 사용 크레딧 × 단가 − 수수료(원화 300원, USD 는 없음) 이므로
    회수 크레딧 = (환불액 + 수수료) ÷ 단가, 전액 환불이면 구매 크레딧 전부.
  - 누적 취소 금액으로 계산하고 이미 회수한 만큼은 빼므로, 같은 웹훅이 다시 와도 두 번 회수하지 않는다.
  - 잔액이 모자라 다 회수하지 못하면 가능한 만큼만 회수하고 '확인 필요'로 표시해 둔다(잔액을 음수로 만들지 않는다).
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

KRW_REFUND_FEE = 300     # 원화 결제 환불 시 결제처리 수수료 (환불정책 제2조). USD(PayPal)는 공제하지 않는다.

# (통화, 결제금액) → 크레딧. USD 는 최소단위(센트). app.py 의 verify_payment 상품표와 같다.
CREDIT_TABLE = {
    ("KRW", 3000): 15, ("KRW", 5000): 28, ("KRW", 10000): 60,
    ("USD", 299): 15, ("USD", 499): 28, ("USD", 999): 60,
}

CANCEL_EVENTS = {"Transaction.Cancelled", "Transaction.PartialCancelled"}


class WebhookError(Exception):
    """웹훅 서명·형식 오류."""


# ── 계산 ─────────────────────────────────────────────────────────────────────
def normalize_currency(value) -> str:
    cur = (value or "").upper()
    return cur[len("CURRENCY_"):] if cur.startswith("CURRENCY_") else cur


def credits_for(currency: str, total: int) -> Optional[int]:
    return CREDIT_TABLE.get((normalize_currency(currency), int(total)))


def fee_for(currency: str) -> int:
    return KRW_REFUND_FEE if normalize_currency(currency) == "KRW" else 0


def credits_to_remove(currency: str, total: int, cancelled: int) -> int:
    """누적 취소 금액(cancelled)에 해당하는 회수 크레딧 수. 상품표에 없으면 0."""
    credits = credits_for(currency, total)
    if credits is None or cancelled <= 0:
        return 0
    if cancelled >= total:
        return credits
    unit = total / credits
    return max(0, min(credits, round((cancelled + fee_for(currency)) / unit)))


def plan_refund(*, balance: int, ledger: dict, cancelled_total: int, target_remove: int) -> dict:
    """이번에 회수할 크레딧과 갱신할 장부를 계산한다(저장소와 무관한 순수 함수)."""
    processed = int(ledger.get("cancelledProcessed", 0))
    if cancelled_total <= processed:
        return {"noop": True, "remove_now": 0, "shortfall": 0, "ledger": ledger}
    removed = int(ledger.get("creditsRemoved", 0))
    need = max(0, target_remove - removed)
    remove_now = min(need, max(0, int(balance)))
    shortfall = need - remove_now
    return {
        "noop": False, "remove_now": remove_now, "shortfall": shortfall,
        "ledger": {
            "cancelledProcessed": cancelled_total,
            "creditsRemoved": removed + remove_now,
            "shortfall": shortfall,
            "needsReview": shortfall > 0,
        },
    }


def cancelled_total_of(payment: dict) -> int:
    amount = payment.get("amount") or {}
    if amount.get("cancelled") is not None:
        return int(amount["cancelled"])
    return sum(int(c.get("totalAmount") or 0) for c in payment.get("cancellations") or []
               if (c.get("status") or "").upper() == "SUCCEEDED")


def process_cancellation(store, payment: dict) -> dict:
    """포트원 결제 정보(취소 반영 후)를 받아 크레딧을 회수한다. store 는 FirestoreStore 와 같은 인터페이스."""
    payment_id = payment.get("id") or ""
    status = (payment.get("status") or "").upper()
    if status not in ("CANCELLED", "PARTIAL_CANCELLED"):
        return {"status": "ignored", "reason": f"payment status {status or 'unknown'}"}

    currency = normalize_currency(payment.get("currency") or (payment.get("amount") or {}).get("currency"))
    total = int((payment.get("amount") or {}).get("total") or 0)
    cancelled = cancelled_total_of(payment)
    if credits_for(currency, total) is None:
        store.record_issue(payment_id, "unknown_product", {"currency": currency, "total": total})
        return {"status": "unknown_product", "currency": currency, "total": total}

    email = ((payment.get("customer") or {}).get("email") or "").strip()
    uids = store.find_user_ids(email) if email else []
    if len(uids) != 1:
        kind = "user_not_found" if not uids else "ambiguous_user"
        store.record_issue(payment_id, kind, {"email": email, "matches": len(uids), "cancelled": cancelled})
        return {"status": kind, "matches": len(uids)}

    target = credits_to_remove(currency, total, cancelled)
    plan = store.apply_refund(uids[0], payment_id, cancelled, target,
                              {"currency": currency, "total": total})
    return {"status": "noop" if plan["noop"] else "ok", "uid": uids[0], "target_remove": target,
            "remove_now": plan["remove_now"], "shortfall": plan["shortfall"]}


# ── 웹훅 서명 검증 (Standard Webhooks) ────────────────────────────────────────
def _check_one(secret: str, msg_id: str, timestamp: str, body: bytes, signatures: str) -> bool:
    raw = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(raw)
    except Exception:
        key = raw.encode()
    signed = f"{msg_id}.{timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for part in signatures.split():
        version, _, sig = part.partition(",")
        if version == "v1" and hmac.compare_digest(sig, expected):
            return True
    return False


def verify_webhook(secret: str, headers, body: bytes, now: Optional[float] = None, tolerance: int = 300) -> None:
    """secret 은 하나 또는 쉼표/공백으로 이은 여러 개(실연동·테스트 모드는 시크릿이 다르다). 하나라도 맞으면 통과."""
    msg_id = headers.get("webhook-id")
    timestamp = headers.get("webhook-timestamp")
    signatures = headers.get("webhook-signature")
    if not (msg_id and timestamp and signatures):
        raise WebhookError("missing signature headers")
    try:
        ts = int(timestamp)
    except ValueError:
        raise WebhookError("bad timestamp")
    if abs((now if now is not None else time.time()) - ts) > tolerance:
        raise WebhookError("timestamp out of tolerance")
    secrets = [x for x in secret.replace(",", " ").split() if x]
    if not any(_check_one(x, msg_id, timestamp, body, signatures) for x in secrets):
        raise WebhookError("signature mismatch")


# ── Firestore 저장소 ─────────────────────────────────────────────────────────
class FirestoreStore:
    """서비스 계정으로 Firestore 에 접속해 크레딧을 회수한다(환경변수 FIREBASE_SERVICE_ACCOUNT_JSON)."""

    def __init__(self, client):
        self.db = client

    @classmethod
    def from_env(cls):
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        if not raw:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON is not set")
        from google.cloud import firestore   # 지연 import: 설정이 없는 환경(테스트 등)에서는 불러오지 않는다
        return cls(firestore.Client.from_service_account_info(json.loads(raw)))

    def find_user_ids(self, email: str) -> list:
        docs = self.db.collection("users").where("email", "==", email).limit(3).stream()
        return [d.id for d in docs]

    def record_issue(self, payment_id: str, kind: str, detail: dict) -> None:
        from google.cloud import firestore
        self.db.collection("refundIssues").document(payment_id or "unknown").set(
            {"kind": kind, "detail": detail, "createdAt": firestore.SERVER_TIMESTAMP}, merge=True)

    def apply_refund(self, uid: str, payment_id: str, cancelled_total: int, target_remove: int, meta: dict) -> dict:
        from google.cloud import firestore
        user_ref = self.db.collection("users").document(uid)
        ledger_ref = self.db.collection("refundLedger").document(payment_id)

        @firestore.transactional
        def run(tx):
            user = user_ref.get(transaction=tx)
            ledger = ledger_ref.get(transaction=tx)
            plan = plan_refund(
                balance=int((user.to_dict() or {}).get("credits") or 0),
                ledger=ledger.to_dict() or {},
                cancelled_total=cancelled_total, target_remove=target_remove)
            if plan["noop"]:
                return plan
            if plan["remove_now"] > 0:
                tx.update(user_ref, {"credits": firestore.Increment(-plan["remove_now"])})
            tx.set(ledger_ref, {**plan["ledger"], "uid": uid, "currency": meta["currency"],
                                "total": meta["total"], "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True)
            if plan["remove_now"] > 0 or plan["shortfall"] > 0:
                tx.set(user_ref.collection("creditHistory").document(), {
                    "type": "refund", "credits": -plan["remove_now"],
                    "currency": meta["currency"], "amount": cancelled_total,
                    "purpose": "환불에 따른 크레딧 회수" + (" (잔액 부족: 확인 필요)" if plan["shortfall"] else ""),
                    "paymentId": payment_id, "date": firestore.SERVER_TIMESTAMP})
            return plan

        return run(self.db.transaction())
