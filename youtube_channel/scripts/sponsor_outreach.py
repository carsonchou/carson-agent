#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sponsor_outreach.py — 贊助/接案開發信系統(Carson 已授權自動寄)。

⚠️ 誠實前提(讀 STUDIO/REPORTS/贊助商名單.md 後的真相):名單裡大多數是**官網 affiliate 表單申請**
(Bitget/MEXC/Perplexity/TradingView 都是填官網表單,不是寄 email 的對象);真正能「寄 email」的
目標只有少數(Pionex service@pionex.com 問升級 Creator 專案、CMoney/券商 需 BD 洽談但無公開信箱)。
所以「自動寄 30-50 家」的前提不成立——本工具:
  ① 寄真正的 EMAIL 目標(EMAIL_TARGETS,目前僅 Pionex)。
  ② 對表單申請型,產一份「一鍵申請清單」(URL + 預填頻道簡介),給 Carson 自己送(表單無法代填,涉個資/KYC)。

紅線(Carson 授權自動寄,但寄信不可逆、對外代表 Carson,故綁三閂):
  (a) 每封寄前須經 fresh-context agent 獨立驗證(收件人/內容/誠信/無亂承諾)——本檔不自跑驗證,
      由主流程在 --send 前派驗證 agent;--send 需帶 --verified 旗標(代表已過獨立驗證)才會真寄。
  (b) 第一批寄出前渲染成品+收件清單給 Carson 過目(--dry-run 就是這個)。
  (c) 只寄信,絕不簽約/動錢(本檔無任何付款/簽署呼叫)。
需 env:GMAIL_ADDRESS + GMAIL_APP_PASSWORD(Carson 提供 App Password;沒有就只能 --dry-run)。

用法:
  python scripts/sponsor_outreach.py --dry-run     # (預設)印出所有信+收件人+表單清單,不寄
  python scripts/sponsor_outreach.py --send --verified   # 真寄(需 Gmail creds + 已過獨立驗證)
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"

# 真正的 EMAIL 收件目標(只放有公開信箱、且適合 email 洽談的;表單申請型不放這)
EMAIL_TARGETS = [
    {
        "name": "Pionex(升級 Creator 專案)",
        "to": "service@pionex.com",
        "subject": "量化阿森 Carson Quant｜現有合作夥伴，想請教升級 Creator 專案",
        "kind": "pionex_upgrade",
    },
]

# 表單申請型(無法代填→給 Carson 清單自己送)
FORM_TARGETS = [
    ("Perplexity(官方正版 affiliate·$15/有效名單·零風險,優先)", "https://partners.dub.co/programs/perplexity"),
    ("Bitget affiliate(門檻極低 100 粉絲·審核1天)", "https://www.bitget.com/affiliates"),
    ("MEXC affiliate(佣金業界最高之一·審核~7天)", "https://affiliates.mexc.com/"),
    ("TradingView Partner(內容契合度最高·先產一支台股圖表教學片再置入)", "https://www.tradingview.com/partner-program/"),
]


def _media_stats():
    """從最新媒體包抽近28天觀看/完播/總片數(找不到就回佔位,誠實標『待補』)。"""
    stats = {"views28": "〔近28天觀看·待補〕", "avgpct": "〔完播率·待補〕", "total": "〔總片數·待補〕"}
    kits = sorted(REPORTS.glob("媒體包_*.md"), reverse=True)
    if kits:
        txt = kits[0].read_text(encoding="utf-8", errors="replace")
        m = re.search(r"近 28 天頻道觀看數\s*\|\s*([\d,]+)", txt)
        if m:
            stats["views28"] = m.group(1)
        m = re.search(r"近 28 天平均完播率\s*\|\s*([\d.]+%)", txt)
        if m:
            stats["avgpct"] = m.group(1)
        m = re.search(r"總影片數\s*\|\s*([\d,]+)", txt)
        if m:
            stats["total"] = m.group(1)
    return stats


