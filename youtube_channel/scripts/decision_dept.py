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

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ops import log_ops
import llm  # 共用 LLM 路由(主 OpenRouter/DeepSeek→退回 Anthropic)，不再直打死掉的 Anthropic
import studio_common as sc  # 共用地基：PERSONA / has_llm_key / evidence_block

# 配額計量(全域 patch HttpRequest.execute,只掛一次;壞掉不影響本腳本)
try:
    import quota_meter as _qm; _qm.install()
except Exception:
    pass
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
LEDGER = STUDIO / "uploaded_ledger.json"
ORDERS = STUDIO / "production_orders.json"
PENDING = STUDIO / "pending_decisions.json"      # 待老闆拍板的決策(含選項)
AUTO_LOG = STUDIO / "auto_actions_log.json"       # 低風險決策自動執行紀錄(list)
BOSS_DEC = STUDIO / "boss_decisions.json"         # 老闆已拍板的選擇
DAILY = STUDIO / "metrics_daily.json"            # 每日乾淨快照（retro 寫，決策讀趨勢）
QUALITY = STUDIO / "quality_scores.json"         # 品管分數
COMPLETION = STUDIO / "completion_signals.json"  # 完播率訊號
TOKEN = ROOT / "token_manage.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

ORIGINAL = ["fO-ZyxHI_xY", "ijCNjwEDRnc", "Qf-xkKw4kGQ", "_I82uMc__HM", "K4x90FeqZSo", "wZyBaJJ7A40"]

# ── 主題收斂硬執行（流量作戰表①：演算法信任度＝命門）─────────────────────
# 台股全市場開放（含個股/選股/當沖/存股/財報/籌碼 全放行）；離叢集只剩美股/質押借貸/行為財務
# （＝別的市場＋私人理財，客群不同）。誠信改由角度層守（PERSONA／GUARD／題庫尾註）：
# 台股什麼都能講，但角度一律數據/回測/拆穿/避雷/教學，不喊單、不報明牌、不喊目標價、不保證會漲會賺。
# 馬丁格爾/破產機率/夏普 這類仍屬「自動交易散戶」客群（只要用數字包裝就是好題），不列黑。
# write_orders 會程式層強制：preferred_keywords 去掉離叢集詞、avoid_topics 補上離叢集＋誇大詞，
# 不靠 LLM 自律——避免叢集發散觸發演算法重置、燒掉累積信任。
OFF_CLUSTER = ["美股", "質押", "借貸", "行為財務"]
HYPE_BAN = "理財誇大標題（躺賺/穩賺/保證/一天賺X，2026 被 YouTube 重點限流）"


def _converge(d):
    """主題收斂硬執行：回 (清過的 preferred_keywords, 清過的 produce_more, 補強的 avoid_topics)。"""
    pk = [k for k in (d.get("preferred_keywords") or [])
          if not any(o.lower() in str(k).lower() for o in OFF_CLUSTER)]
    if not pk:  # 全被清掉時的安全網：鎖回核心叢集（含台股大盤ETF 混血雙軌）
        pk = ["派網Pionex", "網格機器人", "定投教學", "0050大盤ETF回測", "台股大盤擇時回測", "自動化交易", "量化交易台灣"]
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


# ── 🚨 自動執行紅線白名單（寫進 code，不靠 LLM 自律）──────────────────────
# 只有「內部可逆」動作才准低風險自動生效。不在白名單一律當高風險→絕不自動、進待老闆拍板。
# 絕對禁止自動（強制 high）：對外/排程發布、買量刷量、開通道 tunnel、花錢支出、
# 改頻道名/簡介、刪除或修改 live 影片——這些一律不在白名單、且高風險關鍵詞再擋一層。
AUTO_SAFE_ACTIONS = {
    "produce_more",        # 調整補產「多做」題材
    "produce_less",        # 調整「少做」（併入 avoid_topics）
    "avoid_topics",        # 補「避免題材」
    "preferred_keywords",  # 調整偏好選題關鍵字
    "format",              # 調整主攻格式 short/long/both
    "add_topics",          # 加題到題庫（topic_bank.add_topics）
    "downrank",            # 降權某題材（併入 avoid_topics，標降權）
}

