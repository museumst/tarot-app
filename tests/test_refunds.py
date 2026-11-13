import base64
import hashlib
import hmac
import json
import time
import unittest
from unittest import mock

from fastapi import HTTPException
from starlette.requests import Request

import app
import refunds


class MemoryStore:
    """FirestoreStore 와 같은 인터페이스의 메모리 구현(계산은 refunds.plan_refund 를 그대로 쓴다)."""

    def __init__(self, users=None):
        self.users = users or {}          # uid -> {"email", "credits"}
        self.ledgers = {}                 # payment_id -> dict
        self.history = []
        self.issues = []

    def find_user_ids(self, email):
        return [uid for uid, u in self.users.items() if u["email"] == email]

    def record_issue(self, payment_id, kind, detail):
        self.issues.append((payment_id, kind, detail))

    def apply_refund(self, uid, payment_id, cancelled_total, target_remove, meta):
        plan = refunds.plan_refund(balance=self.users[uid]["credits"], ledger=self.ledgers.get(payment_id, {}),
                                   cancelled_total=cancelled_total, target_remove=target_remove)
        if not plan["noop"]:
            self.users[uid]["credits"] -= plan["remove_now"]
            self.ledgers[payment_id] = plan["ledger"]
            if plan["remove_now"] or plan["shortfall"]:
                self.history.append((uid, -plan["remove_now"], payment_id))
        return plan


def payment(status="PARTIAL_CANCELLED", currency="KRW", total=3000, cancelled=2500, email="a@example.com", pid="t_1"):
    return {"id": pid, "status": status, "currency": currency,
            "amount": {"total": total, "cancelled": cancelled}, "customer": {"email": email}}


class CreditsToRemoveTest(unittest.TestCase):
    def test_krw_partial_refund_matches_policy_example(self):
        # 3,000원(15) 결제, 1크레딧 사용 → 환불 2,500원(수수료 300원 공제) → 14크레딧 회수
        self.assertEqual(refunds.credits_to_remove("KRW", 3000, 2500), 14)

    def test_full_refunds_remove_every_credit(self):
        self.assertEqual(refunds.credits_to_remove("KRW", 3000, 3000), 15)     # 서비스 장애 등 전액 환불
        self.assertEqual(refunds.credits_to_remove("KRW", 3000, 2700), 15)     # 미사용 전액(수수료 300원 공제)
        self.assertEqual(refunds.credits_to_remove("USD", 299, 299), 15)
        self.assertEqual(refunds.credits_to_remove("CURRENCY_USD", 999, 999), 60)

    def test_usd_partial_refund_has_no_fee(self):
        # $2.99(15) 결제, 1크레딧 사용 → 환불 $2.79 → 14크레딧 회수
        self.assertEqual(refunds.credits_to_remove("USD", 299, 279), 14)

    def test_unknown_product_or_no_cancellation_removes_nothing(self):
        self.assertEqual(refunds.credits_to_remove("KRW", 1234, 1234), 0)
        self.assertEqual(refunds.credits_to_remove("KRW", 3000, 0), 0)

    def test_result_is_clamped_to_purchased_credits(self):
        self.assertEqual(refunds.credits_to_remove("KRW", 3000, 2999), 15)


class ProcessCancellationTest(unittest.TestCase):
    def store(self, credits=15):
        return MemoryStore({"u1": {"email": "a@example.com", "credits": credits}})

    def test_partial_refund_removes_remaining_credits(self):
        store = self.store(credits=14)
        result = refunds.process_cancellation(store, payment())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["remove_now"], 14)
        self.assertEqual(store.users["u1"]["credits"], 0)
        self.assertEqual(store.history, [("u1", -14, "t_1")])

    def test_repeated_webhook_does_not_remove_twice(self):
        store = self.store(credits=30)
        refunds.process_cancellation(store, payment(status="CANCELLED", cancelled=3000))
        again = refunds.process_cancellation(store, payment(status="CANCELLED", cancelled=3000))
        self.assertEqual(again["status"], "noop")
        self.assertEqual(store.users["u1"]["credits"], 15)

    def test_multiple_partial_refunds_use_cumulative_amount(self):
        store = self.store(credits=15)
        refunds.process_cancellation(store, payment(currency="USD", total=299, cancelled=150))   # 8크레딧
        first = store.users["u1"]["credits"]
        refunds.process_cancellation(store, payment(status="CANCELLED", currency="USD", total=299, cancelled=299))
        self.assertEqual(first, 7)
        self.assertEqual(store.users["u1"]["credits"], 0)          # 합계 15크레딧, 두 번째에 나머지 7개 회수

    def test_insufficient_balance_removes_what_is_left_and_flags_review(self):
        store = self.store(credits=3)
        result = refunds.process_cancellation(store, payment(status="CANCELLED", cancelled=3000))
        self.assertEqual(result["remove_now"], 3)
        self.assertEqual(result["shortfall"], 12)
        self.assertEqual(store.users["u1"]["credits"], 0)            # 음수가 되지 않는다
        self.assertTrue(store.ledgers["t_1"]["needsReview"])

    def test_non_cancelled_payment_is_ignored(self):
        store = self.store()
        self.assertEqual(refunds.process_cancellation(store, payment(status="PAID", cancelled=0))["status"], "ignored")
        self.assertEqual(store.users["u1"]["credits"], 15)

    def test_unknown_or_ambiguous_user_is_recorded_not_guessed(self):
        store = self.store()
        missing = refunds.process_cancellation(store, payment(email="nobody@example.com"))
        self.assertEqual(missing["status"], "user_not_found")
        store.users["u2"] = {"email": "a@example.com", "credits": 5}
        ambiguous = refunds.process_cancellation(store, payment())
        self.assertEqual(ambiguous["status"], "ambiguous_user")
        self.assertEqual([i[1] for i in store.issues], ["user_not_found", "ambiguous_user"])
        self.assertEqual(store.users["u1"]["credits"], 15)

    def test_unknown_product_is_recorded(self):
        store = self.store()
        result = refunds.process_cancellation(store, payment(total=1234, cancelled=1234))
        self.assertEqual(result["status"], "unknown_product")
        self.assertEqual(store.issues[0][1], "unknown_product")

    def test_cancelled_total_falls_back_to_cancellation_list(self):
        pay = payment()
        pay["amount"] = {"total": 3000}
        pay["cancellations"] = [{"status": "SUCCEEDED", "totalAmount": 2500}, {"status": "FAILED", "totalAmount": 500}]
        self.assertEqual(refunds.cancelled_total_of(pay), 2500)


