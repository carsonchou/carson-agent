"""收了錢就該給東西:tier 判不出來的付費訂閱者,不可以從所有寄送名單消失。

背景(HUNT_silent_failures S1,2026-07-16):
`classify_tier` 靠「金額+幣別」猜層級,而 normalize.py 自己寫著 Portaly 欄位「皆為暫定、
待校準」。實測 4 種真實情境全部落到 tier="unknown":金額以分為單位(14900)/幣別寫 NTD/
首月促銷價 49/amount 欄位名猜錯→default 0。

舊行為的災難:TIER_RANK["unknown"]=0 < basic(1) → export_active("basic") 與
export_active("full") **兩張名單都排除他** → 付 149/月的人永遠收不到任何一期。
而每一環都回報成功:HTTP 200 ✓ 名冊 status=active ✓ /health +1 ✓ 金流有帳 ✓
開通信也寄了 ✓ —— 唯獨他不在名單裡,零 log。發現時機:訂戶抱怨(數週後)。

本測試群釘死兩件事:
1. **業務不變量**:任何 status=active 的訂閱者,都必須至少出現在一張會寄的名單裡。
   這是 test_integration_send_list 沒釘到的那條縫 —— 它只釘 schema 形狀,
   沒問「所有付費 active 訂閱者都拿得到東西嗎」。
2. **雙向**:unknown 保底進 basic(有利方向)、但**不得**混進 full(反方向)。
   #1/#3/S1 全部死在「測試在產生 unknown 的那一刻就停了,沒人問『然後呢』」。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _util  # noqa: F401  (掛 sys.path)
from webhook import subscribers
from webhook.config import classify_tier


def _book(**tiers) -> Path:
    p = Path(tempfile.mkdtemp()) / "subs.json"
    p.write_text(json.dumps({
        f"{k}@e.com": {"email": f"{k}@e.com", "name": k, "tier": v, "status": "active",
                       "platform": "portaly", "amount": 149, "currency": "TWD"}
        for k, v in tiers.items()}, ensure_ascii=False), encoding="utf-8")
    return p


class TestUnknownTierStillDelivered(unittest.TestCase):
    # ── 業務不變量:付費 active 的人不可以從所有名單消失 ──
    def test_active_subscriber_never_vanishes_from_every_list(self):
        for tier in ("basic", "full", "full_annual", "unknown", "weird_new_tier", ""):
            with self.subTest(tier=tier):
                p = _book(paid=tier)
                lists = {t: subscribers.export_active(p, tier=t) for t in ("basic", "full")}
                self.assertTrue(
                    any(lists.values()),
                    f"tier={tier!r} 的付費 active 訂閱者從兩張名單都消失了 —— 收了錢什麼都不給")

    def test_unknown_tier_falls_back_to_basic(self):
        p = _book(paid="unknown")
        self.assertEqual(len(subscribers.export_active(p, tier="basic")), 1,
                         "unknown 應保底寄基礎版(收了錢就該給東西)")

    # ── 反方向:保底不可以變成「送出完整版」──
    def test_unknown_tier_does_not_leak_into_full(self):
        p = _book(paid="unknown")
        self.assertEqual(len(subscribers.export_active(p, tier="full")), 0,
                         "判不出來就送完整版 = 白送 full-only 內容")

    def test_real_tiers_unaffected(self):
        """保底規則不可污染正常分層(basic 仍不該收到 full)。"""
        p = _book(b="basic", f="full", a="full_annual")
        basic = {r["email"] for r in subscribers.export_active(p, tier="basic")}
        full = {r["email"] for r in subscribers.export_active(p, tier="full")}
        self.assertEqual(basic, {"b@e.com", "f@e.com", "a@e.com"})   # full 也收 basic 內容
        self.assertEqual(full, {"f@e.com", "a@e.com"})               # basic 不得混進 full

    def test_cancelled_unknown_not_delivered(self):
        """保底只對 active —— 取消的人不可以因為 tier=unknown 就被保底寄。"""
        p = _book(paid="unknown")
        book = json.loads(p.read_text(encoding="utf-8"))
        book["paid@e.com"]["status"] = "cancelled"
        p.write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(subscribers.export_active(p, tier="basic"), [])

    # ── 觸發 unknown 的真實情境(證明這不是假想) ──
    def test_realistic_inputs_produce_unknown(self):
        """會落到 unknown 的真實情境 —— 證明保底規則不是為假想問題而寫。

        註(2026-07-17):原本這裡把 49 當「首月促銷價」的 unknown 範例,但 Carson 已把
        basic 正價定為 NT$49 → 49 現在**應該**判 basic。當初留的「若已能正確分層,
        本測試的前提要更新」就是指這一刻。已換成離牌價夠遠的促銷價 19。
        """
        cases = [(14900, "TWD", "金額以分為單位"), (149, "NTD", "幣別寫 NTD"),
                 (19, "TWD", "首月超低促銷價"), (0, "TWD", "amount 欄位名猜錯")]
        for amt, cur, desc in cases:
            with self.subTest(desc=desc):
                self.assertEqual(classify_tier(amt, cur), "unknown",
                                 f"{desc} 若已能正確分層,本測試的前提要更新")

    def test_unknown_is_announced_not_silent(self):
        """零告警是這個 codebase 反覆中招的病根 —— 保底時必須留下人看得到的痕跡。"""
        import io
        from contextlib import redirect_stdout
        p = _book(paid="unknown")
        buf = io.StringIO()
        with redirect_stdout(buf):
            subscribers.export_active(p, tier="basic")
        out = buf.getvalue()
        self.assertIn("paid@e.com", out, "保底了卻不出聲 = 又一個靜默失敗")
        self.assertIn("tier", out.lower())


if __name__ == "__main__":
    unittest.main()
