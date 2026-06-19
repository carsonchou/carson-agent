#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""decision_dept.py — 【決策部門】閉環大腦。

拉成效數據 → 用 Claude 分析決策 → 寫「生產指令」回饋給補產部門 + 決策匯報。
讓工廠越跑越聰明：自動加碼會紅的、砍掉沒人看的、發現方向就轉。

輸出：
  STUDIO/production_orders.json  → produce_batch 讀取，偏向高效題材
  STUDIO/REPORTS/{date}_決策.md  → 給老闆看的決策匯報
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ops import log_ops
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
LEDGER = STUDIO / "uploaded_ledger.json"
ORDERS = STUDIO / "production_orders.json"
PENDING = STUDIO / "pending_decisions.json"      # 待老闆拍板的決策(含選項)
BOSS_DEC = STUDIO / "boss_decisions.json"         # 老闆已拍板的選擇
TOKEN = ROOT / "token_manage.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"  # 決策用較強模型，一天一次成本低

ORIGINAL = ["fO-ZyxHI_xY", "ijCNjwEDRnc", "Qf-xkKw4kGQ", "_I82uMc__HM", "K4x90FeqZSo", "wZyBaJJ7A40"]


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def queue_topics(n: int = 20) -> list[str]:
    """讀目前片庫（output/*.md）按修改時間最新的 n 筆題目，讓決策部門知道庫存已有哪些題材。"""
    out_dir = ROOT / "output"
    if not out_dir.exists():
        return []
    titles = []
    for f in sorted(out_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:n]:
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0]
            t = first.replace("# 🎬", "").replace("#", "").strip()
            if t:
                titles.append(t)
        except Exception:
            pass
    return titles


def yt_service():
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def gather_stats(yt):
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    id_to_slug = {v: k for k, v in ledger.items()}
    ids = list(dict.fromkeys(ORIGINAL + list(ledger.values())))
    rows = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        try:
            resp = yt.videos().list(part="snippet,statistics", id=",".join(chunk)).execute()
            for it in resp.get("items", []):
                st = it.get("statistics", {})
                rows.append({
                    "id": it["id"],
                    "slug": id_to_slug.get(it["id"], ""),
                    "title": it["snippet"]["title"][:50],
                    "is_short": id_to_slug.get(it["id"], "").startswith("S_"),
                    "views": int(st.get("viewCount", 0)),
                    "likes": int(st.get("likeCount", 0)),
                    "comments": int(st.get("commentCount", 0)),
                })
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 抓數據失敗：{exc}", file=sys.stderr)
    rows.sort(key=lambda r: r["views"], reverse=True)
    return rows


def load_boss():
    p = STUDIO / "boss_directives.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def decide(rows):
    total_views = sum(r["views"] for r in rows)
    boss = load_boss()
    boss_txt = ""
    if boss.get("directives"):
        boss_txt += "\n\n【老闆直接指令（最高優先，務必納入決策與生產指令）】：\n" + "\n".join(f"- {x}" for x in boss["directives"])
    fmt = boss.get("format_override", "auto")
    if fmt and fmt != "auto":
        boss_txt += f"\n【老闆指定主攻格式】：{fmt}（format_focus 請輸出此值）"
    answered = {}
    if BOSS_DEC.exists():
        try:
            answered = json.loads(BOSS_DEC.read_text(encoding="utf-8"))
        except Exception:
            answered = {}
    if answered:
        boss_txt += "\n\n【老闆已拍板的決策（務必遵守，不要再問）】：\n" + "\n".join(
            f"- {v.get('question','')} → 老闆選：{v.get('choice','')}" for v in answered.values())
    summary = "\n".join(f"- [{'短' if r['is_short'] else '長'}] {r['title']}｜觀看{r['views']} 讚{r['likes']} 留言{r['comments']}" for r in rows[:30])
    # 片庫現況：讓決策部門知道哪些題材已在排隊，避免重複推薦同質題材
    qt = queue_topics(20)
    queue_ctx = ""
    if qt:
        queue_ctx = "\n\n【目前片庫已有的題目（請推薦不同方向，避免庫存同質化）】：\n" + "\n".join(f"- {t[:44]}" for t in qt[:15])
    prompt = f"""你是量化阿森 YouTube 工作室的【決策部門】總監，直接對大老闆 Carson 負責。
頻道主題=量化/自動交易教學(網格、定投、派網Pionex、回測、風控)，繁體中文。
第一目標=YPP 達標(主攻 Shorts 衝1000萬觀看/訂閱1000)。誠信鐵則:不編造損益、不保證收益。

目前所有影片成效(總觀看 {total_views})：
{summary or '（尚無影片數據，頻道剛起步）'}{boss_txt}{queue_ctx}

【多樣性鐵則】produce_more 必須橫跨至少 3 種不同主題維度（如：風控/策略/工具使用/回測方法/心態/定投等類別）。
片庫已有大量某類型→降優先、推新方向。嚴禁把同一個概念拆成 3-6 個換字變體充數（如「破產機率A/B/C/D」）。
每個 produce_more 條目要能代表一個獨立可拍的角度，且與庫存中現有題目明顯不同。

請做出**營運決策**並只輸出 JSON(不要其他字)：
{{
 "situation":"一句話現況判斷",
 "produce_more":["接下來該多做的題材/角度(3-6項,具體)"],
 "produce_less":["該少做或停的(可空陣列)"],
 "preferred_keywords":["偏好的選題關鍵字(英文或中文,給補產部門用)"],
 "avoid_topics":["要避免重複或表現差的題材(可空)"],
 "format_focus":"short 或 long 或 both(現階段建議)",
 "actions_for_departments":{{"靈感":"...","Shorts":"...","流量SEO":"...","宣傳":"..."}},
 "pending_decisions":[{{"question":"需要老闆拍板的具體策略選擇","options":["選項A","選項B","選項C"],"recommendation":"你建議選哪個+一句理由"}}],
 "one_line":"給老闆的一句話戰略判斷"
}}
pending_decisions：**不設數量上限** —— 凡是「真正需要老闆拍板」的策略選擇，有幾個就列幾個，全部端出來給老闆看(別為了精簡而漏掉該問的)。判準＝會花錢、大方向轉變、題材/節奏/品牌取捨、是否擴編或做某系列、實驗性方向等真正該老闆決定的事；每個給 2-4 個具體選項＋你的建議。但**只放真正值得老闆決定的，絕不為湊數硬湊填充**；老闆已拍板過的不要重複問；真的沒有值得問的就回空陣列。寧可這次 0 個、需要時 5 個、8 個都行，重點是「必要才給、必要的全給」。
數據太少時方向就給「保持多元測試、衝Shorts量、累積數據」這類務實方向,不要硬掰假洞察。"""
    body = {"model": MODEL, "max_tokens": 3500, "messages": [{"role": "user", "content": prompt}]}
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json=body, timeout=120)
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0))


