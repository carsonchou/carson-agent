#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multipost_dept.py — 【跨平台分發部門｜半自動】把短片整理成 5 平台可直接貼的發布包。

平台：TikTok / Instagram Reels / Threads / 小紅書 / Facebook，各平台文案文化分開調。

為什麼半自動：各平台全自動發布需開發者 App 審核＋(IG)商業帳號＋公開影片網址，設定多、
對自動化敏感；小紅書更無開放發布 API。本工具不碰那些 —— 你的產線本來就出直式 mp4，這裡把
「新短片 + 各平台現成文案」整理成清單＋機器可讀佇列(STUDIO/dist_queue.json)，你抓檔貼文即可，
觸及 ×N、零帳號設定、零封號風險。日後若設好各平台 token，可在此基礎上接 API 改全自動。

流程：找已成片但還沒打包的 Shorts → 依其 .md 產 TikTok / Reels 文案(含鉤子+Pionex+風險聲明+平台標籤)
     → 寫 STUDIO/REPORTS/{date}_多平台發布包.md（含 mp4 完整路徑可直接抓檔）→ 記入 ledger 避免重複列。

用法：python scripts/multipost_dept.py [--max 10]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from studio_common import save_json_atomic
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
OUT = ROOT / "output"
CFG = ROOT / "channel_config.json"
LEDGER = STUDIO / "multipost_ledger.json"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m): pass

# 各平台「文案文化」不同：標籤組、語氣、長度都分開調，貼上去才像在地內容、不像機器轉貼。
# audience 供共用 gen_captions(promo_dept) 產受眾客製文案用；tags 加了小白避雷向(#新手 #避雷 #怕被割)。
PLATFORMS = [
    {"key": "tiktok",  "name": "TikTok",          "emoji": "🎵",
     "audience": "刷得快、要 3 秒抓住的年輕用戶，衝 fyp",
     "tags": "#量化交易 #網格交易 #定投 #加密貨幣 #理財 #投資理財 #Pionex #派網 #fyp #foryou #幣圈 #新手 #避雷 #怕被割",
     "style": "punchy"},   # 鉤子優先、短、衝 fyp
    {"key": "reels",   "name": "Instagram Reels", "emoji": "📸",
     "audience": "視覺導向、靠標籤被發現的年輕理財新手",
     "tags": "#量化交易 #網格交易 #定投 #被動收入 #加密貨幣 #理財 #投資理財 #Pionex #派網 #reels #投資理財筆記 #新手理財 #避雷",
     "style": "clean"},    # 主題標籤、乾淨
    {"key": "threads", "name": "Threads",         "emoji": "🧵",
     "audience": "愛討論、口語、反感業配味",
     "tags": "#網格交易 #幣圈 #新手",
     "style": "talk"},     # 對話感、少標籤、結尾拋問題逼互動
    {"key": "xhs",     "name": "小紅書",           "emoji": "📕",
     "audience": "看筆記/標題黨、怕踩雷的小白，收藏導向",
     "tags": "#網格交易 #量化交易 #理財筆記 #定投 #幣圈 #投資理財 #被動收入 #新手必看 #避雷指南",
     "style": "notes"},    # emoji 多、筆記/標題黨語氣、話題標籤
    {"key": "fb",      "name": "Facebook",         "emoji": "👍",
     "audience": "偏熟齡理財族、願讀長文、愛互動",
     "tags": "#量化交易 #網格交易 #Pionex #派網 #理財 #新手理財",
     "style": "long"},     # 較長描述、連結可點、少標籤
]


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def aff_link():
    try:
        c = json.loads(CFG.read_text(encoding="utf-8"))
        return (c.get("affiliate", {}) or {}).get("pionex_url",
                "https://accounts.pionex.com/zh-TW/signUp?r=08NAcfvcWna")
    except Exception:
        return "https://accounts.pionex.com/zh-TW/signUp?r=08NAcfvcWna"


def parse_md(slug):
    """從 {slug}.md 取 title 與第一段旁白(當價值句)。"""
    md = OUT / f"{slug}.md"
    title, hook = slug, ""
    if md.exists():
        txt = md.read_text(encoding="utf-8")
        m = re.search(r"^#\s*🎬?\s*(.+)$", txt, re.M)
        if m:
            title = m.group(1).strip()
        m2 = re.search(r"\*\*旁白[：:]\*\*\s*(.+)$", txt, re.M)
        if m2:
            hook = m2.group(1).strip()[:60]
    return title, hook


