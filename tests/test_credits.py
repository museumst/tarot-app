import itertools
import unittest
from unittest import mock

import httpx
from fastapi import HTTPException

import app
import credits

TS = "SERVER_TIMESTAMP"


# ── 아주 작은 Firestore 흉내(트랜잭션 안에서 읽고 쓰는 부분만) ──────────────────────
class Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class Ref:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def get(self, transaction=None):
        return Snap(self.db.docs.get(self.path))

    def collection(self, name):
        return Col(self.db, self.path + (name,))


class Col:
    _ids = itertools.count(1)

    def __init__(self, db, path):
        self.db, self.path = db, path

    def document(self, doc_id=None):
        return Ref(self.db, self.path + (doc_id or f"auto{next(self._ids)}",))


class Tx:
    def __init__(self, db):
        self.db = db

    def set(self, ref, data, merge=False):
        if merge and ref.path in self.db.docs:
            self.db.docs[ref.path] = {**self.db.docs[ref.path], **data}
        else:
            self.db.docs[ref.path] = dict(data)


class FakeDb:
    def __init__(self):
        self.docs = {}

    def collection(self, name):
        return Col(self, (name,))

    def transaction(self):
        return Tx(self)

    def history(self, uid):
        return [d for p, d in self.docs.items() if p[:3] == ("users", uid, "creditHistory")]


def make_store(db=None):
    db = db or FakeDb()
    return db, credits.CreditStore(db, transactional=lambda fn: fn, server_ts=TS)


class PlanConsumeTest(unittest.TestCase):
    def test_priority_is_free_then_credit(self):
        self.assertEqual(credits.plan_consume({"free_used": 0, "credits": 5}, False), "free")
        self.assertEqual(credits.plan_consume({"free_used": 2, "credits": 5}, False), "credit")
        self.assertEqual(credits.plan_consume({"free_used": 2, "credits": 0}, False), "none")
        self.assertEqual(credits.plan_consume(None, False), "free")
        self.assertEqual(credits.plan_consume({"free_used": 2, "credits": 0}, True), "admin")


class ConsumeReadingTest(unittest.TestCase):
    def test_new_user_gets_two_free_readings_then_must_buy(self):
        db, store = make_store()
        kinds = [store.consume_reading("u1", "a@example.com", False)["kind"] for _ in range(3)]
        self.assertEqual(kinds, ["free", "free", "none"])
        self.assertEqual(db.docs[("users", "u1")]["free_used"], 2)
        self.assertEqual(db.docs[("users", "u1")]["email"], "a@example.com")

    def test_credit_is_used_after_free_readings_and_history_is_written(self):
        db, store = make_store()
        db.docs[("users", "u1")] = {"email": "a@example.com", "free_used": 2, "credits": 2}
        result = store.consume_reading("u1", "a@example.com", False)
        self.assertEqual((result["kind"], result["credits"]), ("credit", 1))
        history = db.history("u1")
        self.assertEqual(len(history), 1)
        self.assertEqual((history[0]["type"], history[0]["credits"]), ("use", -1))

    def test_never_goes_negative(self):
        db, store = make_store()
        db.docs[("users", "u1")] = {"free_used": 2, "credits": 0}
        self.assertEqual(store.consume_reading("u1", "a@example.com", False)["kind"], "none")
        self.assertEqual(db.docs[("users", "u1")]["credits"], 0)

    def test_admin_is_not_charged(self):
        db, store = make_store()
        db.docs[("users", "u1")] = {"free_used": 2, "credits": 0}
        self.assertEqual(store.consume_reading("u1", "admin@example.com", True)["kind"], "admin")
        self.assertEqual(db.docs[("users", "u1")], {"free_used": 2, "credits": 0})

    def test_restore_undoes_the_charge(self):
        db, store = make_store()
        db.docs[("users", "u1")] = {"free_used": 2, "credits": 2}
        store.consume_reading("u1", "a@example.com", False)
        store.restore_reading("u1", "credit")
        self.assertEqual(db.docs[("users", "u1")]["credits"], 2)
        db.docs[("users", "u2")] = {"free_used": 2, "credits": 0}
        store.restore_reading("u2", "free")
        self.assertEqual(db.docs[("users", "u2")]["free_used"], 1)
        store.restore_reading("u2", "admin")          # 알 수 없는 종류는 아무것도 바꾸지 않는다
        self.assertEqual(db.docs[("users", "u2")]["free_used"], 1)


