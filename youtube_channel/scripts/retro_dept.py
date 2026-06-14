#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retro_dept.py — 【⑫ 回顧檢討部門】自省閉環（老闆指令：每輪跑完回顧+檢討，並自己分析報告做優化）。

流程：
  1) 收集當輪真實訊號（產量／審核過審率＋失敗原因／上架數／頻道數據與昨日 delta／錯誤）
  2) 產出《回顧檢討》報告 → STUDIO/REPORTS/{date}_回顧檢討.md
  3) 自己分析 → 產出**具體優化**（規則式 + 有金鑰時加 Claude）
  4) 把優化寫回 boss_directives（【自省優化】標籤、去重升級）與 production_orders（avoid/多做）
  5) 存每日快照到 metrics_history.json（給明天算 delta）

誠實鐵則：數據薄時給務實方向（衝量、累積數據），不掰假洞察；不編造損益、不保證收益。
"""
from __future__ import annotations

import json
import os
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
SCR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCR))

STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
OUT = ROOT / "output"
LEDGER = STUDIO / "uploaded_ledger.json"
ORDERS = STUDIO / "production_orders.json"
DIRECTIVES = STUDIO / "boss_directives.json"
HISTORY = STUDIO / "metrics_history.json"
OPS = STUDIO / "ops_log.txt"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"
RETRO_TAG = "【自省優化】"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(dept, msg):
        try:
            OPS.parent.mkdir(parents=True, exist_ok=True)
            with OPS.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%H:%M')} [{dept}] {msg}\n")
        except Exception:
            pass


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default
    except Exception:
        return default


def _today_outputs(prefix):
    today = tw_today()
    out = []
    for p in OUT.glob(f"{prefix}*.mp4"):
        try:
            d = datetime.fromtimestamp(p.stat().st_mtime, timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            if d == today:
                out.append(p.stem)
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------- #
# 1) 收集訊號
# --------------------------------------------------------------------------- #
def collect():
    sig = {"date": tw_today()}
    sig["shorts_today"] = _today_outputs("S_")
    sig["longs_today"] = _today_outputs("L_")

    # 審核：對「今日產出且尚未上架」的片跑審核，收集失敗原因
    ledger = _load(LEDGER, {})
    uploaded = set(ledger.keys()) if isinstance(ledger, dict) else set()
    audit_targets = [s for s in (sig["shorts_today"] + sig["longs_today"]) if s not in uploaded]
    passes, fails = [], []
    try:
        from audit_video import audit
        for slug in audit_targets:
            try:
                ok, reasons = audit(slug)
            except Exception as e:  # noqa: BLE001
                ok, reasons = False, [f"audit 例外:{e}"]
            (passes if ok else fails).append({"slug": slug, "reasons": [] if ok else reasons})
    except Exception as e:  # noqa: BLE001
        sig["audit_err"] = str(e)[:80]
    sig["audit_pass"] = passes
    sig["audit_fail"] = fails

    # 上架：今日是否已上架報表 + 累計
    sig["published_today"] = (REPORTS / f"{sig['date']}_自動上架.md").exists()
    sig["total_uploaded"] = len(uploaded)
    sig["library"] = len(list(OUT.glob("S_*.mp4")) + list(OUT.glob("L_*.mp4")))

    # 頻道數據 + 與上次快照的 delta
    stats = None
    try:
        from decision_dept import yt_service, gather_stats
        rows = gather_stats(yt_service())
        stats = {
            "total_views": sum(r["views"] for r in rows),
            "n_videos": len(rows),
            "top": [{"title": r["title"], "views": r["views"], "is_short": r["is_short"]} for r in rows[:5]],
            "bottom": [{"title": r["title"], "views": r["views"], "is_short": r["is_short"]}
                       for r in rows[-5:] if r["views"] >= 0][::-1] if len(rows) > 5 else [],
        }
    except Exception as e:  # noqa: BLE001
        sig["stats_err"] = str(e)[:80]
    sig["stats"] = stats

    # 真實 Analytics（拿到權限後才有；沒有就 None，誠實不假裝）
    sig["analytics"] = None
    try:
        import yt_analytics as ya
        if ya.available():
            summ = ya.channel_summary(28)
            ic = ya.impressions_ctr(28)
            if summ is not None:
                sig["analytics"] = {"avg_pct": summ.get("avg_pct"), "minutes": summ.get("minutes"),
                                    "subs_gained": summ.get("subs_gained"),
                                    "ctr": (ic or {}).get("ctr"), "impressions": (ic or {}).get("impressions")}
    except Exception:
        pass

    hist = _load(HISTORY, [])
    prev = hist[-1] if hist else None
    if stats and prev and prev.get("total_views") is not None:
        sig["dview"] = stats["total_views"] - prev["total_views"]
        sig["ddays"] = 1
    else:
        sig["dview"] = None

    # 錯誤心跳（今日 ops_log 含 ⚠️/FAIL/錯誤）
    errs = []
    try:
        for ln in OPS.read_text(encoding="utf-8").splitlines()[-60:]:
            if any(k in ln for k in ("⚠️", "FAIL", "錯誤", "失敗", "FATAL")):
                errs.append(ln.strip())
    except Exception:
        pass
    sig["errors"] = errs[-8:]
    return sig


# --------------------------------------------------------------------------- #
# 2) 規則式分析 → 具體優化（永遠可跑，不依賴金鑰）
# --------------------------------------------------------------------------- #
def rule_optimizations(sig):
    opt = []
    nprod = len(sig["shorts_today"]) + len(sig["longs_today"])
    paused = _load(DIRECTIVES, {}).get("paused", False)

    if sig["audit_fail"]:
        reasons = sorted({r for f in sig["audit_fail"] for r in f.get("reasons", [])})
        opt.append(f"審核未過 {len(sig['audit_fail'])} 支，腳本下輪務必避免：{ '；'.join(reasons)[:160] }")
    if nprod == 0 and not paused:
        opt.append("今日零產出 → 檢查補產流程（ANTHROPIC_API_KEY／配音／make_video）是否中斷。")
    elif len(sig["shorts_today"]) < 3 and not paused:
        opt.append(f"Shorts 今日只產 {len(sig['shorts_today'])} 支（KPI≥3）→ 下輪加碼 Shorts 衝量。")
    if sig.get("stats") and sig["stats"]["total_views"] == 0:
        opt.append("總觀看仍為 0 → 現階段重點是『多元測試＋衝 Shorts 量＋累積數據』，先不過度優化。")
    if sig.get("dview") is not None and sig["dview"] <= 0 and (sig.get("stats") or {}).get("n_videos", 0) > 3:
        opt.append("觀看較昨日無成長 → 加強前 2 秒鉤子與標題點擊率，並複製目前最高觀看片的角度。")
    bottom = (sig.get("stats") or {}).get("bottom", [])
    if bottom and (sig.get("stats") or {}).get("total_views", 0) > 50:
        worst = bottom[0]
        opt.append(f"表現最弱：「{worst['title']}」({worst['views']} 觀看)→ 該角度先少做，題材往高觀看靠攏。")
    a = sig.get("analytics")
    if a:
        if (a.get("avg_pct") or 0) and a["avg_pct"] < 30:
            opt.append(f"平均觀看僅 {a['avg_pct']:.0f}%（偏低）→ 強化前 3 秒鉤子、縮短鋪陳、開門見山給結論。")
        if (a.get("ctr") or 0) and a["ctr"] < 3:
            opt.append(f"曝光點閱率 CTR {a['ctr']:.1f}%（偏低）→ ⑮縮圖部 A/B 換縮圖與標題（數字/反差/痛點）。")
    if sig.get("errors"):
        opt.append(f"偵測到 {len(sig['errors'])} 條異常日誌 → 排查（見報告錯誤區）。")
    if not opt:
        opt.append("本輪運作正常、無明顯異常；維持衝量與多元測試，持續累積數據。")
    return opt[:6]


# --------------------------------------------------------------------------- #
# 3) Claude 加強分析（有金鑰才跑）→ 補充優化 + 生產偏好
# --------------------------------------------------------------------------- #
def claude_optimizations(sig, report_md):
    if not API_KEY:
        return None
    try:
        import requests
        prompt = f"""你是量化阿森 YouTube 工作室的【回顧檢討部門】總監。以下是本輪自動產線的回顧報告。
