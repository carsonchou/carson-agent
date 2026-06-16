#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""breakout_hunter.py — 【爆款獵手·週迭代引擎】把「中爆款」從碰運氣變系統化。

每週自動跑：
  1) 從 quality_scores.json 的已發布片，依『觀看數』找出你自己表現最好的前 N 支（你的 outlier）
  2) AI 拆解這幾支的『共同贏點』（鉤子/主題/結構/標題型），＋產一批同模式的新題目
  3) 把贏點寫回 competitor_playbook.md 的『P. 本頻道實證贏點』區（produce_batch 即時讀→下週產線專攻它）
  4) 同模式新題目插隊進 topic_bank（front 優先做）；淘汰輸的格式（記 avoid）
  5) 若有任一支破『爆款門檻』(--breakout，預設 5000) → 觸發『全押』：同模式多灌一批題目
輸出 STUDIO/REPORTS/{date}_爆款獵手.md。
用法：python scripts/breakout_hunter.py [--top 4] [--breakout 5000] [--dry]
"""
from __future__ import annotations
import argparse, json, os, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
REPORTS = STUDIO / "REPORTS"
QSCORES = STUDIO / "quality_scores.json"
PLAYBOOK = STUDIO / "competitor_playbook.md"
TW = timezone(timedelta(hours=8))
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"  # 一週一次、直接形塑全產線的贏點，用較強模型值得
WIN_MARK = "P. ★本頻道實證贏點"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(s, m): pass


def tw_today():
    return datetime.now(TW).strftime("%Y-%m-%d")


def _voice(slug):
    p = OUT / f"{slug}.voice.txt"
    try:
        return p.read_text(encoding="utf-8")[:600] if p.exists() else ""
    except Exception:
        return ""


def top_performers(n):
    try:
        d = json.loads(QSCORES.read_text(encoding="utf-8"))
    except Exception:
        return []
    pub = [p for p in d.get("published", []) if isinstance(p.get("views"), int)]
    pub.sort(key=lambda x: x["views"], reverse=True)
    return pub[:n]


def distill(tops):
    """AI 拆解贏點＋產同模式新題目。回 dict 或 None。"""
    if not API_KEY:
        return None
    import requests
    lines = []
    for t in tops:
        v = _voice(t.get("slug", ""))
        lines.append(f"- 觀看{t['views']}、留存{t.get('retention','?')}%｜{t.get('title','')}"
                     + (f"｜旁白開頭：{v[:120]}" if v else ""))
    block = "\n".join(lines)
    prompt = (
        "你是量化阿森（量化/網格/派網/風控，繁中 faceless Shorts）的成長分析師。"
        "下面是本頻道『觀看數最高』的幾支片（含留存與旁白開頭）。\n" + block + "\n\n"
        "任務：①找出它們的『共同贏點』——什麼鉤子/主題/結構/標題型讓它們贏？越具體越好，"
        "要能直接指導下一批怎麼做。②據此產 5 個『同贏點模式』的新題目（衝量用）。"
        "③一句話講『輸的片通常錯在哪、要避免什麼』。守誠實鐵則。\n"
        '只輸出 JSON：{"win":"贏點心法(150字內,具體可照做)","topics":[{"title":"標題","angle":"切入點"}],"avoid":"一句要避免的"}'
    )
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": MODEL, "max_tokens": 1500, "temperature": 0.4,
                                "messages": [{"role": "user", "content": prompt}]}, timeout=150)
        r.raise_for_status()
        m = re.search(r"\{.*\}", r.json()["content"][0]["text"], re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 拆解失敗：{str(e)[:80]}", file=sys.stderr)
        return None


def write_playbook(win, avoid):
    """把贏點寫進 competitor_playbook.md 的 P 區（取代舊的），produce_batch 下次製作即吃到。"""
    if not PLAYBOOK.exists():
        return False
    pb = PLAYBOOK.read_text(encoding="utf-8")
    sect = (f"{WIN_MARK}（爆款獵手每週更新，最高優先照做）：\n{win}\n"
            f"避免：{avoid}\n（依本頻道實際觀看數據回推，比競品心法更貼合你的受眾）\n")
    # 移除舊 P 區（從 WIN_MARK 到下一個 \n\n 區塊邊界）
    pb = re.sub(re.escape(WIN_MARK) + r".*?(?=\n\n|\Z)", "", pb, flags=re.S).rstrip()
    # 插在『自動增補』前，沒有就接在最後
    mark = "## 自動增補"
    if mark in pb:
        head, _, tail = pb.partition(mark)
        new = head.rstrip() + "\n\n" + sect + "\n" + mark + tail
    else:
        new = pb.rstrip() + "\n\n" + sect
    PLAYBOOK.write_text(new, encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--breakout", type=int, default=5000, help="任一支觀看達此數＝爆款，觸發全押多灌題目")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    tops = top_performers(args.top)
    if not tops:
        print("[info] 還沒有帶觀看數據的已發布片（先讓 quality_score 抓 analytics）。"); return 0
    best = tops[0]["views"]
    print(f"== 本頻道前 {len(tops)} 名（最高 {best} 觀看）==")
    for t in tops:
        print(f"   👁{t['views']:>7} 留存{t.get('retention','?')}%  {t.get('title','')[:34]}")

    res = distill(tops)
    if not res:
        print("[FATAL] 拆解不出贏點。", file=sys.stderr); return 3
    win, avoid = res.get("win", "").strip(), res.get("avoid", "").strip()
    topics = [t for t in res.get("topics", []) if t.get("title")]
    breakout = best >= args.breakout

    print(f"\n★ 贏點：{win}\n⛔ 避免：{avoid}")
    print(f"★ 同模式新題目 {len(topics)} 個{'｜🚀 偵測到爆款，全押模式' if breakout else ''}")
    if args.dry:
        for t in topics:
            print(f"   - {t['title']}")
        return 0

    pb_ok = write_playbook(win, avoid)
    from topic_bank import add_topics
    items = [{"title": t["title"], "angle": t.get("angle", ""), "category": "市場觀念",
              "format": "short", "priority": "breakout"} for t in topics]
    if breakout:  # 全押：同模式題目灌兩份(衝量壓這條線)
        items = items + items
    added = add_topics(items, source="breakout", front=True)

    REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# 🏆 爆款獵手週報｜{tw_today()}", "",
         f"## 本頻道前 {len(tops)} 名（最高 {best:,} 觀看）", ""]
    for t in tops:
        L.append(f"- 👁 {t['views']:,}　留存 {t.get('retention','?')}%　{t.get('title','')}")
    L += ["", "## ★ 本週實證贏點（已寫回心法，下週產線專攻）", "", win,
          "", f"## ⛔ 要避免", "", avoid,
          "", f"## 🎯 已灌 {added} 個同模式題目進題庫（優先製作）" + ("　🚀【全押】偵測到爆款！" if breakout else ""), ""]
    for t in topics:
        L.append(f"- {t['title']}")
    (REPORTS / f"{tw_today()}_爆款獵手.md").write_text("\n".join(L), encoding="utf-8")

    log_ops("爆款獵手", f"贏點回寫{'✓' if pb_ok else '✗'}、灌 {added} 題{'、🚀全押' if breakout else ''}（最高 {best} 觀看）")
    print(f"\n[ok] 爆款獵手完成：贏點已回寫心法、{added} 個同模式題目進題庫"
          f"{'，🚀 全押模式已啟動' if breakout else ''} → {tw_today()}_爆款獵手.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
