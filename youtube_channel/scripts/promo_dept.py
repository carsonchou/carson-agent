#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""promo_dept.py — 【⑥ 宣傳部】產跨平台導流文案（草稿，不自動發）。

為最近上架的影片，用共用 LLM 路由(llm.complete)產 FB / IG / Threads / Dcard 版文案
（含 Pionex 連結＋風險聲明），存成草稿給老闆人工貼。
誠實：無社群自動發文 API，且為避免 spam/封號，只產草稿不自動發。

昇華(2026-07)：
  - 餵影片**實際旁白內容**(讀 output/{slug}.md 全部旁白，不只標題)＋影片描述。
  - 注入 sc.PERSONA(怕被割小白×實測避雷 軟性定位)＋各平台受眾畫像＋鉤子公式＋小白避雷語氣。
  - LLM 改走共用路由 llm.complete(json_mode)，不再直打 api.anthropic.com。
  - 抽出共用 gen_captions()／read_narration()：跨平台分發部(multipost_dept)直接呼叫共用，
    兩部門文案邏輯一套、語氣/誠信/避雷一致，不再各寫各的。
輸出：STUDIO/REPORTS/{date}_宣傳文案.md
"""
from __future__ import annotations
import json, os, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace"); sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_common as sc          # 共用地基：PERSONA / has_llm_key
import llm                          # 共用 LLM 路由：主供應商→退回，換模型只改 env
STUDIO = ROOT / "STUDIO"; REPORTS = STUDIO / "REPORTS"; LEDGER = STUDIO / "uploaded_ledger.json"
OUT = ROOT / "output"; CFG = ROOT / "channel_config.json"
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


# 宣傳部平台組：受眾畫像＋語氣＋標籤各自客製（供共用 gen_captions 用）。
PROMO_PLATFORMS = [
    {"key": "fb", "name": "Facebook",
     "audience": "偏熟齡理財族、願讀長文、愛用問句互動",
     "style": "2-3 句故事感＋1 個互動問句，段落清楚",
     "tags": "#量化交易 #網格交易 #Pionex #派網 #理財 #投資理財 #新手理財"},
    {"key": "ig", "name": "Instagram",
     "audience": "年輕、視覺導向、耐心短，靠標籤被發現",
     "style": "精簡、適度 emoji、主題標籤收尾",
     "tags": "#量化交易 #網格交易 #被動收入 #理財 #投資理財 #幣圈 #新手 #避雷"},
    {"key": "threads", "name": "Threads",
     "audience": "愛討論、口語、反感業配味",
     "style": "口語鉤子開頭、結尾拋問題逼互動、少標籤",
     "tags": "#網格交易 #幣圈 #新手"},
    {"key": "dcard", "name": "Dcard/PTT",
     "audience": "理性鄉民、怕被業配割、重證據與條列",
     "style": "理性分享口吻、重點條列、不浮誇、先講缺點再講好處",
     "tags": ""},
]


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def aff_link():
    try:
        c = json.loads(CFG.read_text(encoding="utf-8"))
        return (c.get("affiliate", {}) or {}).get("pionex_url", "https://accounts.pionex.com/zh-TW/signUp?r=08NAcfvcWna")
    except Exception:
        return "https://accounts.pionex.com/zh-TW/signUp?r=08NAcfvcWna"


def read_narration(slug: str, limit: int = 1200):
    """讀 output/{slug}.md：回 (title, narration, desc)。
    narration = 影片全部『**旁白：**』區塊串起來(影片真正講的內容，不只標題)。"""
    md = OUT / f"{slug}.md"
    title, narration, desc = slug, "", ""
    if not md.exists():
        return title, narration, desc
    txt = md.read_text(encoding="utf-8")
    m = re.search(r"^#\s*🎬?\s*(.+)$", txt, re.M)
    if m:
        title = m.group(1).strip()
    # 抓所有旁白區塊：從 **旁白：** 到下一個空行 / 下一個粗體標記 / 下一個小標
    blocks = re.findall(r"\*\*旁白[：:]\*\*\s*(.+?)(?=\n\s*\n|\n\*\*|\n##|\Z)", txt, re.S)
    narration = "\n".join(b.strip() for b in blocks if b.strip()).strip()[:limit]
    dm = re.search(r"##\s*📝\s*YouTube 影片描述\s*\n+(.+?)(?=\n##|\n\*\*Hashtags|\Z)", txt, re.S)
    if dm:
        desc = dm.group(1).strip()[:400]
    return title, narration, desc


def gen_captions(vid: dict, platforms: list) -> dict | None:
    """共用 LLM 文案產生器（宣傳部＋跨平台分發部共用，一套邏輯）。
    vid: {slug, title, url(optional)}；platforms: [{key,name,audience,style,tags}]。
    回 {platform_key: caption} dict；無 key 或失敗回 None（呼叫端可自行退回模板）。"""
    if not sc.has_llm_key():
        return None
    slug = vid.get("slug", "")
    title, narration, desc = read_narration(slug)
    title = vid.get("title") or title
    link = aff_link()
    url = vid.get("url", "")

    plat_lines, keys = [], []
    for p in platforms:
        keys.append(p["key"])
        tagtxt = (f"；指定標籤(原樣附在結尾)：{p['tags']}" if p.get("tags")
                  else "；此平台不要放一堆標籤")
        plat_lines.append(
            f"- {p['key']}（{p['name']}）：受眾={p.get('audience','')}；語氣/格式={p.get('style','')}{tagtxt}")
    plat_block = "\n".join(plat_lines)
    keys_hint = "、".join(keys)

    prompt = f"""{sc.PERSONA}

