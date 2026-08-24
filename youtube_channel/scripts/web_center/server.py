#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_center/server.py — 量化阿森「決策中心 網頁版」後端（純標準庫 http.server）。

J.A.R.V.I.S 質感的科幻 HUD 決策中心，取代醜陋的 tkinter 版（control_center.py 保留當備援）。

提供：
  GET  /                → index.html（單頁 HUD 儀表板）
  GET  /api/state       → 一份完整 JSON 快照（KPI / 走勢 / 18 部門 / 待拍板 / 倉庫 / 財務 / 雲端）
  POST /api/action      → 觸發雲端操作（補產/上架/跑一輪/壓榨/設產量/拍板/暫停…）
  POST /api/say         → 「跟小祕說」自然語言派工（先關鍵字、認不出再用 haiku）

設計原則（對齊 control_center.py）：
  - 單一真相＝本機：雲端 droplet 已欠費停權退役，部門出勤/倉庫/待拍板一律以本機檔案為準。
  - 誠實鐵則：部門狀態依「今日真實報告」判定，未自動化的部門如實標規劃中，不假綠燈。
  - 唯讀為主：/api/state 只讀檔/查 API；任何「寫」都集中在 /api/action，直接觸發本機腳本（scripts/local_cron.py 同一套排程共用）。
  - 省資源：YouTube/Analytics 都有快取節流，前端每 8 秒輪詢也不會狂打 API。
  - 不阻塞：操作丟背景執行緒、回 202 式訊息，下一次輪詢由 /api/state 反映結果。

