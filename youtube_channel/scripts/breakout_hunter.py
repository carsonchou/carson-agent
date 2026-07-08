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
import argparse, json, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import llm  # 共用 LLM 路由(主 OpenRouter/DeepSeek→退回 Anthropic)，不再直打死掉的 Anthropic
import studio_common as sc  # 共用地基：PERSONA / has_llm_key / evidence_block
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
REPORTS = STUDIO / "REPORTS"
QSCORES = STUDIO / "quality_scores.json"
PLAYBOOK = STUDIO / "competitor_playbook.md"
TW = timezone(timedelta(hours=8))
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


def _win_score(p):
    """贏點綜合分：小頻道觀看噪音大、完播才是真訊號，故用 觀看 × 完播加權 ×(1+CTR)。
    缺完播/CTR 時各退回中性值(不放大也不歸零)，仍以觀看為底。"""
    views = p.get("views") or 0
    ret = p.get("retention")
    ctr = p.get("ctr") if p.get("ctr") is not None else p.get("impressions_ctr")
    ret_factor = 1 + (ret / 100.0) if isinstance(ret, (int, float)) else 1.0
    ctr_factor = 1 + (ctr / 100.0) if isinstance(ctr, (int, float)) else 1.0
    return views * ret_factor * ctr_factor


def top_performers(n):
    try:
        d = json.loads(QSCORES.read_text(encoding="utf-8"))
    except Exception:
        return []
    pub = [p for p in d.get("published", []) if isinstance(p.get("views"), int)]
    # 贏點判定納入完播/CTR 綜合(非純觀看排序)：小頻道靠完播才篩得出真正的贏片
    pub.sort(key=_win_score, reverse=True)
    return pub[:n]