請做**冷靜的自我檢討**並只輸出 JSON（不要多餘字）：
{{
 "diagnosis":"一句話本輪總體判斷",
 "optimizations":["2-4 條具體、可執行的優化動作（給各部門下輪照做）"],
 "produce_more":["建議多做的題材/角度(可空)"],
 "avoid_topics":["建議少做的題材(可空)"]
}}
誠實鐵則：數據薄時就說『先衝量累積數據』，不要掰假洞察；不編造損益、不保證收益。
頻道=量化/自動交易教學(網格/定投/派網/回測/風控)，第一目標 YPP(主攻 Shorts)。

=== 回顧報告 ===
{report_md[:3500]}"""
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": MODEL, "max_tokens": 1200,
                                "messages": [{"role": "user", "content": prompt}]}, timeout=120)
        r.raise_for_status()
        txt = r.json()["content"][0]["text"]
        m = re.search(r"\{.*\}", txt, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Claude 檢討失敗，僅用規則式：{e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# 4) 寫報告 + 套用優化
# --------------------------------------------------------------------------- #
def write_report(sig, rule_opt, ai):
    REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ⑫ 回顧檢討報告｜{sig['date']}", "",
         f"> 自省閉環：產量 / 審核 / 上架 / 數據 → 分析 → 優化下一輪", ""]
    L += ["## 一、本輪產出",
          f"- 今日 Shorts：{len(sig['shorts_today'])} 支　長片：{len(sig['longs_today'])} 支　片庫共 {sig['library']} 支",
          f"- 累計上架：{sig['total_uploaded']} 支　今日已上架：{'是' if sig['published_today'] else '否'}", ""]
    L += ["## 二、審核（發布前品管）"]
    if sig["audit_fail"]:
        L.append(f"- ❌ 未過 {len(sig['audit_fail'])} 支：")
        for f in sig["audit_fail"]:
            L.append(f"    - {f['slug']}：{'；'.join(f.get('reasons', []))}")
    L.append(f"- ✅ 通過 {len(sig['audit_pass'])} 支" + (f"（未過 {len(sig['audit_fail'])}）" if sig['audit_fail'] else "（全數通過）"))
    if sig.get("audit_err"):
        L.append(f"- ⚠️ 審核模組異常：{sig['audit_err']}")
    L += ["", "## 三、頻道數據"]
    st = sig.get("stats")
    if st:
        dv = sig.get("dview")
        dtxt = "（首次快照，明天起算）" if dv is None else (f"較昨日 {'+' if dv >= 0 else ''}{dv}")
        L.append(f"- 總觀看：{st['total_views']}　影片數：{st['n_videos']}　{dtxt}")
        if st.get("top"):
            L.append("- 觀看 Top：")
            for t in st["top"]:
                L.append(f"    - [{'短' if t['is_short'] else '長'}] {t['title']}：{t['views']}")
    else:
        L.append(f"- （數據未取得{('：' + sig['stats_err']) if sig.get('stats_err') else '，頻道剛起步'}）")
    a = sig.get("analytics")
    if a:
        L.append(f"- 📊 Analytics(近28天)：平均觀看 {a.get('avg_pct') or 0:.1f}%、曝光點閱率 CTR {a.get('ctr') or 0:.2f}%、"
                 f"新增訂閱 {a.get('subs_gained') or 0}、總觀看分鐘 {a.get('minutes') or 0}")
    if sig.get("errors"):
        L += ["", "## 四、異常日誌"] + [f"- {e}" for e in sig["errors"]]
    L += ["", "## 五、檢討結論與優化（已自動套用至下一輪）", "", "**規則式檢討：**"]
    L += [f"- {o}" for o in rule_opt]
    if ai:
        L += ["", f"**Claude 檢討：** {ai.get('diagnosis', '')}"]
        L += [f"- {o}" for o in (ai.get("optimizations") or [])]
    L += ["", "> 以上優化已寫入 boss_directives（決策部門明早讀取）與 production_orders。"]
    path = REPORTS / f"{sig['date']}_回顧檢討.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def apply_optimizations(sig, rule_opt, ai):
    # 4a) 優化動作 → boss_directives（去重：每次替換掉舊的【自省優化】行）
    d = _load(DIRECTIVES, {})
    if not isinstance(d, dict):
        d = {}
    actions = list(rule_opt)
    if ai:
        actions = (ai.get("optimizations") or []) + actions
    # 取前 4 條，避免指令爆量
    seen, picked = set(), []
    for a in actions:
        a = a.strip()
        if a and a not in seen:
            seen.add(a); picked.append(a)
        if len(picked) >= 4:
            break
    ds = [x for x in d.get("directives", []) if not x.startswith(RETRO_TAG)]
    for a in picked:
        ds.append(f"{RETRO_TAG}{sig['date']}｜{a}")
    d["directives"] = ds
    DIRECTIVES.parent.mkdir(parents=True, exist_ok=True)
    DIRECTIVES.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4b) 生產偏好 → production_orders（合併 avoid/多做，去重）
    if ai and (ai.get("avoid_topics") or ai.get("produce_more")):
        orders = _load(ORDERS, {})
        if not isinstance(orders, dict):
            orders = {}
        def merge(key, new):
            cur = orders.get(key, []) or []
            for x in new or []:
                if x and x not in cur:
                    cur.append(x)
            orders[key] = cur[:12]
        merge("avoid_topics", ai.get("avoid_topics"))
        merge("produce_more", ai.get("produce_more"))
        orders["retro_updated"] = sig["date"]
        ORDERS.write_text(json.dumps(orders, ensure_ascii=False, indent=2), encoding="utf-8")


def save_snapshot(sig):
    hist = _load(HISTORY, [])
    if not isinstance(hist, list):
        hist = []
    st = sig.get("stats") or {}
    hist.append({"date": sig["date"], "total_views": st.get("total_views"),
                 "n_videos": st.get("n_videos"), "uploaded": sig["total_uploaded"],
                 "shorts_today": len(sig["shorts_today"]), "longs_today": len(sig["longs_today"]),
                 "audit_fail": len(sig["audit_fail"])})
    HISTORY.write_text(json.dumps(hist[-120:], ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    log_ops("回顧檢討", "開始自省：收集訊號→分析→優化…")
    sig = collect()
    rule_opt = rule_optimizations(sig)
    # 先寫一版報告（給 Claude 看），再用 Claude 補強
    tmp_report = REPORTS / f"{sig['date']}_回顧檢討.md"
    REPORTS.mkdir(parents=True, exist_ok=True)
    write_report(sig, rule_opt, None)
    ai = claude_optimizations(sig, tmp_report.read_text(encoding="utf-8"))
    path = write_report(sig, rule_opt, ai)      # 最終報告（含 Claude）
    apply_optimizations(sig, rule_opt, ai)
    save_snapshot(sig)
    nfix = len(rule_opt) + (len(ai.get("optimizations", [])) if ai else 0)
    log_ops("回顧檢討", f"完成 產出{len(sig['shorts_today'])+len(sig['longs_today'])}支 審核未過{len(sig['audit_fail'])} 優化{nfix}項 → {path.name}")
    print(f"[ok] 回顧檢討完成：{path}")
    print(f"     產出 {len(sig['shorts_today'])} 短 / {len(sig['longs_today'])} 長；審核未過 {len(sig['audit_fail'])}；優化 {nfix} 項已套用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