def write_orders(d):
    orders = {
        "preferred_keywords": d.get("preferred_keywords", []),
        "produce_more": d.get("produce_more", []),
        "avoid_topics": d.get("avoid_topics", []),
        "format_focus": d.get("format_focus", "both"),
        "updated": tw_today(),
    }
    ORDERS.write_text(json.dumps(orders, ensure_ascii=False, indent=2), encoding="utf-8")


def write_pending(d):
    """把 Claude 產的待拍板決策寫成可選選項；過濾老闆已答過的。"""
    answered = {}
    if BOSS_DEC.exists():
        try:
            answered = json.loads(BOSS_DEC.read_text(encoding="utf-8"))
        except Exception:
            answered = {}
    out = []
    for pd in (d.get("pending_decisions") or []):
        q = (pd.get("question") or "").strip()
        opts = pd.get("options") or []
        if not q or len(opts) < 2:
            continue
        pid = "d" + hashlib.md5(q.encode("utf-8")).hexdigest()[:8]
        if pid in answered:
            continue
        out.append({"id": pid, "question": q, "options": opts, "recommendation": pd.get("recommendation", "")})
    PENDING.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def write_report(d, rows, date):
    REPORTS.mkdir(parents=True, exist_ok=True)
    lines = [f"# 決策部門匯報｜{date}", "", f"> 現況：{d.get('situation','')}", "",
             f"**戰略判斷**：{d.get('one_line','')}", "", "## 成效快照（前 10）", ""]
    for r in rows[:10]:
        lines.append(f"- [{'短' if r['is_short'] else '長'}] {r['title']}：觀看 {r['views']}、讚 {r['likes']}")
    if not rows:
        lines.append("-（尚無數據，頻道剛起步）")
    lines += ["", "## 決策：多做", *[f"- {x}" for x in d.get("produce_more", [])],
              "", "## 決策：少做/停", *[f"- {x}" for x in d.get("produce_less", []) or ["（無）"]],
              "", f"## 格式建議：{d.get('format_focus','both')}",
              "", "## 給各部門指令"]
    for k, v in (d.get("actions_for_departments", {}) or {}).items():
        lines.append(f"- **{k}**：{v}")
    pend = d.get("pending_decisions", []) or []
    lines += ["", "## ⚠️ 待你拍板（請到決策中心點選選項）"]
    if pend:
        for p in pend:
            opts = " / ".join(p.get("options", []))
            lines.append(f"- **{p.get('question','')}**\n  選項：{opts}\n  建議：{p.get('recommendation','')}")
    else:
        lines.append("- （本日無需老闆決策）")
    lines += ["", "> 生產指令已寫入 production_orders.json，補產部門明早自動套用。"]
    (REPORTS / f"{date}_決策.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if not API_KEY:
        print("[FATAL] 無 ANTHROPIC_API_KEY", file=sys.stderr)
        return 2
    date = tw_today()
    log_ops("決策部門", "開始拉數據做決策…")
    try:
        rows = gather_stats(yt_service())
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 取數據失敗，以空數據決策：{exc}", file=sys.stderr)
        rows = []
    try:
        d = decide(rows)
    except Exception as exc:  # noqa: BLE001
        log_ops("決策部門", f"⚠️ 決策失敗（保留舊指令）：{str(exc)[:60]}")
        return 1
    write_orders(d)
    pend = write_pending(d)
    write_report(d, rows, date)
    log_ops("決策部門", f"完成 格式={d.get('format_focus')} 多做{len(d.get('produce_more',[]))}項 待拍板{len(pend)}項｜{d.get('one_line','')[:36]}")
    print(f"[ok] 決策完成。格式建議={d.get('format_focus')}，多做 {len(d.get('produce_more',[]))} 項。")
    print(f"     一句話：{d.get('one_line','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
