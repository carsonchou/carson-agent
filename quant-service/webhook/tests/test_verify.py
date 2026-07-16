"""驗簽層測試：primitives timing-safe 比對 + guards fail-closed（密鑰未設→503、不符→401）。"""
from __future__ import annotations

import unittest

import _util  # noqa: F401  掛 sys.path
from fastapi import HTTPException
from webhook import verify
from webhook.config import Settings


class TestPrimitives(unittest.TestCase):
    def test_hmac_hex_roundtrip(self):
        body = b'{"a":1}'
        sig = _util.sign_hex("secret", body)
        self.assertTrue(verify.verify_hmac_hex("secret", body, sig))
        self.assertTrue(verify.verify_hmac_hex("secret", body, sig.upper()))  # 大小寫容錯

    def test_hmac_hex_rejects_wrong(self):
        body = b'{"a":1}'
        self.assertFalse(verify.verify_hmac_hex("secret", body, _util.sign_hex("other", body)))
        self.assertFalse(verify.verify_hmac_hex("", body, "x"))        # 無密鑰
        self.assertFalse(verify.verify_hmac_hex("secret", body, ""))    # 無簽章

    def test_standard_webhooks(self):
        secret = "whsec_" + __import__("base64").b64encode(b"k").decode()
        body = b'{"type":"payment.succeeded"}'
        sig = _util.sign_standard_webhooks(secret, "id1", "1700000000", body)
        self.assertTrue(verify.verify_standard_webhooks(secret, "id1", "1700000000", body, sig))
        self.assertFalse(verify.verify_standard_webhooks(secret, "id1", "1700000000", body, "v1,bad"))

    def test_token_ok(self):
        self.assertTrue(verify.token_ok("abc", "abc"))
        self.assertFalse(verify.token_ok("abc", "abcd"))
        self.assertFalse(verify.token_ok("", "abc"))


class TestGuards(unittest.TestCase):
    def _s(self, **over):
        return Settings(**over)

    def test_gumroad_missing_token_503(self):
        with self.assertRaises(HTTPException) as c:
            verify.require_gumroad(self._s(), {"seller_id": "X"}, "t")
        self.assertEqual(c.exception.status_code, 503)

    def test_gumroad_bad_token_401(self):
        s = self._s(gumroad_ping_token="good", gumroad_seller_id="X")
        with self.assertRaises(HTTPException) as c:
            verify.require_gumroad(s, {"seller_id": "X"}, "bad")
        self.assertEqual(c.exception.status_code, 401)

    def test_gumroad_bad_seller_401(self):
        s = self._s(gumroad_ping_token="good", gumroad_seller_id="X")
        with self.assertRaises(HTTPException) as c:
            verify.require_gumroad(s, {"seller_id": "Y"}, "good")
        self.assertEqual(c.exception.status_code, 401)

    def test_gumroad_ok(self):
        s = self._s(gumroad_ping_token="good", gumroad_seller_id="X")
        verify.require_gumroad(s, {"seller_id": "X"}, "good")  # 不 raise

    def test_lemonsqueezy_missing_secret_503(self):
        with self.assertRaises(HTTPException) as c:
            verify.require_lemonsqueezy(self._s(), b"{}", "sig")
        self.assertEqual(c.exception.status_code, 503)

    def test_portaly_bad_sig_401(self):
        s = self._s(portaly_secret="psec")
        with self.assertRaises(HTTPException) as c:
            verify.require_portaly(s, b'{"x":1}', "deadbeef")
        self.assertEqual(c.exception.status_code, 401)

    def test_whop_missing_secret_503(self):
        with self.assertRaises(HTTPException) as c:
            verify.require_whop(self._s(), b"{}", "i", "t", "s")
        self.assertEqual(c.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