class GrantPurchaseTest(unittest.TestCase):
    def test_grants_credits_once_per_payment(self):
        db, store = make_store()
        first = store.grant_purchase("u1", "a@example.com", "t_pay1", 15, "KRW", 3000)
        again = store.grant_purchase("u1", "a@example.com", "t_pay1", 15, "KRW", 3000)
        self.assertEqual((first["credits"], first["already"]), (15, False))
        self.assertEqual((again["credits"], again["already"]), (15, True))     # 중복 지급 없음
        self.assertEqual(db.docs[("users", "u1")]["credits"], 15)

    def test_history_matches_existing_format(self):
        db, store = make_store()
        store.grant_purchase("u1", "a@example.com", "t_pay1", 15, "KRW", 3000)
        store.grant_purchase("u1", "a@example.com", "t_pay2", 15, "USD", 299)
        krw, usd = db.history("u1")
        self.assertEqual((krw["amount"], krw["amount_krw"], krw["currency"]), (3000, 3000, "KRW"))
        self.assertEqual((usd["amount"], usd["amount_krw"], usd["currency"]), (2.99, None, "USD"))
        self.assertEqual(db.docs[("users", "u1")]["credits"], 30)

    def test_payment_cannot_be_claimed_by_another_user(self):
        db, store = make_store()
        store.grant_purchase("u1", "a@example.com", "t_pay1", 15, "KRW", 3000)
        with self.assertRaises(PermissionError):
            store.grant_purchase("u2", "b@example.com", "t_pay1", 15, "KRW", 3000)
        self.assertNotIn(("users", "u2"), db.docs)

    def test_existing_user_fields_are_kept(self):
        db, store = make_store()
        db.docs[("users", "u1")] = {"email": "a@example.com", "free_used": 2, "credits": 1, "created_at": "x"}
        store.grant_purchase("u1", "a@example.com", "t_pay1", 28, "KRW", 5000)
        self.assertEqual(db.docs[("users", "u1")],
                         {"email": "a@example.com", "free_used": 2, "credits": 29, "created_at": "x"})


class VerifyPaymentEndpointTest(unittest.IsolatedAsyncioTestCase):
    def portone_response(self, email="a@example.com", total=3000, currency="KRW", status="PAID"):
        body = {"id": "t_u1xxxxxxxxxxxx_1", "status": status, "currency": currency,
                "amount": {"total": total}, "customer": {"email": email}}
        return mock.Mock(status_code=200, json=lambda: body)

    async def call(self, response, user=None, request=None, store=None):
        user = user or {"sub": "u1xxxxxxxxxxxxxxxx", "email": "a@example.com"}
        request = request or app.PaymentVerifyRequest(payment_id="t_u1xxxxxxxxxxxx_1", amount=3000)
        store = store or make_store()[1]
        with mock.patch("httpx.AsyncClient.get", mock.AsyncMock(return_value=response)), \
                mock.patch.object(app, "get_credit_store", return_value=store):
            return await app.verify_payment(request, user=user)

    async def test_grants_credits_for_the_logged_in_owner(self):
        db, store = make_store()
        result = await self.call(self.portone_response(), store=store)
        self.assertEqual((result["credits"], result["balance"]), (15, 15))
        self.assertEqual(db.docs[("users", "u1xxxxxxxxxxxxxxxx")]["credits"], 15)

    async def test_someone_elses_payment_is_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            await self.call(self.portone_response(email="victim@example.com"))
        self.assertEqual(caught.exception.status_code, 403)

    async def test_missing_payer_email_falls_back_to_payment_id_prefix(self):
        ok = await self.call(self.portone_response(email=""))
        self.assertEqual(ok["credits"], 15)
        other = app.PaymentVerifyRequest(payment_id="t_someoneelse000_1", amount=3000)
        with self.assertRaises(HTTPException):
            await self.call(self.portone_response(email=""), request=other)

    async def test_unpaid_or_wrong_amount_is_rejected_and_nothing_is_granted(self):
        db, store = make_store()
        with self.assertRaises(HTTPException):
            await self.call(self.portone_response(status="READY"), store=store)
        with self.assertRaises(HTTPException):
            await self.call(self.portone_response(total=5000), store=store)
        self.assertEqual(db.docs, {})

    async def test_replaying_the_same_payment_does_not_grant_twice(self):
        db, store = make_store()
        await self.call(self.portone_response(), store=store)
        again = await self.call(self.portone_response(), store=store)
        self.assertTrue(again["already"])
        self.assertEqual(db.docs[("users", "u1xxxxxxxxxxxxxxxx")]["credits"], 15)