def sign(secret, body, msg_id="msg_1", ts=None):
    ts = str(int(ts if ts is not None else time.time()))
    key = base64.b64decode(secret.split("_", 1)[1])
    sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"webhook-id": msg_id, "webhook-timestamp": ts, "webhook-signature": f"v1,{sig}"}


SECRET = "whsec_" + base64.b64encode(b"super-secret-key").decode()


class WebhookSignatureTest(unittest.TestCase):
    def test_valid_signature_passes(self):
        body = b'{"type":"x"}'
        refunds.verify_webhook(SECRET, sign(SECRET, body), body)

    def test_any_of_several_secrets_may_match(self):
        body = b'{"type":"x"}'
        other = "whsec_" + base64.b64encode(b"another-key").decode()
        refunds.verify_webhook(f"{other}, {SECRET}", sign(SECRET, body), body)       # 실연동+테스트 시크릿을 함께 설정
        refunds.verify_webhook(f"{SECRET} {other}", sign(other, body), body)
        with self.assertRaises(refunds.WebhookError):
            refunds.verify_webhook(f"{other}", sign(SECRET, body), body)

    def test_tampered_body_wrong_secret_and_old_timestamp_fail(self):
        body = b'{"type":"x"}'
        headers = sign(SECRET, body)
        with self.assertRaises(refunds.WebhookError):
            refunds.verify_webhook(SECRET, headers, b'{"type":"y"}')
        other = "whsec_" + base64.b64encode(b"another-key").decode()
        with self.assertRaises(refunds.WebhookError):
            refunds.verify_webhook(other, headers, body)
        with self.assertRaises(refunds.WebhookError):
            refunds.verify_webhook(SECRET, sign(SECRET, body, ts=time.time() - 3600), body)
        with self.assertRaises(refunds.WebhookError):
            refunds.verify_webhook(SECRET, {}, body)


def make_request(body: bytes, headers: dict):
    raw = [(k.encode(), v.encode()) for k, v in headers.items()]
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/api/portone/webhook", "headers": raw}, receive)


class WebhookEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_not_configured_returns_503(self):
        with mock.patch.dict("os.environ", {"PORTONE_WEBHOOK_SECRET": ""}):
            with self.assertRaises(HTTPException) as caught:
                await app.portone_webhook(make_request(b"{}", {}))
        self.assertEqual(caught.exception.status_code, 503)

    async def test_bad_signature_returns_401(self):
        with mock.patch.dict("os.environ", {"PORTONE_WEBHOOK_SECRET": SECRET}):
            with self.assertRaises(HTTPException) as caught:
                await app.portone_webhook(make_request(b'{"type":"Transaction.Cancelled"}', {"webhook-id": "a"}))
        self.assertEqual(caught.exception.status_code, 401)

    async def test_other_event_types_are_ignored(self):
        body = json.dumps({"type": "Transaction.Paid", "data": {"paymentId": "t_1"}}).encode()
        with mock.patch.dict("os.environ", {"PORTONE_WEBHOOK_SECRET": SECRET}):
            result = await app.portone_webhook(make_request(body, sign(SECRET, body)))
        self.assertEqual(result["ignored"], "Transaction.Paid")

    async def test_cancel_event_refetches_payment_and_removes_credits(self):
        body = json.dumps({"type": "Transaction.PartialCancelled", "data": {"paymentId": "t_1"}}).encode()
        store = MemoryStore({"u1": {"email": "a@example.com", "credits": 14}})
        with mock.patch.dict("os.environ", {"PORTONE_WEBHOOK_SECRET": SECRET}), \
                mock.patch.object(app, "fetch_portone_payment", mock.AsyncMock(return_value=payment())) as fetch, \
                mock.patch.object(app, "get_refund_store", return_value=store):
            result = await app.portone_webhook(make_request(body, sign(SECRET, body)))
        fetch.assert_awaited_once_with("t_1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(store.users["u1"]["credits"], 0)


if __name__ == "__main__":
    unittest.main()