# 高風險關鍵詞：命中即強制 high（即使 type 混進白名單也擋，雙保險）。
_HIGH_RISK_MARKERS = (
    "publish", "schedule", "發布", "發佈", "排程", "上架", "上片",
    "buy", "刷量", "買量", "衝量", "推廣", "投放", "廣告",
    "tunnel", "通道", "開通道",
    "花錢", "付費", "課金", "支出", "預算", "budget", "spend", "cost", "$",
    "改名", "頻道名", "簡介", "品牌名", "rename",
    "刪除", "刪掉", "delete", "remove", "下架", "改 live", "改live", "改 上線",
)


def _is_auto_safe(action):
    """紅線白名單過濾：只有『內部可逆』動作（改生產指令/加題/降權）才回 True。
    不在白名單、格式不符、或命中高風險關鍵詞（發布/排程/買量/通道/花錢/改品牌/刪改live）
    一律回 False → 當高風險、絕不自動執行、改由老闆拍板。"""
    if not isinstance(action, dict):
        return False
    t = str(action.get("type", "")).strip().lower()
    if t not in AUTO_SAFE_ACTIONS:
        return False
    blob = json.dumps(action, ensure_ascii=False).lower()
    if any(m.lower() in blob for m in _HIGH_RISK_MARKERS):
        return False
    return True


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def tw_now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def _off_cluster_filter(items):
    """濾掉離核心受眾叢集的詞（沿用 _converge 的紅線），避免自動套用時把叢集發散。"""
    return [x for x in items
            if x and not any(o.lower() in str(x).lower() for o in OFF_CLUSTER)]


def apply_low_risk(d):
    """把 risk=='low' 且通過白名單 (_is_auto_safe) 的決策**自動套用**：
    併進 production_orders（多做/少做/避免/關鍵字/格式/降權）或呼叫 topic_bank.add_topics 加題。
    每筆寫一則到 auto_actions_log.json（list, {ts,question,action,result}）。
    高風險或不在白名單者一律不動，留給老闆拍板。回傳已執行清單（給匯報用）。"""
    applied = []
    decisions = d.get("pending_decisions") or []
    try:
        orders = json.loads(ORDERS.read_text(encoding="utf-8")) if ORDERS.exists() else {}
    except Exception:
        orders = {}
    changed = False
    for pd in decisions:
        if str(pd.get("risk", "")).strip().lower() != "low":
            continue  # 只自動處理低風險
        action = pd.get("auto_action")
        if not _is_auto_safe(action):
            continue  # 🚨紅線：不在白名單/命中高風險詞 → 絕不自動，留給老闆
        t = str(action.get("type", "")).strip().lower()
        vals = action.get("values") or action.get("value") or []
        if isinstance(vals, str):
            vals = [vals]
        vals = [str(v).strip() for v in vals if str(v).strip()]
        result = ""
        try:
            if t == "produce_more":
                add = _off_cluster_filter(vals)
                cur = list(orders.get("produce_more") or [])
                for x in add:
                    if x not in cur:
                        cur.append(x)
                orders["produce_more"] = cur[:12]
                changed = True
                result = f"補產『多做』+{len(add)} 項"
            elif t in ("produce_less", "downrank"):
                tag = "（決策降權）" if t == "downrank" else "（決策少做）"
                cur = list(orders.get("avoid_topics") or [])
                cnt = 0
                for x in vals:
                    line = f"{x}{tag}"
                    if line not in cur:
                        cur.append(line)
                        cnt += 1
                orders["avoid_topics"] = cur[:20]
                changed = True
                result = f"{'降權' if t == 'downrank' else '少做'} +{cnt} 項（併入 avoid）"
            elif t == "avoid_topics":
                cur = list(orders.get("avoid_topics") or [])
                cnt = 0
                for x in vals:
                    if x not in cur:
                        cur.append(x)
                        cnt += 1
                orders["avoid_topics"] = cur[:20]
                changed = True
                result = f"避免題材 +{cnt} 項"
            elif t == "preferred_keywords":
                add = _off_cluster_filter(vals)
                cur = list(orders.get("preferred_keywords") or [])
                for x in add:
                    if x not in cur:
                        cur.append(x)
                orders["preferred_keywords"] = cur
                changed = True
                result = f"偏好關鍵字 +{len(add)} 項"
            elif t == "format":
                fv = (vals[0] if vals else "").strip().lower()
                if fv in ("short", "long", "both"):
                    orders["format_focus"] = fv
                    changed = True
                    result = f"主攻格式→{fv}"
                else:
                    continue
            elif t == "add_topics":
                topics = action.get("topics") or [{"title": v} for v in vals]
                topics = [x for x in topics if isinstance(x, dict) and x.get("title")]
                if not topics:
                    continue
                import topic_bank
                n = topic_bank.add_topics(topics, source="決策自動")
                result = f"加題到題庫 +{n} 題"
            else:
                continue
        except Exception as exc:  # noqa: BLE001
            result = f"套用失敗：{str(exc)[:60]}"
        applied.append({
            "ts": tw_now(),
            "question": pd.get("question", ""),
            "action": action,
            "result": result,
        })
    if changed:
        orders["updated"] = tw_today()
        sc.save_json_atomic(ORDERS, orders)
    if applied:
        log = []
        try:
            if AUTO_LOG.exists():
                log = json.loads(AUTO_LOG.read_text(encoding="utf-8"))
            if not isinstance(log, list):
                log = []
        except Exception:
            log = []
        log.extend(applied)
        AUTO_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return applied


