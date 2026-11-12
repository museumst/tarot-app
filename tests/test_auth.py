import time
import unittest
from unittest import mock

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from starlette.requests import Request

import app

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PROJECT = app.FIREBASE_PROJECT_ID


def make_token(provider="google.com", uid="user-1", key=_KEY, **overrides):
    now = int(time.time())
    claims = {
        "iss": f"https://securetoken.google.com/{_PROJECT}", "aud": _PROJECT, "sub": uid,
        "iat": now - 10, "exp": now + 3600, "firebase": {"sign_in_provider": provider},
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-kid"})


def make_request(token=None, scheme="Bearer"):
    headers = [(b"authorization", f"{scheme} {token}".encode())] if token is not None else []
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


async def fake_signing_key(kid):
    return _KEY.public_key() if kid == "test-kid" else None


class RequireUserTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = mock.patch.object(app, "_get_signing_key", fake_signing_key)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def assert_rejected(self, request, status=401):
        with self.assertRaises(HTTPException) as caught:
            await app.require_user(request)
        self.assertEqual(caught.exception.status_code, status)

    async def test_missing_or_malformed_header_is_rejected(self):
        await self.assert_rejected(make_request(None))
        await self.assert_rejected(make_request("", "Bearer"))
        await self.assert_rejected(make_request("abc", "Basic"))
        await self.assert_rejected(make_request("not-a-jwt"))

    async def test_bad_tokens_are_rejected(self):
        await self.assert_rejected(make_request(make_token(exp=int(time.time()) - 60)))      # 만료
        await self.assert_rejected(make_request(make_token(aud="other-project")))            # 다른 프로젝트
        await self.assert_rejected(make_request(make_token(iss="https://evil.example")))     # 다른 발급자
        await self.assert_rejected(make_request(make_token(key=_OTHER_KEY)))                 # 위조 서명
        await self.assert_rejected(make_request(make_token(sub="")))                         # sub 없음

    async def test_google_account_passes(self):
        claims = await app.require_user(make_request(make_token()))
        self.assertEqual(claims["sub"], "user-1")

    async def test_anonymous_account_is_rejected(self):
        # 비회원 결제를 없앴으므로 익명 계정은 리딩 API 를 쓸 수 없다(크레딧이 있어도)
        await self.assert_rejected(make_request(make_token(provider="anonymous", uid="guest-1")), status=403)


class ProtectedEndpointsTest(unittest.IsolatedAsyncioTestCase):
    async def test_ai_endpoints_require_login(self):
        transport = httpx.ASGITransport(app=app.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            spread = await client.post("/api/select-spread", json={"question": "q", "language": "ko", "mode": "reading"})
            reading = await client.post("/api/reading", json={"question": "q", "spread_name": "s", "language": "ko", "cards": []})
        self.assertEqual(spread.status_code, 401)
        self.assertEqual(reading.status_code, 401)


if __name__ == "__main__":
    unittest.main()
