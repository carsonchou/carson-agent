#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""weekly_winners.py — 每週贏家自動分析(飛輪)。

把「觀看 × 完播 × 標題模式 × 禁用骨架命中率」的分析自動化成週報,並把結論回灌到既有的
STUDIO/traffic_signals.json(win_keywords/weak_keywords/top_videos)——studio_common.evidence_block()
本來就會讀它注入選題/寫稿 prompt,所以回灌後產線自動往贏家型別靠、遠離濫用模板,不必另接管線。

另做「洗版洩漏監控」:掃近期已發布標題有沒有又混進禁用骨架(爆倉還活著/勝率9X破產),
有的話報告標紅 + ntfy 提醒(代表 topic_gate 某處有漏,要查)。

資料來源:yt_analytics.video_stats(近180天 per-video);拿不到→讀 STUDIO/analytics_cache 最大 per-video 快取。
標題:quality_scores.json published(videoId→title)。
輸出:STUDIO/REPORTS/{date}_每週贏家分析.md + 更新 traffic_signals.json;--notify 推 ntfy。純讀分析,不改題庫內容本身。

用法:python scripts/weekly_winners.py [--notify]
"""
from __future__ import annotations
import sys
import time
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

import studio_common as sc

# 分析用關鍵字詞庫(涵蓋兩大主軸+格式+框架);逐詞算「含該詞的片」平均觀看/完播,找出真正相關的贏/弱關鍵字
KEYWORDS = [
    "定投", "網格", "回測", "複利", "停損", "停利", "勝率", "爆倉", "破產", "實測", "EP",
    "台股", "大盤", "0050", "0056", "00878", "006208", "除權息", "存股", "當沖", "台積電",
    "AI", "Claude", "比特幣", "以太", "ETF", "微笑曲線", "馬丁格爾", "夏普", "凱利",
    "虧光", "剩多少", "差多少", "vs", "你猜", "賓士", "手續費", "新手", "小白", "被割",
]


def _load_video_stats():
    """回傳 [(views, retention, subs, title), ...];優先 yt_analytics,退回 analytics_cache。"""
    rows = []
    # 標題對照
    q = sc.load_json_safe(STUDIO / "quality_scores.json", {}) or {}
    id2title = {}
    for x in (q.get("published") or []):
        if isinstance(x, dict) and x.get("videoId"):
            id2title[x["videoId"]] = x.get("title") or x.get("slug") or x["videoId"]
    # 1) 試 yt_analytics
    try:
        import yt_analytics as ya
        if ya.available():
            vs = ya.video_stats(days=180, limit=200) or {}
            if isinstance(vs, dict) and vs:
                for vid, m in vs.items():
                    if isinstance(m, dict) and m.get("views"):
                        rows.append((m.get("views", 0), m.get("retention") or m.get("avg_pct") or 0,
                                     m.get("subs") or 0, id2title.get(vid, vid)))
    except Exception:  # noqa: BLE001
        pass
    # 2) 退回 analytics_cache 最大 per-video 快取
    if not rows:
        import json
        best = {}
        cache = STUDIO / "analytics_cache"
        if cache.exists():
            for f in cache.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(d, dict) and d and all(isinstance(v, dict) and "views" in v for v in d.values()):
                    if len(d) > len(best):
                        best = d
        for vid, m in best.items():
            rows.append((m.get("views", 0), m.get("retention", 0), m.get("subs", 0), id2title.get(vid, vid)))
    return rows


def analyze(rows):
    if not rows:
        return None
    rows = [r for r in rows if r[0]]
    n = len(rows)
    med_v = sorted(r[0] for r in rows)[n // 2]
    # 每關鍵字:含該詞片的平均觀看/完播 vs 全站
    avg_v = sum(r[0] for r in rows) / n
    kw_stat = []
    for kw in KEYWORDS:
        hit = [r for r in rows if kw.lower() in (r[3] or "").lower()]
        if len(hit) >= 3:  # 至少 3 支才算數,避免雜訊
            kw_stat.append((kw, len(hit), sum(h[0] for h in hit) / len(hit),
                            sum(h[1] for h in hit) / len(hit)))
    kw_stat.sort(key=lambda x: -x[2])
    win_kw = [k for k, c, v, r in kw_stat if v >= avg_v * 1.15][:10]
    weak_kw = [k for k, c, v, r in kw_stat if v <= avg_v * 0.7][:8]
    top = sorted(rows, reverse=True)[:8]
    # 禁用骨架洩漏監控
    leaks = [r for r in rows if sc.is_banned_skeleton(r[3] or "")]
    return {
        "n": n, "avg_v": round(avg_v, 1), "med_v": med_v,
        "kw_stat": kw_stat, "win_kw": win_kw, "weak_kw": weak_kw,
        "top": top, "leaks": leaks,
    }


def write_report(a):
    REPORTS.mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d")
    lines = [f"# 每週贏家自動分析 · {date}", "",
             f"樣本 {a['n']} 支有數據片｜平均觀看 {a['avg_v']}｜中位觀看 {a['med_v']}", ""]
    lines.append("## 🏆 觀看 Top 8")
    for v, r, s, t in a["top"]:
        lines.append(f"- {int(v)}v ｜完播 {round(r)}% ｜{(t or '')[:44]}")
    lines.append("")
    lines.append("## 贏家關鍵字(含此詞片平均觀看 ≥ 全站115%)")
    lines.append("　" + "、".join(a["win_kw"]) if a["win_kw"] else "　(本週無明顯贏家關鍵字)")
    lines.append("")
    lines.append("## 弱關鍵字(含此詞片平均觀看 ≤ 全站70%,少碰或換角度)")
    lines.append("　" + "、".join(a["weak_kw"]) if a["weak_kw"] else "　(無)")
    lines.append("")
    lines.append("## 關鍵字明細(詞｜片數｜平均觀看｜平均完播)")
    for k, c, v, r in a["kw_stat"][:20]:
        lines.append(f"- {k}：{c} 支｜{round(v)}v｜{round(r)}%")
    lines.append("")
    if a["leaks"]:
        lines.append(f"## 🔴 洗版洩漏警報:{len(a['leaks'])} 支已發布片命中禁用骨架(topic_gate 有漏,要查)")
        for v, r, s, t in a["leaks"][:10]:
            lines.append(f"- {(t or '')[:44]}")
    else:
        lines.append("## ✅ 洗版洩漏監控:近期已發布無命中禁用骨架")
    path = REPORTS / f"{date}_每週贏家分析.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def feed_back(a):
    """回灌 traffic_signals.json(evidence_block 會讀它注入 prompt)——把贏家/弱關鍵字與 top 片寫回。"""
    ts = sc.load_json_safe(STUDIO / "traffic_signals.json", {}) or {}
    if not isinstance(ts, dict):
        ts = {}
    ts["win_keywords"] = a["win_kw"]
    ts["weak_keywords"] = a["weak_kw"]
    ts["top_videos"] = [{"title": (t or "")[:40], "avg_pct": round(r)} for v, r, s, t in a["top"][:6]]
    ts["updated_by"] = "weekly_winners"
    ts["updated"] = time.strftime("%Y-%m-%d %H:%M")
    sc.save_json_atomic(STUDIO / "traffic_signals.json", ts)


def _auto_seed(a):
    """A5 飛輪自動行動:①用本週贏家詞主動增產 8 題(過 topic_gate 才入庫)②把題庫中含輸家詞的未用題標降權。"""
    try:
        import topic_bank as tb
    except Exception:  # noqa: BLE001
        return
    # ① 增產贏家題
    try:
        recent = sc.recent_titles(80)
        items = tb.gen_topics(8, recent, bias_keywords=a.get("win_kw"))
        n = tb.add_topics(items, source="flywheel") if items else 0  # add_topics 內建 topic_gate
        print(f"[flywheel] 自動增產贏家題:入庫 {n} 題(偏 {a.get('win_kw', [])[:5]})")
    except Exception as e:  # noqa: BLE001
        print(f"[flywheel] 增產略過:{str(e)[:70]}", file=sys.stderr)
    # ② 降權輸家題(題庫中未用、標題含輸家詞→deprioritized,pull_topic 排最後)
    try:
        weak = a.get("weak_kw") or []
        if weak:
            bank = tb.load_bank()
            changed = 0
            for t in bank:
                if not t.get("used") and not t.get("deprioritized") and any(w in t.get("title", "") for w in weak):
                    t["deprioritized"] = True
                    changed += 1
            if changed:
                tb.save_bank(bank)
                print(f"[flywheel] 降權輸家題 {changed} 筆(含 {weak[:4]})")
    except Exception as e:  # noqa: BLE001
        print(f"[flywheel] 降權略過:{str(e)[:70]}", file=sys.stderr)


def main() -> int:
    rows = _load_video_stats()
    a = analyze(rows)
    if not a:
        print("[weekly_winners] 無 per-video 數據,略過。")
        return 0
    path = write_report(a)
    feed_back(a)
    if "--no-seed" not in sys.argv:
        _auto_seed(a)
    # 洗版洩漏基準線:首跑記住現有數(多為 gate 上線前的舊片,Carson 不碰);只有「超過基準」才是新洩漏、才報警
    st = sc.load_json_safe(STUDIO / "weekly_winners_state.json", {}) or {}
    baseline = st.get("leak_baseline")
    cur_leak = len(a["leaks"])
    new_leak = cur_leak > baseline if isinstance(baseline, int) else False
    if not isinstance(baseline, int) or cur_leak < baseline:
        st["leak_baseline"] = cur_leak  # 首跑設基準;舊片被刪→基準下修
        sc.save_json_atomic(STUDIO / "weekly_winners_state.json", st)
    print(f"[ok] 週報寫入 {path}")
    print(f"[ok] 回灌 traffic_signals.json：贏家詞 {a['win_kw']}｜弱詞 {a['weak_kw']}")
    print(f"[i] 洗版命中 {cur_leak} 支(基準 {baseline if isinstance(baseline,int) else cur_leak}=gate上線前舊片)"
          + ("　🔴 有新洩漏!topic_gate 有漏要查" if new_leak else "　✅ 無新洩漏"))
    if "--notify" in sys.argv:
        try:
            import notify
            body = (f"樣本{a['n']}支｜均觀看{a['avg_v']}\n贏家詞:{'、'.join(a['win_kw'][:6])}\n"
                    + ("🔴 有新洗版洩漏,查 topic_gate" if new_leak else "✅ 無新洗版洩漏"))
            notify.push("量化阿森｜每週贏家分析", body, tag="trophy")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] ntfy 失敗：{e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