def yt_service():
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def gather_stats(yt, report=None):
    """report:傳入 dict 即可拿到本次抓取的完整性(chunks_failed / complete)。

    2026-08-24 修:原本分塊查詢碰 403 quotaExceeded 只 print 一行 warn 就繼續下一塊,
    呼叫端拿到「少了幾百筆的 rows」卻無從得知,len(rows) 被當成「頻道影片數」寫進
    metrics 快照(07-11 / 07-15 / 08-22 三次),害 northstar 趨勢算出 -98.5% 假崩盤,
    再害 growth_agent 連續對假訊號出手。len(rows) 是「這次成功回來的筆數」,
    不是頻道影片數 —— 把失敗塊數回報給呼叫端,讓它能 fail-closed。
    """
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    id_to_slug = {v: k for k, v in ledger.items()}
    ids = list(dict.fromkeys(ORIGINAL + list(ledger.values())))
    rows = []
    chunks_total = chunks_failed = 0
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        chunks_total += 1
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
            chunks_failed += 1
            print(f"[warn] 抓數據失敗(第 {chunks_total} 塊)：{exc}", file=sys.stderr)
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
    if report is not None:
        report.update({"requested": len(ids), "returned": len(rows),
                       "chunks_total": chunks_total, "chunks_failed": chunks_failed,
                       "complete": chunks_failed == 0})
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
    try:
        daily_hist = json.loads(DAILY.read_text(encoding="utf-8")) if DAILY.exists() else []
        if isinstance(daily_hist, list) and len(daily_hist) >= 2:
            latest_v = daily_hist[-1].get("total_views") or 0
            idx7 = max(0, len(daily_hist) - 8)
            idx28 = max(0, len(daily_hist) - 29)
            d7 = latest_v - (daily_hist[idx7].get("total_views") or latest_v)
            d28 = latest_v - (daily_hist[idx28].get("total_views") or latest_v)
            trend_txt = (f"\n\n【歷史趨勢】近7天觀看 delta={'+' if d7 >= 0 else ''}{d7}"
                         f"；近28天 delta={'+' if d28 >= 0 else ''}{d28}")
    except Exception:
        pass

    # 補充：本頻道實證 few-shot（decision 已吃大量真數據，這裡只作橫向補強、不重複）
    evidence_txt = ""
    try:
        eb = sc.evidence_block()
        if eb:
            evidence_txt = "\n\n" + eb
    except Exception:
        pass

    prompt = f"""{sc.PERSONA}

你是量化阿森 YouTube 工作室的【決策部門】總監，直接對大老闆 Carson 負責。
頻道主題=量化/自動交易教學(網格、定投、派網Pionex、回測、風控)，繁體中文。
第一目標=YPP 達標(主攻 Shorts 衝1000萬觀看/訂閱1000)。誠信鐵則:不編造損益、不保證收益。
★主題收斂鐵律(2026-06-28 流量作戰表,演算法信任度是命門):produce_more/avoid_topics 必須鎖定**單一受眾叢集＝想自動化又怕被割的上班族散戶(小資新手)**——主題一致演算法才建得起「你服務誰」的辨識;離核心受眾的題材(美股/個股選股/質押借貸/AI×交易/行為財務等不同客群)只當小注實驗、別變主力(台股大盤ETF/當沖/存股/籌碼已是正式主力叢集,全力做),避免發散觸發演算法重置、燒掉累積。produce_more 至少 1 項要是「可搜尋長尾題」(吃不挑帳號權重的搜尋流量,如「派網網格怎麼設」)。avoid_topics 務必含「理財誇大標題(躺賺/穩賺/一天賺X)——2026 被 YouTube 重點限流」。
新手方向(2026-07-02 新增·重點方向之一，非唯一):受眾多納入**想被動賺但怕被割的投資小白**;有個好用角度＝**「我先幫你試、別自己送死」實測避雷**(用回測替小白試，恐懼→安心)。produce_more **至少 1-2 項**走小白恐懼+避雷題(被割/被套/該不該碰/會不會虧/我幫你試);硬核公式題(破產機率/夏普/凱利)完播偏低、酌量別當主力(不必列入 avoid，能白話化就做)。整體能白話就白話。

目前所有影片成效(總觀看 {total_views})：
{summary or '（尚無影片數據，頻道剛起步）'}{boss_txt}{traffic_txt}{train_txt}{quality_txt}{completion_txt}{trend_txt}{evidence_txt}

請做出**營運決策**並只輸出 JSON(不要其他字)：
{{
 "situation":"一句話現況判斷",
 "produce_more":["接下來該多做的題材/角度(3-6項,具體)"],
 "produce_less":["該少做或停的(可空陣列)"],
 "preferred_keywords":["偏好的選題關鍵字(英文或中文,給補產部門用)"],
 "avoid_topics":["要避免重複或表現差的題材(可空)"],
 "format_focus":"short 或 long 或 both(現階段建議)",
 "actions_for_departments":{{"靈感":"...","Shorts":"...","流量SEO":"...","宣傳":"..."}},
 "pending_decisions":[{{"question":"需要決策的具體策略選擇","options":["選項A","選項B","選項C"],"evidence":"用上方真數據替各選項附佐證(如相關題材的完播/觀看/品管分)，讓老闆有據可拍；沒有直接數據就寫『暫無數據，屬前瞻性判斷』","recommendation":"你建議選哪個+一句理由","risk":"low 或 high","auto_action":{{"type":"produce_more|produce_less|avoid_topics|preferred_keywords|format|add_topics|downrank","values":["..."],"note":"為何這是內部可逆的低風險動作"}}}}],
 "one_line":"給老闆的一句話戰略判斷"
}}
★決策自主分級(2026-07-02 新增·讓決策部門更自主)：每筆 pending_decision **務必**自貼 `risk`＝"low" 或 "high"，並在 risk="low" 時給出可自動執行的 `auto_action`：
 ・risk="low"＝**內部可逆、低風險**的營運微調，系統會**自動執行不等老闆**。auto_action.type **只允許**這幾種：produce_more(多做某題材)、produce_less(少做)、avoid_topics(避免某題材)、preferred_keywords(調偏好關鍵字)、format(改主攻格式 short/long/both)、add_topics(加題到題庫，values 放標題字串)、downrank(降權某題材)。values 放對應字串陣列(format 放單一 short/long/both)。
 ・risk="high"＝**要老闆拍板**的重大/不可逆決策，系統**只會列給老闆、不自動做**。凡涉及以下一律必須 high、且**不要**給 auto_action：對外發布/排程發布(schedule/publish)、買量刷量/投放廣告、開通道 tunnel、任何花錢或大額支出、改頻道名/簡介/品牌、刪除或修改已上線(live)影片、擴編、大方向轉型。
 ・拿不準就標 high(寧可讓老闆看)。系統另有白名單硬性把關：auto_action 不在上述七種或命中發布/花錢/買量/改品牌/刪改live 等關鍵詞者，一律被降級為需老闆拍板——所以別想用 low 夾帶對外或花錢動作。
pending_decisions：**不設數量上限** —— 凡是「真正需要老闆拍板」的策略選擇，有幾個就列幾個，全部端出來給老闆看(別為了精簡而漏掉該問的)。判準＝會花錢、大方向轉變、題材/節奏/品牌取捨、是否擴編或做某系列、實驗性方向等真正該老闆決定的事；每個給 2-4 個具體選項＋你的建議。**每個 pending_decision 的 evidence 欄務必盡量引用上方真實成效數據(相關完播率/觀看/品管分)當佐證**——讓老闆是「看數據拍板」而非憑感覺；真的沒有相關數據才寫暫無。但**只放真正值得老闆決定的，絕不為湊數硬湊填充**；老闆已拍板過的不要重複問；真的沒有值得問的就回空陣列。寧可這次 0 個、需要時 5 個、8 個都行，重點是「必要才給、必要的全給」。
數據太少時方向就給「保持多元測試、衝Shorts量、累積數據」這類務實方向,不要硬掰假洞察。"""
    last = None
    for attempt in range(2):  # json_mode 強制合格 JSON,3→2 次夠;截斷才是真因(見下 max_tokens 降量)
        # 2026-08-12:4500→7000。「輸出遠小於8000」是非推理模型時代量的;現在大請求走
        # OpenRouter gemini-2.5-flash(推理模型,thinking 吃同一份 max_tokens 預算),實測
        # 05:37 連 3 次只回「{」就斷=thinking 燒光預算正文被截。7000 給 thinking 留空間。
        txt = llm.complete(prompt, 7000, json_mode=True)
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
    sc.save_json_atomic(ORDERS, orders)


