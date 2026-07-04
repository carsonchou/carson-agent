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
DAILY = STUDIO / "metrics_daily.json"            # 每日乾淨快照（retro 寫，決策讀趨勢）
QUALITY = STUDIO / "quality_scores.json"         # 品管分數
COMPLETION = STUDIO / "completion_signals.json"  # 完播率訊號
TOKEN = ROOT / "token_manage.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"  # 決策用較強模型，一天一次成本低

ORIGINAL = ["fO-ZyxHI_xY", "ijCNjwEDRnc", "Qf-xkKw4kGQ", "_I82uMc__HM", "K4x90FeqZSo", "wZyBaJJ7A40"]

# ── 主題收斂硬執行（流量作戰表①：演算法信任度＝命門）─────────────────────
# 以「受眾叢集」為界（非機制題）：台股/美股個股/質押/AI選股 等＝不同客群→離叢集。
# 馬丁格爾/破產機率/夏普 這類仍屬「自動交易散戶」客群（只要用數字包裝就是好題），不列黑。
# write_orders 會程式層強制：preferred_keywords 去掉離叢集詞、avoid_topics 補上離叢集＋誇大詞，
# 不靠 LLM 自律——避免叢集發散觸發演算法重置、燒掉累積信任。
OFF_CLUSTER = ["台股", "美股", "個股", "存股", "質押", "借貸", "AI選股", "選股", "行為財務", "ETF定期"]
HYPE_BAN = "理財誇大標題（躺賺/穩賺/保證/一天賺X，2026 被 YouTube 重點限流）"


def _converge(d):
    """主題收斂硬執行：回 (清過的 preferred_keywords, 清過的 produce_more, 補強的 avoid_topics)。"""
    pk = [k for k in (d.get("preferred_keywords") or [])
          if not any(o.lower() in str(k).lower() for o in OFF_CLUSTER)]
    if not pk:  # 全被清掉時的安全網：鎖回核心叢集
        pk = ["派網Pionex", "網格機器人", "定投教學", "Pionex新手", "自動化交易", "量化交易台灣"]
    # produce_more 也過濾離叢集詞，避免 LLM 自律失效導致叢集發散
    pm = [t for t in (d.get("produce_more") or [])
          if not any(o.lower() in str(t).lower() for o in OFF_CLUSTER)]
    av = list(d.get("avoid_topics") or [])
    for o in OFF_CLUSTER:
        if not any(o in str(a) for a in av):
            av.append(f"{o}（離核心受眾，僅限小注實驗、別當主力）")
    if not any(("誇大" in str(a) or "躺賺" in str(a) or "穩賺" in str(a)) for a in av):
        av.append(HYPE_BAN)
    return pk, pm, av


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


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
                    "retention": None,  # 稍後由 yt_analytics 補入
                })
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 抓數據失敗：{exc}", file=sys.stderr)
    # 補 retention 欄位（yt_analytics.video_stats），排序改成複合分
    try:
        import yt_analytics as ya
        vstats = ya.video_stats() or {}
        for r in rows:
            vs = vstats.get(r["id"])
            if vs:
                r["retention"] = vs.get("retention")
        # 複合排序：views × (1 + retention/100)；retention 為 None 時當 0（純觀看排序）
        rows.sort(key=lambda r: r["views"] * (1 + (r.get("retention") or 0) / 100.0), reverse=True)
    except Exception:
        # yt_analytics 不可用時退回純觀看排序
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


