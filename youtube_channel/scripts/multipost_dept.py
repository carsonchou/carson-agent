#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multipost_dept.py — 【多平台發布包｜半自動】把短片整理成 TikTok / IG Reels 可直接貼的發布包。

為什麼半自動：TikTok/IG 全自動發布需開發者 App 審核＋(IG)商業帳號＋公開影片網址，設定多、
對自動化敏感。本工具不碰那些 —— 你的產線本來就出直式 mp4，這裡把「新短片 + 各平台現成文案」
整理成一份清單，你 5 分鐘抓檔貼文發出去，觸及 ×3、零帳號設定、零封號風險。

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
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
OUT = ROOT / "output"
CFG = ROOT / "channel_config.json"
LEDGER = STUDIO / "multipost_ledger.json"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m): pass

# 平台標籤組（廣泛+利基混用；TikTok 偏好 fyp 類，IG 偏好主題標籤）
TIKTOK_TAGS = "#量化交易 #網格交易 #定投 #被動收入 #加密貨幣 #理財 #投資理財 #Pionex #派網 #fyp #foryou"
REELS_TAGS = "#量化交易 #網格交易 #定投 #被動收入 #加密貨幣 #理財 #投資理財 #Pionex #派網 #reels #投資"


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


def make_caption(title, hook, tags, link):
    lines = [f"{title}"]
    if hook:
        lines.append(hook + ("…" if len(hook) >= 60 else ""))
    lines.append(f"📈 想用工具實作？Pionex 派網 👉 {link}（邀請碼 08NAcfvcWna）")
    lines.append("⚠️ 投資有風險，內容為教學分享，非投資建議。")
    lines.append(tags)
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
    LEDGER.write_text(json.dumps(sorted(s), ensure_ascii=False, indent=2), encoding="utf-8")


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
    L = [f"# 📲 多平台發布包｜{date}", "",
         f"> 共 {len(shorts)} 支待發布短片。**做法**：抓下方 mp4 路徑的檔案 → 到 TikTok／IG Reels App 上傳 → "
         "貼上對應文案發布。直式 <60 秒、零額外製作，觸及 ×3。", ""]
    if not shorts:
        L.append("（目前沒有新的待發布短片——都打包過了，或還沒產新片）")
    for i, p in enumerate(shorts, 1):
        slug = p.stem
        title, hook = parse_md(slug)
        size_mb = round(p.stat().st_size / 1e6, 1)
        L += [f"## {i}. {title}",
              f"- 🎬 影片檔（直接抓）：`{p}`（{size_mb} MB）",
              "",
              "**▼ TikTok 文案（複製貼上）**", "```", make_caption(title, hook, TIKTOK_TAGS, link), "```",
              "**▼ Instagram Reels 文案（複製貼上）**", "```", make_caption(title, hook, REELS_TAGS, link), "```",
              ""]
        packaged.add(slug)

    (REPORTS / f"{date}_多平台發布包.md").write_text("\n".join(L), encoding="utf-8")
    save_ledger(packaged)
    log_ops("多平台發布", f"打包 {len(shorts)} 支待發布短片 → {date}_多平台發布包.md")
    print(f"[ok] 多平台發布包完成：{len(shorts)} 支短片待你貼到 TikTok/Reels。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