用法：python scripts/web_center/server.py [port]   → 開 http://127.0.0.1:8788
"""
from __future__ import annotations

import base64
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 路徑 ──
HERE = Path(__file__).resolve().parent          # .../scripts/web_center
SCRIPTS = HERE.parent                            # .../scripts
ROOT = SCRIPTS.parent                            # .../youtube_channel
sys.path.insert(0, str(SCRIPTS))
from studio_common import save_json_atomic

# 配額計量(全域 patch HttpRequest.execute/next_chunk,只掛一次;壞掉不影響本腳本)
try:
    import quota_meter as _qm; _qm.install()
except Exception:
    pass
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
OUT = ROOT / "output"
CLOUD_CFG = ROOT / "cloud.json"
CLOUD_SSH = SCRIPTS / "cloud_ssh.py"
TOKEN = ROOT / "token_manage.json"
METRICS_FILE = STUDIO / "metrics_history.json"
DIRECTIVES = STUDIO / "boss_directives.json"
PENDING = STUDIO / "pending_decisions.json"
BOSS_DEC = STUDIO / "boss_decisions.json"
HEADCOUNT = STUDIO / "headcount.json"

# 跑 cloud_ssh.py 需要 paramiko → 用工作室 venv 的 python（本機）。缺則退回目前直譯器。
PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)

# Windows：子程序（SSH）不要彈黑窗
_CF = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
TW = timezone(timedelta(hours=8))

CHANNEL_URL = "https://www.youtube.com/channel/UCqP5JQXlQR5ZDLtEiBt4kLA"
STUDIO_URL = "https://studio.youtube.com/channel/UCqP5JQXlQR5ZDLtEiBt4kLA"
SUB_GOAL = 1000
VIEW_GOAL = 10_000_000
MAX_BOOST_LV = 5

# ── 18 大部門（對齊 control_center.DEPTS；kind 決定狀態怎麼誠實判定）──
DEPTS = [
    {"tag": "①", "name": "影片部門（長片）",   "head": 3, "kind": "long",     "act": "produce_long",  "boost": "①影片部門：多產長片"},
    {"tag": "②", "name": "Shorts 部門",       "head": 4, "kind": "shorts",   "act": "produce_short", "boost": "②Shorts：加碼多產 Shorts，衝量優先"},
    {"tag": "③", "name": "創作靈感部門",       "head": 2, "kind": "idea",     "act": "decision",      "boost": "③創作靈感：擴大選題、多找熱點題材"},
    {"tag": "④", "name": "頻道整理部門",       "head": 2, "kind": "organize", "act": "organize",      "boost": "④整理：更積極歸類與維護播放清單"},
    {"tag": "⑤", "name": "流量部門（數據選題）", "head": 2, "kind": "seo",      "act": "traffic",       "boost": "⑤流量：更積極用數據加碼高流量題材、優化點擊"},
    {"tag": "⑥", "name": "宣傳部門",          "head": 2, "kind": "promo",    "act": "promo",         "boost": "⑥宣傳：多產跨平台導流文案"},
    {"tag": "⑦", "name": "數據分析部門",       "head": 2, "kind": "data",     "act": "data",          "boost": None},
    {"tag": "⑧", "name": "社群留言部門",       "head": 2, "kind": "comment",  "act": "comment",       "boost": "⑧留言：更積極回覆與挖掘觀眾問題"},
    {"tag": "⑨", "name": "審核部門（發布閘門）", "head": 3, "kind": "audit",    "act": "publish",       "boost": "⑨上架：提高每日上架量、衝量"},
    {"tag": "⑩", "name": "總監管部門",        "head": 1, "kind": "manage",   "act": "reports",       "boost": None},
    {"tag": "⑪", "name": "決策部門（大腦）",    "head": 2, "kind": "decision", "act": "decision",      "boost": "⑪決策：更積極加碼會紅的、砍掉沒人看的"},
    {"tag": "⑫", "name": "回顧檢討部門（自省）", "head": 1, "kind": "retro",    "act": "retro",         "boost": None},
    {"tag": "⑬", "name": "人事部（監察＋編制）", "head": 2, "kind": "hr",       "act": "hr",            "boost": None},
    {"tag": "⑭", "name": "財務／變現部",        "head": 2, "kind": "finance",  "act": "finance",       "boost": "⑭財務：強化變現、衝聯盟返佣轉換"},
    {"tag": "⑮", "name": "縮圖／CTR 部",        "head": 2, "kind": "thumb",    "act": "thumb",         "boost": "⑮縮圖：更積極 A/B 優化點擊率"},
    {"tag": "⑯", "name": "競品情報部",          "head": 2, "kind": "intel",    "act": "intel",         "boost": "⑯競品：更密集掃描對手熱點題材"},
    {"tag": "⑰", "name": "美編部門（品牌視覺）", "head": 2, "kind": "design",   "act": "design",        "boost": "⑰美編：更積極優化字體/配色/版面設計感"},
    {"tag": "⑱", "name": "消息部門（時事即時）", "head": 2, "kind": "news",     "act": "news",          "boost": "⑱消息：更積極蹭金融時事、提高每日時事片上限"},
]
DEPT_HEAD_DEFAULT = {d["tag"]: d["head"] for d in DEPTS}

# 後勤部門員額需求權重（對齊 control_center._NEED）：rebalance 依此重新分配
_NEED = {
    "③": (2, "選題靈感，隨產量"), "④": (1, "整理維護性，精簡"),
    "⑤": (3, "流量數據選題＝成長核心 ↑"), "⑥": (3, "跨平台分發＝冷啟動最快流量 ↑"),
    "⑦": (2, "數據分析支撐決策"), "⑧": (2, "社群互動拉留存"),
    "⑨": (2, "審核隨上架量"), "⑩": (1, "監管精簡編制"),
    "⑪": (2, "決策大腦，保持精幹"), "⑫": (1, "回顧輕量自省"),
    "⑬": (1, "人事輕量編制"), "⑭": (1, "財務隨變現規模"),
    "⑮": (3, "縮圖CTR＝點擊率＝流量 ↑"), "⑯": (3, "競品情報餵選題 ↑"),
    "⑰": (2, "品牌視覺設計，撐住非AI質感與CTR"),
    "⑱": (3, "時事即時產發＝免費流量爆發點 ↑"),
}

# 各部門「激活」對應的雲端腳本（與 control_center.activate_dept 對齊）
DEPT_SCRIPTS = {
    "produce_long":  ("scripts/produce_batch.py", ["--long", "1", "--shorts", "0", "--target", "60"]),
    "produce_short": ("scripts/produce_batch.py", ["--shorts", "4", "--long", "0", "--target", "60"]),
    "decision":      ("scripts/decision_dept.py", []),
    "publish":       ("scripts/daily_publish.py", ["--max", "6"]),
    "retro":         ("scripts/retro_dept.py", []),
    "hr":            ("scripts/hr_dept.py", []),
    "finance":       ("scripts/finance_dept.py", []),
    "organize":      ("scripts/organize_dept.py", []),
    "promo":         ("scripts/promo_dept.py", []),
    "comment":       ("scripts/comment_dept.py", []),
    "thumb":         ("scripts/thumbnail_dept.py", []),
    "intel":         ("scripts/intel_dept.py", []),
    "traffic":       ("scripts/traffic_dept.py", []),
    "news":          ("scripts/news_dept.py", []),
    "data":          ("scripts/analytics_weekly.py", []),   # ⑦數據分析:跑週分析(完播/觀看)
    "reports":       ("scripts/daily_check.py", []),         # ⑩總監管:跑每日大檢查彙整
    "design":        ("scripts/cover_backfill.py", []),      # ⑰美編:批次補產高質感封面
}

# ════════════════════════════════════════════════════════════════════
#  共用：讀檔工具
# ════════════════════════════════════════════════════════════════════

def _load(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def load_cloud_cfg():
    if CLOUD_CFG.exists():
        try:
            c = json.loads(CLOUD_CFG.read_text(encoding="utf-8"))
            if c.get("ip") and c.get("password"):
                c.setdefault("user", "root")
                c.setdefault("remote_root", "/root/yt")
                return c
        except Exception:
            pass
    return None


def load_directives():
    d = _load(DIRECTIVES)
    if isinstance(d, dict):
        return d
    return {"directives": [], "format_override": "auto", "privacy": "public", "paused": False}


def save_directives(d):
    DIRECTIVES.parent.mkdir(parents=True, exist_ok=True)
    save_json_atomic(DIRECTIVES, d)


def load_headcount():
    hc = dict(DEPT_HEAD_DEFAULT)
    saved = _load(HEADCOUNT)
    if isinstance(saved, dict):
        for k, v in saved.items():
            if k in hc and isinstance(v, int) and v >= 0:
                hc[k] = v
    return hc


def save_headcount(hc):
    HEADCOUNT.parent.mkdir(parents=True, exist_ok=True)
    save_json_atomic(HEADCOUNT, hc)


# ════════════════════════════════════════════════════════════════════
#  雲端：透過 cloud_ssh.py 子程序操作（密碼經環境變數帶入，不落檔）
# ════════════════════════════════════════════════════════════════════

def _cloud_env(cfg):
    env = dict(os.environ)
    env["DROPLET_IP"] = cfg["ip"]
    env["DROPLET_PW"] = cfg["password"]
    env["DROPLET_USER"] = cfg.get("user", "root")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def cloud_ssh(mode, *args, timeout=60):
    """呼叫 cloud_ssh.py（mode: run / detached / put）。回 (ok, output)。"""
    cfg = load_cloud_cfg()
    if not cfg:
        return False, "未設定 cloud.json"
    try:
        p = subprocess.run([str(PY), str(CLOUD_SSH), mode, *args],
                           env=_cloud_env(cfg), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=_CF)
        out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
        return p.returncode == 0, out.strip()
    except subprocess.TimeoutExpired:
        return False, "連線逾時"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:160]


def _remote(tail):
    cfg = load_cloud_cfg()
    return f"cd {cfg['remote_root']} && {tail}" if cfg else None


def _detach(tail, logname):
    """組 fire-and-forget 背景指令：setsid nohup 確保 channel 關閉不被 SIGHUP 殺掉。"""
    return _remote(
        f"setsid nohup {tail} </dev/null >>logs/web_{logname}.log 2>&1 & echo triggered")


def trig_decision():
    return "scripts/decision_dept.py"


def trig_produce(shorts, longn):
    # 已在渲染就不重複啟動（避免堆疊）
    if _proc_running("produce_batch"):
        return None
    return f"scripts/produce_batch.py --shorts {int(shorts)} --long {int(longn)} --target 60"


def cloud_status_fetch(cfg):
    """雲端已退役（droplet 停權）：函式簽名保留避免舊呼叫端出錯，不再實際連線。"""
    return None, "雲端已退役"


# ════════════════════════════════════════════════════════════════════
#  本機：直接跑本機腳本（雲端 droplet 已停權退役，全改本機執行）
# ════════════════════════════════════════════════════════════════════

def _local_env():
    """把專案根 .env 併進 os.environ 的副本，讓子程序吃得到金鑰（對齊 local_cron.load_env）。"""
    env = dict(os.environ)
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip()
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("LLM_PROVIDER", "openrouter")
    return env


def _seg_to_argv(seg):
    """把一段雲端指令（./run.sh scripts/X.py args >>log 2>&1）轉成本機 argv（不含直譯器）。"""
    seg = seg.replace("./run.sh ", "")
    seg = re.split(r"\s>>|\s2>", seg)[0].strip()
    return shlex.split(seg) if seg else []


def _run_local(tail):
    """把雲端指令字串（./run.sh scripts/X.py args，或 cycle 特例 bash -c "段1; 段2; ..."）
    轉本機執行，用工作室 .venv 的 python（PY）＋灌 .env 金鑰。單段 fire-and-forget；
    多段（cycle）依序等前一支跑完才下一支（本函式已在背景執行緒中呼叫，不會卡住請求）。"""
    env = _local_env()
    if tail.startswith("bash -c "):
        inner = shlex.split(tail)[2]
        for seg in inner.split(";"):
            argv = _seg_to_argv(seg.strip())
            if argv:
                subprocess.run([str(PY), *argv], cwd=str(ROOT), env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=_CF)
    else:
        argv = _seg_to_argv(tail)
        if argv:
            subprocess.Popen([str(PY), *argv], cwd=str(ROOT), env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=_CF)


def _proc_running(name):
    """本機是否已有背景 python 程序在跑 name（如 produce_batch），避免重複啟動堆疊渲染。
    偵測失敗就當作沒在跑（寧可偶爾重複觸發，也別永久卡住補產）。"""
    try:
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              f"Where-Object {{ $_.CommandLine -like '*{name}*' }} | "
              "Measure-Object | Select-Object -ExpandProperty Count")
        p = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=10, creationflags=_CF)
        return int((p.stdout or "0").strip() or "0") > 0
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════════
#  快取（節流避免每 8 秒狂打 API / SSH）
# ════════════════════════════════════════════════════════════════════
CACHE = {
    "yt": {"data": None, "ts": 0, "busy": False},          # YouTube Data API：subs/views/videos
    "analytics": {"data": None, "ts": 0, "busy": False},   # YouTube Analytics：avg_pct 等
    "cloud": {"data": None, "ts": 0, "busy": False, "state": "noconfig", "err": "", "last": None},  # 雲端已退役，永遠 noconfig
    "studio": {"ts": 0, "busy": False},                    # 已無雲端可同步（本機 local_cron 直接寫本機 STUDIO，見 _sync_studio 退役說明）
}
_LOCK = threading.Lock()
OPLOG = []  # 最近操作回報（環形）


def op_log(msg):
    ts = datetime.now(TW).strftime("%H:%M:%S")
    with _LOCK:
        OPLOG.append({"t": ts, "msg": msg})
        del OPLOG[:-30]


def _refresh_yt():
    """背景抓 YouTube Data API（subs/views/videos）並記一筆走勢。"""
    c = CACHE["yt"]
    if c["busy"]:
        return
    c["busy"] = True
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        creds = Credentials.from_authorized_user_file(
            str(TOKEN), ["https://www.googleapis.com/auth/youtube.force-ssl"])
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        yt = build("youtube", "v3", credentials=creds)
        r = yt.channels().list(part="statistics", mine=True).execute()
        st = r["items"][0]["statistics"]
        data = {"subs": int(st.get("subscriberCount", 0)),
                "views": int(st.get("viewCount", 0)),
                "videos": int(st.get("videoCount", 0))}
        c["data"] = data
        _log_metric(data["subs"], data["views"])
    except Exception as e:  # noqa: BLE001
        if c["data"] is None:
            c["data"] = {"err": str(e)[:80]}
    finally:
        c["ts"] = time.time()
        c["busy"] = False


def _refresh_analytics():
    c = CACHE["analytics"]
    if c["busy"]:
        return
    c["busy"] = True
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        import yt_analytics as ya
        c["data"] = ya.channel_summary(28) if ya.available() else None
    except Exception:
        pass
    finally:
        c["ts"] = time.time()
        c["busy"] = False


def _refresh_cloud():
    """雲端已退役（droplet 停權、cloud.json 已刪除）：函式簽名保留避免舊呼叫端出錯，不再輪詢。"""
    return


def _adopt_cloud(data):
    """雲端已退役：函式簽名保留避免舊呼叫端出錯，不再有呼叫路徑會走到這裡。"""
    return


def _log_metric(subs, views):
    try:
        if not isinstance(subs, int) or not isinstance(views, int):
            return
        hist = _load(METRICS_FILE, []) or []
        if not isinstance(hist, list):
            return
        last = hist[-1] if hist else {}
        if last.get("subs") == subs and last.get("views") == views:
            return  # 沒變就不灌水
        hist.append({"t": datetime.now(TW).strftime("%m-%d %H:%M"), "subs": subs, "views": views})
        METRICS_FILE.write_text(json.dumps(hist[-240:], ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _sync_studio():
    """雲端已退役：本機 local_cron.py 本來就直接寫本機 STUDIO/*.json，不再需要從雲端拉。
    函式簽名保留避免舊呼叫端出錯，不再實際同步。"""
    return


def _maybe_refresh():
    """依節流啟動背景刷新（不阻塞請求）。雲端輪詢已停用（droplet 已退役）。"""
    now = time.time()
    if now - CACHE["yt"]["ts"] > 200 and not CACHE["yt"]["busy"]:
        threading.Thread(target=_refresh_yt, daemon=True).start()
    if now - CACHE["analytics"]["ts"] > 200 and not CACHE["analytics"]["busy"]:
        threading.Thread(target=_refresh_analytics, daemon=True).start()


# ════════════════════════════════════════════════════════════════════
#  /api/state — 組裝完整快照
# ════════════════════════════════════════════════════════════════════

def _cloud_online():
    c = CACHE["cloud"]
    return c["data"] if c["state"] == "online" and c["data"] else None


def _today_tw():
    return datetime.now(TW).strftime("%Y-%m-%d")


def _clean_rolling_series():
    """P0-a：metrics_history.json 混雜兩種 schema（{date,total_views,...} 每日快照 /
    {t,subs,views} 即時快照）——兩者其實是同一個「近28天滾動觀看」數字在不同時間點的紀錄。
    舊 `_series()` 直接用 p.get("views",0) 撈值，date-schema 沒有 "views" 欄位會撈成 0，
    在 sparkline 上鑿出假的骨折式驟降，正是 Carson「流量鋸齒」體感誤判的元凶之一。
    這裡統一正規化成單一時間序列，並丟掉 0 值假點。"""
    hist = _load(METRICS_FILE, []) or []
    if not isinstance(hist, list) or not hist:
        return []
    pts = []
    for p in hist:
        if not isinstance(p, dict):
            continue
        if "views" in p and p.get("t"):
            v, label = p.get("views"), p.get("t", "")
        elif "total_views" in p and p.get("date"):
            v, label = p.get("total_views"), p.get("date", "")
        else:
            continue
        if not v:  # 0/None＝壞快照，不是真的觀看歸零，丟掉別畫進趨勢線
            continue
        pts.append({"t": label, "subs": p.get("subs"), "views": v})
    return pts[-28:]  # 對齊「28D VIEWS TREND」標籤:只留近28個快照點,別把更早的基期拉進來算變化率


def _view_trend(series):
    """近7日／近28日滾動觀看趨勢方向，供前端凸顯（別只看單日增量鋸齒）。"""
    if not series or len(series) < 2:
        return {"trend_7d_pct": None, "trend_28d_pct": None, "trend_direction": None}
    latest = series[-1]["views"]
    base7 = series[max(0, len(series) - 8)]["views"]
    base28 = series[0]["views"]
    pct7 = round((latest - base7) / base7 * 100, 1) if base7 else None
    pct28 = round((latest - base28) / base28 * 100, 1) if base28 else None
    direction = "up" if (pct7 or 0) > 1 else ("down" if (pct7 or 0) < -1 else "flat")
    return {"trend_7d_pct": pct7, "trend_28d_pct": pct28, "trend_direction": direction}


def _kpi():
    yt = CACHE["yt"]["data"] or {}
    hist = _load(METRICS_FILE, []) or []
    subs = yt.get("subs")
    views = yt.get("views")
    if subs is None and hist:
        subs = hist[-1].get("subs")
    if views is None and hist:
        views = hist[-1].get("views")
    ana = CACHE["analytics"]["data"] or {}
    retention = ana.get("avg_pct")
    fin = _load(STUDIO / "finance.json") or {}
    net = (fin.get("summary") or {}).get("net")
    trend = _view_trend(_clean_rolling_series())
    return {
        "subs": subs, "views": views,
        "videos": yt.get("videos"),
        "retention": retention,
        "net": net,
        "subs_gained": ana.get("subs_gained"),
        "views_28": ana.get("views"),
        "minutes_28": ana.get("minutes"),
        "sub_goal": SUB_GOAL, "view_goal": VIEW_GOAL,
        "sub_gap": max(0, SUB_GOAL - (subs or 0)),
        **trend,
    }


def _series():
    return _clean_rolling_series()


def _departments():
    """依真實檔案/雲端報告誠實判定 18 部門狀態。level: on/idle/warn/paused/readonly。"""
    today = _today_tw()
    paused = load_directives().get("paused", False)
    cloud = _cloud_online()
    cloud_today = set(cloud.get("dept_reports_today", [])) if cloud else None
    produced_today = (cloud.get("produced_today", 0) if cloud else _local_produced_today())
    subs = (CACHE["yt"]["data"] or {}).get("subs")
    hc = load_headcount()
    boost = load_directives().get("boost", {})
    # 成績單:接 hr_status.json(每部門 kpi 等級/成效備註/今日產出)——已算好、只是沒接進節點
    _hr = {r.get("tag"): r for r in ((_load(STUDIO / "hr_status.json") or {}).get("rows") or [])
           if isinstance(r, dict)}
    # 該部門當日報告檔(給「看報告」直開該部門 md,不再開通用連結)
    _RSUF = {"seo": "流量洞察", "audit": "自動上架", "manage": "營運匯報", "decision": "決策",
             "retro": "回顧檢討", "hr": "人事監察", "organize": "頻道整理", "promo": "宣傳文案",
             "comment": "留言回覆草稿", "thumb": "縮圖CTR", "intel": "競品情報", "news": "消息",
             "finance": "財務"}

    def rep(suffix):
        if cloud_today is not None:
            return suffix in cloud_today
        return (REPORTS / f"{today}_{suffix}.md").exists()

    rows = []
    for d in DEPTS:
        k, tag = d["kind"], d["tag"]
        st, lv = "—", "idle"
        if k in ("long", "shorts"):
            ok = produced_today > 0
            if ok:
                st, lv = "今日已產出", "on"
            elif paused:
                st, lv = "暫停", "paused"
            else:
                st, lv = "排程 06:07 待產", "idle"
        elif k == "idea":
            ok = (STUDIO / "production_orders.json").exists()
            st, lv = ("題庫指令已就緒", "on") if ok else ("待決策部門產出", "idle")
        elif k == "seo":
            ok = rep("流量洞察")
            st, lv = ("今日已分析流量數據選題", "on") if ok else ("數據選題待命（05:35）", "idle")
        elif k == "data":
            if isinstance(subs, int):
                st, lv = f"已連線・訂閱 {subs}", "on"
            else:
                st, lv = "待連線 YouTube", "idle"
        elif k == "audit":
            ok = rep("自動上架")
            st, lv = ("把關中・今日已上架", "on") if ok else ("待今日上架報告", "idle")
        elif k == "manage":
            ok = rep("營運匯報")
            st, lv = ("今日已匯報", "on") if ok else ("待 09 點後彙整", "idle")
        elif k == "decision":
            ok = rep("決策")
            if ok:
                st, lv = "今日已決策", "on"
            elif paused:
                st, lv = "暫停", "paused"
            else:
                st, lv = "排程 05:37", "idle"
        elif k == "retro":
            ok = rep("回顧檢討")
            st, lv = ("今日已自省", "on") if ok else ("待每輪後自省", "idle")
        elif k == "hr":
            ok = rep("人事監察")
            st, lv = ("今日已監察", "on") if ok else ("監察+編制待命", "idle")
        elif k == "finance":
            fin = _load(STUDIO / "finance.json") or {}
            net = (fin.get("summary") or {}).get("net")
            if isinstance(net, (int, float)):
                st, lv = f"淨利 NT${net:,.0f}", "on"
            else:
                st, lv = "待記帳/出報告", "idle"
        elif k == "organize":
            ok = rep("頻道整理")
            st, lv = ("今日已歸類", "on") if ok else ("待整理播放清單", "idle")
        elif k == "promo":
            ok = rep("宣傳文案")
            st, lv = ("今日已產文案", "on") if ok else ("待產導流文案", "idle")
        elif k == "comment":
            ok = rep("留言回覆草稿")
            st, lv = ("今日已擬回覆", "on") if ok else ("待擬留言回覆", "idle")
        elif k == "thumb":
            ok = rep("縮圖CTR")
            st, lv = ("今日已分析", "on") if ok else ("待縮圖/CTR 分析", "idle")
        elif k == "intel":
            ok = rep("競品情報")
            st, lv = ("今日已掃描", "on") if ok else ("待掃描競品", "idle")
        elif k == "design":
            ok = (STUDIO / "design_system.json").exists()
            st, lv = ("品牌設計系統運作中", "on") if ok else ("待設定品牌設計（可激活）", "idle")
        elif k == "news":
            ok = rep("消息")
            st, lv = ("今日已產時事片", "on") if ok else ("每2h掃時事（待今日報告）", "idle")
        bn = d.get("boost")
        bl = boost.get(f"{tag} {d['name']}", 0) if bn else 0
        hr = _hr.get(tag, {})
        suf = _RSUF.get(k)
        rows.append({"tag": tag, "name": d["name"], "head": hc.get(tag, d["head"]),
                     "status": st, "level": lv, "act": d.get("act"),
                     "boostable": bool(bn), "boost_lv": bl,
                     # 成績單:今日產出/成效備註 + KPI 等級 + 當日報告檔(給前端顯示+看報告)
                     "output_today": hr.get("note", ""),
                     "kpi": hr.get("kpi", ""), "kpi_note": hr.get("kpi_note", ""),
                     "report": (f"{today}_{suf}.md" if suf else "")})
    return rows


def _local_produced_today():
    today = _today_tw()
    n = 0
    try:
        for p in list(OUT.glob("S_*.mp4")) + list(OUT.glob("L_*.mp4")):
            # 排除 _ytcta 跨平台衍生檔:它和原片同一天產生,不排除會把同一支片算兩次
            # (實測今日顯示 7 支、真實只有 6 支,虛增 17%)。同 output/ 的其他消費者作法。
            if "_ytcta" in p.stem:
                continue
            if datetime.fromtimestamp(p.stat().st_mtime, TW).strftime("%Y-%m-%d") == today:
                n += 1
    except Exception:
        pass
    return n


def _pending():
    answered = set()
    bd = _load(BOSS_DEC)
    if isinstance(bd, dict):
        answered = set(bd.keys())
    pend = _load(PENDING, []) or []
    if not isinstance(pend, list):
        return []
    out = []
    for p in pend:
        if not isinstance(p, dict) or p.get("id") in answered:
            continue
        out.append({"id": p.get("id"), "question": p.get("question", ""),
                    "options": p.get("options", []), "recommendation": p.get("recommendation", "")})
    return out


def _warehouse():
    q = _load(STUDIO / "quality_scores.json") or {}
    s = q.get("summary") or {}
    cloud = _cloud_online()
    pending = s.get("pending")
    if cloud and cloud.get("queue") is not None:
        pending = cloud["queue"]   # 線上以雲端即時 queue 為準（避免快照過期）
    return {"pending": pending, "published": s.get("published"),
            "pass": s.get("pass"), "reject": s.get("reject"),
            "min_score": q.get("min_score"), "updated": q.get("updated")}


def _scoring_items(limit=60):
    """倉庫評分：未發布 queue 清單（標題/分數/是否退件＋評分明細：四面向/建議/硬傷扣分）。"""
    q = _load(STUDIO / "quality_scores.json") or {}
    mn = q.get("min_score")
    out = []
    for it in (q.get("pending") or []):
        if not isinstance(it, dict):
            continue
        sc = it.get("score")
        ai = it.get("ai") if isinstance(it.get("ai"), dict) else {}
        # 退件：低於門檻，或被手動退件
        rej = bool((sc is not None and mn is not None and sc < mn)
                   or it.get("status") == "rejected_manual")
        out.append({"slug": it.get("slug"),
                    "title": it.get("title") or it.get("slug") or "（未命名）",
                    "score": sc, "reject": rej,
                    # 四面向各 0–25（鉤子/標題/內容/誠信）
                    "hook": ai.get("hook"), "ti": ai.get("title"),
                    "content": ai.get("content"), "honesty": ai.get("honesty"),
                    "ai_total": ai.get("total"),
                    "note": it.get("ai_note") or ai.get("note") or "",
                    # 硬傷扣分原因（audit reasons）
                    "reasons": [str(r) for r in (it.get("reasons") or [])][:6]})
    out.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))
    return out[:limit]


def _published_list(limit=60):
    """已發布影片成效列（依觀看排序）。"""
    q = _load(STUDIO / "quality_scores.json") or {}
    pub = [x for x in (q.get("published") or []) if isinstance(x, dict)]
    pub.sort(key=lambda x: (x.get("views") or 0), reverse=True)
    out = []
    for it in pub[:limit]:
        out.append({"title": it.get("title") or it.get("slug") or "（未命名）",
                    "videoId": it.get("videoId"),
                    "views": it.get("views"), "retention": it.get("retention"),
                    "subs": it.get("subs"), "score": it.get("score"),
                    "avg_sec": it.get("avg_sec") or it.get("avg_view_sec")})
    return out


def _reports(limit=24):
    """每日匯報：REPORTS/*.md 最新清單（檔名/日期/標題）。"""
    try:
        files = sorted(REPORTS.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        return [{"f": p.name, "date": p.name[:10],
                 "title": (p.stem[11:] if len(p.stem) > 11 else p.stem)} for p in files]
    except Exception:
        return []


def _headcount_rows():
    """人事編制：18 部門 tag/名稱/編制人數。"""
    hc = load_headcount()
    return [{"tag": d["tag"], "name": d["name"], "head": hc.get(d["tag"], d["head"])} for d in DEPTS]


def _decisions_log(limit=20):
    """我的決策：老闆過往拍板紀錄（boss_decisions.json）。"""
    bd = _load(BOSS_DEC)
    if not isinstance(bd, dict):
        return []
    rows = []
    for pid, v in bd.items():
        if isinstance(v, dict):
            rows.append({"id": pid, "question": v.get("question", ""),
                         "choice": v.get("choice", ""), "ts": v.get("ts", "")})
    rows.sort(key=lambda x: x.get("ts", ""), reverse=True)
    return rows[:limit]


def _finance():
    fin = _load(STUDIO / "finance.json") or {}
    s = fin.get("summary") or {}
    return {"revenue": s.get("revenue"), "cost": s.get("cost"), "net": s.get("net"),
            "roi": s.get("roi"), "month": s.get("month"),
            "affiliate": s.get("affiliate"), "adsense": s.get("adsense")}


def _cloud_block():
    """雲端已退役：不再有 droplet 系統指標(磁碟/負載/cron…)，只留本機仍算得出的 produced_today，
    queue 留空讓前端 fallback 用 warehouse.pending（既有 `??` 寫法，見 index.html renderMeters）。"""
    c = CACHE["cloud"]
    return {"state": c["state"], "last": c["last"], "err": c["err"],
            "produced_today": _local_produced_today()}


def _directives_state():
    """我的決策：目前生效中的指令陣列＋主攻格式（讀 boss_directives.json）。"""
    d = load_directives()
    ds = d.get("directives", [])
    return {"list": [str(x) for x in ds] if isinstance(ds, list) else [],
            "format": d.get("format_override", "auto")}


def _insight():
    """數據洞察：含曝光 impressions / 點閱率 CTR（YouTube Analytics，部分帳號才有）。"""
    ana = CACHE["analytics"]["data"] or {}
    out = {"views_28": ana.get("views"), "avg_pct": ana.get("avg_pct"),
           "minutes_28": ana.get("minutes"), "subs_gained": ana.get("subs_gained"),
           "impressions": None, "ctr": None}
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        import yt_analytics as ya
        if ya.available():
            ic = ya.impressions_ctr(28)
            if isinstance(ic, dict):
                out["impressions"] = ic.get("impressions")
                out["ctr"] = ic.get("ctr")
    except Exception:
        pass
    return out


def _out_today(prefix):
    today = _today_tw()
    try:
        return sum(1 for p in OUT.glob(f"{prefix}*.mp4")
                   if "_ytcta" not in p.stem      # 衍生檔同日產生,會讓今日產出重複計數
                   and datetime.fromtimestamp(p.stat().st_mtime, TW).strftime("%Y-%m-%d") == today)
    except Exception:
        return 0


def _hr_monitor():
    """部門監察文字（出勤/健康/KPI考核/編制建議）— 對齊 control_center._hr_monitor_text。"""
    today = _today_tw()
    cloud = _cloud_online()
    cloud_today = set(cloud.get("dept_reports_today", [])) if cloud else None

    def rep(s):
        if cloud_today is not None:
            return s in cloud_today
        return (REPORTS / f"{today}_{s}.md").exists()

    s_n = (cloud.get("produced_today", 0) if cloud else _out_today("S_"))
    l_n = _out_today("L_")
    paused = load_directives().get("paused", False)
    L = ["🗓 今日出勤"]
    att = [("⑪ 決策", rep("決策")),
           ("①② 補產", (s_n + l_n) > 0 or bool(cloud and cloud.get("produced_today"))),
           ("⑨ 審核上架", rep("自動上架")),
           ("⑩ 總監管", rep("營運匯報")),
           ("⑫ 回顧檢討", rep("回顧檢討")),
           ("⑬ 人事監察", rep("人事監察"))]
    for nm, ok in att:
        L.append(f"   {'✅ 已出勤' if ok else ('⏸ 暫停' if paused else '🕒 未出勤')}　{nm}")
    L.append(f"   今日產出：Shorts {s_n} 支、長片 {l_n} 支")
    # 健康（掃 ops_log 異常）
    errs = []
    try:
        for ln in (STUDIO / "ops_log.txt").read_text(encoding="utf-8").splitlines()[-80:]:
            if any(k in ln for k in ("⚠️", "FAIL", "失敗", "錯誤", "FATAL")):
                errs.append(ln.strip())
    except Exception:
        pass
    L += ["", "🩺 健康"]
    if errs:
        L.append(f"   ⚠ 偵測到 {len(errs)} 條異常（近期）：")
        for e in errs[-4:]:
            L.append(f"     - {e[:70]}")
    else:
        L.append("   ✅ 近期無異常日誌")
    # KPI 考核（hr_status.json）
    try:
        st = _load(STUDIO / "hr_status.json")
        if isinstance(st, dict):
            weak = st.get("kpi_weak", [])
            L += ["", f"📋 KPI 考核（對照職掌定義書・{st.get('date','')}）"]
            if weak:
                rows = {r.get("tag"): r for r in st.get("rows", [])}
                L.append(f"   ⚠ 待加強／未達 {len(weak)} 項：")
                for t in weak:
                    r = rows.get(t, {})
                    L.append(f"     - {t} {r.get('name','')}：{r.get('kpi','')}（{r.get('kpi_note','')}）")
            else:
                L.append("   ✅ 全部門 KPI 達標（或不適用）")
    except Exception:
        pass
    # 編制建議
    L += ["", "🧑‍💼 編制建議"]
    hc = load_headcount()
    if hc.get("②", 0) < 4:
        L.append("   ・②Shorts 員額偏低（衝量主力建議 ≥4）。")
    L.append("   ・加 ①／② 員額＝直接擴大每日產量；其餘部門員額為容量編制。")
    return "\n".join(L)


def _latest_check_text():
    try:
        files = sorted(REPORTS.glob("*_大檢查.md"), reverse=True)
        if not files:
            return ""
        verdict, issues = "", []
        for ln in files[0].read_text(encoding="utf-8").splitlines():
            if ln.startswith("## 總評"):
                verdict = ln.split("：", 1)[-1].strip()
            if ln.startswith("- ") and "待處理" not in ln:
                issues.append(ln[2:].strip())
        v = verdict or ""
        if issues:
            v += "（" + "；".join(issues[:2]) + ("…" if len(issues) > 2 else "") + "）"
        return v
    except Exception:
        return ""


def _brief():
    """擬真特助完整報告（純數據組裝，不打 API）— 對齊 control_center._assistant_brief。"""
    cloud = _cloud_online()
    yt = CACHE["yt"]["data"] or {}
    subs = yt.get("subs")
    ana = CACHE["analytics"]["data"] or {}
    fin = _load(STUDIO / "finance.json") or {}
    net = (fin.get("summary") or {}).get("net")
    pend = len(_pending())
    q = _load(STUDIO / "quality_scores.json") or {}
    qs = q.get("summary") or {}
    qpend = qs.get("pending")
    if cloud and cloud.get("queue") is not None:
        qpend = cloud["queue"]
    top = None
    scored = [p for p in (q.get("published") or []) if isinstance(p, dict) and p.get("views") is not None]
    if scored:
        top = max(scored, key=lambda x: x.get("views") or 0)
    health = _latest_check_text()
    h = datetime.now(TW).hour
    greet = "早安老闆 ☀" if h < 11 else ("午安老闆 🌤" if h < 18 else "晚安老闆 🌙")
    L = [f"{greet}，今天的狀況一次跟你報："]
    if health:
        L.append(f"🩺 系統體檢：{health}")
    if cloud:
        run = "趕工中 🎬" if cloud.get("render_running") else "已收工"
        line = f"🏭 雲端今天做了 {cloud.get('produced_today', 0)} 支、倉庫 {cloud.get('queue', 0)} 支（{run}）"
        if cloud.get("errors_recent"):
            line += f"，⚠ 有 {cloud['errors_recent']} 條異常我盯著"
        L.append(line + "。")
        running = cloud.get("running_now") or []
        L.append(("⏳ 正在跑：" + "、".join(running)) if running else "⏳ 目前沒有腳本在跑（待下個排程）。")
    elif CACHE["cloud"]["state"] == "offline":
        L.append("🏭 （連不上雲端，看的是本機資料）")
    if isinstance(subs, int):
        g = [f"訂閱 {subs}（離 YPP 還差 {max(0, SUB_GOAL - subs)}）"]
        if ana:
            g.append(f"近28天 {ana.get('views', 0):,} 次觀看、平均看完 {ana.get('avg_pct', 0):.0f}%")
            if isinstance(ana.get("subs_gained"), int):
                g.append(f"+{ana['subs_gained']} 訂閱")
        L.append("📈 " + "，".join(g) + "。")
    if qpend is not None:
        L.append(f"🎬 倉庫 {qpend} 支待發（{qs.get('pass', 0)} 達標／{qs.get('reject', 0)} 待補強，門檻 {q.get('min_score', '?')}）。")
    if top:
        rt = f"、留存 {top['retention']:g}%" if top.get("retention") is not None else ""
        L.append(f"🔥 最紅：「{(top.get('title') or '')[:22]}」{int(top.get('views') or 0):,} 次觀看{rt} — 這類可多做。")
    if isinstance(net, (int, float)):
        L.append(f"💰 累計淨利 NT$ {net:,.0f}。")
    if pend:
        L.append(f"📌 有 {pend} 件等你拍板 → 去「決策」分頁。")
    # 今日焦點
    if health and "❌" in health:
        focus = "系統體檢有嚴重問題，先看大檢查匯報處理。"
    elif health and "⚠" in health:
        focus = "體檢有幾項要注意，抽空看匯報。"
    elif pend:
        focus = "先去把待拍板的決策處理掉，其餘我顧著。"
    elif isinstance(qs.get("reject"), int) and qs.get("reject", 0) >= 3:
        focus = f"倉庫有 {qs['reject']} 支沒到門檻，可去倉庫按自動退件補強。"
    elif cloud and not cloud.get("render_running") and (cloud.get("queue", 99) < 10):
        focus = "倉庫存量偏低，建議按立即補產囤一點。"
    elif top and top.get("retention") is not None and top["retention"] >= 60:
        focus = "最紅那支留存很高，叫產線多複製它的主題/結構衝量。"
    else:
        focus = "一切順、沒有要你決定的事，放心去忙 ✌"
    L.append("👉 今日焦點：" + focus)
    return "\n".join(L)


def _focus(kpi, pend, wh, paused):
    if paused:
        return "工廠目前<b>已暫停</b>。要恢復就按上面的「恢復全自動」。"
    if pend:
        return f"有 <b>{len(pend)}</b> 件等你拍板，其餘我顧著。"
    gap = kpi.get("sub_gap")
    if wh.get("pending") and gap:
        return f"倉庫 <b>{wh['pending']}</b> 支待發，離 YPP 還差 <b>{gap}</b> 訂閱。全自動衝量中。"
    return "一切順，沒有要你決定的事，放心去忙。"


def _ep_num(s):
    """從標題/slug 取 EP 集數（EP12 / EP.3 / EP 5 → int）；無則 None。"""
    m = re.search(r"EP\.?\s*(\d+)", str(s or ""), re.I)
    return int(m.group(1)) if m else None


def _northstar(completion_avg=None):
    """通往百萬的四個北極星指標（全讀現成 json / CACHE，零外呼）。

    ① 訂閱轉換率 = subs_gained_28d / views_28 × 1000（‰，每千次觀看轉幾個訂閱）
    ② EP 追更率 = EP 末集 views / EP 首集 views（含 "EP" 的已發布片）
    ③ 加權完播 = 直接取 _analytics 已算的 completion.avg（未傳則自算同式，勿重造邏輯）
    ④ 破圈頻率 = count(views ≥ 3×median) / n_published

    缺資料的指標一律回 None（不報錯）。ep_data 新欄位缺時 graceful default。
    """
    # ── 訂閱數 + 缺口 ──
    yt = CACHE["yt"]["data"] or {}
    hist = _load(METRICS_FILE, []) or []
    subs = yt.get("subs")
    if subs is None and isinstance(hist, list) and hist:
        subs = hist[-1].get("subs")
    ana = CACHE["analytics"]["data"] or {}

    # ① 訂閱轉換率（‰）
    sg = ana.get("subs_gained")
    v28 = ana.get("views")
    sub_conv = round(sg / v28 * 1000, 2) if (sg is not None and v28) else None

    # ── 已發布片（有真實完播率的） ──
    q = _load(STUDIO / "quality_scores.json") or {}
    pub = [x for x in (q.get("published") or []) if isinstance(x, dict) and x.get("retention") is not None]
    n_pub = len(pub)

    # ② EP 追更率（末集 / 首集 觀看）
    eps = []
    for x in pub:
        num = _ep_num(x.get("title") or "")
        if num is None:
            num = _ep_num(x.get("slug") or "")
        if num is not None:
            eps.append((num, x.get("views") or 0))
    ep_follow = ep_retain_pct = None
    if len(eps) >= 2:
        eps.sort(key=lambda z: z[0])
        first_v, last_v = eps[0][1], eps[-1][1]
        if first_v:
            ep_follow = round(last_v / first_v, 2)
            ep_retain_pct = round(ep_follow * 100, 1)

    # ③ 加權完播（優先用 _analytics 已算值）
    wc = completion_avg
    if wc is None and pub:
        rets = [min(100.0, float(x["retention"])) for x in pub]
        vws = [(x.get("views") or 0) for x in pub]
        tw = sum(vws)
        wc = round(sum(rets[i] * vws[i] for i in range(len(rets))) / tw, 1) if tw \
            else round(sum(rets) / len(rets), 1)

    # ④ 破圈頻率
    breakout_rate, breakout_n = None, 0
    if pub:
        vs = sorted((x.get("views") or 0) for x in pub)
        med = vs[len(vs) // 2] or 0
        if med:
            breakout_n = sum(1 for v in vs if v >= 3 * med)
            breakout_rate = round(breakout_n / n_pub * 100, 1)

    # ── EP 連載狀態（建置1 ep_engine 擴充 schema；缺欄位 graceful default） ──
    ep_raw = _load(STUDIO / "ep_data.json") or {}
    ep_state = {"season": ep_raw.get("season") or 1,
                "current_ep": ep_raw.get("current_ep"),
                "character_state": ep_raw.get("character_state"),
                "cumulative": ep_raw.get("cumulative") or {}}

    return {
        "goal_subs": SUB_GOAL, "subs": subs,
        "sub_gap": (max(0, SUB_GOAL - subs) if subs is not None else None),
        "sub_conv_permille": sub_conv,
        "ep_retain_pct": ep_retain_pct, "ep_follow": ep_follow, "ep_n": len(eps),
        "weighted_completion": wc, "completion_goal": 50,
        "breakout_rate": breakout_rate, "breakout_n": breakout_n,
        "n_published": n_pub,
        "ep_state": ep_state,
    }


def _analytics():
    """頻道數據分析聚合(全讀現成 STUDIO/*.json):趨勢/完播/題材/四象限/Top/優化建議。"""
    # ── 每日趨勢:同日去重(取最後有值一筆)、濾掉 total_views==0 的降級筆 ──
    hist = _load(METRICS_FILE, []) or []
    daily_map = {}
    if isinstance(hist, list):
        for p in hist:
            if not isinstance(p, dict):
                continue
            d = p.get("date"); tv = p.get("total_views") or 0
            if not d:
                continue
            if tv == 0 and daily_map.get(d, {}).get("views"):
                continue
            daily_map[d] = {"date": d, "views": tv, "uploaded": p.get("uploaded") or 0,
                            "shorts": p.get("shorts_today") or 0, "longs": p.get("longs_today") or 0}
    daily = [daily_map[k] for k in sorted(daily_map)]
    daily = [x for x in daily if x["views"] > 0][-60:]

    # ── 已發布片(有真實完播率) ──
    q = _load(STUDIO / "quality_scores.json") or {}
    pub = [x for x in (q.get("published") or []) if isinstance(x, dict) and x.get("retention") is not None]
    for _x in pub:  # 數據清洗:少數 retention 壞值(>100%)夾回 0-100,避免污染平均/排行
        _r = _x.get("retention")
        if isinstance(_r, (int, float)) and _r > 100:
            _x["retention"] = 100.0

    def wsc(x):  # 贏片綜合分(對齊 breakout_hunter；CTR 恆 0 故省略)
        return (x.get("views") or 0) * (1 + (x.get("retention") or 0) / 100.0)

    rets = [float(x["retention"]) for x in pub]  # 上面已夾 ≤100
    vws = [(x.get("views") or 0) for x in pub]
    completion = {}
    if rets:
        b = [0] * 5  # 0-20 / 20-40 / 40-60 / 60-80 / 80-100
        for r in rets:
            b[min(4, int(r // 20))] += 1
        tw = sum(vws)
        # 觀看加權均值(小觀看片自然低權重,不再和大片同權)——這才逼近頻道真實完播
        wavg = round(sum(rets[i] * vws[i] for i in range(len(rets))) / tw, 1) if tw else round(sum(rets) / len(rets), 1)
        big = [rets[i] for i in range(len(rets)) if vws[i] >= 30]  # 樣本足(≥30觀看)的簡單均值,參考
        completion = {"avg": wavg, "simple_avg": round(sum(rets) / len(rets), 1),
                      "big_avg": (round(sum(big) / len(big), 1) if big else None), "big_n": len(big),
                      "n": len(rets), "goal": 50, "weighted": True,
                      "winners": sum(1 for r in rets if r >= 60),
                      "mid": sum(1 for r in rets if 40 <= r < 60),
                      "losers": sum(1 for r in rets if r < 40), "buckets": b}

    # ── 觀看×完播 四象限(API 無 CTR,用觀看替代) ──
    quadrant = {}
    if pub:
        vs = sorted((x.get("views") or 0) for x in pub)
        medv = vs[len(vs) // 2] or 1

        def cell(cond, tip):
            it = sorted([x for x in pub if cond(x)], key=wsc, reverse=True)
            return {"n": len(it), "tip": tip,
                    "examples": [{"title": (x.get("title") or x.get("slug") or "")[:38],
                                  "views": x.get("views"), "retention": x.get("retention")} for x in it[:3]]}
        hi = lambda x: (x.get("views") or 0) >= medv
        hr = lambda x: (x.get("retention") or 0) >= 50
        quadrant = {
            "winner":    cell(lambda x: hi(x) and hr(x),         "雙高 → 贏家,多做同類全押"),
            "clickbait": cell(lambda x: hi(x) and not hr(x),     "高觀看低完播 → 標題黨/鉤子弱,強化前3秒"),
            "hidden":    cell(lambda x: not hi(x) and hr(x),     "低觀看高完播 → 好片沒曝光,換縮圖/標題"),
            "drop":      cell(lambda x: not hi(x) and not hr(x), "雙低 → 待汰,降權別再做"),
        }

    def vrow(x):
        return {"title": (x.get("title") or x.get("slug") or "")[:44], "videoId": x.get("videoId"),
                "views": x.get("views"), "retention": x.get("retention"), "subs": x.get("subs")}
    top = [vrow(x) for x in sorted(pub, key=wsc, reverse=True)[:8]]
    bottom = [vrow(x) for x in sorted(pub, key=wsc)[:6]]

    # ── 題材有效性(traffic_signals 關鍵字法) ──
    ts = _load(STUDIO / "traffic_signals.json") or {}
    win_kw = [str(k) for k in (ts.get("win_keywords") or [])][:10]
    weak_kw = [str(k) for k in (ts.get("weak_keywords") or [])][:10]
    topics = {"win": win_kw, "weak": weak_kw, "channel_28d": ts.get("channel_28d") or {},
              "top_videos": [{"slug": (v.get("slug") or "")[:38], "views": v.get("views"), "avg_pct": v.get("avg_pct")}
                             for v in (ts.get("top_videos") or [])[:6]]}

    # ── 更狠:健康分 / 本週一件事 / 問題片 / 短長對比 / 散點 / 題材排行 / 財務 ──
    ch = ts.get("channel_28d") or {}
    comp_pct = ch.get("avg_pct")
    if comp_pct is None:
        comp_pct = completion.get("avg")
    summ = q.get("summary") or {}
    pas, rej = summ.get("pass") or 0, summ.get("reject") or 0
    sg = ch.get("subs_gained") or 0
    recent7 = daily[-7:]
    prod_days = sum(1 for d in recent7 if (d.get("shorts") or 0) + (d.get("longs") or 0) > 0)
    hp = {"completion": max(0, min(100, round((comp_pct or 0) / 50 * 100))),
          "quality": (round(pas / max(1, pas + rej) * 100) if (pas or rej) else 60),
          "growth": max(0, min(100, 30 + sg * 1.4)),
          "production": (round(prod_days / 7 * 100) if recent7 else 60)}
    health = {"score": round(0.4 * hp["completion"] + 0.25 * hp["growth"] + 0.2 * hp["quality"] + 0.15 * hp["production"]),
              "parts": hp}

    if comp_pct is not None and comp_pct < 50:
        one_thing = {"text": f"完播 {comp_pct}% 未達 50% 門檻——本週最該做：每支前3秒直接講結果、標題改可搜尋。這是成長最大瓶頸。"}
    elif weak_kw and win_kw:
        one_thing = {"text": f"停做無效題材「{weak_kw[0]}」，把產能全轉去有效題材「{'、'.join(win_kw[:2])}」。",
                     "kind": "avoid_topics", "values": weak_kw[:3], "label": "降權無效題材"}
    elif win_kw:
        one_thing = {"text": f"「{win_kw[0]}」最留人，本週全押它的續集與變體。",
                     "kind": "produce_more", "values": win_kw[:3], "label": "全押這題材"}
    else:
        one_thing = {"text": "資料累積中，先穩定每日產出衝樣本量。"}

    medv2 = sorted((x.get("views") or 0) for x in pub)[len(pub) // 2] if pub else 0

    def prow(x):
        return {"title": (x.get("title") or x.get("slug") or "")[:44], "videoId": x.get("videoId"),
                "views": x.get("views"), "retention": x.get("retention"), "score": x.get("score")}
    clickbait = sorted([x for x in pub if (x.get("views") or 0) >= medv2 and (x.get("retention") or 0) < 40],
                       key=lambda x: -(x.get("views") or 0))[:5]
    lowscore = sorted([x for x in pub if x.get("score") is not None and x.get("score") < 60],
                      key=lambda x: (x.get("score") or 0))[:5]
    problems = {"clickbait": [prow(x) for x in clickbait], "lowscore": [prow(x) for x in lowscore]}

    def _grp(pred):
        g = [x for x in pub if pred(x)]
        if not g:
            return {"n": 0, "ret": 0, "views": 0, "subs": 0}
        return {"n": len(g),
                "ret": round(sum((x.get("retention") or 0) for x in g) / len(g), 1),
                "views": round(sum((x.get("views") or 0) for x in g) / len(g)),
                "subs": round(sum((x.get("subs") or 0) for x in g) / len(g), 1)}
    sl = lambda x: str(x.get("slug") or "")
    format_split = {"short": _grp(lambda x: sl(x).startswith("S")), "long": _grp(lambda x: sl(x).startswith("L"))}

    scatter = [{"v": x.get("views") or 0, "r": x.get("retention") or 0, "s": x.get("score")} for x in pub]

    kws = []
    try:
        import importlib
        kws = list(getattr(importlib.import_module("traffic_dept"), "NICHE_KW", []) or [])
    except Exception:  # noqa: BLE001
        kws = []
    DEFAULT_KW = ["回測", "複利", "網格", "定投", "DCA", "風控", "勝率", "實測", "虧光", "被割",
                  "避雷", "詐", "槓桿", "ETF", "比特幣", "BTC", "機器人", "派網", "停利", "停損",
                  "報酬", "本金", "破產", "公式", "抱"]
    seen_kw, kwset = set(), []
    for k in list(kws) + DEFAULT_KW + win_kw + weak_kw:
        k = str(k)
        if k and k not in seen_kw:
            seen_kw.add(k); kwset.append(k)
    topic_rank = []
    for kw in kwset:
        m = [x for x in pub if kw in (x.get("title") or x.get("slug") or "")]
        if len(m) >= 2:
            topic_rank.append({"kw": kw, "ret": round(sum((x.get("retention") or 0) for x in m) / len(m), 1), "n": len(m)})
    topic_rank.sort(key=lambda z: z["ret"], reverse=True)
    topic_rank = topic_rank[:12]

    fin = (_load(STUDIO / "finance.json") or {}).get("summary") or {}
    finance = {"revenue": fin.get("revenue"), "cost": fin.get("cost"), "net": fin.get("net"),
               "roi": fin.get("roi"), "affiliate": fin.get("affiliate"), "adsense": fin.get("adsense")}

    # ── v3:週比 / 預測 / 異常 / 相關 / 競品 / 連載 / 今日TODO ──
    dv = [d.get("views") or 0 for d in daily]
    n = len(daily)
    wow = {}
    if n >= 4:
        h = min(7, n // 2)
        rec, prv = daily[-h:], daily[-2 * h:-h]
        rv = (rec[-1]["views"] - rec[0]["views"]) if len(rec) >= 2 else 0
        pv = (prv[-1]["views"] - prv[0]["views"]) if len(prv) >= 2 else 0
        rp = sum((d.get("shorts") or 0) + (d.get("longs") or 0) for d in rec)
        pp = sum((d.get("shorts") or 0) + (d.get("longs") or 0) for d in prv)
        pct = lambda a, b: (round((a - b) / b * 100) if b else None)
        wow = {"views_recent": rv, "views_delta": pct(rv, pv),
               "prod_recent": rp, "prod_delta": pct(rp, pp), "span": h}

    forecast = {}
    if n >= 3:
        xs = list(range(n)); mx = sum(xs) / n; my = sum(dv) / n
        den = sum((x - mx) ** 2 for x in xs) or 1
        slope = sum((xs[i] - mx) * (dv[i] - my) for i in range(n)) / den
        forecast = {"slope": round(slope), "cur": dv[-1], "next": round(dv[-1] + slope * 7),
                    "note": "樣本少僅供參考" if n < 10 else ""}

    gains = [dv[i] - dv[i - 1] for i in range(1, n)]
    anomalies = []
    if len(gains) >= 4:
        gm = sum(gains) / len(gains)
        gsd = (sum((g - gm) ** 2 for g in gains) / len(gains)) ** 0.5 or 1
        for i, g in enumerate(gains):
            z = (g - gm) / gsd
            if abs(z) >= 2:
                anomalies.append({"date": daily[i + 1]["date"], "gain": round(g),
                                  "z": round(z, 1), "kind": "spike" if z > 0 else "drop"})
        anomalies = anomalies[-6:]

    pairs = [(x.get("score"), x.get("retention")) for x in pub
             if x.get("score") is not None and x.get("retention") is not None]
    correlation = {}
    if len(pairs) >= 5:
        xs2 = [p[0] for p in pairs]; ys2 = [p[1] for p in pairs]
        m1 = sum(xs2) / len(xs2); m2 = sum(ys2) / len(ys2)
        s1 = sum((x - m1) ** 2 for x in xs2) ** 0.5
        s2 = sum((y - m2) ** 2 for y in ys2) ** 0.5
        r = round(sum((xs2[i] - m1) * (ys2[i] - m2) for i in range(len(xs2))) / (s1 * s2), 2) if s1 and s2 else 0
        verdict = ("AI 評分與實際完播正相關，評分可信" if r >= 0.3
                   else "AI 評分與完播幾乎無關，評分沒抓到留人關鍵——評分改看鉤子/節奏" if r < 0.1
                   else "AI 評分與完播弱相關，參考即可")
        correlation = {"r": r, "n": len(pairs), "verdict": verdict}

    ep_raw = _load(STUDIO / "ep_data.json") or {}
    ep = {k: ep_raw.get(k) for k in ("series_name", "current_ep", "day", "return_pct",
                                     "account_value", "investment", "profit", "cliffhanger")} if ep_raw else {}
    if ep_raw:  # 建置1 ep_engine 擴充 schema，缺欄位 graceful default（不報錯）
        ep["season"] = ep_raw.get("season") or 1
        ep["character_state"] = ep_raw.get("character_state")
        ep["cumulative"] = ep_raw.get("cumulative") or {}

    ol = (_load(STUDIO / "outliers.json") or {}).get("outliers") or []
    competitor = [{"title": (o.get("title") or "")[:50], "channel": o.get("channel"),
                   "views": o.get("views"), "ratio": o.get("ratio"), "url": o.get("url")}
                  for o in ol[:6] if isinstance(o, dict)]

    todo = []
    if comp_pct is not None and comp_pct < 50:
        todo.append({"text": "每支前3秒直接講結果、標題改可搜尋", "prio": 1,
                     "impact": f"完播 {comp_pct}%→拉近 50% 是解鎖推薦流量的關鍵"})
    if weak_kw:
        todo.append({"text": f"停做無效題材「{'、'.join(weak_kw[:2])}」", "prio": 2,
                     "impact": "把產能挪去有效題材,拉高整體留存",
                     "kind": "avoid_topics", "values": weak_kw[:3], "label": "降權"})
    if win_kw:
        todo.append({"text": f"全押有效題材「{win_kw[0]}」的續集與變體", "prio": 2,
                     "impact": "複製已驗證贏家模式,衝下一支爆款",
                     "kind": "produce_more", "values": win_kw[:3], "label": "全押"})
    if lowscore:
        todo.append({"text": f"退件重做 {len(lowscore)} 支低分片", "prio": 3,
                     "impact": "清掉拉低頻道權重的弱片", "act": "lib_autoreject", "label": "退件"})
    todo.sort(key=lambda z: z["prio"])
    today_actions = todo[:3]

    # ── 優化建議(kind/values→analytics_apply;act→既有內部動作;全內部可逆) ──
    recs = []
    if weak_kw:
        recs.append({"text": f"表現弱的題材建議降權：{'、'.join(weak_kw[:5])}",
                     "kind": "avoid_topics", "values": weak_kw[:5], "label": "降權這些"})
    if win_kw:
        recs.append({"text": f"有效題材建議多做：{'、'.join(win_kw[:5])}",
                     "kind": "produce_more", "values": win_kw[:5], "label": "多做這些"})
        recs.append({"text": f"把有效關鍵字設為選題偏好：{'、'.join(win_kw[:5])}",
                     "kind": "preferred_keywords", "values": win_kw[:5], "label": "設為偏好"})
    if comp_pct is not None and comp_pct < 50:
        recs.append({"text": f"頻道平均完播 {comp_pct}% 未達 50%，強化前3秒鉤子＋可搜尋標題（建議）"})
    if lowscore:
        recs.append({"text": "倉庫低分片一鍵退件重做（內部可逆，退回倉庫）", "act": "lib_autoreject", "label": "退件低分片"})
    if win_kw:
        recs.append({"text": "贏家批量補產（內部，雲端做片）", "act": "produce", "actPayload": {"n": 6}, "label": "批量產6支"})
    if not recs:
        recs.append({"text": "資料累積中或暫無明確優化點，持續產片累積樣本。"})

    return {"daily": daily, "completion": completion, "quadrant": quadrant,
            "top": top, "bottom": bottom, "topics": topics, "recommendations": recs,
            "health": health, "one_thing": one_thing, "problems": problems,
            "format_split": format_split, "scatter": scatter, "topic_rank": topic_rank, "finance": finance,
            "wow": wow, "forecast": forecast, "anomalies": anomalies, "correlation": correlation,
            "today_actions": today_actions, "competitor": competitor, "ep": ep,
            "northstar": _northstar(completion_avg=completion.get("avg")),
            "meta": {"has_analytics": bool(q.get("has_analytics")), "n_published": len(pub)}}


def build_state():
    _maybe_refresh()
    paused = load_directives().get("paused", False)
    kpi = _kpi()
    pend = _pending()
    wh = _warehouse()
    return {
        "ok": True,
        "ts": datetime.now(TW).strftime("%Y-%m-%d %H:%M:%S"),
        "paused": paused,
        "kpi": kpi,
        "series": _series(),
        "departments": _departments(),
        "pending": pend,
        "warehouse": wh,
        "finance": _finance(),
        "cloud": _cloud_block(),
        "focus": _focus(kpi, pend, wh, paused),
        "ops": list(OPLOG[-12:]),
        "links": {"channel": CHANNEL_URL, "studio": STUDIO_URL},
        "depts_total": len(DEPTS),
        "running_count": sum(1 for d in _departments() if d["level"] == "on"),
        "headcount": _headcount_rows(),
        "scoring": _scoring_items(),
        "published_list": _published_list(),
        "reports": _reports(),
        "decisions_log": _decisions_log(),
        "directives": _directives_state(),
        "hr_monitor": _hr_monitor(),
        "insight": _insight(),
        "brief": _brief(),
        "qa": _qa_status(),
        "auto_actions": _auto_actions(),
        "ab_titles": _ab_suggestions(),
        "ab_thumbs": _ab_thumb_suggestions(),
        "analytics": _analytics(),
    }


def _fmt_auto_detail(x):
    """把 auto_loop 的 dict detail 轉成白話一行(不要生 JSON 給老闆看)。"""
    loop = x.get("loop")
    det = x.get("detail")
    if isinstance(det, dict):
        if loop == "winner":
            titles = det.get("winner_titles") or det.get("winners") or []
            head = "、".join(str(t)[:16] for t in titles[:2])
            return "贏家全押：已把 %s 支續集/變體插進題庫最前%s" % (
                det.get("added", det.get("generated", 0)), ("（%s…）" % head if head else ""))
        if loop == "loser":
            return "輸家自動汰：%s 個低完播題材已降權（只降權、不刪片、不動上線）" % det.get("downweighted", 0)
        # 其他 dict 型 detail：挑常見可讀欄位，最後才退回精簡 JSON
        for k in ("note", "summary", "msg", "text"):
            if det.get(k):
                return str(det[k])
        return str(det)
    # decision 低風險自動套用：question 是決策內容
    return str(det or x.get("question") or x.get("action") or "")


def _auto_actions(limit=12):
    """今日自動執行紀錄(decision 低風險自動套用 + auto_loop 三迴圈)。給老闆事後審。"""
    d = _load(STUDIO / "auto_actions_log.json") or []
    if not isinstance(d, list):
        return []
    return [{"ts": x.get("ts", ""), "who": str(x.get("loop") or x.get("who") or "auto"),
             "detail": _fmt_auto_detail(x)[:120]}
            for x in d[-limit:] if isinstance(x, dict)][::-1]


def _ab_suggestions(limit=12):
    """A/B 標題建議(低完播片的更強變體,給一鍵套用)。"""
    d = _load(STUDIO / "ab_title_suggestions.json") or []
    items = d.get("items", []) if isinstance(d, dict) else d  # 支援 {items:[...]} 或直接 list
    if not isinstance(items, list):
        return []
    out = []
    for x in items[:limit]:
        if not isinstance(x, dict):
            continue
        if x.get("applied"):
            continue
        out.append({"video_id": x.get("video_id"), "old_title": x.get("old_title", ""),
                    "retention": x.get("retention"), "views": x.get("views"),
                    "variants": (x.get("variants") or [])[:3]})
    return out


def _ab_thumb_suggestions(limit=12):
    """A/B 縮圖建議(低完播/低觀看片的變體縮圖,給一鍵換縮圖)。仿 _ab_suggestions。"""
    d = _load(STUDIO / "ab_thumb_suggestions.json") or []
    items = d.get("items", []) if isinstance(d, dict) else d
    if not isinstance(items, list):
        return []
    out = []
    for x in items[:limit]:
        if not isinstance(x, dict) or x.get("applied"):
            continue
        vs = []
        for v in (x.get("variants") or [])[:3]:
            if isinstance(v, dict):
                vs.append({"idx": v.get("idx"), "accent": v.get("accent"),
                           "l1": v.get("l1"), "l2": v.get("l2"), "tag": v.get("tag"),
                           "angle": v.get("angle"), "path": v.get("path")})
        out.append({"video_id": x.get("video_id"), "old_title": x.get("old_title", ""),
                    "retention": x.get("retention"), "views": x.get("views"), "variants": vs})
    return out


def _qa_status():
    """檢測部門最近一次巡檢結果（給決策中心顯示健康燈）。"""
    q = _load(STUDIO / "qa_report.json") or {}
    if not q:
        return {"state": "none", "msg": "尚未巡檢"}
    fails = q.get("fails") or []
    return {"state": ("ok" if q.get("ok") else "fail"),
            "ts": q.get("ts", ""), "passed": q.get("passed", 0), "total": q.get("total", 0),
            "fails": fails[:8], "msg": ("全部正常" if q.get("ok") else f"{len(fails)} 項異常")}


# ════════════════════════════════════════════════════════════════════
#  /api/action — 觸發操作（背景執行，不阻塞請求）
# ════════════════════════════════════════════════════════════════════

def _run_async(fn, *a):
    threading.Thread(target=fn, args=a, daemon=True).start()


def _do_detached(tail, logname, label):
    """觸發本機腳本（原本經 SSH 丟雲端背景執行；雲端退役後改直接本機起子程序）。"""
    try:
        _run_local(tail)
        op_log(f"{label}：已於本機觸發 ✓")
    except Exception as e:  # noqa: BLE001
        op_log(f"{label}：啟動失敗 {str(e)[:60]}")


def _push_and_trigger(files, trigger_remote, label):
    """設定已在呼叫端寫入本機 STUDIO/*.json 完成（原本這裡還要 SFTP 推雲端；雲端退役後不用推，
    本機腳本讀的就是同一份檔案）；若有對應腳本就本機立即觸發生效。"""
    if trigger_remote:
        _run_local(trigger_remote)
        op_log(f"{label}：已更新設定並於本機觸發 ✓")
    else:
        op_log(f"{label}：已更新設定 ✓")


def _privacy():
    return load_directives().get("privacy", "public")


def _apply_boost_local(d, level):
    """把某部門壓榨強度寫進 boss_directives（mirror control_center._apply_boost）。"""
    boost = d.get("boost")
    if not boost:
        return None
    name = f"{d['tag']} {d['name']}"
    doc = load_directives()
    lvmap = doc.setdefault("boost", {})
    lv = max(1, min(MAX_BOOST_LV, int(level)))
    lvmap[name] = lv
    ds = [x for x in doc.get("directives", []) if not x.startswith(f"【壓榨令｜{d['tag']}")]
    suffix = "・最大化" if lv >= MAX_BOOST_LV else ""
    ds.append(f"【壓榨令｜{d['tag']}】{boost}（強度 Lv{lv}{suffix}）")
    doc["directives"] = ds
    save_directives(doc)
    return name, lv


# 所有合法 action（檢測部門乾跑用；新增 action 記得同步加入，否則檢測會抓到「按鈕無對應處理器」）
KNOWN_ACTIONS = {
    "produce", "publish", "rescore", "tidy", "check", "retro", "setmin", "cycle",
    "activate", "squeeze", "maxsqueeze", "setprod", "decide", "pause", "resume",
    "finance", "hr_adjust", "hr_rebalance", "hr_expand", "lib_autoreject", "reject",
    "directive_add", "directive_clear", "directive_reorder", "set_fmt", "decision", "schedule", "refresh", "qa",
    "apply_title", "apply_thumbnail", "analytics_apply",
}


def handle_action(payload):
    """回 (http_status, dict)。動作丟背景，立即回覆。"""
    act = (payload.get("action") or "").strip()
    if not act:
        return 400, {"ok": False, "msg": "缺 action"}
    # ── 檢測部門乾跑：只驗證『這個 action 有對應處理器』並立即回覆，絕不執行任何雲端/寫檔動作 ──
    if payload.get("_qa"):
        ok = act in KNOWN_ACTIONS
        return (200 if ok else 400), {"ok": ok, "qa": True,
                "msg": f"[QA乾跑] action '{act}' " + ("已路由 ✓" if ok else "無對應處理器 ✗")}

    # ── 一鍵操作（直接觸發雲端腳本，背景執行）──
    simple = {
        "produce":  ("./run.sh scripts/produce_batch.py --shorts {n} --long 0 --target 60", "op", "補產"),
        "publish":  (f"./run.sh scripts/daily_publish.py --max 6 --privacy {_privacy()}", "op", "上架"),
        "rescore":  ("./run.sh scripts/quality_score.py", "op", "重新評分"),
        "tidy":     ("./run.sh scripts/quality_score.py --tidy", "op", "整理倉庫"),
        "check":    ("./run.sh scripts/daily_check.py", "op", "每日大檢查"),
        "retro":    ("./run.sh scripts/retro_dept.py", "op", "回顧檢討"),
    }
    if act in simple:
        tail, logn, label = simple[act]
        if act == "produce":
            n = int(payload.get("n") or 4)
            tail = tail.format(n=max(1, min(20, n)))
            label = f"補產 {max(1, min(20, n))} 支"
        _run_async(_do_detached, tail, logn, label)
        return 200, {"ok": True, "msg": f"已送出：{label}（背景在本機執行，稍候看狀態）"}

    if act == "directive_reorder":  # 拖曳調整生效中指令的優先順序(決策部門依序讀)
        order = payload.get("order")
        if not isinstance(order, list):
            return 400, {"ok": False, "msg": "缺 order"}
        doc = load_directives()
        cur = [str(x) for x in (doc.get("directives") or [])]
        if sorted([str(x) for x in order]) != sorted(cur):
            return 409, {"ok": False, "msg": "指令清單已變動，請重新整理後再排"}
        doc["directives"] = [str(x) for x in order]
        save_directives(doc)
        _run_async(_push_and_trigger, ["boss_directives.json"], None, "調整指令優先順序")
        return 200, {"ok": True, "msg": "已更新指令優先順序（本機即時生效）"}

    if act == "apply_title":  # 一鍵套用 A/B 變體標題(Carson 主動按=非自動;雲端有 token 的地方改)
        vid = (payload.get("video_id") or "").strip()
        idx = payload.get("idx")
        if not vid or idx is None:
            return 400, {"ok": False, "msg": "缺 video_id 或 idx"}
        _run_async(_do_detached, f"./run.sh scripts/ab_title.py --apply {shlex.quote(vid)} {int(idx)}",
                   "op", f"套用A/B標題 {vid}")
        return 200, {"ok": True, "msg": "已送出：套用新標題（背景執行，稍候看 YouTube）"}

    if act == "apply_thumbnail":  # 一鍵套用 A/B 變體縮圖(對外紅線;Carson 主動按=非自動;雲端有 token 的地方換)
        vid = (payload.get("video_id") or "").strip()
        idx = payload.get("idx")
        if not vid or idx is None:
            return 400, {"ok": False, "msg": "缺 video_id 或 idx"}
        _run_async(_do_detached, f"./run.sh scripts/ab_thumbnail.py --apply {shlex.quote(vid)} {int(idx)}",
                   "op", f"套用A/B縮圖 {vid}")
        return 200, {"ok": True, "msg": "已送出：套用新縮圖（背景執行，稍候看 YouTube）"}

    if act == "qa":  # 一鍵巡檢：本機起測試server把每顆按鈕乾跑一遍(零副作用)，結果寫 qa_report.json
        qa = Path(__file__).resolve().parent / "qa_check.py"
        _run_async(lambda: subprocess.run([sys.executable, str(qa), "--port", "8796"],
                                          cwd=str(ROOT), timeout=120))
        return 200, {"ok": True, "msg": "已開始巡檢決策中心（約 20 秒，完成後看健康燈）"}

    if act == "setmin":
        n = int(payload.get("n") or 75)
        _run_async(_do_detached, f"./run.sh scripts/quality_score.py --set-min {n}", "op", f"設門檻 {n}")
        return 200, {"ok": True, "msg": f"已送出：設門檻 {n}"}

    if act == "cycle":
        chain = ("./run.sh scripts/decision_dept.py; "
                 "./run.sh scripts/produce_batch.py --shorts 4 --long 0 --target 999 --manual; "
                 f"./run.sh scripts/daily_publish.py --max 6 --privacy {_privacy()}; "
                 "./run.sh scripts/retro_dept.py; ./run.sh scripts/hr_dept.py")
        _run_async(_do_detached, f"bash -c {shlex.quote(chain)}", "cycle", "跑一輪（決策→補產→上架→回顧→人事）")
        return 200, {"ok": True, "msg": "已送出：跑一輪（背景在本機依序執行，約數十分鐘）"}

    if act == "activate":
        tag = payload.get("tag")
        d = next((x for x in DEPTS if x["tag"] == tag), None)
        if not d:
            return 400, {"ok": False, "msg": "未知部門"}
        sc = DEPT_SCRIPTS.get(d.get("act"))
        if not sc:
            return 200, {"ok": True, "msg": f"{d['tag']}{d['name']} 為唯讀部門，無需手動觸發"}
        script, args = sc
        argstr = (" " + shlex.join(args)) if args else ""
        _run_async(_do_detached, f"./run.sh {script}{argstr}", "op", f"激活 {d['tag']}{d['name']}")
        return 200, {"ok": True, "msg": f"已送出：激活 {d['tag']}{d['name']}"}

    if act in ("squeeze", "maxsqueeze"):
        tag = payload.get("tag")  # 指定則單部門，否則全公司
        targets = [x for x in DEPTS if x.get("boost") and (tag is None or x["tag"] == tag)]
        if not targets:
            return 400, {"ok": False, "msg": "沒有可壓榨的部門"}
        n = 0
        for d in targets:
            if act == "maxsqueeze":
                res = _apply_boost_local(d, MAX_BOOST_LV)
            else:
                cur = load_directives().get("boost", {}).get(f"{d['tag']} {d['name']}", 0)
                res = _apply_boost_local(d, cur + 1)
            if res:
                n += 1
        label = ("最大化壓榨" if act == "maxsqueeze" else "壓榨") + (f" {targets[0]['tag']}{targets[0]['name']}" if tag else " 全公司")
        _run_async(_push_and_trigger, ["boss_directives.json"], trig_decision(), label)
        return 200, {"ok": True, "msg": f"已對 {n} 個部門{('拉到最大' if act == 'maxsqueeze' else '+1 壓榨')}，本機即時加碼"}

    if act == "setprod":
        s = int(payload.get("shorts") or 0)
        lg = int(payload.get("long") or 0)
        s, lg = max(0, min(40, s)), max(0, min(5, lg))
        hc = load_headcount()
        hc["②"], hc["①"] = s, lg
        save_headcount(hc)
        _run_async(_push_and_trigger, ["headcount.json"], trig_produce(s, lg), f"設定每日產量 Shorts{s}/長片{lg}")
        warn = "（注意：YouTube 每天上架上限約 6 支，多的會囤庫存）" if (s + lg) > 6 else ""
        return 200, {"ok": True, "msg": f"已設定：每天 Shorts {s} 支、長片 {lg} 支。{warn}"}

    if act == "decide":
        pid = payload.get("id")
        choice = payload.get("choice")
        if not pid or choice is None:
            return 400, {"ok": False, "msg": "缺 id 或 choice"}
        pend = _load(PENDING, []) or []
        q = next((p.get("question", "") for p in pend if isinstance(p, dict) and p.get("id") == pid), "")
        bd = _load(BOSS_DEC)
        if not isinstance(bd, dict):
            bd = {}
        ts = datetime.now(TW).strftime("%Y-%m-%d %H:%M")
        bd[pid] = {"question": q, "choice": choice, "ts": ts}
        BOSS_DEC.parent.mkdir(parents=True, exist_ok=True)
        save_json_atomic(BOSS_DEC, bd)
        rest = [p for p in pend if not (isinstance(p, dict) and p.get("id") == pid)]
        save_json_atomic(PENDING, rest)
        _run_async(_push_and_trigger, ["boss_decisions.json"], trig_decision(), "拍板決策")
        return 200, {"ok": True, "msg": f"已記錄你的決定「{choice}」，決策部門立即依此重新規劃"}

    if act in ("pause", "resume"):
        doc = load_directives()
        doc["paused"] = (act == "pause")
        save_directives(doc)
        _run_async(_push_and_trigger, ["boss_directives.json"], None,
                   "暫停全自動" if act == "pause" else "恢復全自動")
        return 200, {"ok": True, "msg": ("已暫停全自動（補產/上架今天先停）" if act == "pause" else "已恢復全自動運轉")}

    if act == "finance":
        kind = (payload.get("kind") or "").strip()
        kmap = {"返佣": "affiliate", "廣告": "adsense", "支出": "cost",
                "affiliate": "affiliate", "adsense": "adsense", "cost": "cost"}
        etype = kmap.get(kind)
        try:
            amt = float(payload.get("amount"))
        except Exception:
            amt = None
        if not etype or amt is None:
            return 400, {"ok": False, "msg": "記帳需 kind（返佣/廣告/支出）與 amount"}
        note = str(payload.get("note") or "").replace('"', "'")
        args = f"--add {etype} --amount {amt} --note {shlex.quote(note)}"
        _run_async(_do_detached, f"./run.sh scripts/finance_dept.py {args}", "op", f"記帳 {kind} {amt:.0f}")
        return 200, {"ok": True, "msg": f"已記一筆「{kind}」NT$ {amt:.0f}"}

    # ── 人事編制（headcount.json → 推雲端；①②變動＝真產能，立即補產）──
    if act == "hr_adjust":
        tag = payload.get("tag")
        try:
            delta = int(payload.get("delta"))
        except Exception:
            delta = 0
        if tag not in DEPT_HEAD_DEFAULT or delta == 0:
            return 400, {"ok": False, "msg": "缺 tag 或 delta"}
        hc = load_headcount()
        hc[tag] = max(0, int(hc.get(tag, 0)) + delta)
        save_headcount(hc)
        trig = trig_produce(hc.get("②", 0), hc.get("①", 0)) if tag in ("①", "②") else None
        _run_async(_push_and_trigger, ["headcount.json"], trig, f"員額調整 {tag}{'+' if delta > 0 else ''}{delta}")
        name = next((d["name"] for d in DEPTS if d["tag"] == tag), tag)
        extra = "，並立即依新員額在本機補產" if tag in ("①", "②") else "，下一輪生效"
        return 200, {"ok": True, "msg": f"{tag}{name} 員額 → {hc[tag]} 人（已更新本機{extra}）"}

    if act == "hr_rebalance":
        hc = load_headcount()
        support = [d["tag"] for d in DEPTS if d["tag"] not in ("①", "②")]
        need = lambda t: _NEED.get(t, (1, "編制容量"))  # noqa: E731
        total = sum(int(hc.get(t, 0)) for t in support)
        if total <= 0:
            total = sum(need(t)[0] for t in support) * 2
        sw = sum(need(t)[0] for t in support) or 1
        raw = {t: total * need(t)[0] / sw for t in support}
        alloc = {t: int(raw[t]) for t in support}
        rem = total - sum(alloc.values())
        for t in sorted(support, key=lambda x: raw[x] - int(raw[x]), reverse=True)[:rem]:
            alloc[t] += 1
        for t in support:
            hc[t] = alloc[t]
        save_headcount(hc)
        _run_async(_push_and_trigger, ["headcount.json"], None, "調整員額分配")
        return 200, {"ok": True, "msg": f"已依需求重新分配後勤 {total} 員額並更新本機（製作量①②不受影響）"}

    if act == "hr_expand":
        try:
            n = int(payload.get("add"))
        except Exception:
            n = 0
        n = max(1, min(300, n)) if n else 0
        if not n:
            return 400, {"ok": False, "msg": "請輸入要新增的員額總數"}
        hc = load_headcount()
        tags = [d["tag"] for d in DEPTS]
        weights = {t: 1 for t in tags}
        weights["②"], weights["①"] = 4, 3
        tw_ = sum(weights.values())
        raw = {t: n * weights[t] / tw_ for t in tags}
        alloc = {t: int(raw[t]) for t in tags}
        rem = n - sum(alloc.values())
        for t in sorted(tags, key=lambda x: raw[x] - int(raw[x]), reverse=True)[:rem]:
            alloc[t] += 1
        for t in tags:
            hc[t] = hc.get(t, 0) + alloc[t]
        save_headcount(hc)
        _run_async(_push_and_trigger, ["headcount.json"], trig_produce(hc.get("②", 0), hc.get("①", 0)), "自動擴編")
        return 200, {"ok": True, "msg": f"已自動擴編 {n} 員額（重押 ①②產能），總員額現 {sum(hc.values())} 人，已更新本機"}

    # ── 倉庫退件（quality_score.py）──
    if act == "lib_autoreject":
        _run_async(_do_detached, "./run.sh scripts/quality_score.py --auto-reject", "op", "自動退件低分片")
        return 200, {"ok": True, "msg": "已送出：把所有低於門檻的未發布片自動退件重做（已發布的不動）"}

    if act == "reject":
        slug = (payload.get("slug") or "").strip()
        if not slug:
            return 400, {"ok": False, "msg": "缺 slug"}
        remake = bool(payload.get("remake"))
        tail = f"./run.sh scripts/quality_score.py --reject {shlex.quote(slug)}" + (" --remake" if remake else "")
        _run_async(_do_detached, tail, "op", f"退件{'＋重做' if remake else ''} {slug}")
        return 200, {"ok": True, "msg": f"已送出：退件{'並立即在本機重產一支同主題新片' if remake else '（交下一輪自動補產）'}"}

    # ── 我的決策：指令／主攻格式（boss_directives.json → 推雲端觸發決策部門）──
    if act == "directive_add":
        txt = str(payload.get("text") or "").strip()
        if not txt:
            return 400, {"ok": False, "msg": "請輸入指令內容"}
        doc = load_directives()
        doc.setdefault("directives", [])
        if isinstance(doc["directives"], list):
            doc["directives"].append(txt)
        save_directives(doc)
        _run_async(_push_and_trigger, ["boss_directives.json"], trig_decision(), "送指令")
        return 200, {"ok": True, "msg": "指令已送出，決策部門正在本機立即重新評估"}

    if act == "directive_clear":
        doc = load_directives()
        doc["directives"] = []
        save_directives(doc)
        _run_async(_push_and_trigger, ["boss_directives.json"], trig_decision(), "清空指令")
        return 200, {"ok": True, "msg": "已清空所有給工廠的指令"}

    if act == "set_fmt":
        fmt = (payload.get("fmt") or "auto").strip()
        if fmt not in ("auto", "short", "long", "both"):
            return 400, {"ok": False, "msg": "格式須為 auto/short/long/both"}
        doc = load_directives()
        doc["format_override"] = fmt
        save_directives(doc)
        _run_async(_push_and_trigger, ["boss_directives.json"], trig_decision(), "主攻格式")
        label = {"auto": "讓決策部門自己決定", "short": "主攻 Shorts", "long": "主攻長片", "both": "長短並重"}[fmt]
        return 200, {"ok": True, "msg": f"主攻格式已設為「{label}」並更新本機"}

    # ── 控制台：立即決策 / 排程囤片 ──
    if act == "decision":
        _run_async(_do_detached, "./run.sh scripts/decision_dept.py", "decision", "立即決策")
        return 200, {"ok": True, "msg": "已送出：決策部門立即重新規劃（背景在本機執行）"}

    if act == "schedule":
        try:
            days = int(payload.get("days") or 9)
        except Exception:
            days = 9
        days = max(1, min(14, days))
        tail = f"./run.sh scripts/schedule_publish.py --days {days} --per-day 1 --start 1 --hour 19 --max 6"
        _run_async(_do_detached, tail, "op", f"排程囤片 {days} 天")
        return 200, {"ok": True, "msg": f"已送出：把本機渲好的 Shorts 排程公開、分散未來 {days} 天自動發布"}

    if act == "refresh":
        # 強制下次輪詢重抓
        CACHE["yt"]["ts"] = CACHE["analytics"]["ts"] = 0
        _maybe_refresh()
        return 200, {"ok": True, "msg": "正在重新抓取數據…"}

    if act == "analytics_apply":  # 數據分析一鍵套用：只碰內部可逆(production_orders 的題材/關鍵字清單)，絕不發布/排程/花錢
        kind = (payload.get("kind") or "").strip()
        vals = payload.get("values")
        if isinstance(vals, str):
            vals = [vals]
        if kind not in ("avoid_topics", "preferred_keywords", "produce_more") or not isinstance(vals, list) or not vals:
            return 400, {"ok": False, "msg": "analytics_apply 需 kind(avoid_topics/preferred_keywords/produce_more)+values[]"}
        po_path = STUDIO / "production_orders.json"
        po = _load(po_path) or {}
        cur = po.get(kind) if isinstance(po.get(kind), list) else []
        seen = {str(x) for x in cur}
        added = []
        for v in vals:
            s = str(v).strip()
            if s and s not in seen:
                cur.append(s); seen.add(s); added.append(s)
        po[kind] = cur
        try:
            save_json_atomic(po_path, po)
        except Exception as e:  # noqa: BLE001
            return 500, {"ok": False, "msg": f"寫入失敗：{e}"}
        _run_async(_push_and_trigger, ["production_orders.json"], trig_decision(), "數據優化套用")
        lbl = {"avoid_topics": "降權題材", "preferred_keywords": "偏好關鍵字", "produce_more": "多做題材"}[kind]
        return 200, {"ok": True, "msg": f"已套用「{lbl}」：{('、'.join(added) or '（皆已存在）')}，已更新本機"}

    return 400, {"ok": False, "msg": f"未知動作：{act}"}


# ════════════════════════════════════════════════════════════════════
#  /api/say — 自然語言派工（先關鍵字，認不出再 haiku）
# ════════════════════════════════════════════════════════════════════
_SAY_RULES = [
    (("補產", "產片", "做片", "囤片", "生產"), "produce"),
    (("上架", "發布", "發片", "上片", "公開"), "publish"),
    (("跑一輪", "整輪", "一條龍", "全部跑", "整套"), "cycle"),
    (("整理", "去重", "tidy"), "tidy"),
    (("門檻", "threshold", "標準"), "setmin"),
    (("評分", "重評", "打分", "重新評"), "rescore"),
    (("大檢查", "體檢", "檢查", "健檢"), "check"),
    (("回顧", "檢討", "自省"), "retro"),
    (("壓榨", "加碼", "衝刺", "火力"), "squeeze"),
    (("暫停", "停一下", "先停"), "pause"),
    (("恢復", "繼續", "開工"), "resume"),
    (("刷新", "更新", "重新整理", "抓資料"), "refresh"),
]


def _haiku_route(txt):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    try:
        import urllib.request
        prompt = ("把老闆這句指令對應到一個動作代號，只回代號(不要其他字)："
                  "produce/publish/cycle/tidy/rescore/check/retro/squeeze/pause/resume/refresh/none。\n"
                  f"指令：{txt}")
        body = json.dumps({"model": "claude-haiku-4-5-20251001", "max_tokens": 12, "temperature": 0,
                           "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                              "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode("utf-8"))
        action = "".join(ch for ch in j["content"][0]["text"].lower() if ch.isalpha())
        valid = {"produce", "publish", "cycle", "tidy", "rescore", "check", "retro",
                 "squeeze", "pause", "resume", "refresh"}
        return action if action in valid else None
    except Exception:
        return None


def handle_say(payload):
    txt = (payload.get("text") or "").strip()
    if not txt:
        return 400, {"ok": False, "msg": "請說點什麼"}
    m = re.search(r"(\d+)", txt)
    num = int(m.group(1)) if m else None
    action = None
    for kws, key in _SAY_RULES:
        if any(k in txt for k in kws):
            action = key
            break
    via = "關鍵字"
    if action is None:
        action = _haiku_route(txt)
        via = "AI 理解"
    if action is None:
        return 200, {"ok": False, "msg": "這句我不太確定，可直接按按鈕，或說：補產/上架/跑一輪/整理倉庫/重新評分/大檢查/壓榨/暫停。"}
    p = {"action": action}
    if action == "produce" and num:
        p["n"] = num
    if action == "setmin" and num:
        p["n"] = num
    status, res = handle_action(p)
    res["msg"] = f"（{via}）{res.get('msg', '')}"
    return status, res


# ════════════════════════════════════════════════════════════════════
#  HTTP
# ════════════════════════════════════════════════════════════════════
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n) if n else b""
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    def do_GET(self):
        if self.path.startswith("/api/state"):
            try:
                self._send(200, build_state())
            except Exception as e:  # noqa: BLE001
                self._send(200, {"ok": False, "error": str(e)[:200]})
            return
        if self.path.startswith("/api/report"):
            try:
                from urllib.parse import urlparse, parse_qs
                fn = (parse_qs(urlparse(self.path).query).get("f") or [""])[0]
                safe = os.path.basename(fn)
                p = REPORTS / safe
                if safe.endswith(".md") and p.exists():
                    self._send(200, {"ok": True, "name": safe, "content": p.read_text(encoding="utf-8")})
                else:
                    self._send(200, {"ok": False, "msg": "報告不存在"})
            except Exception as e:  # noqa: BLE001
                self._send(200, {"ok": False, "msg": str(e)[:120]})
            return
        # 靜態檔（three.js / css / 圖示等）：只服務 HERE 目錄內、白名單副檔名，防路徑穿越
        try:
            from urllib.parse import urlparse, unquote
            rel = unquote(urlparse(self.path).path).lstrip("/")
            if rel and rel != "index.html":
                MIMES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
                         ".json": "application/json", ".map": "application/json", ".svg": "image/svg+xml",
                         ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                         ".ico": "image/x-icon", ".woff2": "font/woff2", ".wasm": "application/wasm"}
                ext = os.path.splitext(rel)[1].lower()
                if ext in MIMES:
                    safe = (HERE / rel).resolve()
                    if str(safe).startswith(str(HERE.resolve())) and safe.is_file():
                        ct = MIMES[ext]
                        if ext in (".js", ".mjs", ".css", ".json", ".svg", ".map"):
                            ct += "; charset=utf-8"
                        self._send(200, safe.read_bytes(), ct)
                        return
        except Exception:  # noqa: BLE001
            pass
        # 其餘回前端頁
        try:
            html = (HERE / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        except Exception as e:  # noqa: BLE001
            self._send(500, str(e).encode("utf-8"), "text/plain; charset=utf-8")

    def do_POST(self):
        payload = self._read_json()
        try:
            if self.path.startswith("/api/action"):
                code, res = handle_action(payload)
            elif self.path.startswith("/api/say"):
                code, res = handle_say(payload)
            else:
                code, res = 404, {"ok": False, "msg": "not found"}
            self._send(code, res)
        except Exception as e:  # noqa: BLE001
            self._send(200, {"ok": False, "msg": f"伺服器錯誤：{str(e)[:160]}"})


def main():
    base = int(sys.argv[1]) if len(sys.argv) > 1 else 8788
    # 啟動時先暖機一次（背景），讓首屏盡快有資料
    _maybe_refresh()
    ThreadingHTTPServer.allow_reuse_address = True  # 處理 TIME_WAIT，避免重啟卡 port
    srv = None
    for port in range(base, base + 12):  # port 被佔自動讓位，永不打不開
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), H)
            break
        except OSError:
            print(f"[port {port} 被佔，換下一個…]", file=sys.stderr)
    if srv is None:
        print("[FATAL] 找不到可用 port", file=sys.stderr); return
    print(f"量化阿森 決策中心（網頁版）：http://127.0.0.1:{port}   (Ctrl-C 結束)")
    try:
        import webbrowser  # server 端也補開一次瀏覽器（保險：就算 .bat 沒開到，這裡會開對的 port）
        webbrowser.open(f"http://127.0.0.1:{port}/")
    except Exception:
        pass
    srv.serve_forever()


if __name__ == "__main__":
    main()