def _extract_json(txt):
    """容錯抽 JSON：去 markdown 圍欄、去尾逗號、截斷救援(平衡括號)。失敗回 None。"""
    if not txt:
        return None
    s = txt.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i == -1:
        return None
    cand = s[i:j + 1] if j > i else s[i:]
    try:
        return json.loads(cand)
    except Exception:
        pass
    try:  # 去尾逗號
        return json.loads(re.sub(r",\s*([}\]])", r"\1", cand))
    except Exception:
        pass
    try:  # 截斷救援：抓第一個完整平衡的物件
        depth = 0; instr = False; esc = False
        for k, ch in enumerate(cand):
            if esc:
                esc = False; continue
            if ch == "\\":
                esc = True; continue
            if ch == '"':
                instr = not instr
            if instr:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(cand[:k + 1])
    except Exception:
        pass
    return None


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
        # 只取最近 15 筆（以 ts 欄位或 key 字典序排序，避免 prompt 爆量）
        _items_sorted = sorted(answered.items(), key=lambda x: x[1].get("ts", x[0]))[-15:]
        boss_txt += "\n\n【老闆已拍板的決策（務必遵守，不要再問）】：\n" + "\n".join(
            f"- {v.get('question','')} → 老闆選：{v.get('choice','')}" for _, v in _items_sorted)
    # 先載流量訊號(含 per-video 完播率)：讓主排行榜也標上完播%＝決策看「品質」不只看觀看數
    sig = {}
    try:
        sig = json.loads((STUDIO / "traffic_signals.json").read_text(encoding="utf-8"))
    except Exception:
        sig = {}
    retmap = {v.get("slug", ""): v.get("avg_pct")
              for v in (sig.get("top_videos") or []) if v.get("slug")}

    def _row_line(r):
        base = f"- [{'短' if r['is_short'] else '長'}] {r['title']}｜觀看{r['views']} 讚{r['likes']} 留言{r['comments']}"
        pct = retmap.get(r.get("slug"))
        return base + (f" ★完播{pct}%" if pct is not None else "")
    summary = "\n".join(_row_line(r) for r in rows[:30])
    # 流量部門訊號：把「真實有流量的題材」餵進決策（資料驅動選題）
    traffic_txt = ""
    try:
        if sig.get("win_keywords") or sig.get("top_videos"):
            tv = "；".join(f"{v['slug'][:24]}({v['views']}觀看/{v['avg_pct']}%)"
                           for v in sig.get("top_videos", [])[:5])
            traffic_txt = ("\n\n【流量部門·真實數據洞察（務必納入選題）】"
                           f"\n・有流量的題材(優先多做)：{('、'.join(sig['win_keywords'])) or '數據累積中'}"
                           f"\n・表現弱的題材(少做)：{('、'.join(sig.get('weak_keywords', []))) or '無'}"
                           f"\n・近28天最高流量影片：{tv or '累積中'}"
                           "\n・★完播率＝命門：排行榜標★完播%者，多做高完播題材；高觀看但低完播(<35%)的標題黨題材要砍。")
    except Exception:
        pass
    # 進修部門（每週）資料驅動洞察 → 納入選題與方向
    train_txt = ""
    try:
        tf = STUDIO / "training_insights.md"
        if tf.exists():
            t = tf.read_text(encoding="utf-8").strip()
            if t:
                train_txt = "\n\n【進修部門·本週資料驅動洞察（納入選題與方向）】\n" + t[:1200]
    except Exception:
        pass

    # ③ 品管分數回流：低分(<60) 或低完播(<35%) 的題材列為「應少做」
    quality_txt = ""
    try:
        qdata = json.loads(QUALITY.read_text(encoding="utf-8")) if QUALITY.exists() else {}
        pub = qdata.get("published") or []
        bad_topics = []
        for p in pub:
            score = p.get("score")
            ret = p.get("retention") or p.get("avg_pct")
            _bad_score = score is not None and float(score) < 60
            _bad_ret = ret is not None and float(ret) < 35
            if _bad_score or _bad_ret:
                label = p.get("slug") or p.get("title") or ""
                if label:
                    reason = []
                    if _bad_score:
                        reason.append(f"品管{score}分")
                    if _bad_ret:
                        reason.append(f"完播{ret}%")
                    bad_topics.append(f"{label[:28]}({'/'.join(reason)})")
        if bad_topics:
            quality_txt = ("\n\n【品管分數·低分/低完播題材（應少做/避免）】\n"
                           + "、".join(bad_topics[:8]))
    except Exception:
        pass

    # ④ 完播率訊號回流決策
    completion_txt = ""
    try:
        csig = json.loads(COMPLETION.read_text(encoding="utf-8")) if COMPLETION.exists() else {}
        if csig:
            delta = csig.get("new_vs_overall_delta")
            high_c = csig.get("high_completion_topics") or []
            low_c = csig.get("low_completion_topics") or []
            parts = []
            if delta is not None:
                arrow = f"↑+{delta}%" if delta > 0 else f"↓{delta}%"
                parts.append(f"新片完播趨勢 {arrow}（vs 整體 {csig.get('overall_avg_pct','?')}%）")
            if high_c:
                parts.append(f"高完播題材（多做）：{'、'.join(high_c[:4])}")
            if low_c:
                parts.append(f"低完播題材（少做）：{'、'.join(low_c[:4])}")
            if parts:
                completion_txt = "\n\n【完播率訊號·閉環回饋（命門指標，納入選題）】\n" + "；".join(parts)
    except Exception:
        pass

    # ④ 歷史趨勢（7/28 天觀看 delta，讓決策知道成長方向）
    trend_txt = ""
    dview_for_model = None  # 供下方條件式模型選擇用
    try:
        daily_hist = json.loads(DAILY.read_text(encoding="utf-8")) if DAILY.exists() else []
        if isinstance(daily_hist, list) and len(daily_hist) >= 2:
            latest_v = daily_hist[-1].get("total_views") or 0
            prev_v = daily_hist[-2].get("total_views") or latest_v
            dview_for_model = latest_v - prev_v
            idx7 = max(0, len(daily_hist) - 8)
            idx28 = max(0, len(daily_hist) - 29)
            d7 = latest_v - (daily_hist[idx7].get("total_views") or latest_v)
            d28 = latest_v - (daily_hist[idx28].get("total_views") or latest_v)
            trend_txt = (f"\n\n【歷史趨勢】近7天觀看 delta={'+' if d7 >= 0 else ''}{d7}"
                         f"；近28天 delta={'+' if d28 >= 0 else ''}{d28}")
    except Exception:
        pass

    # 根據活躍度條件式選模型：數據少或無顯著變化→省成本用 Haiku；有明顯趨勢→Sonnet 深度分析
    _use_model = MODEL
    try:
        _small_channel = total_views < 100
        _flat = dview_for_model is None or abs(dview_for_model) < 5
        if _small_channel or _flat:
            _use_model = "claude-haiku-4-5-20251001"
    except Exception:
        pass

    prompt = f"""你是量化阿森 YouTube 工作室的【決策部門】總監，直接對大老闆 Carson 負責。
頻道主題=量化/自動交易教學(網格、定投、派網Pionex、回測、風控)，繁體中文。
第一目標=YPP 達標(主攻 Shorts 衝1000萬觀看/訂閱1000)。誠信鐵則:不編造損益、不保證收益。
★主題收斂鐵律(2026-06-28 流量作戰表,演算法信任度是命門):produce_more/avoid_topics 必須鎖定**單一受眾叢集＝想自動化又怕被割的上班族散戶(小資新手)**——主題一致演算法才建得起「你服務誰」的辨識;離核心受眾的題材(純硬核quant/台股/AI×交易/行為財務等不同客群)只當小注實驗、別變主力,避免發散觸發演算法重置、燒掉累積。produce_more 至少 1 項要是「可搜尋長尾題」(吃不挑帳號權重的搜尋流量,如「派網網格怎麼設」)。avoid_topics 務必含「理財誇大標題(躺賺/穩賺/一天賺X)——2026 被 YouTube 重點限流」。

目前所有影片成效(總觀看 {total_views})：
{summary or '（尚無影片數據，頻道剛起步）'}{boss_txt}{traffic_txt}{train_txt}{quality_txt}{completion_txt}{trend_txt}

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
    last = None
    for attempt in range(3):
        body = {"model": _use_model, "max_tokens": 8000, "messages": [{"role": "user", "content": prompt}]}
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json=body, timeout=180)
        r.raise_for_status()
        txt = r.json()["content"][0]["text"]
        parsed = _extract_json(txt)
        if parsed is not None:
            return parsed
        last = (txt or "")[:160]
        print(f"[warn] 決策 JSON 解析失敗 第 {attempt+1}/3 次，重試…", file=sys.stderr)
    raise ValueError(f"決策 JSON 連續 3 次解析失敗：{last}")


def write_orders(d):
    pk, pm, av = _converge(d)  # 主題收斂硬執行：pk=關鍵字、pm=多做(已過濾離叢集)、av=避免
    # 先讀現有指令：保留 retro 寫的 retro_updated/produce_more/avoid_topics 區塊，merge 不覆蓋
    existing = {}
    try:
        existing = json.loads(ORDERS.read_text(encoding="utf-8")) if ORDERS.exists() else {}
    except Exception:
        existing = {}
    # 合併 produce_more（決策新結果在前，retro 補充在後，去重）
    pm_merged = list(pm)
    for t in (existing.get("produce_more") or []):
        if t and t not in pm_merged:
            pm_merged.append(t)
    # 合併 avoid_topics（去重）
    av_merged = list(av)
    for t in (existing.get("avoid_topics") or []):
        if t and t not in av_merged:
            av_merged.append(t)
    orders = {
        "preferred_keywords": pk,
        "produce_more": pm_merged[:12],
        "avoid_topics": av_merged[:20],
        "format_focus": d.get("format_focus", "both"),
        "updated": tw_today(),
    }
    # 保留 retro 寫的標記
    if existing.get("retro_updated"):
        orders["retro_updated"] = existing["retro_updated"]
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
