"""定價只能有一個事實來源:webhook 的層級表必須從 ecommerce/config.SUBSCRIPTION 導出。

背景(2026-07-17 端到端測試抓到):
webhook/config.py 原本硬寫自己一份 `SUBSCRIPTION_TIERS`(basic TWD 99 / full USD 15 /
annual USD 129)。Carson 把 basic 降成 49、full USD 改 9、annual 停售之後,**兩張表靜默分岔**:
  classify_tier(49, "TWD") → "unknown"   (|49-99|=50 > 容差 max(20, 99*0.25)=24.75)
→ 每一個付 49 的基礎版訂閱者名冊 tier 全錯。若不是 subscribers.export_active 剛好有
「unknown 保底寄 basic」的防線接住,**每個付 49 的人都會一封都收不到**。

這與 make_landing 把 NT$99 寫死在 HTML 是同型病:**多個事實來源 + 不同步時零告警**。
本測試群把它變成結構上不可能:層級表用導出的,分岔就沒有存在的空間;
若有人日後又手寫回去,下面的測試會紅。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import _util  # noqa: F401  (掛 sys.path 到 quant-service)
from webhook.config import SUBSCRIPTION_TIERS, classify_tier

_ECOM = Path(__file__).resolve().parents[2] / "ecommerce"
if str(_ECOM) not in sys.path:
    sys.path.insert(0, str(_ECOM))
import config as ecom_cfg  # noqa: E402  (quant-service/ecommerce/config.py)


class TestPricingSingleSource(unittest.TestCase):
    def test_tiers_match_the_single_source(self):
        """webhook 的層級表逐值等於 ecommerce/config.SUBSCRIPTION —— 不容許第二份定價。"""
        src = ecom_cfg.SUBSCRIPTION
        got = {t["tier"]: t for t in SUBSCRIPTION_TIERS}
        self.assertEqual(got["basic"]["TWD"], src["basic"]["ntd_month"])
        self.assertEqual(got["basic"]["USD"], src["basic"]["usd_month"])
        self.assertEqual(got["full"]["TWD"], src["full"]["ntd_month"])
        self.assertEqual(got["full"]["USD"], src["full"]["usd_month"])

    def test_current_prices_classify_correctly(self):
        """真實情境:照現行牌價付款的人,tier 必須判得出來(不可落到 unknown)。"""
        src = ecom_cfg.SUBSCRIPTION
        cases = [
            (src["basic"]["ntd_month"], "TWD", "basic"),
            (src["full"]["ntd_month"], "TWD", "full"),
            (src["basic"]["usd_month"], "USD", "basic"),
            (src["full"]["usd_month"], "USD", "full"),
        ]
        for amount, cur, want in cases:
            with self.subTest(amount=amount, cur=cur):
                self.assertEqual(
                    classify_tier(amount, cur), want,
                    f"照牌價付 {amount} {cur} 卻判成 unknown —— 名冊 tier 會全錯")

    def test_disabled_tier_excluded(self):
        """停售的層級不參與分類(年繳目前 enabled=False)。"""
        if ecom_cfg.SUBSCRIPTION.get("annual", {}).get("enabled") is False:
            self.assertNotIn("full_annual", {t["tier"] for t in SUBSCRIPTION_TIERS},
                             "已停售的年繳不該還在分類表裡")

    def test_price_change_propagates(self):
        """改單一事實來源 → webhook 端跟著變(證明是導出的,不是巧合相等)。"""
        import importlib
        orig = ecom_cfg.SUBSCRIPTION["basic"]["ntd_month"]
        try:
            ecom_cfg.SUBSCRIPTION["basic"]["ntd_month"] = 777
            import webhook.config as wc
            regenerated = wc._tiers_from_single_source()
            basic = {t["tier"]: t for t in regenerated}["basic"]
            self.assertEqual(basic["TWD"], 777,
                             "改了單一事實來源,webhook 層級表卻沒跟上 → 又是兩份定價")
        finally:
            ecom_cfg.SUBSCRIPTION["basic"]["ntd_month"] = orig

    def test_no_hardcoded_price_literals_in_tier_table(self):
        """原始碼層級:層級表不得又被手寫回硬編碼數字。"""
        src = (Path(__file__).resolve().parents[1] / "config.py").read_text(encoding="utf-8")
        i = src.find("SUBSCRIPTION_TIERS: list[dict] =")
        self.assertGreater(i, 0, "找不到 SUBSCRIPTION_TIERS 宣告 —— 掃描器失效")
        decl = src[i:i + 200]
        self.assertNotIn('"TWD":', decl,
                         "SUBSCRIPTION_TIERS 又被硬寫定價了 —— 必須從 SUBSCRIPTION 導出")


if __name__ == "__main__":
    unittest.main()