def make_caption(plat, title, hook, link):
    """依平台文化客製文案：同一支片、五種口吻，貼哪個平台都像在地內容。
    這是『無 LLM key / LLM 失敗』時的降級模板；語氣對齊小白避雷向(先幫你試、別自己送死)。
    有 key 時主路徑走共用 gen_captions(promo_dept)，兩部門一套文案邏輯。"""
    style, tags = plat["style"], plat["tags"]
    hk = (hook + ("…" if len(hook) >= 60 else "")) if hook else ""
    risk = "⚠️ 投資有風險，內容為教學分享，非投資建議。"
    pio = f"想自己動手、又怕被割？我先幫你試過的工具：Pionex 派網 👉 {link}（邀請碼 08NAcfvcWna）"

    if style == "punchy":          # TikTok：鉤子先行、短、衝 fyp
        lines = [title]
        if hk:
            lines.append(hk)
        lines += ["新手最容易踩的雷，你中了嗎👇", f"📈 {pio}", risk, tags]
    elif style == "clean":         # IG Reels：乾淨、主題標籤
        lines = [title]
        if hk:
            lines.append(hk)
        lines += ["怕虧的小白先看完再進場👀", f"📈 {pio}", risk, "", tags]
    elif style == "talk":          # Threads：對話感、結尾拋問題逼互動、少標籤
        lines = [title]
        if hk:
            lines.append(hk)
        lines += ["你會停手還是加碼？留言聊聊，別自己悶著踩雷👇", f"（{pio}）", risk, tags]
    elif style == "notes":         # 小紅書：emoji 多、筆記/標題黨語氣
        lines = [f"💡{title}", ""]
        if hk:
            lines.append("📌 " + hk)
        lines += ["✅ 避雷重點我幫你整理在影片裡，新手 3 分鐘看懂",
                  f"🔧 {pio}", risk, "", tags]
    else:                          # Facebook：較長描述、連結可點
        lines = [title, ""]
        if hk:
            lines.append(hk)
        lines += ["", f"📈 想自己動手、又怕送頭？{pio}", risk, "", tags]
    return "\n".join(lines)


def load_ledger():
    if LEDGER.exists():
        try:
            return set(json.loads(LEDGER.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_ledger(s):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    save_json_atomic(LEDGER, sorted(s))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=10)
    args = ap.parse_args()

    packaged = load_ledger()
    # 已成片、還沒打包過的 Shorts，新到舊
    shorts = [p for p in OUT.glob("S_*.mp4") if p.stem not in packaged]
    shorts.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    shorts = shorts[: args.max]

    date = tw_today()
    REPORTS.mkdir(parents=True, exist_ok=True)
    link = aff_link()
    plats_line = "／".join(p["name"] for p in PLATFORMS)
    L = [f"# 📲 多平台發布包｜{date}", "",
         f"> 共 {len(shorts)} 支待發布短片 × {len(PLATFORMS)} 平台（{plats_line}）。",
         "> **做法**：抓下方 mp4 → 到各 App 上傳 → 貼上對應平台文案。直式 <60 秒、零額外製作，觸及 ×N。",
         "> 💡 小紅書無開放發布 API、只能手貼；其餘平台若日後設定好 token 可改全自動（見 README）。", ""]
    queue = []   # 機器可讀佇列：未來接 API 自動發、或給決策中心顯示用
    if not shorts:
        L.append("（目前沒有新的待發布短片——都打包過了，或還沒產新片）")
    for i, p in enumerate(shorts, 1):
        slug = p.stem
        title, hook = parse_md(slug)
        size_mb = round(p.stat().st_size / 1e6, 1)
        L += [f"## {i}. {title}",
              f"- 🎬 影片檔（直接抓）：`{p}`（{size_mb} MB）", ""]
        # 主路徑：呼叫共用 gen_captions(promo_dept)——餵影片實際旁白＋受眾畫像＋PERSONA，
        # 與宣傳部同一套文案邏輯；無 key/失敗時每平台各自降級用模板 make_caption。
        llm_caps = None
        try:
            from promo_dept import gen_captions
            llm_caps = gen_captions({"slug": slug, "title": title}, PLATFORMS)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 共用 LLM 文案失敗，改用模板：{e}", file=sys.stderr)
        caps = {}
        for plat in PLATFORMS:
            cap = (llm_caps or {}).get(plat["key"]) or make_caption(plat, title, hook, link)
            caps[plat["key"]] = cap
            L += [f"**▼ {plat['emoji']} {plat['name']} 文案（複製貼上）**", "```", cap, "```"]
        L.append("")
        queue.append({"slug": slug, "title": title, "file": str(p), "captions": caps})
        packaged.add(slug)

    (REPORTS / f"{date}_多平台發布包.md").write_text("\n".join(L), encoding="utf-8")
    # 機器可讀佇列（給未來的自動發布器 / 決策中心讀）
    save_json_atomic(STUDIO / "dist_queue.json",
                      {"date": date, "platforms": [p["key"] for p in PLATFORMS], "items": queue})
    save_ledger(packaged)
    log_ops("多平台分發", f"打包 {len(shorts)} 支 × {len(PLATFORMS)} 平台 → {date}_多平台發布包.md")
    print(f"[ok] 多平台發布包完成：{len(shorts)} 支短片 × {len(PLATFORMS)} 平台文案已備妥。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