def build_email(target, stats):
    """組一封誠實開發信(繁中);小頻道就誠實講規模,不假裝大頻道(對方一眼看得出真假)。"""
    if target["kind"] == "pionex_upgrade":
        body = f"""Pionex 團隊 您好，

我是「量化阿森 Carson Quant」的經營者 Carson，我們是既有的 Pionex 聯盟合作夥伴，頻道主題是量化交易、自動交易機器人與台股技術分析，用真實回測數據跟觀眾溝通，不喊單、不誇大報酬。

寫信是想請教：我們近期是否符合升級到 **Creator 專案** 的資格？

- 頻道已累積 {stats['total']} 支影片，內容全誠實回測/實測導向
- 近 28 天頻道觀看 {stats['views28']}、平均完播率 {stats['avgpct']}
- 近期熱門影片單支觀看已達 500+（符合 Creator 專案門檻之一）
- 現有 Pionex 聯盟合作已產生實際轉換與入帳，證明我們的觀眾會真的點連結、真的行動

我們仍是成長中的頻道，但受眾精準——想自動化交易又怕被割的台灣散戶。想了解 Creator 專案的佣金結構與素材支援，看能否讓合作更長期、更有效。

謝謝撥冗，期待回覆。

Carson｜量化阿森 Carson Quant
（YouTube 頻道連結、媒體包如需附上請告知）"""
        return body
    return f"您好，關於「量化阿森」頻道的合作，附上媒體包供參考。頻道近28天觀看 {stats['views28']}、完播 {stats['avgpct']}。"


def send_smtp(to, subject, body):
    addr = os.environ.get("GMAIL_ADDRESS", "").strip()
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()  # Gmail App Password 顯示帶空格,去掉才是16碼
    if not addr or not pw:
        print("[FATAL] 未設 GMAIL_ADDRESS / GMAIL_APP_PASSWORD,無法寄送。", file=sys.stderr)
        return False
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = addr
    msg["To"] = to
    try:
        # local_hostname=localhost:避免 EHLO 送出中文電腦名導致 ascii 編碼錯
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30, local_hostname="localhost") as s:
            s.login(addr, pw)
            s.sendmail(addr, [to], msg.as_string())
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] 寄送失敗:{e}", file=sys.stderr)
        return False


def main() -> int:
    dry = "--send" not in sys.argv
    verified = "--verified" in sys.argv
    stats = _media_stats()

    print("=" * 60)
    print("📧 EMAIL 開發信目標(真正能寄信的)")
    print("=" * 60)
    for t in EMAIL_TARGETS:
        print(f"\n── 收件:{t['to']}｜{t['name']}")
        print(f"主旨:{t['subject']}")
        print("-" * 40)
        print(build_email(t, stats))
        print("-" * 40)

    print("\n" + "=" * 60)
    print("📝 表單申請清單(無法代填,Carson 自己送;附預填頻道簡介)")
    print("=" * 60)
    print(f"預填簡介:量化阿森 Carson Quant｜台灣繁中量化交易/自動交易/台股技術分析頻道｜"
          f"{stats['total']}支影片、近28天觀看{stats['views28']}、完播{stats['avgpct']}｜誠實回測導向不喊單")
    for name, url in FORM_TARGETS:
        print(f"  • {name}\n    {url}")

    if dry:
        print("\n[dry-run] 以上為預覽,未寄出任何信。確認無誤後:")
        print("  1) 先派 fresh-context agent 獨立驗證每封(收件人/內容/誠信)")
        print("  2) 設好 GMAIL_ADDRESS/GMAIL_APP_PASSWORD")
        print("  3) 跑 python scripts/sponsor_outreach.py --send --verified")
        return 0

    if not verified:
        print("\n[擋] --send 需同時帶 --verified(代表已過 fresh-context 獨立驗證)。"
              "對外寄信零例外必先獨立驗證,拒絕未驗證直寄。", file=sys.stderr)
        return 2

    print("\n[send] 開始寄送 EMAIL 目標(已標記 verified)...")
    ok = 0
    for t in EMAIL_TARGETS:
        if send_smtp(t["to"], t["subject"], build_email(t, stats)):
            ok += 1
            print(f"  ✓ 已寄 {t['to']}")
    try:
        from ops import log_ops
        log_ops("贊助開發", f"寄出 {ok}/{len(EMAIL_TARGETS)} 封 email 開發信")
    except Exception:  # noqa: BLE001
        pass
    print(f"[ok] 寄出 {ok}/{len(EMAIL_TARGETS)} 封。表單型仍需 Carson 手動申請。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