【任務】為一支已上架的影片，替各社群平台各寫一則導流文案（繁體中文、台灣用字，嚴禁任何簡體字）。
【影片標題】{title}
【影片實際旁白內容（務必根據這個寫，不要只看標題臆測、不要亂編數據）】
{narration or '（旁白從缺，就依標題發揮，但別杜撰任何數字或損益）'}
【影片描述】{desc or '（無）'}
{('【影片連結】' + url) if url else ''}

【鉤子公式】開頭第一句用「具體數字 / 反差 / 痛點恐懼」戳中『想被動賺、但怕被割的小白』
（會不會被割？被套？虧光？），接著給安心感——「我先用回測幫你試，別自己送死」，最後才導流。
【小白避雷語氣】能白話就白話，術語順手翻人話（網格=機器人低買高賣、回測=拿歷史行情跑一遍、
夏普=賺得穩不穩）；站在新手怕虧的角度說話，但別為白話犧牲該有的乾貨。
【誠信鐵則】不保證收益、不喊單、不編造損益；禁用「躺賺/穩賺/穩定獲利/一天賺X」等詞（會被限流）。
【收尾】每則自然帶一句工具導流：想自己動手可用 Pionex 派網 👉 {link}（邀請碼 08NAcfvcWna），
並附一句「投資有風險，內容為教學分享、非投資建議」。

各平台文化不同，分別客製：
{plat_block}

只輸出 JSON（不要多餘文字、不要 markdown 圍欄），格式為一個物件，
key 用上面列的平台代碼（{keys_hint}），value 是該平台完整文案字串。"""
    try:
        txt = llm.complete(prompt, 1600, json_mode=True)
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return None
        data = json.loads(m.group(0))
        out = {p["key"]: str(data.get(p["key"], "")).strip() for p in platforms if str(data.get(p["key"], "")).strip()}
        return out or None
    except Exception as e:
        print(f"[warn] 文案生成失敗：{e}", file=sys.stderr)
        return None


def recent_videos(n=2):
    led = {}
    try:
        led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    except Exception:
        pass
    items = []
    for slug, vid in (led.items() if isinstance(led, dict) else []):
        title = slug
        md = OUT / f"{slug}.md"
        if md.exists():
            m = re.search(r"^#\s*🎬?\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
            if m:
                title = m.group(1).strip()
        url = f"https://youtu.be/{vid}"
        mtime = (OUT / f"{slug}.mp4").stat().st_mtime if (OUT / f"{slug}.mp4").exists() else 0
        items.append({"slug": slug, "title": title, "url": url, "mtime": mtime})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:n]


def main() -> int:
    vids = recent_videos(2)
    date = tw_today(); REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ⑥ 宣傳文案（草稿）｜{date}", "",
         "> 跨平台導流文案草稿。誠實：無社群自動發文 API，為避免 spam/封號**只產草稿、不自動發**，請人工貼。",
         "> 文案已餵影片實際旁白內容＋各平台受眾畫像，語氣走『怕被割小白×實測避雷』(軟性)。", ""]
    if not vids:
        L.append("（尚無已上架影片）")
    for v in vids:
        L += [f"## 🎬 {v['title']}", f"連結：{v['url']}", ""]
        caps = gen_captions(v, PROMO_PLATFORMS)
        if caps:
            for p in PROMO_PLATFORMS:
                cap = caps.get(p["key"])
                if cap:
                    L += [f"**▼ {p['name']}文案（複製貼上）**", "```", cap, "```", ""]
        else:
            L += ["（文案生成失敗或無 LLM 供應商 key，請稍後重跑）", ""]
    (REPORTS / f"{date}_宣傳文案.md").write_text("\n".join(L), encoding="utf-8")
    log_ops("宣傳部", f"產出 {len(vids)} 支影片的跨平台文案草稿")
    print(f"[ok] 宣傳文案草稿完成：{len(vids)} 支影片。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
