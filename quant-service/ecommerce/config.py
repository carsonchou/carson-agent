# -*- coding: utf-8 -*-
"""config.py — 電商 v2 定價 / tier 名稱 / 品牌字串(單一事實來源)。

Carson 對定價與 tier 名稱的最終拍板還在等;引擎一律讀本檔,他微調只改這裡,不重工。
週報引擎(weekly_report_v2)只讀 BRAND / SUBSCRIPTION / SECTION_TIERS。
"""
from __future__ import annotations

# ── 品牌 ─────────────────────────────────────────────────────────────────────
BRAND = {
    "name_zh": "量化阿森",
    "name_en": "Carson Quant",
    "product_zh": "台股全市場週報",
    "product_en": "Taiwan Whole-Market Weekly",
    "youtube": "https://www.youtube.com/@carsonquant",
    "tagline_zh": "全市場掃描 · 法人籌碼 · 真實訊號追蹤",
}

# ── 訂閱雙層 + 年繳(NT$ / US$)——**單一事實來源**,改這裡即可 ────────────────
# 2026-07-16 Carson 拍板(依 REVIEW_weekly_value 的獨立評審):
#  · basic 99 → 49:評審兩次判定「basic 四段沒有任何不可替代內容」,真正的風險不是
#    「沒人升級」而是**沒人會買 basic**。降到衝動價當漏斗入口,不當獲利層。
#  · 國際版 15 → 9:規格原本宣稱「US$15 是對 Substack $30.6 的低價卡位」,但複查
#    發現那個 $30.6 是**誤引**(該來源標題是 Top 15 **by Revenue**,倖存者偏誤子集;
#    原文實際講 $5–20、主群集 $5–15)→ **US$15 是天花板不是卡位價**。重訂 US$5/9。
#  · 年繳:**暫緩**(enabled=False)。續訂殺手會在第 2–3 個月暴露,年繳等於把不滿意的
#    客戶鎖 12 個月;對只有 ~30 訂閱的頻道是負資產。補完 S7 點播且有真實續訂率後再開。
# 台灣競品實查(2026-07-16):財經M平方 PRO ≈NT$533/月、CMoney 籌碼K線 ≈NT$299/月
# → NT$149 定位成立(M平方的 1/4、CMoney 的 1/2),但三者不直接對打,沒有價格參考點
# 可搭便車,買家會純用「149 換到什麼」評判。
SUBSCRIPTION = {
    "basic":  {"name_zh": "基礎版", "name_en": "Basic",  "ntd_month": 49,  "usd_month": 5},
    "full":   {"name_zh": "完整版", "name_en": "Full",   "ntd_month": 149, "usd_month": 9},
    "annual": {"name_zh": "完整版年繳", "name_en": "Full Annual", "ntd_year": 1290,
               "usd_year": 99, "enabled": False},
    "platform_tw": "Portaly",
    "platform_intl": "Whop",
}

# ── Section 分層:★=基礎版可見,full=完整版限定(對齊商業規格 §2.3)────────────
# 值為 "basic" 或 "full";引擎據此標 tier 徽章,並在 tier="basic" 出報告時隱藏 full section。
SECTION_TIERS = {
    "S1": "basic",   # 市場溫度與體質
    "S2": "basic",   # 板塊輪動熱力
    "S3": "basic",   # 全市場強弱榜
    "S4": "full",    # 法人與籌碼週流向
    "S5": "full",    # 估值位階雷達
    "S6": "basic",   # 訊號追蹤 · 誠實成績單(招牌)
    "S7": "full",    # 本週深度體檢個股
    "S8": "full",    # 結構基準(月度輪替)
}

# 一次性 SKU 定價 + 名稱 + 平台 + 出哪些語系(product_factory_v2 讀;週報引擎不用)。
# langs:要產的語系(對齊商業規格 §3——國際只保留 C1/C2 英版,tripwire 只出中版)。
# platform_zh / platform_en:上架平台(生成物分目錄用)。
ONE_OFF = {
    "T1": {"name_zh": "台股定投追蹤模板", "name_en": "Taiwan DCA Tracker",
           "ntd": 99, "usd": 5, "langs": ["zh"], "platform_zh": "shopee", "platform_en": "gumroad"},
    "T2": {"name_zh": "個股體檢單檔報告", "name_en": "Single-Stock Health-Check",
           "ntd": 149, "usd": 7, "langs": ["zh"], "platform_zh": "shopee", "platform_en": "gumroad"},
    "T3": {"name_zh": "個股體檢多檔組合(最多5檔)", "name_en": "Multi-Stock Health-Check Bundle (up to 5)",
           "ntd": 100, "usd": 4, "langs": ["zh"], "platform_zh": "ecpay", "platform_en": "gumroad"},
    # T4:09-18 Carson 拍板的 50 檔大量方案,NT$500。只走 ECPay 中文站,USD 價未定案 → None。
    "T4": {"name_zh": "個股體檢多檔組合(最多50檔)", "name_en": "Multi-Stock Health-Check Bundle (up to 50)",
           "ntd": 500, "usd": None, "langs": ["zh"], "platform_zh": "ecpay", "platform_en": None},
    "C1": {"name_zh": "台股全市場回測數據包", "name_en": "Taiwan Full-Market Backtest Pack",
           "ntd": 990, "usd": 35, "langs": ["zh", "en"], "platform_zh": "portaly", "platform_en": "gumroad"},
    "C2": {"name_zh": "台股權值股體檢合輯", "name_en": "Taiwan Blue-Chip Health-Check Bundle",
           "ntd": 1280, "usd": 39, "langs": ["zh", "en"], "platform_zh": "portaly", "platform_en": "gumroad"},
}

# L0 免費磁鐵(抓 Email/TG,不收費;每日重生,不賣過期)。
MAGNETS = {
    "M1": {"name_zh": "台股當沖適格清單", "name_en": "TW Day-Trade Eligibility List",
           "ntd": 0, "usd": 0, "langs": ["zh"], "platform_zh": "magnet", "platform_en": "magnet"},
    "M2": {"name_zh": "單檔旗艦體檢報告(台積電)", "name_en": "Flagship Health-Check (TSMC)",
           "ntd": 0, "usd": 0, "langs": ["zh"], "platform_zh": "magnet", "platform_en": "magnet"},
}