class ReadingEndpointChargeTest(unittest.IsolatedAsyncioTestCase):
    def reading_request(self):
        return app.ReadingRequest(question="q", spread_name="s", language="ko", cards=[])

    async def test_no_credit_returns_402_and_never_calls_the_ai(self):
        store = mock.Mock(consume_reading=mock.Mock(return_value={"kind": "none", "free_used": 2, "credits": 0}))
        with mock.patch.object(app, "get_credit_store", return_value=store), \
                mock.patch.object(app.anthropic, "AsyncAnthropic") as ai:
            with self.assertRaises(HTTPException) as caught:
                await app.tarot_reading(self.reading_request(), user={"sub": "u1", "email": "a@example.com"})
        self.assertEqual((caught.exception.status_code, caught.exception.detail), (402, "no_credit"))
        ai.assert_not_called()

    async def test_response_reports_balance_headers(self):
        store = mock.Mock(consume_reading=mock.Mock(return_value={"kind": "credit", "free_used": 2, "credits": 9}))

        class Stream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            @property
            def text_stream(self):
                async def chunks():
                    yield "hi"
                return chunks()

        client = mock.Mock(messages=mock.Mock(stream=mock.Mock(return_value=Stream())))
        with mock.patch.object(app, "get_credit_store", return_value=store), \
                mock.patch.object(app.anthropic, "AsyncAnthropic", return_value=client):
            response = await app.tarot_reading(self.reading_request(), user={"sub": "u1", "email": "a@example.com"})
            [_ async for _ in response.body_iterator]
        self.assertEqual(response.headers["x-credits"], "9")
        self.assertEqual(response.headers["x-entitlement"], "credit")

    async def test_failure_before_any_text_restores_the_charge(self):
        store = mock.Mock(consume_reading=mock.Mock(return_value={"kind": "credit", "free_used": 2, "credits": 9}),
                          restore_reading=mock.Mock())

        class Boom:
            async def __aenter__(self):
                raise RuntimeError("api down")

            async def __aexit__(self, *_):
                return False

        client = mock.Mock(messages=mock.Mock(stream=mock.Mock(return_value=Boom())))
        with mock.patch.object(app, "get_credit_store", return_value=store), \
                mock.patch.object(app.anthropic, "AsyncAnthropic", return_value=client):
            response = await app.tarot_reading(self.reading_request(), user={"sub": "u1", "email": "a@example.com"})
            with self.assertRaises(RuntimeError):
                [_ async for _ in response.body_iterator]
        store.restore_reading.assert_called_once_with("u1", "credit")


class AdminTest(unittest.TestCase):
    def test_admin_requires_verified_email(self):
        self.assertTrue(app.is_admin({"email": "museumst@gmail.com", "email_verified": True}))
        self.assertFalse(app.is_admin({"email": "museumst@gmail.com", "email_verified": False}))
        self.assertFalse(app.is_admin({"email": "other@gmail.com", "email_verified": True}))
        self.assertFalse(app.is_admin({}))


if __name__ == "__main__":
    unittest.main()