def distill(tops):
    """AI 拆解贏點＋產同模式新題目。回 dict 或 None。"""
    if not sc.has_llm_key():
        return None
    lines = []
    for t in tops:
        ctr = t.get("ctr") if t.get("ctr") is not None else t.get("impressions_ctr")
        v = _voice(t.get("slug", ""))
        lines.append(f"- 觀看{t['views']}、留存{t.get('retention','?')}%"
                     + (f"、CTR{ctr}%" if isinstance(ctr, (int, float)) else "")
                     + f"｜{t.get('title','')}"
                     + (f"｜旁白開頭：{v[:120]}" if v else ""))
    block = "\n".join(lines)
    ev = ""
    try:
        eb = sc.evidence_block()
        if eb:
            ev = "\n\n" + eb
    except Exception:
        pass
    prompt = (
        sc.PERSONA + "\n\n"
        "你是量化阿森（量化/網格/派網/風控，繁中 faceless Shorts）的成長分析師。"
        "下面是本頻道『綜合表現最好』的幾支片（依觀看×完播×CTR 排序，含留存/CTR與旁白開頭）。"
        "注意：小頻道觀看噪音大，**完播率/CTR 才是真訊號**——高觀看但低完播的別當成贏片。\n"
        + block + ev + "\n\n"
        "任務：①找出它們的『共同贏點』——什麼鉤子/主題/結構/標題型讓它們贏（完播/CTR 高）？越具體越好，"
        "要能直接指導下一批怎麼做。②據此產 5 個『同贏點模式』的新題目（衝量用）。"
        "③一句話講『輸的片通常錯在哪、要避免什麼』。"
        "④用一句話評這套贏點『能否小白化複製』——即新手/沒背景的觀眾能不能照著懂、能不能低門檻量產同模式片。守誠實鐵則。\n"
        '只輸出 JSON：{"win":"贏點心法(150字內,具體可照做)","topics":[{"title":"標題","angle":"切入點"}],'
        '"avoid":"一句要避免的","beginner_replicable":"一句：這套贏點能否小白化複製、怎麼複製"}'
    )
    try:
        txt = llm.complete(prompt, 1500, json_mode=True)  # 共用路由+強制 JSON
        m = re.search(r"\{.*\}", txt, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 拆解失敗：{str(e)[:80]}", file=sys.stderr)
        return None


def write_playbook(win, avoid, beginner=""):
    """把贏點寫進 competitor_playbook.md 的 P 區（取代舊的），produce_batch 下次製作即吃到。"""
    if not PLAYBOOK.exists():
        return False
    pb = PLAYBOOK.read_text(encoding="utf-8")
    sect = (f"{WIN_MARK}（爆款獵手每週更新，最高優先照做）：\n{win}\n"
            f"避免：{avoid}\n"
            + (f"小白化複製：{beginner}\n" if beginner else "")
            + "（依本頻道實際觀看×完播×CTR 綜合回推，比競品心法更貼合你的受眾）\n")
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


SEEN_FILE = STUDIO / "breakout_seen.json"


def _seen():
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _mark_seen(vid):
    s = _seen(); s.add(vid)
    try:
        SEEN_FILE.write_text(json.dumps(sorted(s), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def do_full(tops, breakout, dry=False):
    """拆贏點→回寫心法→灌同模式題目→寫報告。breakout=True 時題目灌兩份(全押)。"""
    best = tops[0]["views"]
    res = distill(tops)
    if not res:
        print("[FATAL] 拆解不出贏點。", file=sys.stderr); return 3
    win, avoid = res.get("win", "").strip(), res.get("avoid", "").strip()
    beginner = (res.get("beginner_replicable") or "").strip()
    topics = [t for t in res.get("topics", []) if t.get("title")]
    print(f"\n★ 贏點：{win}\n⛔ 避免：{avoid}")
    if beginner:
        print(f"🐣 小白化複製：{beginner}")
    print(f"★ 同模式新題目 {len(topics)} 個{'｜🚀 全押模式' if breakout else ''}")
    if dry:
        for t in topics:
            print(f"   - {t['title']}")
        return 0
    pb_ok = write_playbook(win, avoid, beginner)
    from topic_bank import add_topics
    items = [{"title": t["title"], "angle": t.get("angle", ""), "category": "市場觀念",
              "format": "short", "priority": "breakout"} for t in topics]
    if breakout:
        items = items + items + items  # 台股中了灌三份同款加碼(×2→×3:爆款全押火力再加碼)
    added = add_topics(items, source="breakout", front=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# 🏆 爆款獵手{'·全押' if breakout else '週報'}｜{tw_today()}", "",
         f"## 本頻道前 {len(tops)} 名（最高 {best:,} 觀看）", ""]
    for t in tops:
        L.append(f"- 👁 {t['views']:,}　留存 {t.get('retention','?')}%　{t.get('title','')}")
    L += ["", "## ★ 實證贏點（已寫回心法，產線專攻）", "", win, "", "## ⛔ 要避免", "", avoid]
    if beginner:
        L += ["", "## 🐣 能否小白化複製", "", beginner]
    L += ["", f"## 🎯 已灌 {added} 個同模式題目進題庫（優先製作）" + ("　🚀【全押】偵測到爆款！" if breakout else ""), ""]
    for t in topics:
        L.append(f"- {t['title']}")
    (REPORTS / f"{tw_today()}_爆款獵手.md").write_text("\n".join(L), encoding="utf-8")
    log_ops("爆款獵手", f"贏點回寫{'✓' if pb_ok else '✗'}、灌 {added} 題{'、🚀全押' if breakout else ''}（最高 {best} 觀看）")
    print(f"\n[ok] 爆款獵手完成：贏點已回寫心法、{added} 個同模式題目進題庫"
          f"{'，🚀 全押已啟動' if breakout else ''} → {tw_today()}_爆款獵手.md")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--breakout", type=int, default=5000, help="任一支觀看達此數＝爆款")
    ap.add_argument("--watch", action="store_true",
                    help="每日輕量盯：只在出現新爆款時才啟動全套＋全押，否則便宜空轉、不動心法")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    tops = top_performers(args.top)
    if not tops:
        print("[info] 還沒有帶觀看數據的已發布片（先讓 quality_score 抓 analytics）。"); return 0
    best = tops[0]["views"]

    # 動態爆款門檻:5000 對 30 訂閱頻道是天文數字(自家最高才幾百)。改成「相對自家中位數」
    # 門檻 = 中位數×5,夾在 [150, 最高×1.2] 之間 → 真的會觸發又不氾濫;頻道長大自動水漲船高。
    if args.breakout == 5000:  # 沒被 CLI 明確 override 才動態化(5000=哨兵值)
        allv = sorted(t["views"] for t in top_performers(9999) if t.get("views"))
        med = allv[len(allv) // 2] if allv else 0
        args.breakout = max(120, min(int(med * 3), int(best * 1.2)))
        print(f"[dyn] 動態爆款門檻={args.breakout}（中位數 {med}×3,夾 [120, 最高×1.2]）")

    if args.watch:
        # 每日跑：沒爆款就只記一行、不打 AI、不動心法（贏點交給每週完整跑）
        topvid = tops[0].get("videoId", "")
        if best >= args.breakout and topvid not in _seen():
            print(f"🚀 偵測到爆款（{best:,} 觀看）！立即啟動全押…")
            _mark_seen(topvid)
            return do_full(tops, breakout=True, dry=args.dry)
        log_ops("爆款獵手", f"每日盯：最高 {best} 觀看，未達爆款門檻 {args.breakout}")
        print(f"[watch] 最高 {best} 觀看，未達爆款門檻 {args.breakout}，持續盯著（不動心法、不花 AI）。")
        return 0

    # 每週完整跑：拆贏點＋回寫心法
    print(f"== 本頻道前 {len(tops)} 名（最高 {best} 觀看）==")
    for t in tops:
        print(f"   👁{t['views']:>7} 留存{t.get('retention','?')}%  {t.get('title','')[:34]}")
    return do_full(tops, breakout=best >= args.breakout, dry=args.dry)


if __name__ == "__main__":
    raise SystemExit(main())
