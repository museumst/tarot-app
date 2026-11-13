"""크레딧·무료 횟수를 서버가 관리한다 (Firestore 서비스 계정).

예전에는 브라우저가 Firestore 의 `users/{uid}` 를 직접 고쳤기 때문에, 사용자가 개발자 도구로 자기 크레딧을
마음대로 늘릴 수 있었다. 이제는 아래 세 가지 변경만 서버가 하고, Firestore 보안 규칙은 클라이언트의 쓰기를 막는다.

  - grant_purchase : 결제 확인 후 크레딧 지급 (결제번호당 1번만 — 같은 결제를 다시 확인해도 중복 지급 없음)
  - consume_reading: 리딩 1회 시작 시 무료 횟수 → 크레딧 순으로 차감 (관리자는 차감 없음)
  - restore_reading: 리딩이 시작도 못 하고 실패했을 때 차감 복구

모든 변경은 트랜잭션 안에서 읽고 쓰므로 동시에 요청이 와도 잔액이 꼬이지 않는다.
"""
from typing import Optional

FREE_LIMIT = 3          # static/index.html·acct-bar.js 의 FREE_LIMIT 과 같다
USE_VALUE_KRW = 100     # 이용내역에 기록하는 '사용 1회' 표시 금액(기존 기록과 동일)


def plan_consume(user: Optional[dict], is_admin: bool, free_limit: int = FREE_LIMIT) -> str:
    """어떤 방식으로 차감할지: 'admin' | 'free' | 'credit' | 'none'."""
    if is_admin:
        return "admin"
    data = user or {}
    if int(data.get("free_used") or 0) < free_limit:
        return "free"
    if int(data.get("credits") or 0) > 0:
        return "credit"
    return "none"


class CreditStore:
    def __init__(self, db, transactional=None, server_ts=None):
        self.db = db
        if transactional is None or server_ts is None:
            from google.cloud import firestore   # 지연 import (테스트에서는 주입한다)
            transactional = transactional or firestore.transactional
            server_ts = server_ts if server_ts is not None else firestore.SERVER_TIMESTAMP
        self._transactional = transactional
        self._ts = server_ts

    # ── 공통 ────────────────────────────────────────────────────────────────
    def _run(self, fn):
        return self._transactional(fn)(self.db.transaction())

    def _user_ref(self, uid):
        return self.db.collection("users").document(uid)

    @staticmethod
    def _counters(snap):
        data = snap.to_dict() if snap.exists else {}
        data = data or {}
        return data, int(data.get("free_used") or 0), int(data.get("credits") or 0)

    def _base_fields(self, snap, email):
        """문서가 아직 없으면 기본 필드를 함께 만든다(클라이언트가 만든 문서가 있으면 그대로 둔다)."""
        return {} if snap.exists else {"email": email or None, "created_at": self._ts}

    # ── 결제 확인 후 크레딧 지급 ────────────────────────────────────────────
    def grant_purchase(self, uid: str, email: str, payment_id: str, credits: int,
                       currency: str, amount_minor: int) -> dict:
        user_ref = self._user_ref(uid)
        pay_ref = self.db.collection("payments").document(payment_id)

        def run(tx):
            user = user_ref.get(transaction=tx)
            pay = pay_ref.get(transaction=tx)
            data, free_used, balance = self._counters(user)
            if pay.exists:
                prior = (pay.to_dict() or {}).get("uid")
                if prior != uid:
                    raise PermissionError("payment belongs to another user")
                return {"credits": balance, "free_used": free_used, "already": True}
            new_balance = balance + credits
            tx.set(user_ref, {**self._base_fields(user, email), "free_used": free_used, "credits": new_balance}, merge=True)
            tx.set(pay_ref, {"uid": uid, "credits": credits, "currency": currency, "amount": amount_minor,
                             "grantedAt": self._ts})
            shown = amount_minor / 100 if currency == "USD" else amount_minor    # 기존 이용내역과 같은 표기
            tx.set(user_ref.collection("creditHistory").document(), {
                "type": "charge", "credits": credits, "currency": currency, "amount": shown,
                "amount_krw": shown if currency == "KRW" else None,
                "purpose": f"타로 크레딧 {credits}회 충전", "paymentId": payment_id, "date": self._ts})
            return {"credits": new_balance, "free_used": free_used, "already": False}

        return self._run(run)

    # ── 리딩 차감 ───────────────────────────────────────────────────────────
    def consume_reading(self, uid: str, email: str, is_admin: bool) -> dict:
        user_ref = self._user_ref(uid)

        def run(tx):
            user = user_ref.get(transaction=tx)
            data, free_used, credits = self._counters(user)
            kind = plan_consume(data, is_admin)
            if kind in ("none", "admin"):
                return {"kind": kind, "free_used": free_used, "credits": credits}
            fields = self._base_fields(user, email)
            if kind == "free":
                free_used += 1
            else:
                credits -= 1
                tx.set(user_ref.collection("creditHistory").document(), {
                    "type": "use", "credits": -1, "currency": "KRW", "amount": USE_VALUE_KRW,
                    "amount_krw": USE_VALUE_KRW, "purpose": "타로 리딩", "date": self._ts})
            tx.set(user_ref, {**fields, "free_used": free_used, "credits": credits}, merge=True)
            return {"kind": kind, "free_used": free_used, "credits": credits}

        return self._run(run)

    def restore_reading(self, uid: str, kind: str) -> dict:
        if kind not in ("free", "credit"):
            return {}
        user_ref = self._user_ref(uid)

        def run(tx):
            user = user_ref.get(transaction=tx)
            _, free_used, credits = self._counters(user)
            if kind == "free":
                free_used = max(0, free_used - 1)
            else:
                credits += 1
                tx.set(user_ref.collection("creditHistory").document(), {
                    "type": "use", "credits": 1, "currency": "KRW", "amount": USE_VALUE_KRW,
                    "amount_krw": USE_VALUE_KRW, "purpose": "리딩 생성 실패로 크레딧 복구", "date": self._ts})
            tx.set(user_ref, {"free_used": free_used, "credits": credits}, merge=True)
            return {"free_used": free_used, "credits": credits}

        return self._run(run)