def write_pending(d):
    """把 Claude 產的待拍板決策寫成可選選項；只寫**真正要老闆拍板**的(risk=="high"，
    或 risk=="low" 但 auto_action 未通過白名單→被降級為高風險的)；低風險已自動執行者不再列。
    另過濾老闆已答過的。"""
    answered = sc.load_json_safe(BOSS_DEC, default={})
    out = []
    for pd in (d.get("pending_decisions") or []):
        # 低風險且通過白名單者＝apply_low_risk 已自動執行，不進待拍板；其餘(含低風險但不安全)一律當高風險端給老闆
        if str(pd.get("risk", "")).strip().lower() == "low" and _is_auto_safe(pd.get("auto_action")):
            continue
        q = (pd.get("question") or "").strip()
        opts = pd.get("options") or []
        if not q or len(opts) < 2:
            continue
        pid = "d" + hashlib.md5(q.encode("utf-8")).hexdigest()[:8]
        if pid in answered:
            continue
        out.append({"id": pid, "question": q, "options": opts,
                    "evidence": pd.get("evidence", ""),  # 數據佐證(相關完播/觀看)，讓老闆拍板有據
                    "recommendation": pd.get("recommendation", "")})
    sc.save_json_atomic(PENDING, out)
    return out


def write_report(d, rows, date, applied=None):
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
    # 今日自動執行（低風險決策已自動生效，無需老闆動作）
    applied = applied or []
    lines += ["", "## 今日自動執行（低風險·系統已自動生效）"]
    if applied:
        for a in applied:
            act = a.get("action") or {}
            atype = act.get("type", "")
            lines.append(f"- **{a.get('question','')}**（{atype}）→ {a.get('result','')}")
    else:
        lines.append("- （本日無低風險可自動執行的決策）")
    # 待拍板只顯示真正要老闆決定的（排除已自動執行的低風險）
    pend = [p for p in (d.get("pending_decisions", []) or [])
            if not (str(p.get("risk", "")).strip().lower() == "low" and _is_auto_safe(p.get("auto_action")))]
    lines += ["", "## ⚠️ 待你拍板（請到決策中心點選選項）"]
    if pend:
        for p in pend:
            opts = " / ".join(p.get("options", []))
            ev = p.get("evidence", "")
            line = f"- **{p.get('question','')}**\n  選項：{opts}"
            if ev:
                line += f"\n  數據佐證：{ev}"
            line += f"\n  建議：{p.get('recommendation','')}"
            lines.append(line)
    else:
        lines.append("- （本日無需老闆決策）")
    lines += ["", "> 生產指令已寫入 production_orders.json，補產部門明早自動套用。"]
    (REPORTS / f"{date}_決策.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    # 任一 LLM 供應商 key 即可放行(Anthropic 沒錢→實際呼叫由 llm.complete 改道 OpenRouter;
    # 舊版死綁 ANTHROPIC_API_KEY 導致每天 FATAL 退出→從不產生待拍板→決策中心永遠空)。
    if not sc.has_llm_key():
        print("[FATAL] 無任何 LLM 供應商 API key", file=sys.stderr)
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
    applied = apply_low_risk(d)          # 低風險決策自動執行(白名單過濾),疊加到 production_orders/題庫
    pend = write_pending(d)             # 只寫真正要老闆拍板的(高風險)
    write_report(d, rows, date, applied)
    log_ops("決策部門", f"完成 格式={d.get('format_focus')} 多做{len(d.get('produce_more',[]))}項 自動執行{len(applied)}項 待拍板{len(pend)}項｜{d.get('one_line','')[:36]}")
    print(f"[ok] 決策完成。格式建議={d.get('format_focus')}，多做 {len(d.get('produce_more',[]))} 項，自動執行 {len(applied)} 項，待老闆拍板 {len(pend)} 項。")
    print(f"     一句話：{d.get('one_line','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
