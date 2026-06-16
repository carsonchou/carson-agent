#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""control_center.py — 量化阿森 決策中心（桌面 GUI，升級版）。

分頁：🏠總覽儀表板 / 📋每日匯報 / 🧠我的決策 / 🎛控制台。
老闆雙擊桌面捷徑打開：一眼看達標進度與工廠狀態、下決策、控制。
決策寫入 STUDIO/boss_directives.json，由決策/補產/上架部門讀取遵循。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog

# Windows：背景子程序（連雲端的 SSH/python）不要彈出 console 黑窗。
_CF = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
_orig_run, _orig_popen = subprocess.run, subprocess.Popen


def _run(*a, **k):
    k.setdefault("creationflags", _CF)
    return _orig_run(*a, **k)


def _popen(*a, **k):
    k.setdefault("creationflags", _CF)
    return _orig_popen(*a, **k)

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
DIRECTIVES = STUDIO / "boss_directives.json"
LEDGER = STUDIO / "uploaded_ledger.json"
PENDING = STUDIO / "pending_decisions.json"
BOSS_DEC = STUDIO / "boss_decisions.json"
METRICS_FILE = STUDIO / "metrics_history.json"  # 即時成效波形的歷史資料
OPS = STUDIO / "ops_log.txt"
TOKEN = ROOT / "token_manage.json"
OUT = ROOT / "output"
CHANNEL_URL = "https://www.youtube.com/channel/UCqP5JQXlQR5ZDLtEiBt4kLA"
STUDIO_URL = "https://studio.youtube.com/channel/UCqP5JQXlQR5ZDLtEiBt4kLA"

# ── 雲端（DigitalOcean droplet）連線設定 ──
# cloud.json（本機、不進版控）：{"ip": "...", "user": "root", "password": "...", "remote_root": "/root/yt"}
CLOUD_CFG = ROOT / "cloud.json"
CLOUD_SSH = ROOT / "scripts" / "cloud_ssh.py"


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

FONT = ("Microsoft JhengHei", 11)
FONT_B = ("Microsoft JhengHei", 13, "bold")
FONT_BIG = ("Microsoft JhengHei", 26, "bold")
# ── 配色系統（深色金融儀表板）──
NAVY = "#0b1224"      # 主背景（更深、更沉穩）
PANEL = "#111a31"     # 中層面板（介於背景與卡片）
CARD = "#182543"      # 卡片表面（抬升感）
BORDER = "#28395f"    # 細邊框／分隔線
ACCENT = "#ffd23f"    # 品牌主色（金黃）
ACCENT2 = "#5b8cff"   # 次要強調（藍）
GREEN = "#46d98a"
RED = "#ff6b6b"
TEXTCOL = "#eef2ff"
SUB = "#8da3c4"       # 次要文字（柔藍灰）

SUB_GOAL = 1000
VIEW_GOAL = 10_000_000  # Shorts 路徑

# 11 大部門（對齊 STUDIO/00_工作室章程.md）。head = AI 員額（AI 代理數，非真人）。
# kind 用來決定「狀態」怎麼判：有真排程/腳本的標運轉，未獨立自動化的如實標規劃中（誠實鐵則）。
DEPTS = [
    {"tag": "①", "name": "影片部門（長片）",   "head": 3, "kind": "long",     "owner": "produce_batch.py ・06:07",
     "act": "produce_long",  "boost": "①影片部門：多產長片"},
    {"tag": "②", "name": "Shorts 部門",       "head": 4, "kind": "shorts",   "owner": "produce_batch.py ・06:07",
     "act": "produce_short", "boost": "②Shorts：加碼多產 Shorts，衝量優先"},
    {"tag": "③", "name": "創作靈感部門",       "head": 2, "kind": "idea",     "owner": "決策部門產出題庫指令",
     "act": "decision",      "boost": "③創作靈感：擴大選題、多找熱點題材"},
    {"tag": "④", "name": "頻道整理部門",       "head": 2, "kind": "organize", "owner": "organize_dept.py ・歸播放清單",
     "act": "organize",      "boost": "④整理：更積極歸類與維護播放清單"},
    {"tag": "⑤", "name": "流量部門（數據選題）", "head": 2, "kind": "seo",      "owner": "traffic_dept.py ・05:35 數據選題",
     "act": "traffic",       "boost": "⑤流量：更積極用數據加碼高流量題材、優化點擊"},
    {"tag": "⑥", "name": "宣傳部門",          "head": 2, "kind": "promo",    "owner": "promo_dept.py ・跨平台文案",
     "act": "promo",         "boost": "⑥宣傳：多產跨平台導流文案"},
    {"tag": "⑦", "name": "數據分析部門",       "head": 2, "kind": "data",     "owner": "YouTube Data API",
     "act": "data",          "boost": None},
    {"tag": "⑧", "name": "社群留言部門",       "head": 2, "kind": "comment",  "owner": "comment_dept.py ・回覆草稿",
     "act": "comment",       "boost": "⑧留言：更積極回覆與挖掘觀眾問題"},
    {"tag": "⑨", "name": "審核部門（發布閘門）", "head": 3, "kind": "audit",    "owner": "audit_video.py ・09:07",
     "act": "publish",       "boost": "⑨上架：提高每日上架量、衝量"},
    {"tag": "⑩", "name": "總監管部門",        "head": 1, "kind": "manage",   "owner": "每日匯報 → REPORTS/",
     "act": "reports",       "boost": None},
    {"tag": "⑪", "name": "決策部門（大腦）",    "head": 2, "kind": "decision", "owner": "decision_dept.py ・05:37",
     "act": "decision",      "boost": "⑪決策：更積極加碼會紅的、砍掉沒人看的"},
    {"tag": "⑫", "name": "回顧檢討部門（自省）", "head": 1, "kind": "retro",    "owner": "retro_dept.py ・每輪後",
     "act": "retro",         "boost": None},
    {"tag": "⑬", "name": "人事部（監察＋編制）", "head": 2, "kind": "hr",       "owner": "hr_dept.py ・監察+招募",
     "act": "hr",            "boost": None},
    {"tag": "⑭", "name": "財務／變現部",        "head": 2, "kind": "finance",  "owner": "finance_dept.py ・損益ROI",
     "act": "finance",       "boost": "⑭財務：強化變現、衝聯盟返佣轉換"},
    {"tag": "⑮", "name": "縮圖／CTR 部",        "head": 2, "kind": "thumb",    "owner": "thumbnail_dept.py ・點擊優化",
     "act": "thumb",         "boost": "⑮縮圖：更積極 A/B 優化點擊率"},
    {"tag": "⑯", "name": "競品情報部",          "head": 2, "kind": "intel",    "owner": "intel_dept.py ・對手熱點",
     "act": "intel",         "boost": "⑯競品：更密集掃描對手熱點題材"},
    {"tag": "⑰", "name": "美編部門（品牌視覺）", "head": 2, "kind": "design",   "owner": "design_system.json ・字體/配色",
     "act": "design",        "boost": "⑰美編：更積極優化字體/配色/版面設計感"},
    {"tag": "⑱", "name": "消息部門（時事即時）", "head": 2, "kind": "news",     "owner": "news_dept.py ・每2h掃時事→自動產+即時發布",
     "act": "news",          "boost": "⑱消息：更積極蹭金融時事、提高每日時事片上限"},
]
MAX_BOOST_LV = 5   # 壓榨強度上限（最大化壓榨會拉到這個值）
DEPT_HEAD_DEFAULT = {d["tag"]: d["head"] for d in DEPTS}   # 預設員額（headcount.json 缺項時的種子）
HEADCOUNT = STUDIO / "headcount.json"


def load_headcount():
    """員額表 {tag: 數}。缺檔/缺項用 DEPT_HEAD_DEFAULT 補。"""
    hc = dict(DEPT_HEAD_DEFAULT)
    if HEADCOUNT.exists():
        try:
            saved = json.loads(HEADCOUNT.read_text(encoding="utf-8"))
            for k, v in (saved.items() if isinstance(saved, dict) else []):
                if k in hc and isinstance(v, int) and v >= 0:
                    hc[k] = v
        except Exception:
            pass
    return hc


def save_headcount(hc):
    HEADCOUNT.parent.mkdir(parents=True, exist_ok=True)
    HEADCOUNT.write_text(json.dumps(hc, ensure_ascii=False, indent=2), encoding="utf-8")


def load_directives():
    if DIRECTIVES.exists():
        try:
            return json.loads(DIRECTIVES.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"directives": [], "format_override": "auto", "privacy": "public", "paused": False}


def save_directives(d):
    DIRECTIVES.parent.mkdir(parents=True, exist_ok=True)
    DIRECTIVES.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def read_ops_tail(n=12):
    if OPS.exists():
        try:
            return "\n".join(OPS.read_text(encoding="utf-8").splitlines()[-n:])
        except Exception:
            return ""
    return "（工廠首次運轉後出現心跳）"


def latest_decision():
    """回傳 (戰略一句話, [待拍板項])。"""
    if not REPORTS.exists():
        return "", []
    files = sorted(REPORTS.glob("*_決策.md"), reverse=True)
    if not files:
        return "", []
    txt = files[0].read_text(encoding="utf-8")
    m = re.search(r"\*\*戰略判斷\*\*：(.+)", txt)
    one = m.group(1).strip() if m else ""
    esc = []
    sec = re.search(r"## ⚠️ 需老闆拍板\s*(.+?)(?:\n##|\Z)", txt, re.S)
    if sec:
        for line in sec.group(1).splitlines():
            line = line.strip()
            if line.startswith("- ") and "無需老闆" not in line:
                esc.append(line[2:])
    return one, esc


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("量化阿森 ｜ 決策中心")
        # 視窗自動配合螢幕大小（小筆電也不會被切掉）；可自由縮放，內容可捲動。
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            w = min(1080, sw - 80)
            h = min(780, sh - 120)
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2 - 20)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            self.geometry("1080x760")
        self.minsize(820, 480)
        self.configure(bg=NAVY)
        self.d = load_directives()
        self.stats = {"subs": None, "views": None, "videos": None}
        self._tick = 0          # auto_tick 計數（用來決定多久抓一次 YouTube 數據）
        self._fetching = False   # 避免重複併發抓取
        self._cloud = None       # 最近一次雲端狀態（dict）
        self._cloud_state = "idle"  # idle / fetching / online / offline
        self._cloud_fetching = False
        self._cloud_last = None

        head = tk.Frame(self, bg=NAVY)
        head.pack(fill="x", padx=20, pady=(16, 2))
        titlebox = tk.Frame(head, bg=NAVY); titlebox.pack(side="left")
        tk.Frame(titlebox, bg=ACCENT, width=5, height=34).pack(side="left", padx=(0, 12))
        namecol = tk.Frame(titlebox, bg=NAVY); namecol.pack(side="left")
        tk.Label(namecol, text="量化阿森 決策中心", font=("Microsoft JhengHei", 20, "bold"),
                 bg=NAVY, fg=TEXTCOL).pack(anchor="w")
        tk.Label(namecol, text="CARSON QUANT ・ AUTONOMOUS STUDIO", font=("Consolas", 8, "bold"),
                 bg=NAVY, fg=SUB).pack(anchor="w")
        right = tk.Frame(head, bg=NAVY); right.pack(side="right")
        self.status_lbl = tk.Label(right, text="", font=FONT, bg=NAVY, fg=TEXTCOL)
        self.status_lbl.pack(anchor="e")
        self.updated_lbl = tk.Label(right, text="🕒 最後更新 --:--:--", font=("Microsoft JhengHei", 9),
                                    bg=NAVY, fg=SUB)
        self.updated_lbl.pack(anchor="e")
        # 標題下細分隔線
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(8, 0))

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=NAVY, borderwidth=0, tabmargins=(6, 6, 6, 0))
        style.configure("TNotebook.Tab", font=FONT, padding=(18, 9),
                        background=PANEL, foreground=SUB, borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", CARD), ("active", "#1d2c4d")],
                  foreground=[("selected", ACCENT), ("active", TEXTCOL)],
                  padding=[("selected", (18, 10))])
        style.configure("Y.Horizontal.TProgressbar", troughcolor=PANEL, background=ACCENT,
                        borderwidth=0, thickness=14)
        style.configure("G.Horizontal.TProgressbar", troughcolor=PANEL, background=GREEN,
                        borderwidth=0, thickness=14)
        # 捲軸：扁平、融入深色背景
        style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=NAVY,
                        bordercolor=NAVY, arrowcolor=SUB, borderwidth=0)
        style.map("Vertical.TScrollbar", background=[("active", ACCENT2)])
        # Treeview（倉庫評分清單）：融入深色主題，不要預設白底醜表格
        style.configure("Lib.Treeview", background=CARD, fieldbackground=CARD, foreground=TEXTCOL,
                        borderwidth=0, rowheight=30, font=("Microsoft JhengHei", 10))
        style.configure("Lib.Treeview.Heading", background=PANEL, foreground=SUB, borderwidth=0,
                        relief="flat", font=("Microsoft JhengHei", 10, "bold"), padding=(8, 6))
        style.map("Lib.Treeview.Heading", background=[("active", "#1d2c4d")])
        style.map("Lib.Treeview", background=[("selected", ACCENT2)], foreground=[("selected", "#0b1224")])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=16, pady=8)
        self.tab_dashboard(nb)
        self.tab_cloud(nb)
        self.tab_departments(nb)
        self.tab_library(nb)
        self.tab_published(nb)
        self.tab_hr(nb)
        self.tab_reports(nb)
        self.tab_decisions(nb)
        self.tab_control(nb)

        self.refresh_status()
        self.fetch_stats()           # 開啟時自動抓一次
        self.fetch_cloud()           # 開啟時自動抓一次雲端狀態
        self.after(8000, self.auto_tick)  # 每 8 秒刷新本地狀態

    # ---------- Tab 0: 總覽（戰情室） ----------
    def _section(self, parent, text):
        """區段標題：左側 accent 直條 + 標題，視覺層次更分明（專業感）。"""
        bar = tk.Frame(parent, bg=NAVY); bar.pack(fill="x", padx=18, pady=(14, 4))
        tk.Frame(bar, bg=ACCENT, width=4, height=18).pack(side="left", padx=(0, 9))
        tk.Label(bar, text=text, font=FONT_B, bg=NAVY, fg=TEXTCOL).pack(side="left")
        tk.Frame(bar, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, padx=(12, 0))
        return bar

    def _kpi_card(self, parent, key):
        stripe = {"subs": ACCENT, "views": ACCENT2, "retention": GREEN, "net": "#ff9f43"}.get(key, ACCENT)
        border = tk.Frame(parent, bg=BORDER); border.pack(side="left", expand=True, fill="both", padx=6)
        c = tk.Frame(border, bg=CARD); c.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Frame(c, bg=stripe, height=3).pack(fill="x")            # 頂部色條
        tk.Label(c, text=self._kpi_labels[key], font=("Microsoft JhengHei", 10), bg=CARD, fg=SUB).pack(pady=(11, 0))
        val = tk.Label(c, text="—", font=("Microsoft JhengHei", 26, "bold"), bg=CARD, fg=TEXTCOL)
        val.pack(pady=(2, 0))
        sub = tk.Label(c, text="", font=("Microsoft JhengHei", 9), bg=CARD, fg=stripe)
        sub.pack(pady=(0, 12))
        self.kpi[key] = val
        self.kpi_sub[key] = sub

    def _scroll_tab(self, nb, title):
        """建一個可上下捲動的分頁，回傳內層 frame；小筆電螢幕也能滑到所有功能。"""
        outer = tk.Frame(nb, bg=NAVY)
        nb.add(outer, text=title)
        canvas = tk.Canvas(outer, bg=NAVY, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=NAVY)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind("<Enter>", lambda e: canvas.bind_all(
            "<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        inner._outer = outer  # 需要 nb.select 的分頁(雲端/控制台)取外層用
        return inner

    def tab_dashboard(self, nb):
        f = self._scroll_tab(nb, "🏠 總覽")

        # ── 擬真特助：像真人秘書用人話跟老闆報告 ──
        _abg = "#15213d"
        aborder = tk.Frame(f, bg=BORDER); aborder.pack(fill="x", padx=12, pady=(14, 2))
        abar = tk.Frame(aborder, bg=_abg); abar.pack(fill="x", padx=1, pady=1)
        tk.Frame(abar, bg=ACCENT2, width=4).pack(side="left", fill="y")   # 左側強調條
        tk.Label(abar, text="🤝", font=("Microsoft JhengHei", 22), bg=_abg).pack(side="left", padx=(12, 6), pady=10)
        self.assistant_lbl = tk.Label(abar, text="特助小祕正在看今天的狀況…", font=("Microsoft JhengHei", 11),
                                      bg=_abg, fg=TEXTCOL, justify="left", wraplength=900, anchor="w")
        self.assistant_lbl.pack(side="left", fill="x", expand=True, pady=8)

        # ── KPI 卡片列（4 張：訂閱 / 總觀看 / 留存 / 淨利）──
        self._kpi_labels = {"subs": "訂閱數", "views": "總觀看", "retention": "平均觀看率", "net": "淨利 NT$"}
        self.kpi = {}; self.kpi_sub = {}
        row = tk.Frame(f, bg=NAVY); row.pack(fill="x", padx=12, pady=(14, 2))
        for key in ("subs", "views", "retention", "net"):
            self._kpi_card(row, key)
        tk.Button(f, text="🔄 刷新數據", font=("Microsoft JhengHei", 9), bg=CARD, fg=TEXTCOL, bd=0,
                  command=self.fetch_stats).pack(anchor="e", padx=16, pady=(4, 0))

        # ── 即時成效波形（觀看 / 訂閱 隨時間）──
        self._section(f, "📈 即時成效（觀看 / 訂閱 走勢）")
        self.wave_canvas = tk.Canvas(f, height=120, bg="#0a1020", highlightthickness=0)
        self.wave_canvas.pack(fill="x", padx=20, pady=(2, 4))
        self.wave_canvas.bind("<Configure>", lambda e: self._draw_waveform())

        # ── YPP 達標進度 ──
        self._section(f, "🎯 YPP 達標進度")
        self.pb_sub = self._progress(f, "訂閱 → 1,000", SUB_GOAL, "Y")
        self.pb_view = self._progress(f, "Shorts 觀看 → 1,000 萬", VIEW_GOAL, "G")
        self.ypp_gap = tk.Label(f, text="", font=("Microsoft JhengHei", 10), bg=NAVY, fg=ACCENT)
        self.ypp_gap.pack(anchor="w", padx=24, pady=(1, 0))

        # ── 數據洞察（近 28 天，來自 YouTube Analytics）──
        self._section(f, "📊 數據洞察（近 28 天）")
        self.insight_lbl = tk.Label(f, text="（連線 Analytics 後顯示真實留存 / 新增訂閱 / 點閱率）",
                                    font=FONT, bg=NAVY, fg=TEXTCOL, justify="left", wraplength=1000)
        self.insight_lbl.pack(anchor="w", padx=24)

        # ── 工廠狀態 ──
        self._section(f, "🏭 工廠狀態")
        self.fac_lbl = tk.Label(f, text="", font=FONT, bg=NAVY, fg=TEXTCOL, justify="left")
        self.fac_lbl.pack(anchor="w", padx=24)
        self.cloud_oneline = tk.Label(f, text="☁ 雲端：連線中…", font=FONT, bg=NAVY, fg=SUB, justify="left")
        self.cloud_oneline.pack(anchor="w", padx=24, pady=(2, 0))
        tk.Label(f, text="自動排程：05:30 競品 → 05:37 決策 → 06:07 補產 → 09:07 上架 → 09:37 回顧 → 09:42 人事 …",
                 font=("Microsoft JhengHei", 9), bg=NAVY, fg=SUB).pack(anchor="w", padx=24, pady=(1, 0))

        # ── 今日戰略 & 待你拍板 ──
        self._section(f, "🧭 今日戰略 & 待你拍板")
        self.brief = scrolledtext.ScrolledText(f, height=4, font=FONT, wrap="word",
                                               bg="#0a1020", fg=TEXTCOL, bd=0, padx=12, pady=8)
        self.brief.pack(fill="both", expand=True, padx=16, pady=(2, 4))

        # ── 工廠心跳（精簡）──
        self._section(f, "📜 工廠心跳")
        self.ops_box = scrolledtext.ScrolledText(f, height=4, font=("Consolas", 9), wrap="none",
                                                 bg="#06090f", fg=GREEN, bd=0, padx=10, pady=4)
        self.ops_box.pack(fill="x", padx=16, pady=(2, 4))

        tk.Button(f, text="▶ 立即跑一輪（決策 → 補產 → 上架 → 回顧 → 人事）", font=FONT_B, bg=ACCENT, fg=NAVY, bd=0,
                  command=self.run_full_cycle).pack(fill="x", padx=16, pady=(4, 12))

    def _progress(self, parent, label, goal, style):
        wrap = tk.Frame(parent, bg=NAVY); wrap.pack(fill="x", padx=20, pady=3)
        tk.Label(wrap, text=label, font=FONT, bg=NAVY, fg=TEXTCOL, width=20, anchor="w").pack(side="left")
        pb = ttk.Progressbar(wrap, style=f"{style}.Horizontal.TProgressbar", maximum=goal, length=520)
        pb.pack(side="left", padx=8)
        lab = tk.Label(wrap, text=f"0 / {goal:,}", font=FONT, bg=NAVY, fg=SUB)
        lab.pack(side="left")
        pb.lab = lab; pb.goal = goal
        return pb

    def fetch_stats(self):
        if self._fetching:
            return
        self._fetching = True
        def worker():
            try:
                from google.oauth2.credentials import Credentials
                from google.auth.transport.requests import Request
                from googleapiclient.discovery import build
                creds = Credentials.from_authorized_user_file(str(TOKEN),
                        ["https://www.googleapis.com/auth/youtube.force-ssl"])
                if not creds.valid and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                yt = build("youtube", "v3", credentials=creds)
                r = yt.channels().list(part="statistics", mine=True).execute()
                st = r["items"][0]["statistics"]
                self.stats = {"subs": int(st.get("subscriberCount", 0)),
                              "views": int(st.get("viewCount", 0)),
                              "videos": int(st.get("videoCount", 0))}
            except Exception as e:
                self.stats = {"subs": None, "views": None, "videos": None, "err": str(e)[:80]}
            # 順手刷新 Analytics 與財務（每 3 分鐘一次，快取給 render 用，避免每 8 秒打 API）
            try:
                import yt_analytics as ya
                if ya.available():
                    self._analytics = ya.channel_summary(28)
                    self._ya_ctr = ya.impressions_ctr(28)
            except Exception:
                pass
            try:
                fin = STUDIO / "finance.json"
                self._net = (json.loads(fin.read_text(encoding="utf-8")).get("summary") or {}).get("net") \
                    if fin.exists() else None
            except Exception:
                pass
            self._fetching = False
            self._log_metrics()  # 記一筆即時成效（給波形圖）
            self.after(0, self.render_dashboard)
        threading.Thread(target=worker, daemon=True).start()

    def _log_metrics(self):
        """每次抓到頻道數據就記一筆（時間/訂閱/觀看），給總覽波形圖用。"""
        try:
            subs, views = self.stats.get("subs"), self.stats.get("views")
            if not isinstance(subs, int) or not isinstance(views, int):
                return
            from datetime import datetime
            hist = []
            if METRICS_FILE.exists():
                hist = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
            hist.append({"t": datetime.now().strftime("%m-%d %H:%M"), "subs": subs, "views": views})
            METRICS_FILE.write_text(json.dumps(hist[-240:], ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _draw_waveform(self):
        """在總覽畫觀看/訂閱走勢波形（純 Canvas，各自正規化以便同框比較）。"""
        cv = getattr(self, "wave_canvas", None)
        if cv is None:
            return
        cv.delete("all")
        w = cv.winfo_width() or 1000
        h = cv.winfo_height() or 120
        try:
            hist = json.loads(METRICS_FILE.read_text(encoding="utf-8")) if METRICS_FILE.exists() else []
        except Exception:
            hist = []
        if len(hist) < 2:
            cv.create_text(w // 2, h // 2, text="（成效資料累積中…決策中心開著就會自動記錄並畫成走勢）",
                           fill=SUB, font=("Microsoft JhengHei", 10))
            return
        pad = 10

        def line(key, color):
            vals = [p.get(key, 0) for p in hist]
            lo, hi = min(vals), max(vals)
            rng = (hi - lo) or 1
            n = len(vals)
            pts = []
            for i, v in enumerate(vals):
                x = pad + (w - 2 * pad) * i / (n - 1)
                y = h - pad - (h - 2 * pad) * (v - lo) / rng
                pts += [x, y]
            if len(pts) >= 4:
                cv.create_line(*pts, fill=color, width=2, smooth=True)
            return vals[-1], (vals[-1] - vals[0])

        v_now, v_d = line("views", ACCENT)
        s_now, s_d = line("subs", GREEN)
        cv.create_text(pad + 2, pad - 2, anchor="nw",
                       text=f"觀看 {v_now}（+{v_d}）", fill=ACCENT, font=("Microsoft JhengHei", 9, "bold"))
        cv.create_text(pad + 2, pad + 16, anchor="nw",
                       text=f"訂閱 {s_now}（+{s_d}）", fill=GREEN, font=("Microsoft JhengHei", 9, "bold"))

    def _assistant_brief(self) -> str:
        """擬真特助：用人話把今天狀況講給老闆聽（純由數據組裝，不打 API）。"""
        from datetime import datetime
        cloud = self._cloud if (getattr(self, "_cloud_state", "") == "online" and self._cloud) else None
        subs = self.stats.get("subs")
        pend = len(self._load_pending())
        h = datetime.now().hour
        greet = "早安老闆 ☀" if h < 11 else ("午安老闆 🌤" if h < 18 else "晚安老闆 🌙")
        parts = [f"{greet}，我是你的特助小祕。"]
        if cloud:
            run = "正在趕工 🎬" if cloud.get("render_running") else "暫時休息"
            parts.append(f"雲端今天做了 {cloud.get('produced_today', 0)} 支、倉庫 {cloud.get('queue', 0)} 支（{run}）。")
            if cloud.get("errors_recent"):
                parts.append(f"⚠ 有 {cloud['errors_recent']} 條異常我盯著。")
        elif getattr(self, "_cloud_state", "") == "offline":
            parts.append("（連不上雲端，我看的是本機資料）")
        if isinstance(subs, int):
            gap = max(0, SUB_GOAL - subs)
            parts.append(f"訂閱 {subs}，離 YPP 還差 {gap}。")
        if pend:
            parts.append(f"📌 有 {pend} 件等你拍板 → 去「🧠 我的決策」。")
        else:
            parts.append("沒有要你決定的事，其餘我幫你顧著，放心去忙 ✌")
        return "　".join(parts)

    def render_dashboard(self):
        # 讀快取（由 fetch_stats 每 3 分鐘更新；避免每 8 秒打 Analytics API）
        analytics = getattr(self, "_analytics", None)
        net = getattr(self, "_net", None)
        try:
            self.assistant_lbl.config(text=self._assistant_brief())
        except Exception:
            pass

        # ── 4 張 KPI 卡 ──
        subs, views = self.stats.get("subs"), self.stats.get("views")
        self.kpi["subs"].config(text=f"{subs:,}" if isinstance(subs, int) else "—")
        self.kpi["views"].config(text=f"{views:,}" if isinstance(views, int) else "—")
        self.kpi["retention"].config(
            text=f"{analytics['avg_pct']:.0f}%" if analytics else "—")
        self.kpi["net"].config(text=f"{net:,.0f}" if isinstance(net, (int, float)) else "—")
        # 卡片副標（綠色佐證）
        sg = analytics.get("subs_gained") if analytics else None
        self.kpi_sub["subs"].config(text=(f"近28天 +{sg}" if isinstance(sg, int) else ""))
        self.kpi_sub["retention"].config(text=("留得住人" if analytics and analytics["avg_pct"] >= 50 else ""))
        self.kpi_sub["net"].config(text="（手動記帳）" if isinstance(net, (int, float)) else "")
        self.kpi_sub["views"].config(text="")

        # ── YPP 進度 + 還差 ──
        for pb, key in [(self.pb_sub, "subs"), (self.pb_view, "views")]:
            v = self.stats.get(key) or 0
            pb["value"] = min(v, pb.goal)
            pct = (v / pb.goal * 100) if pb.goal else 0
            pb.lab.config(text=f"{v:,} / {pb.goal:,}  ({pct:.2f}%)")
        gap_sub = max(0, SUB_GOAL - (subs or 0))
        gap_view = max(0, VIEW_GOAL - (views or 0))
        self.ypp_gap.config(text=f"距達標：還差 {gap_sub:,} 訂閱　或　{gap_view:,} Shorts 觀看（擇一達成即可營利）")

        # ── 數據洞察（Analytics）──
        if analytics:
            ctr = getattr(self, "_ya_ctr", None)
            ctr_txt = f"・曝光點閱率 {ctr['ctr']:.2f}%" if ctr else "・點閱率（待流量累積）"
            self.insight_lbl.config(
                text=f"平均觀看率 {analytics['avg_pct']:.1f}%　・　近28天新增訂閱 {analytics['subs_gained']}　"
                     f"・　總觀看分鐘 {analytics['minutes']:,}{ctr_txt}", fg=TEXTCOL)
        else:
            self.insight_lbl.config(
                text="（尚未連線 YouTube Analytics，或數據累積中）", fg=SUB)

        # ── 工廠狀態（16 部門）──
        q = len(set(p.stem for p in OUT.glob("S_*.mp4")) | set(p.stem for p in OUT.glob("L_*.mp4")))
        pub = len(json.loads(LEDGER.read_text(encoding="utf-8"))) if LEDGER.exists() else 0
        paused = load_directives().get("paused", False)
        self.fac_lbl.config(
            text=f"{len(DEPTS)} 部門　｜　倉庫 {q} 支　｜　累計上架 {pub} 支　｜　"
                 + ("⏸ 已暫停" if paused else "▶ 全自動運轉中"))
        # 戰略 + 待拍板（線上時戰略以雲端為準）
        cloud = self._cloud if (getattr(self, "_cloud_state", "") == "online" and self._cloud) else None
        one, _ = latest_decision()
        if cloud and cloud.get("strategy"):
            one = cloud["strategy"]
        pend = self._load_pending()
        self.brief.delete("1.0", "end")
        self.brief.insert("end", "【今日戰略】\n" + (one or "（決策部門明早 05:37 首次運轉後產生）") + "\n\n")
        if pend:
            self.brief.insert("end", f"【待你拍板 {len(pend)} 項】→ 到「🧠 我的決策」分頁點選\n")
            for p in pend:
                self.brief.insert("end", f"• {p.get('question','')}\n")
        else:
            self.brief.insert("end", "【待你拍板】（目前沒有，工廠自己跑）\n")
        if self.stats.get("err"):
            self.brief.insert("end", f"\n（數據抓取提醒：{self.stats['err']}）")
        # 工廠心跳（線上時顯示雲端心跳）
        try:
            self.ops_box.delete("1.0", "end")
            if cloud and cloud.get("ops_tail"):
                self.ops_box.insert("1.0", "\n".join(cloud["ops_tail"]))
            else:
                self.ops_box.insert("1.0", read_ops_tail(12))
            self.ops_box.see("end")
        except Exception:
            pass
        try:
            self._draw_waveform()
        except Exception:
            pass

    def run_full_cycle(self):
        if not messagebox.askyesno("確認", "立即依序執行：決策 → 補產 → 上架 → 回顧 → 人事？\n（預設在雲端跑，背景進行，可在『☁ 雲端營運』看輸出）"):
            return
        priv = load_directives().get("privacy", "public")
        cfg = load_cloud_cfg()
        if cfg:  # 在雲端跑整輪（背景）
            self._nb.select(self._cloud_frame)
            chain = ("./run.sh scripts/decision_dept.py; "
                     "./run.sh scripts/produce_batch.py --shorts 4 --long 1 --target 60; "
                     f"./run.sh scripts/daily_publish.py --max 6 --privacy {priv}; "
                     "./run.sh scripts/retro_dept.py; ./run.sh scripts/hr_dept.py")
            self._cloud_stream(
                f"cd {cfg['remote_root']} && nohup bash -c '{chain}' > logs/full_cycle.log 2>&1 & echo '已在雲端背景啟動整輪（看 logs/full_cycle.log）'",
                "雲端跑一輪")
            return
        # 無雲端 → 本機跑（備援）
        self._goto_control()

        def chain():
            for args, name in [(["scripts/decision_dept.py"], "決策"),
                               (["scripts/produce_batch.py", "--shorts", "4", "--long", "1"], "補產"),
                               (["scripts/daily_publish.py", "--max", "6", "--privacy", priv], "上架"),
                               (["scripts/retro_dept.py"], "回顧檢討"),
                               (["scripts/hr_dept.py"], "人事監察")]:
                self._run_blocking(args, name)
            self.after(0, self.fetch_stats)
        threading.Thread(target=chain, daemon=True).start()

    # ---------- Tab: ☁ 雲端營運中心 ----------
    def tab_cloud(self, nb):
        f = self._scroll_tab(nb, "☁ 雲端營運")
        self._cloud_frame = f._outer

        # 連線狀態橫幅
        top = tk.Frame(f, bg=CARD); top.pack(fill="x", padx=16, pady=(14, 6))
        self.cloud_banner = tk.Label(top, text="☁ 雲端連線中…", font=FONT_B, bg=CARD, fg=ACCENT,
                                     anchor="w", justify="left")
        self.cloud_banner.pack(side="left", padx=12, pady=10)
        self.cloud_sub = tk.Label(top, text="", font=("Microsoft JhengHei", 9), bg=CARD, fg=SUB)
        self.cloud_sub.pack(side="right", padx=12)

        # 雲端 KPI 四卡（倉庫 / 今日已產 / 累計上架 / 排程囤片剩餘）
        self._cloud_kpi_labels = {"queue": "雲端倉庫", "produced": "今日已產",
                                  "published": "累計上架", "buffer": "排程囤片剩餘"}
        self.cloud_kpi = {}
        krow = tk.Frame(f, bg=NAVY); krow.pack(fill="x", padx=12, pady=(2, 2))
        for key in ("queue", "produced", "published", "buffer"):
            c = tk.Frame(krow, bg=CARD); c.pack(side="left", expand=True, fill="both", padx=5)
            val = tk.Label(c, text="—", font=("Microsoft JhengHei", 24, "bold"), bg=CARD, fg=ACCENT)
            val.pack(pady=(12, 0))
            tk.Label(c, text=self._cloud_kpi_labels[key], font=("Microsoft JhengHei", 10),
                     bg=CARD, fg=SUB).pack(pady=(0, 10))
            self.cloud_kpi[key] = val

        # 操作列
        bar = tk.Frame(f, bg=NAVY); bar.pack(fill="x", padx=16, pady=(8, 2))
        tk.Button(bar, text="🔄 立即刷新雲端", font=FONT, bg=ACCENT, fg=NAVY, bd=0, padx=12, pady=5,
                  command=self.fetch_cloud).pack(side="left", padx=(0, 6))
        tk.Button(bar, text="📜 看雲端日誌", font=FONT, bg=CARD, fg=TEXTCOL, bd=0, padx=12, pady=5,
                  command=self.cloud_view_log).pack(side="left", padx=6)
        tk.Label(bar, text="（補產／上架／排程囤片都在「🎛 控制台」操作）", font=("Microsoft JhengHei", 9),
                 bg=NAVY, fg=SUB).pack(side="left", padx=10)

        # 排程囤片清單（出國保險）
        self._section(f, "📅 排程囤片（YouTube 伺服器自動公開・不依賴家用網路）")
        self.cloud_buffer_box = scrolledtext.ScrolledText(f, height=6, font=("Microsoft JhengHei", 10),
                                                          wrap="word", bg="#0a1020", fg=TEXTCOL, bd=0,
                                                          padx=12, pady=8)
        self.cloud_buffer_box.pack(fill="x", padx=16, pady=(2, 4))

        # 主機健康
        self._section(f, "🖥 主機健康")
        self.cloud_host_lbl = tk.Label(f, text="（連線後顯示磁碟／記憶體／負載／運行時間）",
                                       font=FONT, bg=NAVY, fg=TEXTCOL, justify="left", wraplength=1000)
        self.cloud_host_lbl.pack(anchor="w", padx=24)

        # cron 日誌
        self._section(f, "📜 雲端 cron 最近日誌")
        self.cloud_cronbox = scrolledtext.ScrolledText(f, height=5, font=("Consolas", 9), wrap="none",
                                                       bg="#06090f", fg=GREEN, bd=0, padx=10, pady=4)
        self.cloud_cronbox.pack(fill="x", padx=16, pady=(2, 4))

        # 操作輸出
        self._section(f, "⌨ 雲端操作輸出")
        self.cloud_log = scrolledtext.ScrolledText(f, height=7, font=("Consolas", 9), wrap="word",
                                                   bg="#06090f", fg="#b9f7c0", bd=0, padx=10, pady=6)
        self.cloud_log.pack(fill="both", expand=True, padx=16, pady=(2, 12))

    def _cloud_env(self, cfg):
        env = dict(os.environ)
        env["DROPLET_IP"] = cfg["ip"]
        env["DROPLET_PW"] = cfg["password"]
        env["DROPLET_USER"] = cfg.get("user", "root")
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def fetch_cloud(self):
        """背景抓一次雲端狀態（跑 cloud_status.py via SSH，解析 JSON）。"""
        if self._cloud_fetching:
            return
        cfg = load_cloud_cfg()
        if not cfg:
            self._cloud_state = "noconfig"
            self.render_cloud()
            return
        self._cloud_fetching = True
        self._cloud_state = "fetching"
        try:
            self.render_cloud()
        except Exception:
            pass

        def worker():
            t0 = time.time()
            data, err = None, None
            try:
                remote = f"cd {cfg['remote_root']} && ./run.sh scripts/cloud_status.py"
                p = _run([str(PY), str(CLOUD_SSH), "run", remote],
                                   env=self._cloud_env(cfg), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=40)
                out = p.stdout or ""
                for line in out.splitlines():
                    if "@@CLOUDJSON64@@" in line:
                        import base64
                        b64 = line.split("@@CLOUDJSON64@@", 1)[1].strip()
                        data = json.loads(base64.b64decode(b64).decode("utf-8"))
                        break
                if data is None:
                    err = (out.strip().splitlines()[-1] if out.strip() else "") or (p.stderr or "無回應")
            except subprocess.TimeoutExpired:
                err = "連線逾時（伺服器忙或網路慢）"
            except Exception as e:  # noqa: BLE001
                err = str(e)[:120]
            data and data.update({"_latency": round(time.time() - t0, 1)})
            self._cloud = data
            self._cloud_err = err
            self._cloud_state = "online" if data else "offline"
            self._cloud_fetching = False
            from datetime import datetime
            self._cloud_last = datetime.now().strftime("%H:%M:%S")
            if data:
                self._adopt_cloud(data)
            self.after(0, self.render_cloud)
            self.after(0, self._after_cloud_sync)
        threading.Thread(target=worker, daemon=True).start()

    def render_cloud(self):
        st = self._cloud_state
        # 一行式（總覽用）
        oneline = getattr(self, "cloud_oneline", None)
        if st == "noconfig":
            banner = "🔧 尚未設定雲端連線（缺 cloud.json）"
            if hasattr(self, "cloud_banner"):
                self.cloud_banner.config(text=banner, fg=SUB)
                self.cloud_sub.config(text="")
            if oneline:
                oneline.config(text="☁ 雲端：未設定（建立 cloud.json 即可監看）", fg=SUB)
            return
        if st == "fetching" and not self._cloud:
            if hasattr(self, "cloud_banner"):
                self.cloud_banner.config(text="☁ 連線雲端中…", fg=ACCENT)
            if oneline:
                oneline.config(text="☁ 雲端：連線中…", fg=SUB)
            return

        d = self._cloud
        if not d:  # offline
            msg = getattr(self, "_cloud_err", "") or "無法連線"
            if hasattr(self, "cloud_banner"):
                self.cloud_banner.config(text="🔴 雲端離線 / 連不上", fg=RED)
                self.cloud_sub.config(text=f"最後嘗試 {self._cloud_last or '--'} ・ {msg[:50]}")
            if oneline:
                oneline.config(text=f"☁ 雲端：🔴 離線（{msg[:40]}）", fg=RED)
            return

        # online
        render_txt = "🎬 渲染中" if d.get("render_running") else "💤 閒置"
        cron_txt = "✅ cron 已裝" if d.get("cron_installed") else "⚠ cron 未裝"
        errn = d.get("errors_recent", 0)
        if hasattr(self, "cloud_banner"):
            self.cloud_banner.config(
                text=f"🟢 雲端線上 ・ {render_txt} ・ {cron_txt}", fg=GREEN)
            self.cloud_sub.config(
                text=f"伺服器時間 {d.get('ts','')} ・ 延遲 {d.get('_latency','?')}s ・ 本機更新 {self._cloud_last or '--'}")
        # KPI
        if hasattr(self, "cloud_kpi"):
            self.cloud_kpi["queue"].config(text=str(d.get("queue", "—")))
            self.cloud_kpi["produced"].config(text=str(d.get("produced_today", "—")))
            self.cloud_kpi["published"].config(text=str(d.get("published_total", "—")))
            bc = d.get("buffer_count", 0)
            self.cloud_kpi["buffer"].config(text=str(bc), fg=(GREEN if bc else SUB))
        # 排程囤片清單
        if hasattr(self, "cloud_buffer_box"):
            self.cloud_buffer_box.delete("1.0", "end")
            buf = d.get("buffer", [])
            if buf:
                nextp = d.get("next_publish")
                self.cloud_buffer_box.insert("end", f"共 {d.get('buffer_count',0)} 支待自動公開"
                                             + (f"，下一支 {nextp}（台灣）\n" if nextp else "\n"))
                for b in buf:
                    title = b.get("slug", "")[:42]
                    self.cloud_buffer_box.insert("end", f"  • {b.get('at_tw','')}　{title}\n")
                self.cloud_buffer_box.insert("end", "\n這些影片由 YouTube 伺服器定時翻牌公開，你人在國外/家裡斷網也照發。")
            else:
                self.cloud_buffer_box.insert("end", "（目前沒有排程囤片。按「📦 雲端排程囤片」把渲好的片排進出國這幾天。）")
        # 主機健康
        if hasattr(self, "cloud_host_lbl"):
            parts = []
            if "disk_pct" in d:
                parts.append(f"💾 磁碟 {d['disk_pct']}%（剩 {d.get('disk_free_gb','?')}GB）")
            if "mem_pct" in d:
                parts.append(f"🧠 記憶體 {d['mem_pct']}%／{d.get('mem_total_gb','?')}GB")
            if "load1" in d:
                parts.append(f"📈 負載 {d['load1']}")
            if "uptime" in d:
                parts.append(f"⏱ 運行 {d['uptime']}")
            parts.append(f"🛠 近期異常 {errn} 條" if errn else "✅ 近期無異常")
            disk_warn = d.get("disk_pct", 0) >= 88
            self.cloud_host_lbl.config(text="　｜　".join(parts), fg=(RED if disk_warn else TEXTCOL))
        # cron 日誌
        if hasattr(self, "cloud_cronbox"):
            self.cloud_cronbox.delete("1.0", "end")
            lines = d.get("cron_recent", [])
            mt = d.get("cron_log_mtime")
            self.cloud_cronbox.insert("1.0", (f"# 最後寫入 {mt}\n" if mt else "")
                                      + ("\n".join(lines) if lines else "（cron 尚未首次執行；明早 06:07 起會有紀錄）"))
            self.cloud_cronbox.see("end")
        # 總覽一行
        if oneline:
            bc = d.get("buffer_count", 0)
            oneline.config(
                text=f"☁ 雲端：🟢 線上　｜　倉庫 {d.get('queue',0)} 支　｜　今日已產 {d.get('produced_today',0)}　"
                     f"｜　累計上架 {d.get('published_total',0)}　｜　排程囤片 {bc} 支　｜　{render_txt}",
                fg=(GREEN if not errn else ACCENT))

    def _cloud_stream(self, remote_cmd, name, logbox=None):
        """在雲端跑一條指令，輸出串到指定 log 框（預設雲端操作輸出框）。"""
        cfg = load_cloud_cfg()
        if not cfg:
            messagebox.showwarning("未設定雲端", "找不到 cloud.json，無法連雲端。")
            return
        box = logbox if logbox is not None else self.cloud_log
        box.insert("end", f"\n=== {name} 開始（雲端）… ===\n"); box.see("end")

        def worker():
            try:
                p = _popen([str(PY), str(CLOUD_SSH), "run", remote_cmd],
                                     env=self._cloud_env(cfg), stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                for line in p.stdout:
                    box.insert("end", line); box.see("end")
                p.wait()
                box.insert("end", f"=== {name} 完成 (exit {p.returncode}) ===\n")
            except Exception as e:  # noqa: BLE001
                box.insert("end", f"[錯誤] {e}\n")
            self.after(0, self.fetch_cloud)
        threading.Thread(target=worker, daemon=True).start()

    def cloud_produce(self):
        if not messagebox.askyesno("☁ 在雲端補產", "在雲端伺服器立即補產 Shorts？\n（不佔用你的電腦，渲染在雲端跑）"):
            return
        n = simpledialog.askinteger("補產數量", "要補產幾支 Shorts？", parent=self,
                                    minvalue=1, maxvalue=20, initialvalue=4)
        if not n:
            return
        cfg = load_cloud_cfg()
        self._cloud_stream(
            f"cd {cfg['remote_root']} && nohup ./run.sh scripts/produce_batch.py --shorts {n} --long 0 --target 60 "
            f"> logs/manual_produce.log 2>&1 & echo '已在雲端背景啟動補產 {n} 支（看 logs/manual_produce.log）'",
            f"雲端補產 {n} 支")

    def cloud_schedule(self):
        if not messagebox.askyesno("📦 雲端排程囤片",
                                   "把雲端渲好的 Shorts 上傳為『排程公開』，分散未來幾天自動發布？\n"
                                   "（YouTube 伺服器定時翻牌，出國斷網照發）"):
            return
        days = simpledialog.askinteger("排幾天份", "排程涵蓋未來幾天（每天 1 支）？", parent=self,
                                       minvalue=1, maxvalue=14, initialvalue=9)
        if not days:
            return
        cfg = load_cloud_cfg()
        if not cfg:
            messagebox.showwarning("未設定雲端", "找不到 cloud.json，無法連雲端。")
            return
        self._cloud_stream(
            f"cd {cfg['remote_root']} && ./run.sh scripts/schedule_publish.py --days {days} --per-day 1 --start 1 --hour 19 --max 6",
            f"雲端排程囤片 {days} 天", logbox=getattr(self, "log", None))

    def cloud_publish(self):
        if not messagebox.askyesno("🚀 雲端立即上架", "在雲端立即把倉庫的影片上架（公開）？"):
            return
        cfg = load_cloud_cfg()
        priv = load_directives().get("privacy", "public")
        self._cloud_stream(
            f"cd {cfg['remote_root']} && ./run.sh scripts/daily_publish.py --max 6 --privacy {priv}",
            "雲端立即上架")

    def cloud_view_log(self):
        cfg = load_cloud_cfg()
        if not cfg:
            messagebox.showwarning("未設定雲端", "找不到 cloud.json，無法連雲端。")
            return
        self._cloud_stream(
            f"cd {cfg['remote_root']} && tail -40 logs/cron.log 2>/dev/null; echo '--- 補產 ---'; tail -20 logs/buffer_render.log 2>/dev/null",
            "讀雲端日誌")

    # ── 整合核心：把本機控制『推送到雲端 + 馬上照做』──
    def _remote(self, tail):
        """組遠端指令（cd 到雲端根目錄）；無 cloud.json 時回 None。"""
        cfg = load_cloud_cfg()
        return f"cd {cfg['remote_root']} && {tail}" if cfg else None

    def _trig_decision(self):
        return self._remote("nohup ./run.sh scripts/decision_dept.py > logs/manual_decision.log 2>&1 & echo triggered")

    def _trig_produce(self, shorts, longn):
        # 已在渲染就不重複啟動，避免堆疊
        return self._remote(
            f"(pgrep -f produce_batch >/dev/null && echo 'already-rendering') || "
            f"(nohup ./run.sh scripts/produce_batch.py --shorts {shorts} --long {longn} --target 60 "
            f"> logs/manual_produce.log 2>&1 & echo triggered)")

    def _cloud_apply(self, files=(), trigger_remote=None, label=""):
        """把指定的 STUDIO 設定檔推到雲端，並（可選）立刻觸發對應腳本。非阻塞。"""
        cfg = load_cloud_cfg()
        if not cfg:
            return False

        def worker():
            okmsg = []
            try:
                for fn in files:
                    lp = STUDIO / fn
                    if lp.exists():
                        _run([str(PY), str(CLOUD_SSH), "put", str(lp),
                                        f"{cfg['remote_root']}/STUDIO/{fn}"],
                                       env=self._cloud_env(cfg), capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=45)
                        okmsg.append(fn)
                if trigger_remote:
                    _run([str(PY), str(CLOUD_SSH), "run", trigger_remote],
                                   env=self._cloud_env(cfg), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=45)
                line = f"[雲端] {label}：已推送 {'、'.join(okmsg) or '設定'}" + ("，並立即觸發執行 ✓\n" if trigger_remote else " ✓\n")
            except Exception as e:  # noqa: BLE001
                line = f"[雲端] {label} 失敗：{str(e)[:80]}\n"
            try:
                self.after(0, lambda: (self.cloud_log.insert("end", line), self.cloud_log.see("end")))
            except Exception:
                pass
            self.after(1800, self.fetch_cloud)  # 稍後刷新雲端狀態，反映結果
        threading.Thread(target=worker, daemon=True).start()
        return True

    def _activate_on_cloud(self, script, args, label):
        """⚡激活：在雲端跑某部門腳本（背景或前景串流）。"""
        cfg = load_cloud_cfg()
        if not cfg:
            return False
        argstr = " ".join(args)
        self._nb.select(self._cloud_frame)
        self._cloud_stream(f"cd {cfg['remote_root']} && ./run.sh {script} {argstr}", label + "（雲端）")
        return True

    def _adopt_cloud(self, data):
        """把雲端的控制面資料寫回本機，讓既有分頁直接顯示雲端真相（單一真相＝雲端）。"""
        try:
            # 待拍板決策：以雲端為準，但用「已持久化的 boss_decisions（你答過的）」永久濾掉，
            # 跨重開也有效 —— 答過的決策不會再被拉回來叫你重決。
            answered = set(getattr(self, "_answered", set()))
            answered |= set((data.get("boss_decisions") or {}).keys())  # 雲端已答（即時）
            try:
                if BOSS_DEC.exists():
                    answered |= set(json.loads(BOSS_DEC.read_text(encoding="utf-8")).keys())  # 本機已答（持久）
            except Exception:
                pass
            pend = [p for p in data.get("pending", []) if p.get("id") not in answered]
            PENDING.write_text(json.dumps(pend, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        # 財務以雲端為準寫回本機（記帳記在雲端，這裡同步顯示，避免支出顯示不到/遺失）
        try:
            fin = data.get("finance")
            if isinstance(fin, dict) and fin:
                (STUDIO / "finance.json").write_text(json.dumps(fin, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        # 首次連線：採用雲端的員額/指令/決策為基準（之後本機改動以推送為準）
        if not getattr(self, "_cloud_baseline", False):
            try:
                doc = data.get("directives_doc")
                if isinstance(doc, dict):
                    save_directives(doc)
                hc = data.get("headcount")
                if isinstance(hc, dict) and hc:
                    save_headcount(hc)
                bd = data.get("boss_decisions")
                if isinstance(bd, dict):
                    BOSS_DEC.write_text(json.dumps(bd, ensure_ascii=False, indent=2), encoding="utf-8")
                self._cloud_baseline = True
            except Exception:
                pass

    def _after_cloud_sync(self):
        """雲端資料寫回本機後，重繪受影響分頁。"""
        self._sig_pending = None  # 逼 render_pending 重畫
        for fn in (self.render_pending, self.render_dashboard, self.render_departments,
                   self._refresh_hr, self.refresh_directives):
            try:
                fn()
            except Exception:
                pass

    # ---------- Tab: 部門總覽 ----------
    def tab_departments(self, nb):
        f = self._scroll_tab(nb, "🏢 部門")

        toprow = tk.Frame(f, bg=NAVY); toprow.pack(fill="x", padx=16, pady=(14, 4))
        self.dept_summary = tk.Label(toprow, text="", font=FONT_B, bg=NAVY, fg=ACCENT, justify="left")
        self.dept_summary.pack(side="left")
        tk.Button(toprow, text="🔄 重新整理", font=FONT, bg=CARD, fg=TEXTCOL, bd=0, padx=12, pady=4,
                  command=self.render_departments).pack(side="right")
        # 一鍵設定每日產量（直接設 ②Shorts／①長片，立即同步雲端）
        outrow = tk.Frame(f, bg=NAVY); outrow.pack(fill="x", padx=16, pady=(0, 4))
        tk.Button(outrow, text="🎬 一鍵設定每日產量", font=FONT_B, bg="#1f5f7a", fg="#eaf6ff", bd=0,
                  padx=12, pady=5, activebackground="#2f7f9a", command=self.set_daily_output).pack(side="left")
        self.output_lbl = tk.Label(outrow, text="", font=("Microsoft JhengHei", 10), bg=NAVY, fg=ACCENT)
        self.output_lbl.pack(side="left", padx=10)

        # 一鍵激活 / 一鍵壓榨 / 一鍵最大化壓榨（全公司）
        allrow = tk.Frame(f, bg=NAVY); allrow.pack(fill="x", padx=16, pady=(0, 2))
        tk.Button(allrow, text="⚡ 一鍵激活全部（雲端跑一輪）", font=FONT_B, bg="#1f6f43", fg="#eafff1", bd=0,
                  padx=12, pady=4, activebackground=GREEN, command=self.activate_all).pack(side="left", padx=(0, 6))
        tk.Button(allrow, text="🔥 一鍵壓榨（全部 +1）", font=FONT, bg="#7a2f2f", fg="#ffeaea", bd=0,
                  padx=12, pady=4, activebackground=RED, command=self.squeeze_all).pack(side="left", padx=(0, 6))
        tk.Button(allrow, text="🔥🔥 一鍵最大化壓榨（火力全開）", font=FONT_B, bg="#a01f1f", fg="#fff0f0", bd=0,
                  padx=12, pady=4, activebackground="#ff5050", command=self.max_squeeze_all).pack(side="left")

        # 表頭
        hdr = tk.Frame(f, bg=NAVY); hdr.pack(fill="x", padx=16, pady=(8, 2))
        for txt, w, anc in [("部門", 18, "w"), ("員額", 5, "center"), ("狀態", 20, "w"), ("操作", 16, "w")]:
            tk.Label(hdr, text=txt, font=("Microsoft JhengHei", 10, "bold"), bg=NAVY, fg=SUB,
                     width=w, anchor=anc).pack(side="left", padx=2)

        self.dept_rows = {}
        self.dept_head_lbls = {}
        hc = load_headcount()
        body = tk.Frame(f, bg=NAVY); body.pack(fill="both", expand=True, padx=16)
        for i, d in enumerate(DEPTS):
            bgc = CARD if i % 2 == 0 else "#16223d"
            r = tk.Frame(body, bg=bgc); r.pack(fill="x", pady=1)
            tk.Label(r, text=f"{d['tag']}{d['name']}", font=("Microsoft JhengHei", 11, "bold"), bg=bgc, fg=TEXTCOL,
                     width=18, anchor="w").pack(side="left", padx=(4, 0), pady=5)
            hl = tk.Label(r, text=f"{hc.get(d['tag'], d['head'])} 人", font=FONT, bg=bgc, fg=ACCENT,
                          width=5, anchor="center")
            hl.pack(side="left", padx=2)
            self.dept_head_lbls[d["tag"]] = hl
            stat = tk.Label(r, text="—", font=("Microsoft JhengHei", 10), bg=bgc, fg=TEXTCOL,
                            width=20, anchor="w")
            stat.pack(side="left", padx=2)
            tk.Button(r, text="⚡激活", font=("Microsoft JhengHei", 9), bg="#1f6f43", fg="#eafff1", bd=0,
                      padx=6, pady=3, activebackground=GREEN,
                      command=lambda dd=d: self.activate_dept(dd)).pack(side="left", padx=(6, 2))
            tk.Button(r, text="🔥壓榨", font=("Microsoft JhengHei", 9), bg="#7a2f2f", fg="#ffeaea", bd=0,
                      padx=6, pady=3, activebackground=RED,
                      command=lambda dd=d: self.squeeze_dept(dd)).pack(side="left", padx=2)
            tk.Button(r, text="🔥🔥最大化", font=("Microsoft JhengHei", 9), bg="#a01f1f", fg="#fff0f0", bd=0,
                      padx=6, pady=3, activebackground="#ff5050",
                      command=lambda dd=d: self.max_squeeze_dept(dd)).pack(side="left", padx=2)
            self.dept_rows[d["tag"]] = stat

        tk.Label(f, text="⚡激活＝立刻叫該部門跑一次　🔥壓榨＝下加碼令，叫它長期多產出（決策部門會讀）。"
                         "員額＝AI 代理數非真人；「規劃中」為章程已列、尚未自動化的部門。",
                 font=("Microsoft JhengHei", 9), bg=NAVY, fg=SUB, justify="left", wraplength=1000).pack(anchor="w", padx=18, pady=(8, 6))
        self.render_departments()

    def render_departments(self):
        """依真實檔案訊號更新各部門狀態（誠實：未自動化的不假裝運轉）。"""
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        paused = load_directives().get("paused", False)

        # 線上時：部門出勤以『雲端』真實報告為準（出國後本機沒跑，不該誤顯示未產出）
        cloud = self._cloud if (getattr(self, "_cloud_state", "") == "online" and self._cloud) else None
        cloud_today = set(cloud.get("dept_reports_today", [])) if cloud else None

        def rep(suffix):
            if cloud_today is not None:
                return suffix in cloud_today
            return (REPORTS / f"{today}_{suffix}.md").exists()

        def out_today(prefix):
            if cloud is not None:
                return cloud.get("produced_today", 0) > 0
            try:
                return any(datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d") == today
                           for p in OUT.glob(f"{prefix}*.mp4"))
            except Exception:
                return False

        has_orders = (STUDIO / "production_orders.json").exists()
        subs = self.stats.get("subs")
        running = 0
        GR, SUBC, YEL = GREEN, SUB, ACCENT

        def setrow(tag, text, color):
            w = self.dept_rows.get(tag)
            if w:
                w.config(text=text, fg=color)

        for d in DEPTS:
            k, tag = d["kind"], d["tag"]
            if k == "long":
                ok = out_today("L_")
                setrow(tag, "✅ 今日已產出" if ok else ("⏸ 暫停" if paused else "🕒 排程 06:07 待產"),
                       GR if ok else (RED if paused else SUBC)); running += ok or (not paused)
            elif k == "shorts":
                ok = out_today("S_")
                setrow(tag, "✅ 今日已產出" if ok else ("⏸ 暫停" if paused else "🕒 排程 06:07 待產"),
                       GR if ok else (RED if paused else SUBC)); running += ok or (not paused)
            elif k == "idea":
                setrow(tag, "✅ 題庫指令已就緒" if has_orders else "🕒 待決策部門產出",
                       GR if has_orders else SUBC); running += has_orders
            elif k == "seo":
                ok = rep("流量洞察")
                setrow(tag, "✅ 今日已分析流量數據選題" if ok else "🟢 數據選題待命（05:35）", GR); running += 1
            elif k == "data":
                if isinstance(subs, int):
                    setrow(tag, f"✅ 已連線・訂閱 {subs}", GR); running += 1
                else:
                    setrow(tag, "🕒 待連線 YouTube", SUBC)
            elif k == "audit":
                done = rep("自動上架")
                setrow(tag, "✅ 把關中・今日已上架" if done else "🟢 發布前自動把關中",
                       GR); running += 1
            elif k == "manage":
                ok = rep("營運匯報")
                setrow(tag, "✅ 今日已匯報" if ok else "🕒 待 09 點後彙整",
                       GR if ok else SUBC); running += ok
            elif k == "decision":
                ok = rep("決策")
                setrow(tag, "✅ 今日已決策" if ok else ("⏸ 暫停" if paused else "🕒 排程 05:37"),
                       GR if ok else (RED if paused else SUBC)); running += ok or (not paused)
            elif k == "retro":
                ok = rep("回顧檢討")
                setrow(tag, "✅ 今日已自省" if ok else "🕒 待每輪後自省",
                       GR if ok else SUBC); running += ok
            elif k == "hr":
                ok = rep("人事監察")
                setrow(tag, "✅ 今日已監察" if ok else "🟢 監察+編制待命",
                       GR if ok else GR); running += 1
            elif k == "finance":
                fin = STUDIO / "finance.json"
                net = None
                if fin.exists():
                    try:
                        net = (json.loads(fin.read_text(encoding="utf-8")).get("summary") or {}).get("net")
                    except Exception:
                        net = None
                setrow(tag, (f"✅ 淨利 NT${net:.0f}" if isinstance(net, (int, float)) else "🟢 待記帳/出報告"),
                       GR); running += 1
            elif k == "organize":
                ok = rep("頻道整理"); setrow(tag, "✅ 今日已歸類" if ok else "🟢 待整理播放清單", GR); running += 1
            elif k == "promo":
                ok = rep("宣傳文案"); setrow(tag, "✅ 今日已產文案" if ok else "🟢 待產導流文案", GR); running += 1
            elif k == "comment":
                ok = rep("留言回覆草稿"); setrow(tag, "✅ 今日已擬回覆" if ok else "🟢 待擬留言回覆", GR); running += 1
            elif k == "thumb":
                ok = rep("縮圖CTR"); setrow(tag, "✅ 今日已分析" if ok else "🟢 待縮圖/CTR 分析", GR); running += 1
            elif k == "intel":
                ok = rep("競品情報"); setrow(tag, "✅ 今日已掃描" if ok else "🟢 待掃描競品", GR); running += 1
            elif k == "design":
                has_ds = (STUDIO / "design_system.json").exists()
                setrow(tag, "✅ 品牌設計系統運作中（每片套用）" if has_ds else "🟢 待設定品牌設計",
                       GR if has_ds else SUBC); running += has_ds
            elif k == "news":
                setrow(tag, "✅ 每2h掃時事・有大事自動產+即時發", GR); running += 1
            else:  # 後備（理論上不會到）
                setrow(tag, "🔧 規劃中・尚未自動化", SUBC)

        # 員額即時刷新（人事部調整後馬上反映）
        hc = load_headcount()
        for tag, lbl in getattr(self, "dept_head_lbls", {}).items():
            try:
                lbl.config(text=f"{hc.get(tag, 0)} 人")
            except Exception:
                pass
        try:
            self.output_lbl.config(
                text=f"目前每日產量：Shorts {hc.get('②', 0)} 支 ・ 長片 {hc.get('①', 0)} 支")
        except Exception:
            pass
        total = sum(v for v in hc.values() if isinstance(v, int))
        state = "⏸ 已暫停" if paused else "▶ 自動運轉中"
        self.dept_summary.config(
            text=f"🏢 量化阿森工作室 ・ {len(DEPTS)} 個部門 ・ 編制 {total} 人 ・ {running} 個運作中 ・ {state}")

    def _append_directive(self, text):
        """把一條指令寫進 boss_directives（決策部門會讀）。"""
        self.d = load_directives()
        self.d.setdefault("directives", []).append(text)
        save_directives(self.d)
        self._sig_dir = None  # 逼 auto_tick 重畫
        try:
            self.refresh_directives()
        except Exception:
            pass

    def activate_dept(self, d):
        """⚡激活：立刻叫該部門跑一次。預設在『雲端』執行（單一真相＝雲端）；無 cloud.json 才退回本機。"""
        name = f"{d['tag']} {d['name']}"
        act = d.get("act")
        priv = load_directives().get("privacy", "public")
        cloud_acts = {
            "produce_long": ("scripts/produce_batch.py", ["--long", "1", "--shorts", "0", "--target", "60"]),
            "produce_short": ("scripts/produce_batch.py", ["--shorts", "4", "--long", "0", "--target", "60"]),
            "decision": ("scripts/decision_dept.py", []),
            "publish": ("scripts/daily_publish.py", ["--max", "6", "--privacy", priv]),
            "retro": ("scripts/retro_dept.py", []),
            "hr": ("scripts/hr_dept.py", []),
            "finance": ("scripts/finance_dept.py", []),
            "organize": ("scripts/organize_dept.py", []),
            "promo": ("scripts/promo_dept.py", []),
            "comment": ("scripts/comment_dept.py", []),
            "thumb": ("scripts/thumbnail_dept.py", []),
            "intel": ("scripts/intel_dept.py", []),
            "traffic": ("scripts/traffic_dept.py", []),
            "news": ("scripts/news_dept.py", []),
        }
        if act in cloud_acts:
            script, args = cloud_acts[act]
            if self._activate_on_cloud(script, args, name + "・激活"):
                return
            self._goto_control(); self.run_script([script] + args, name + "・激活(本機備援)")
        elif act == "data":
            self.fetch_stats(); self.fetch_cloud()
            messagebox.showinfo("已激活", f"{name} 已重新抓取最新頻道數據與雲端狀態。")
        elif act == "reports":
            try:
                subprocess.Popen(["explorer", str(REPORTS)])
            except Exception:
                pass
            messagebox.showinfo("總監管部門", "已打開《每日營運匯報》資料夾。\n總監管的產出就是每日匯報。")
        elif act == "design":
            ds_path = STUDIO / "design_system.json"
            info = "（尚未設定）"
            try:
                ds = json.loads(ds_path.read_text(encoding="utf-8"))
                font = Path(ds.get("font", "")).name or "系統預設"
                npal = len(ds.get("accent_palette", []))
                info = f"品牌字體：{font}\n配色數：{npal} 組\n品牌：{ds.get('brand','')}"
            except Exception:
                pass
            if messagebox.askyesno("美編部門（品牌視覺）",
                                   f"每支影片都會自動套用品牌設計系統：\n\n{info}\n\n"
                                   "要打開 design_system.json 編輯（換字體/配色）嗎？\n"
                                   "（字體檔放 assets/fonts/，改完下支影片即生效）"):
                try:
                    subprocess.Popen(["notepad", str(ds_path)])
                except Exception:
                    subprocess.Popen(["explorer", str(STUDIO)])
        else:  # todo：章程有列、尚未獨立自動化
            if messagebox.askyesno(name,
                                   "這個部門章程有列、但還沒獨立自動化。\n"
                                   "要我之後幫你把它做成自動運轉嗎？\n"
                                   "（例：自動歸播放清單／自動發社群貼文／自動草擬留言回覆）"):
                self._append_directive(f"【開發需求】把「{name}」做成自動化部門。")
                messagebox.showinfo("已記下", "已記錄你的需求，下次我進來會幫你把這個部門自動化。")

    def _apply_boost(self, d, level, refresh=True):
        """把某部門壓榨強度設到 level（1..MAX_BOOST_LV）。回傳 (name, lv) 或 None（不適用）。"""
        boost = d.get("boost")
        if not boost:
            return None
        name = f"{d['tag']} {d['name']}"
        self.d = load_directives()
        lvmap = self.d.setdefault("boost", {})
        lv = max(1, min(MAX_BOOST_LV, int(level)))
        lvmap[name] = lv
        ds = [x for x in self.d.get("directives", []) if not x.startswith(f"【壓榨令｜{d['tag']}")]
        suffix = "・最大化" if lv >= MAX_BOOST_LV else ""
        ds.append(f"【壓榨令｜{d['tag']}】{boost}（強度 Lv{lv}{suffix}）")
        self.d["directives"] = ds
        save_directives(self.d)
        self._sig_dir = None
        if refresh:
            try:
                self.refresh_directives()
            except Exception:
                pass
        return (name, lv)

    def squeeze_dept(self, d):
        """🔥 再壓榨：該部門壓榨強度 +1。"""
        name = f"{d['tag']} {d['name']}"
        if not d.get("boost"):
            messagebox.showinfo(name, "這個部門不適用壓榨（唯讀/無產能調節）。\n先用 ⚡激活。")
            return
        cur = load_directives().get("boost", {}).get(name, 0)
        res = self._apply_boost(d, cur + 1)
        if res:
            self._cloud_apply(["boss_directives.json"], self._trig_decision(), f"壓榨 {res[0]}")
            messagebox.showinfo("🔥 已壓榨", f"{res[0]} 壓榨強度 Lv{res[1]}（上限 {MAX_BOOST_LV}）。\n已推送雲端、決策部門立即加碼。")

    def max_squeeze_dept(self, d):
        """🔥🔥 最大化壓榨：該部門直接拉到最大強度。"""
        name = f"{d['tag']} {d['name']}"
        if not d.get("boost"):
            messagebox.showinfo(name, "這個部門不適用壓榨（唯讀/無產能調節）。")
            return
        res = self._apply_boost(d, MAX_BOOST_LV)
        if res:
            self._cloud_apply(["boss_directives.json"], self._trig_decision(), f"最大化壓榨 {res[0]}")
            messagebox.showinfo("🔥🔥 最大化壓榨", f"{res[0]} 已拉到最大 Lv{res[1]}！已推送雲端、立即火力全開。")

    def squeeze_all(self):
        """🔥 一鍵壓榨：所有可壓榨部門強度 +1。"""
        if not messagebox.askyesno("🔥 一鍵壓榨", "對全公司所有部門 +1 壓榨強度？\n（決策部門明早會全面加碼）"):
            return
        n = 0
        for d in DEPTS:
            if d.get("boost"):
                cur = load_directives().get("boost", {}).get(f"{d['tag']} {d['name']}", 0)
                if self._apply_boost(d, cur + 1, refresh=False):
                    n += 1
        try:
            self.refresh_directives()
        except Exception:
            pass
        self._cloud_apply(["boss_directives.json"], self._trig_decision(), "一鍵壓榨全公司")
        messagebox.showinfo("🔥 一鍵壓榨完成", f"已對 {n} 個部門 +1 壓榨，並推送雲端立即加碼。")

    def max_squeeze_all(self):
        """🔥🔥 一鍵最大化壓榨：所有可壓榨部門拉到最大。"""
        if not messagebox.askyesno("🔥🔥 一鍵最大化壓榨",
                                   f"把全公司所有部門壓榨強度拉到最大（Lv{MAX_BOOST_LV}）？\n⚠️ 火力全開、全力衝刺模式。"):
            return
        n = 0
        for d in DEPTS:
            if d.get("boost"):
                if self._apply_boost(d, MAX_BOOST_LV, refresh=False):
                    n += 1
        try:
            self.refresh_directives()
        except Exception:
            pass
        self._cloud_apply(["boss_directives.json"], self._trig_decision(), "一鍵最大化壓榨")
        messagebox.showinfo("🔥🔥 火力全開", f"已把 {n} 個部門全部拉到最大 Lv{MAX_BOOST_LV}！\n已推送雲端、全公司立即最大化衝刺。")

    def set_daily_output(self):
        """🎬 一鍵設定每日產量：直接設 ②Shorts／①長片 → 存檔 → 推雲端 → 立即依此製作。"""
        hc = load_headcount()
        s = simpledialog.askinteger("🎬 每日產量", "每天做幾支 Shorts？（衝量主力）",
                                    parent=self, minvalue=0, maxvalue=40, initialvalue=int(hc.get("②", 0)))
        if s is None:
            return
        l = simpledialog.askinteger("🎬 每日產量", "每天做幾支長片？\n（長片渲染慢、每支約 30–60 分；不做就填 0）",
                                    parent=self, minvalue=0, maxvalue=5, initialvalue=int(hc.get("①", 0)))
        if l is None:
            l = int(hc.get("①", 0))
        hc["②"], hc["①"] = s, l
        save_headcount(hc)
        try:
            self._refresh_hr(); self.render_departments()
        except Exception:
            pass
        pushed = self._cloud_apply(["headcount.json"], self._trig_produce(s, l), "設定每日產量")
        warn = "\n⚠ YouTube 每天上架上限約 6 支，多的會進庫存囤著。" if (s + l) > 6 else ""
        messagebox.showinfo("✅ 已設定每日產量",
                            f"Shorts {s} 支／天　・　長片 {l} 支／天。\n"
                            + ("已推送雲端，明早起每天依此製作。" if pushed else "已存本機（未連雲端）。") + warn)

    # 後勤各部門「需求權重」與理由（成長階段：流量/分發/CTR/選題加重；維護性精簡）。
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

    def _confirm_scroll(self, title, body, ok_text="確定"):
        """可捲動的確認對話框，回傳 True/False。"""
        dlg = tk.Toplevel(self); dlg.title(title); dlg.configure(bg=NAVY); dlg.geometry("660x540")
        dlg.transient(self); dlg.grab_set()
        txt = scrolledtext.ScrolledText(dlg, font=("Microsoft JhengHei", 10), wrap="word",
                                        bg="#0a1020", fg=TEXTCOL, bd=0, padx=12, pady=10)
        txt.pack(fill="both", expand=True, padx=12, pady=12)
        txt.insert("1.0", body); txt.config(state="disabled")
        result = {"ok": False}
        row = tk.Frame(dlg, bg=NAVY); row.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(row, text=ok_text, font=FONT_B, bg=ACCENT, fg=NAVY, bd=0, padx=16, pady=6,
                  command=lambda: (result.update(ok=True), dlg.destroy())).pack(side="right", padx=6)
        tk.Button(row, text="取消", font=FONT, bg=CARD, fg=TEXTCOL, bd=0, padx=16, pady=6,
                  command=dlg.destroy).pack(side="right")
        dlg.wait_window()
        return result["ok"]

    def rebalance_headcount(self):
        """🧑‍🤝‍🧑 一鍵調整員額分配：依現有總員額＋各部門需求，給出每部門增減建議，確認後套用＋推雲端。"""
        name = {d["tag"]: d["name"] for d in DEPTS}
        hc = load_headcount()
        # 從 DEPTS 動態取後勤部門（①②為製作量、另用設定每日產量）→ 未來新增部門自動納入，不會漏
        support = [d["tag"] for d in DEPTS if d["tag"] not in ("①", "②")]

        def need(t):
            return self._NEED.get(t, (1, "編制容量"))  # 未列在權重表的新部門給預設

        total = sum(int(hc.get(t, 0)) for t in support)
        if total <= 0:
            total = sum(need(t)[0] for t in support) * 2  # 沒員額就用權重種基底
        sw = sum(need(t)[0] for t in support)
        raw = {t: total * need(t)[0] / sw for t in support}
        alloc = {t: int(raw[t]) for t in support}
        rem = total - sum(alloc.values())
        for t in sorted(support, key=lambda x: raw[x] - int(raw[x]), reverse=True)[:rem]:
            alloc[t] += 1
        lines = [f"依現有後勤總員額 {total} 人、各部門需求重新分配（成長階段：流量/分發/CTR/選題加重）：", ""]
        for t in support:
            old = int(hc.get(t, 0)); new = alloc[t]; d = new - old
            sign = f"＋{d}" if d > 0 else (f"－{abs(d)}" if d < 0 else "±0")
            lines.append(f"{t} {name.get(t, t)}　{old} → {new}　({sign})\n      理由：{need(t)[1]}")
        lines += ["", "※ 製作量 ①長片/②Shorts 不在此調整（請用「🎬 一鍵設定每日產量」）。",
                  "※ 按「套用」會把後勤員額改成上面的建議值並推送雲端。"]
        if self._confirm_scroll("🧑‍🤝‍🧑 員額分配建議（依需求）", "\n".join(lines), "套用這個分配"):
            for t in support:
                hc[t] = alloc[t]
            save_headcount(hc)
            try:
                self._refresh_hr(); self.render_departments()
            except Exception:
                pass
            self._cloud_apply(["headcount.json"], None, "調整員額分配")
            messagebox.showinfo("✅ 已套用", "員額已依需求重新分配並推送雲端。製作量①②不受影響。")

    def activate_all(self):
        """⚡ 一鍵激活全部：叫全公司每個部門在雲端各跑一次（背景）。"""
        if not messagebox.askyesno("⚡ 一鍵激活全部",
                                   "立刻叫全公司所有部門在雲端各跑一次？\n"
                                   "（情報→決策→補產→上架→整理→宣傳→留言→縮圖→財務→回顧→人事）\n"
                                   "背景進行，可在『☁ 雲端營運』看輸出。"):
            return
        cfg = load_cloud_cfg()
        priv = load_directives().get("privacy", "public")
        if not cfg:
            self._goto_control()
            for script, args, nm in [("scripts/intel_dept.py", [], "競品"),
                                     ("scripts/decision_dept.py", [], "決策"),
                                     ("scripts/produce_batch.py", ["--target", "60"], "補產"),
                                     ("scripts/daily_publish.py", ["--max", "6", "--privacy", priv], "上架"),
                                     ("scripts/retro_dept.py", [], "回顧"), ("scripts/hr_dept.py", [], "人事")]:
                self.run_script([script] + args, nm + "(本機)")
            return
        self._nb.select(self._cloud_frame)
        chain = ("./run.sh scripts/intel_dept.py; ./run.sh scripts/decision_dept.py; "
                 "./run.sh scripts/produce_batch.py --target 60; "
                 f"./run.sh scripts/daily_publish.py --max 6 --privacy {priv}; "
                 "./run.sh scripts/organize_dept.py; ./run.sh scripts/promo_dept.py; "
                 "./run.sh scripts/comment_dept.py; ./run.sh scripts/thumbnail_dept.py; "
                 "./run.sh scripts/finance_dept.py; ./run.sh scripts/retro_dept.py; ./run.sh scripts/hr_dept.py")
        self._cloud_stream(
            f"cd {cfg['remote_root']} && nohup bash -c '{chain}' > logs/activate_all.log 2>&1 & "
            "echo '已在雲端背景啟動：全部門各跑一次（看 logs/activate_all.log）'",
            "一鍵激活全部")

    # ---------- Tab: 人事部（監察 + 編制） ----------
    # 員額有真實作用：①②的員額 = 每日產出量（produce_batch 讀 headcount.json）。
    HEAD_REAL = {"①": "每日長片數", "②": "每日 Shorts 數"}

    def tab_hr(self, nb):
        f = self._scroll_tab(nb, "🧑‍💼 人事部")

        top = tk.Frame(f, bg=NAVY); top.pack(fill="x", padx=16, pady=(14, 2))
        self.hr_summary = tk.Label(top, text="", font=FONT_B, bg=NAVY, fg=ACCENT)
        self.hr_summary.pack(side="left")
        tk.Button(top, text="🔄 重新整理", font=FONT, bg=CARD, fg=TEXTCOL, bd=0, padx=12, pady=4,
                  command=self._refresh_hr).pack(side="right")
        tk.Button(top, text="🧑‍🤝‍🧑 一鍵調整員額分配", font=FONT_B, bg="#5a3f7a", fg="#f0e8ff", bd=0, padx=12, pady=4,
                  activebackground="#7a5f9a", command=self.rebalance_headcount).pack(side="right", padx=6)
        tk.Button(top, text="🚀 自動擴編", font=FONT_B, bg="#1f6f43", fg="#eafff1", bd=0, padx=12, pady=4,
                  activebackground=GREEN, command=self.auto_expand).pack(side="right", padx=6)

        # 區塊 A：編制管理（招募 / 分配員額）
        tk.Label(f, text="① 編制管理（招募 / 分配員額 → 擴大公司）", font=FONT_B, bg=NAVY, fg=GREEN).pack(anchor="w", padx=16, pady=(10, 2))
        tk.Label(f, text="員額＝AI 代理數。①影片／②Shorts 的員額會『真的』決定每日產出量（加員額＝加產能）；其餘為編制容量。",
                 font=("Microsoft JhengHei", 9), bg=NAVY, fg=SUB, wraplength=1000, justify="left").pack(anchor="w", padx=18)
        grid = tk.Frame(f, bg=NAVY); grid.pack(fill="x", padx=16, pady=(4, 2))
        self.hr_head_lbls = {}
        hc = load_headcount()
        for i, d in enumerate(DEPTS):
            col = i % 2
            if col == 0:
                rowf = tk.Frame(grid, bg=NAVY); rowf.pack(fill="x")
            cell = tk.Frame(rowf, bg=CARD); cell.pack(side="left", expand=True, fill="x", padx=3, pady=2)
            tk.Label(cell, text=f"{d['tag']}{d['name']}", font=("Microsoft JhengHei", 10, "bold"), bg=CARD, fg=TEXTCOL,
                     width=16, anchor="w").pack(side="left", padx=(8, 2), pady=4)
            tk.Button(cell, text="➖", font=("Microsoft JhengHei", 10, "bold"), bg="#3a2330", fg="#ffd0d0", bd=0,
                      width=2, command=lambda t=d["tag"]: self.adjust_headcount(t, -1)).pack(side="left", padx=1)
            hl = tk.Label(cell, text=f"{hc.get(d['tag'], 0)}", font=FONT_B, bg=CARD, fg=ACCENT, width=3, anchor="center")
            hl.pack(side="left")
            self.hr_head_lbls[d["tag"]] = hl
            tk.Button(cell, text="➕招募", font=("Microsoft JhengHei", 9, "bold"), bg="#1f6f43", fg="#eafff1", bd=0,
                      command=lambda t=d["tag"]: self.adjust_headcount(t, +1)).pack(side="left", padx=(1, 8))

        # 區塊 B：部門監察（出勤 / 健康）
        tk.Label(f, text="② 部門監察（出勤 / 考核 / 健康）", font=FONT_B, bg=NAVY, fg=GREEN).pack(anchor="w", padx=16, pady=(12, 2))
        self.hr_box = scrolledtext.ScrolledText(f, height=11, font=("Microsoft JhengHei", 10), wrap="word",
                                                bg="#0a1020", fg=TEXTCOL, bd=0, padx=12, pady=10)
        self.hr_box.pack(fill="both", expand=True, padx=16, pady=(2, 6))
        rowb = tk.Frame(f, bg=NAVY); rowb.pack(fill="x", padx=16, pady=(0, 10))
        tk.Button(rowb, text="🧑‍💼 立即跑人事監察（產報告）", font=FONT, bg=ACCENT, fg=NAVY, bd=0,
                  command=lambda: self.activate_dept({"tag": "⑬", "name": "人事部", "act": "hr"})).pack(side="left")
        self._refresh_hr()

    def adjust_headcount(self, tag, delta):
        hc = load_headcount()
        hc[tag] = max(0, int(hc.get(tag, 0)) + delta)
        save_headcount(hc)
        self._refresh_hr()
        try:
            self.render_departments()
        except Exception:
            pass
        # 推送員額到雲端；①影片/②Shorts 變動 = 真產能，立刻在雲端依新員額補產
        trig = None
        if tag in ("①", "②"):
            trig = self._trig_produce(hc.get("②", 0), hc.get("①", 0))
        self._cloud_apply(["headcount.json"], trig, f"員額調整 {tag}")
        if delta > 0 and tag in self.HEAD_REAL:
            messagebox.showinfo("➕ 招募完成",
                                f"{tag} 員額 +1（現 {hc[tag]} 人）。\n已推送雲端，"
                                + ("並立即依新員額在雲端補產。" if tag in ("①", "②") else "下一輪生效。"))

    def auto_expand(self):
        """🚀 自動擴編：老闆輸入這次要新增的總員額 → 自動分配（重押 ①②產能）。"""
        n = simpledialog.askinteger("🚀 自動擴編", "這次擴編要新增幾個員額（總數）？",
                                    parent=self, minvalue=1, maxvalue=300)
        if not n:
            return
        hc = load_headcount()
        tags = [d["tag"] for d in DEPTS]
        # 權重：②Shorts／①影片 是真產能（衝量主力）→ 重押；其餘平均擴容
        weights = {t: 1 for t in tags}
        weights["②"] = 4
        weights["①"] = 3
        total_w = sum(weights.values())
        raw = {t: n * weights[t] / total_w for t in tags}
        alloc = {t: int(raw[t]) for t in tags}
        rem = n - sum(alloc.values())
        for t in sorted(tags, key=lambda x: raw[x] - int(raw[x]), reverse=True)[:rem]:
            alloc[t] += 1
        for t in tags:
            hc[t] = hc.get(t, 0) + alloc[t]
        save_headcount(hc)
        self._refresh_hr()
        try:
            self.render_departments()
        except Exception:
            pass
        self._cloud_apply(["headcount.json"], self._trig_produce(hc.get("②", 0), hc.get("①", 0)), "自動擴編")
        detail = "　".join(f"{t}+{alloc[t]}" for t in tags if alloc[t] > 0)
        messagebox.showinfo("🚀 擴編完成",
                            f"本次新增 {n} 員額，已自動分配（重押 ①②產能）：\n{detail}\n\n"
                            f"總員額現為 {sum(hc.values())} 人。\n①②增加的員額，下一輪補產會直接變成更多影片。")

    def _refresh_hr(self):
        hc = load_headcount()
        for tag, lbl in getattr(self, "hr_head_lbls", {}).items():
            try:
                lbl.config(text=f"{hc.get(tag, 0)}")
            except Exception:
                pass
        total = sum(hc.values())
        base = sum(DEPT_HEAD_DEFAULT.values())
        grow = total - base
        try:
            self.hr_summary.config(text=f"🧑‍💼 總員額 {total} 人（初始 {base}，擴編 {'+' if grow >= 0 else ''}{grow}）・ {len(DEPTS)} 部門")
        except Exception:
            pass
        # 監察文字
        try:
            self.hr_box.delete("1.0", "end")
            self.hr_box.insert("end", self._hr_monitor_text())
        except Exception:
            pass

    def _hr_monitor_text(self):
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        def rep(s):
            return (REPORTS / f"{today}_{s}.md").exists()

        def out_today(prefix):
            try:
                return sum(1 for p in OUT.glob(f"{prefix}*.mp4")
                           if datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d") == today)
            except Exception:
                return 0
        paused = load_directives().get("paused", False)
        L = []
        # 出勤
        L.append("🗓 今日出勤")
        att = [
            ("⑪ 決策", rep("決策")),
            ("①② 補產", (out_today("S_") + out_today("L_")) > 0),
            ("⑨ 審核上架", rep("自動上架")),
            ("⑩ 總監管", rep("營運匯報")),
            ("⑫ 回顧檢討", rep("回顧檢討")),
            ("⑬ 人事監察", rep("人事監察")),
        ]
        for nm, ok in att:
            L.append(f"   {'✅ 已出勤' if ok else ('⏸ 暫停' if paused else '🕒 未出勤')}　{nm}")
        L.append(f"   今日產出：Shorts {out_today('S_')} 支、長片 {out_today('L_')} 支")
        # 健康（掃 ops_log 異常）
        errs = []
        try:
            for ln in OPS.read_text(encoding="utf-8").splitlines()[-80:]:
                if any(k in ln for k in ("⚠️", "FAIL", "失敗", "錯誤", "FATAL")):
                    errs.append(ln.strip())
        except Exception:
            pass
        L.append("")
        L.append("🩺 健康")
        if errs:
            L.append(f"   ⚠ 偵測到 {len(errs)} 條異常（近期）：")
            for e in errs[-4:]:
                L.append(f"     - {e[:70]}")
        else:
            L.append("   ✅ 近期無異常日誌")
        # KPI 考核（讀 ⑬人事部最近一次 hr_status.json）
        try:
            hs = STUDIO / "hr_status.json"
            if hs.exists():
                st = json.loads(hs.read_text(encoding="utf-8"))
                weak = st.get("kpi_weak", [])
                L.append("")
                L.append(f"📋 KPI 考核（對照職掌定義書・{st.get('date','')}）")
                if weak:
                    rows = {r["tag"]: r for r in st.get("rows", [])}
                    L.append(f"   ⚠ 待加強／未達 {len(weak)} 項：")
                    for t in weak:
                        r = rows.get(t, {})
                        L.append(f"     - {t} {r.get('name','')}：{r.get('kpi','')}（{r.get('kpi_note','')}）")
                else:
                    L.append("   ✅ 全部門 KPI 達標（或不適用）")
        except Exception:
            pass
        # 編制建議
        L.append("")
        L.append("🧑‍💼 編制建議")
        unbuilt = [d['tag'] + d['name'] for d in DEPTS if d.get("kind") == "todo"]
        if unbuilt:
            L.append(f"   ・尚未自動化（可擴編開發）：{ '、'.join(unbuilt) }")
        hc = load_headcount()
        if hc.get("②", 0) < 4:
            L.append("   ・②Shorts 員額偏低（衝量主力建議 ≥4）。")
        L.append("   ・加 ①／② 員額＝直接擴大每日產量；其餘部門員額為容量編制。")
        return "\n".join(L)

    # ---------- Tab 1: 匯報 ----------
    # ---------- Tab: 倉庫評分（每部片品質分數＋退件重做） ----------
    def tab_library(self, nb):
        f = tk.Frame(nb, bg=NAVY); nb.add(f, text="🎬 倉庫評分")
        self._section(f, "🎬 倉庫品質評分")
        # 摘要列（卡片）
        sumwrap = tk.Frame(f, bg=BORDER); sumwrap.pack(fill="x", padx=18, pady=(2, 6))
        sumcard = tk.Frame(sumwrap, bg=CARD); sumcard.pack(fill="x", padx=1, pady=1)
        tk.Frame(sumcard, bg=ACCENT, height=3).pack(fill="x")
        self.lib_summary = tk.Label(sumcard, text="載入中…", font=("Microsoft JhengHei", 11, "bold"),
                                    bg=CARD, fg=TEXTCOL, anchor="w", justify="left", padx=14, pady=10)
        self.lib_summary.pack(fill="x")
        # 評分依據與標準（說明卡）
        ewrap = tk.Frame(f, bg=BORDER); ewrap.pack(fill="x", padx=18, pady=(0, 6))
        ecard = tk.Frame(ewrap, bg=PANEL); ecard.pack(fill="x", padx=1, pady=1)
        expl = ("📊 評分依據（總分 0–100 ＝ AI 內容分 − 品管硬傷扣分）\n"
                "　AI 由 Claude 逐支評，四面向各 0–25 分：\n"
                "　　🪝 鉤子｜前 2 秒抓不抓得住　　🎯 標題｜點擊慾／是否套公式\n"
                "　　📚 內容｜紮實・正確・清晰　　🛡 誠信｜不誇大不喊單、有風險意識、不空泛\n"
                "　品管硬傷再扣：禁語 −50、無影音軌 −45、片長過短 −35、檔案過小 −30、缺風險聲明 −12…\n"
                "　門檻：總分 < 你設定的門檻 → 標「⚠️ 建議退件」；可手動或一鍵自動退件重做。")
        tk.Label(ecard, text=expl, font=("Microsoft JhengHei", 9), bg=PANEL, fg=SUB,
                 anchor="w", justify="left", padx=14, pady=10).pack(fill="x")
        # 工具列（門檻 + 動作）
        thr = tk.Frame(f, bg=NAVY); thr.pack(fill="x", padx=18, pady=(4, 6))
        tk.Label(thr, text="退件門檻", font=FONT, bg=NAVY, fg=SUB).pack(side="left")
        self.lib_thresh = tk.IntVar(value=70)
        tk.Spinbox(thr, from_=0, to=100, width=4, textvariable=self.lib_thresh,
                   font=("Microsoft JhengHei", 11, "bold"), justify="center",
                   bg=PANEL, fg=ACCENT, buttonbackground=CARD, bd=0, relief="flat",
                   highlightthickness=1, highlightbackground=BORDER).pack(side="left", padx=(6, 2))
        tk.Label(thr, text="分", font=FONT, bg=NAVY, fg=SUB).pack(side="left", padx=(0, 8))
        self._btn(thr, "✔ 設定門檻", self.lib_set_threshold)
        self._btn(thr, "🔄 重新評分", self.lib_rescore)
        self._btn(thr, "⟳ 重新整理", self.refresh_library_scores)
        self._btn(thr, "🧹 自動退件低分片", self.lib_auto_reject)
        # 只放未發布（囤貨）；已發布另開唯讀分頁，避免誤觸線上影片
        self._section(f, "📦 未發布（倉庫囤貨）— 選中可退件重做")
        self.lib_tree_pending = self._make_lib_zone(f, 11)
        act = tk.Frame(f, bg=NAVY); act.pack(fill="x", padx=18, pady=(6, 2))
        tk.Button(act, text="❌ 退件重做（選中項）", font=FONT_B, bg="#3a1620", fg=RED, bd=0,
                  padx=14, pady=7, activebackground=RED, activeforeground="#fff",
                  command=self.lib_reject_selected).pack(side="left")
        tk.Label(act, text="  退件＝隔離該片＋釋放題目，下輪雲端自動補產新的（只動未發布囤貨）",
                 font=("Microsoft JhengHei", 9), bg=NAVY, fg=SUB).pack(side="left")
        self._section(f, "🔍 品管細項（製作過程＋AI 評分明細）")
        dwrap = tk.Frame(f, bg=BORDER); dwrap.pack(fill="x", padx=18, pady=(2, 14))
        self.lib_detail = scrolledtext.ScrolledText(dwrap, height=6, font=("Microsoft JhengHei", 10), wrap="word",
                                                    bg="#0a1020", fg=TEXTCOL, bd=0, padx=12, pady=10,
                                                    insertbackground=TEXTCOL)
        self.lib_detail.pack(fill="x", padx=1, pady=1)
        self._lib_items = []
        self.refresh_library_scores()

    # ---------- Tab: 已發布（線上影片，唯讀） ----------
    def tab_published(self, nb):
        f = tk.Frame(nb, bg=NAVY); nb.add(f, text="🟢 已發布")
        self._section(f, "🟢 已發布影片（線上，唯讀）")
        tk.Label(f, text="這裡只看不動：已發布影片的品質分數一覽。雙擊任一列開 YouTube。"
                         "要改線上標題用 refresh_library.py、改縮圖用 refresh_thumbnails.py、下架用 set_public.py。",
                 font=("Microsoft JhengHei", 9), bg=NAVY, fg=SUB, justify="left", anchor="w").pack(anchor="w", padx=20, pady=(0, 4))
        bar = tk.Frame(f, bg=NAVY); bar.pack(fill="x", padx=18, pady=(2, 4))
        self.pub_summary = tk.Label(bar, text="—", font=FONT_B, bg=NAVY, fg=ACCENT)
        self.pub_summary.pack(side="left")
        self._btn(bar, "⟳ 重新整理", self.refresh_library_scores)
        self.lib_tree_pub = self._make_lib_zone(f, 14, [
            ("views", "觀看", 70, "center"), ("retention", "留存%", 70, "center"),
            ("subs", "訂閱+", 60, "center"), ("score", "品質", 58, "center"), ("title", "標題", 460, "w")])
        self.lib_tree_pub.bind("<Double-1>", self._pub_open)
        ddwrap = tk.Frame(f, bg=BORDER); ddwrap.pack(fill="x", padx=18, pady=(6, 14))
        self.pub_detail = scrolledtext.ScrolledText(ddwrap, height=5, font=("Microsoft JhengHei", 10), wrap="word",
                                                    bg="#0a1020", fg=TEXTCOL, bd=0, padx=12, pady=10,
                                                    insertbackground=TEXTCOL)
        self.pub_detail.pack(fill="x", padx=1, pady=1)

    def _pub_open(self, _=None):
        slug = self.lib_tree_pub.selection()[0] if self.lib_tree_pub.selection() else None
        it = next((x for x in self._lib_items if x["slug"] == slug), None)
        if it and it.get("videoId"):
            webbrowser.open(f"https://youtu.be/{it['videoId']}")

    def _make_lib_zone(self, parent, height, cols=None):
        """建一個深色清單 Treeview（無內建標題），回傳 tree。cols=[(key,heading,width,anchor)]。"""
        cols = cols or [("score", "分數", 70, "center"), ("status", "狀態", 110, "center"),
                        ("title", "標題", 620, "w")]
        wrap = tk.Frame(parent, bg=BORDER); wrap.pack(fill="both", expand=True, padx=18, pady=2)
        box = tk.Frame(wrap, bg=CARD); box.pack(fill="both", expand=True, padx=1, pady=1)
        tree = ttk.Treeview(box, columns=[c[0] for c in cols], show="headings", height=height, style="Lib.Treeview")
        tree._libcols = [c[0] for c in cols]
        for c, t, w, anc in cols:
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor=anc)
        tree.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set); sb.pack(side="right", fill="y")
        tree.bind("<<TreeviewSelect>>", lambda e, t=tree: self._lib_on_select(t))
        tree.tag_configure("reject", foreground=RED)
        tree.tag_configure("pass", foreground=GREEN)
        tree.tag_configure("odd", background="#142039")
        tree.tag_configure("even", background=CARD)
        return tree

    def _lib_fetch_worker(self, then):
        cfg = load_cloud_cfg()
        local = STUDIO / "quality_scores.json"
        if cfg:
            try:
                _run([str(PY), str(CLOUD_SSH), "get",
                      f"{cfg['remote_root']}/STUDIO/quality_scores.json", str(local)],
                     env=self._cloud_env(cfg), capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=60)
            except Exception:
                pass
        data = {}
        try:
            data = json.loads(local.read_text(encoding="utf-8"))
        except Exception:
            pass
        self.after(0, lambda: then(data))

    def refresh_library_scores(self):
        try:
            self.lib_summary.config(text="⏳ 從雲端抓評分中…")
        except Exception:
            pass
        threading.Thread(target=lambda: self._lib_fetch_worker(self._render_lib), daemon=True).start()

    def _render_lib(self, data):
        pend = data.get("pending", [])
        pub = data.get("published", [])
        self._lib_items = pend + pub
        s = data.get("summary", {})
        mn = data.get("min_score", 70)
        try:
            self.lib_thresh.set(int(mn))
        except Exception:
            pass
        self.lib_summary.config(
            text=f"📦 未發布囤貨 {len(pend)} 支　｜　✅ 通過 {s.get('pass',0)}　｜　⚠️ 建議退件 {s.get('reject',0)}"
                 f"　｜　門檻 {mn} 分　（更新 {data.get('updated','—')}）")
        if hasattr(self, "pub_summary"):
            extra = "" if data.get("has_analytics") else "（成效待 analytics token）"
            self.pub_summary.config(text=f"🟢 已發布 {len(pub)} 支（含長片；唯讀，雙擊開 YouTube）{extra}")
        STAT = {"pass": "✅ 通過", "reject": "⚠️ 建議退件", "rejected_manual": "❌ 已退件", "published": "🟢 已發布"}

        def cell(it, key):
            v = it.get(key)
            if key == "status":
                return STAT.get(v or "pass", v)
            if key == "title":
                return (v or "")[:64]
            if v is None:
                return "—"
            if key == "views":
                return f"{int(v):,}"
            if key == "retention":
                return f"{v:g}%"
            if key == "subs":
                return f"+{int(v)}" if v else "0"
            return v

        def fill(tree, rows):
            keys = getattr(tree, "_libcols", ["score", "status", "title"])
            for r in tree.get_children():
                tree.delete(r)
            for idx, it in enumerate(rows):
                st = it.get("status", "pass")
                tag = "pass" if st in ("pass", "published") else "reject"
                tree.insert("", "end", iid=it["slug"],
                            values=tuple(cell(it, k) for k in keys),
                            tags=("odd" if idx % 2 else "even", tag))
        fill(self.lib_tree_pending, pend)
        if hasattr(self, "lib_tree_pub"):
            fill(self.lib_tree_pub, pub)
        self.lib_detail.delete("1.0", "end")
        if not pend:
            self.lib_detail.insert("1.0", "未發布囤貨目前 0 支（都發布或都退件了）。按「🔄 重新評分」可在雲端重跑品管。")

    def _lib_on_select(self, tree):
        widget = self.pub_detail if (hasattr(self, "lib_tree_pub") and tree is self.lib_tree_pub) else self.lib_detail
        if tree.selection():
            self._render_detail(tree.selection()[0], widget)

    def _render_detail(self, slug, widget):
        it = next((x for x in self._lib_items if x["slug"] == slug), None)
        if not it:
            return
        widget.delete("1.0", "end")
        sc = it.get("score")
        lines = [f"標題：{it.get('title','')}",
                 f"總分：{'—（無本機腳本可評，如手動發布的長片）' if sc is None else sc}　"
                 f"{'已發布' if it.get('published') else '未發布（倉庫囤貨）'}"]
        if it.get("published"):
            v = it.get("views"); rt = it.get("retention"); sb = it.get("subs"); dur = it.get("avg_dur")
            perf = []
            perf.append(f"👁 觀看 {int(v):,}" if v is not None else "👁 觀看 —")
            perf.append(f"⏱ 留存 {rt:g}%" if rt is not None else "⏱ 留存 —")
            perf.append(f"⏳ 均看 {int(dur)}秒" if dur is not None else "⏳ 均看 —")
            perf.append(f"🔔 訂閱 +{int(sb)}" if sb is not None else "🔔 訂閱 —")
            lines.append("近 180 天成效：" + "　".join(perf) + "（YouTube Analytics；CTR 為 Studio 限定、API 不提供）")
        ai = it.get("ai") or {}
        if ai:
            lines.append(f"AI 內容評分（各 25）：🪝 鉤子 {ai.get('hook','?')}　🎯 標題 {ai.get('title','?')}　"
                         f"📚 內容 {ai.get('content','?')}　🛡 誠信 {ai.get('honesty','?')}")
            if ai.get("note"):
                lines.append(f"💡 最該改：{ai['note']}")
        rs = it.get("reasons", [])
        if rs:
            lines.append("⚠ 品管硬傷扣分：" + "、".join(rs))
        if it.get("videoId"):
            lines.append(f"YouTube：https://youtu.be/{it['videoId']}")
        widget.insert("1.0", "\n".join(lines))

    def _lib_cloud_then_refresh(self, args, name):
        """雲端跑 quality_score.py（阻塞等完成）後刷新清單；無雲端則本機跑。"""
        cfg = load_cloud_cfg()

        def worker():
            try:
                if cfg:
                    _run([str(PY), str(CLOUD_SSH), "run",
                          f"cd {cfg['remote_root']} && ./run.sh scripts/quality_score.py {' '.join(args)}"],
                         env=self._cloud_env(cfg), capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=180)
                else:
                    _run([str(PY), "scripts/quality_score.py"] + args, cwd=str(ROOT),
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            except Exception:
                pass
            self.after(0, self.refresh_library_scores)
        try:
            self.lib_summary.config(text=f"⏳ {name}…")
        except Exception:
            pass
        threading.Thread(target=worker, daemon=True).start()

    def lib_set_threshold(self):
        n = int(self.lib_thresh.get())
        self._lib_cloud_then_refresh(["--set-min", str(n)], f"設定門檻 {n} 分")

    def lib_rescore(self):
        self._lib_cloud_then_refresh([], "雲端重新評分")

    def lib_auto_reject(self):
        if not messagebox.askyesno("自動退件", "把所有『未發布且低於門檻』的片自動退件重做？\n（已發布的不動）"):
            return
        self._lib_cloud_then_refresh(["--auto-reject"], "自動退件低分片")

    def lib_reject_selected(self):
        sel = self.lib_tree_pending.selection()
        if not sel:
            messagebox.showinfo("退件重做", "請先在「📦 未發布」清單點選一支片。\n（已發布影片在另一個分頁，唯讀不退件）")
            return
        slug = sel[0]
        it = next((x for x in self._lib_items if x["slug"] == slug), None)
        title = (it or {}).get("title", slug)
        if not messagebox.askyesno("退件重做", f"確定退件重做這支未發布片？\n\n{title}\n\n"
                                   "（隔離該片＋釋放題目，下輪雲端自動補產新的）"):
            return
        self._lib_cloud_then_refresh(["--reject", slug], f"退件重做 {title[:18]}")

    def tab_reports(self, nb):
        f = tk.Frame(nb, bg=NAVY)
        nb.add(f, text="📋 每日匯報")
        left = tk.Frame(f, bg=NAVY); left.pack(side="left", fill="y", padx=(0, 8), pady=8)
        tk.Label(left, text="選擇匯報", font=FONT_B, bg=NAVY, fg=TEXTCOL).pack(anchor="w")
        self.rep_list = tk.Listbox(left, width=30, height=16, font=("Microsoft JhengHei", 10),
                                   bg=CARD, fg=TEXTCOL, selectbackground=ACCENT, selectforeground=NAVY, bd=0)
        self.rep_list.pack(fill="y", expand=True, pady=6)
        self.rep_list.bind("<<ListboxSelect>>", self.show_report)
        tk.Button(left, text="🔄 從雲端重新整理", font=FONT, command=self.refresh_reports, bg=CARD, fg=TEXTCOL, bd=0).pack(fill="x")
        self.rep_sync_lbl = tk.Label(left, text="", font=("Microsoft JhengHei", 9), bg=NAVY, fg=SUB)
        self.rep_sync_lbl.pack(anchor="w", pady=(4, 0))
        self.rep_text = scrolledtext.ScrolledText(f, font=("Microsoft JhengHei", 11), wrap="word",
                                                  bg="#0a1020", fg=TEXTCOL, bd=0, padx=14, pady=12)
        self.rep_text.pack(side="left", fill="both", expand=True, pady=8)
        self.load_reports()
        self.refresh_reports()  # 開頁即從雲端抓最新報告

    def refresh_reports(self):
        """從雲端把 REPORTS 同步回本機後重新列出（報告是在雲端產生的）。"""
        try:
            self.rep_sync_lbl.config(text="⏳ 從雲端抓報告中…")
        except Exception:
            pass
        self._pull_cloud_reports(then=self._after_reports_pull)

    def _after_reports_pull(self):
        try:
            self.rep_sync_lbl.config(text="✅ 已同步雲端報告")
        except Exception:
            pass
        self.load_reports()

    def _pull_cloud_reports(self, then=None):
        """雲端打包 REPORTS → 抓回本機 → 解壓到 STUDIO/（背景執行緒）。"""
        cfg = load_cloud_cfg()
        if not cfg:
            if then:
                then()
            return

        def worker():
            try:
                import tarfile
                _run([str(PY), str(CLOUD_SSH), "run",
                                f"cd {cfg['remote_root']}/STUDIO && tar czf /tmp/reports.tgz REPORTS 2>/dev/null; echo ok"],
                               env=self._cloud_env(cfg), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=45)
                tmp = str(STUDIO / "_reports_pull.tgz")
                _run([str(PY), str(CLOUD_SSH), "get", "/tmp/reports.tgz", tmp],
                               env=self._cloud_env(cfg), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=90)
                with tarfile.open(tmp) as t:
                    t.extractall(str(STUDIO))
                os.remove(tmp)
            except Exception:
                pass
            if then:
                self.after(0, then)
        threading.Thread(target=worker, daemon=True).start()

    def load_reports(self):
        self.rep_list.delete(0, "end")
        self._reps = []
        if REPORTS.exists():
            for p in sorted(REPORTS.glob("*.md"), reverse=True):
                self._reps.append(p)
                self.rep_list.insert("end", p.stem)
        if self._reps:
            self.rep_list.selection_set(0)
            self.show_report()

    def show_report(self, _=None):
        sel = self.rep_list.curselection()
        if not sel:
            return
        p = self._reps[sel[0]]
        self.rep_text.delete("1.0", "end")
        try:
            self.rep_text.insert("1.0", p.read_text(encoding="utf-8"))
        except Exception as e:
            self.rep_text.insert("1.0", f"讀取失敗：{e}")

    # ---------- Tab 2: 我的決策 ----------
    def tab_decisions(self, nb):
        f = self._scroll_tab(nb, "🧠 我的決策")  # 整頁可捲動，待拍板再多也滑得到
        pad = {"padx": 16, "pady": 6}

        toprow = tk.Frame(f, bg=NAVY); toprow.pack(fill="x", padx=16, pady=(12, 2))
        tk.Label(toprow, text="📌 待你拍板的決策（決策部門提出，點選項即生效）", font=FONT_B, bg=NAVY, fg=ACCENT).pack(side="left")
        tk.Button(toprow, text="🔄 重新整理", font=FONT, bg=CARD, fg=TEXTCOL, bd=0, padx=12, pady=4,
                  command=self.refresh_decisions_tab).pack(side="right")
        # 待拍板區直接放在可捲動分頁內（決策再多，整頁往下捲，不另設內捲避免衝突）
        self.pending_frame = tk.Frame(f, bg=NAVY)
        self.pending_frame.pack(fill="x", padx=16, pady=(2, 0))
        self.render_pending()

        ttk.Separator(f, orient="horizontal").pack(fill="x", padx=16, pady=10)
        tk.Label(f, text="① 給工廠下指令（決策部門明天會照做）", font=FONT_B, bg=NAVY, fg=ACCENT).pack(anchor="w", **pad)
        tk.Label(f, text="例：多做派網教學的 Shorts／停掉定投題材／這週主打風控", font=("Microsoft JhengHei", 10),
                 bg=NAVY, fg=SUB).pack(anchor="w", padx=16)
        self.cmd_entry = tk.Text(f, height=3, font=FONT, bg=CARD, fg=TEXTCOL, bd=0, padx=10, pady=8)
        self.cmd_entry.pack(fill="x", padx=16, pady=6)
        tk.Button(f, text="＋ 送出指令", font=FONT, bg=ACCENT, fg=NAVY, bd=0, command=self.add_directive).pack(anchor="e", padx=16)
        tk.Label(f, text="② 主攻格式", font=FONT_B, bg=NAVY, fg=ACCENT).pack(anchor="w", **pad)
        self.fmt_var = tk.StringVar(value=self.d.get("format_override", "auto"))
        rowf = tk.Frame(f, bg=NAVY); rowf.pack(anchor="w", padx=16)
        for v, t in [("auto", "讓決策部門自己決定"), ("short", "主攻 Shorts"), ("long", "主攻長片"), ("both", "長短並重")]:
            tk.Radiobutton(rowf, text=t, variable=self.fmt_var, value=v, font=FONT, bg=NAVY, fg=TEXTCOL,
                           selectcolor=CARD, activebackground=NAVY, command=self.save_fmt).pack(side="left", padx=6)
        tk.Label(f, text="③ 目前生效中的指令", font=FONT_B, bg=NAVY, fg=ACCENT).pack(anchor="w", **pad)
        self.dir_box = scrolledtext.ScrolledText(f, height=10, font=("Microsoft JhengHei", 10), wrap="word",
                                                 bg="#0a1020", fg=TEXTCOL, bd=0, padx=12, pady=10)
        self.dir_box.pack(fill="both", expand=True, padx=16, pady=(4, 10))
        tk.Button(f, text="🗑 清空所有指令", font=("Microsoft JhengHei", 10), bg=CARD, fg=TEXTCOL, bd=0,
                  command=self.clear_directives).pack(anchor="e", padx=16, pady=(0, 8))
        self.refresh_directives()

    def add_directive(self):
        txt = self.cmd_entry.get("1.0", "end").strip()
        if not txt:
            return
        self.d = load_directives()
        self.d.setdefault("directives", []).append(txt)
        save_directives(self.d)
        self.cmd_entry.delete("1.0", "end")
        self.refresh_directives()
        pushed = self._cloud_apply(["boss_directives.json"], self._trig_decision(), "送指令")
        messagebox.showinfo("已送出", "指令已送到雲端，決策部門正在立即重新評估。" if pushed
                            else "指令已記錄（本機）。設定 cloud.json 後可即時同步雲端。")

    def save_fmt(self):
        self.d = load_directives()
        self.d["format_override"] = self.fmt_var.get()
        save_directives(self.d)
        self._cloud_apply(["boss_directives.json"], self._trig_decision(), "主攻格式")

    def clear_directives(self):
        if messagebox.askyesno("確認", "清空所有給工廠的指令？"):
            self.d = load_directives()
            self.d["directives"] = []
            save_directives(self.d)
            self.refresh_directives()
            self._cloud_apply(["boss_directives.json"], self._trig_decision(), "清空指令")

    def refresh_decisions_tab(self):
        """重新整理「我的決策」整頁：待拍板清單＋生效指令＋格式選項，都重讀檔案。"""
        self.render_pending()
        self.refresh_directives()
        try:  # 同步主攻格式（別人/排程改過 directives 時也跟著變）
            self.fmt_var.set(self.d.get("format_override", "auto"))
        except Exception:
            pass
        self._stamp_updated()

    def refresh_directives(self):
        self.d = load_directives()
        self.dir_box.delete("1.0", "end")
        ds = self.d.get("directives", [])
        if not ds:
            self.dir_box.insert("1.0", "（目前沒有指令，工廠照決策部門自己的判斷跑）")
        else:
            for i, x in enumerate(ds, 1):
                self.dir_box.insert("end", f"{i}. {x}\n")

    def _load_pending(self):
        if PENDING.exists():
            try:
                return json.loads(PENDING.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def render_pending(self):
        for w in self.pending_frame.winfo_children():
            w.destroy()
        pend = self._load_pending()
        if not pend:
            tk.Label(self.pending_frame, text="（目前沒有待拍板的決策。決策部門有需要時會在這裡列出選擇題）",
                     font=("Microsoft JhengHei", 10), bg=NAVY, fg=SUB).pack(anchor="w", pady=4)
            return
        for p in pend:
            card = tk.Frame(self.pending_frame, bg=CARD)
            card.pack(fill="x", pady=5)
            tk.Label(card, text="❓ " + p.get("question", ""), font=FONT, bg=CARD, fg=TEXTCOL,
                     wraplength=940, justify="left").pack(anchor="w", padx=12, pady=(8, 2))
            if p.get("recommendation"):
                tk.Label(card, text="💡 建議：" + p["recommendation"], font=("Microsoft JhengHei", 9),
                         bg=CARD, fg=ACCENT, wraplength=940, justify="left").pack(anchor="w", padx=12)
            brow = tk.Frame(card, bg=CARD)
            brow.pack(anchor="w", padx=12, pady=(6, 10))
            for opt in p.get("options", []):
                tk.Button(brow, text=opt, font=FONT, bg=ACCENT, fg=NAVY, bd=0, padx=12, pady=5,
                          activebackground="#fff", command=lambda pp=p, oo=opt: self.choose_option(pp, oo)).pack(side="left", padx=5)

    def choose_option(self, p, opt):
        from datetime import datetime, timedelta, timezone
        bd = {}
        if BOSS_DEC.exists():
            try:
                bd = json.loads(BOSS_DEC.read_text(encoding="utf-8"))
            except Exception:
                bd = {}
        ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        bd[p["id"]] = {"question": p.get("question", ""), "choice": opt, "ts": ts}
        BOSS_DEC.parent.mkdir(parents=True, exist_ok=True)
        BOSS_DEC.write_text(json.dumps(bd, ensure_ascii=False, indent=2), encoding="utf-8")
        pend = [x for x in self._load_pending() if x.get("id") != p["id"]]
        PENDING.write_text(json.dumps(pend, ensure_ascii=False, indent=2), encoding="utf-8")
        # 記入本次已答，避免雲端尚未重算前又被拉回顯示
        if not hasattr(self, "_answered"):
            self._answered = set()
        self._answered.add(p["id"])
        pushed = self._cloud_apply(["boss_decisions.json"], self._trig_decision(), "拍板決策")
        messagebox.showinfo("已記錄你的決定", f"你選了「{opt}」。\n"
                            + ("已推送雲端，決策部門正在立即依此重新規劃。" if pushed
                               else "決策部門明天起會遵守這個決定。"))
        self.render_pending()
        try:
            self.render_dashboard()
        except Exception:
            pass

    # ---------- Tab 3: 控制台 ----------
    def tab_control(self, nb):
        f = self._scroll_tab(nb, "🎛 控制台")
        self._ctrl_frame = f._outer
        tk.Label(f, text="日常操作（按下＝在 24/7 雲端執行，不佔你電腦）", font=FONT_B, bg=NAVY, fg=ACCENT).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Label(f, text="背景在雲端跑，下方「執行輸出」會回報；進度/狀態看「☁ 雲端營運」。各部門單獨激活在「🏢 部門」。",
                 font=("Microsoft JhengHei", 9), bg=NAVY, fg=SUB).pack(anchor="w", padx=16, pady=(0, 4))
        row = tk.Frame(f, bg=NAVY); row.pack(anchor="w", padx=16, pady=4)
        self._btn(row, "🧠 立即決策", lambda: self._cloud_op("scripts/decision_dept.py", [], "決策"))
        self._btn(row, "🎬 立即補產", lambda: self._cloud_op("scripts/produce_batch.py", ["--target", "60"], "補產"))
        self._btn(row, "🚀 立即上架", lambda: self._cloud_op("scripts/daily_publish.py", ["--max", "6", "--privacy", load_directives().get("privacy", "public")], "上架"))
        self._btn(row, "📦 排程囤片", self.cloud_schedule)
        self._btn(row, "🔁 回顧檢討", lambda: self._cloud_op("scripts/retro_dept.py", [], "回顧"))
        self._btn(row, "💰 記一筆帳", self.record_finance)
        tk.Label(f, text="全自動開關", font=FONT_B, bg=NAVY, fg=ACCENT).pack(anchor="w", padx=16, pady=(14, 4))
        row2 = tk.Frame(f, bg=NAVY); row2.pack(anchor="w", padx=16, pady=4)
        self.pause_var = tk.BooleanVar(value=self.d.get("paused", False))
        tk.Checkbutton(row2, text="⏸ 暫停全自動（補產/上架今天先停）", variable=self.pause_var, font=FONT,
                       bg=NAVY, fg=TEXTCOL, selectcolor=CARD, activebackground=NAVY, command=self.toggle_pause).pack(side="left")
        tk.Label(f, text="快速連結", font=FONT_B, bg=NAVY, fg=ACCENT).pack(anchor="w", padx=16, pady=(14, 4))
        row3 = tk.Frame(f, bg=NAVY); row3.pack(anchor="w", padx=16, pady=4)
        self._btn(row3, "▶ 我的頻道", lambda: webbrowser.open(CHANNEL_URL))
        self._btn(row3, "🎚 YouTube Studio", lambda: webbrowser.open(STUDIO_URL))
        self._btn(row3, "📁 工作室資料夾", lambda: subprocess.Popen(["explorer", str(ROOT)]))
        tk.Label(f, text="執行輸出", font=FONT_B, bg=NAVY, fg=ACCENT).pack(anchor="w", padx=16, pady=(14, 4))
        self.log = scrolledtext.ScrolledText(f, height=14, font=("Consolas", 9), wrap="word",
                                             bg="#06090f", fg="#b9f7c0", bd=0, padx=10, pady=8)
        self.log.pack(fill="both", expand=True, padx=16, pady=(4, 12))
        self._nb = nb

    def record_finance(self):
        """💰 記一筆帳：選類型→輸入金額→寫入 finance.json 並重算報告。"""
        kind = simpledialog.askstring("記一筆帳", "類型？輸入：返佣 / 廣告 / 支出", parent=self)
        if not kind:
            return
        kmap = {"返佣": "affiliate", "廣告": "adsense", "支出": "cost",
                "affiliate": "affiliate", "adsense": "adsense", "cost": "cost"}
        etype = kmap.get(kind.strip())
        if not etype:
            messagebox.showwarning("無效", "請輸入：返佣 / 廣告 / 支出")
            return
        amt = simpledialog.askfloat("金額", f"{kind} 金額（NT$）：", parent=self, minvalue=0)
        if amt is None:
            return
        note = (simpledialog.askstring("備註", "備註（可空）：", parent=self) or "").replace('"', "'")
        if load_cloud_cfg():
            self._activate_on_cloud("scripts/finance_dept.py",
                                    ["--add", etype, "--amount", str(amt), "--note", f'"{note}"'], "財務記帳")
        else:
            self.run_script(["scripts/finance_dept.py", "--add", etype, "--amount", str(amt), "--note", note], "財務記帳")
        messagebox.showinfo("已記帳", f"已記一筆「{kind}」NT$ {amt:.0f}。\n已記在雲端帳上，財務報告更新中。")

    def _btn(self, parent, text, cmd):
        tk.Button(parent, text=text, font=FONT, bg=CARD, fg=TEXTCOL, bd=0, padx=12, pady=6,
                  activebackground=ACCENT, command=cmd).pack(side="left", padx=5)

    def _goto_control(self):
        try:
            self._nb.select(self._ctrl_frame)
        except Exception:
            pass

    def toggle_pause(self):
        self.d = load_directives()
        self.d["paused"] = self.pause_var.get()
        save_directives(self.d)
        self.refresh_status()
        self.render_dashboard()
        self._cloud_apply(["boss_directives.json"], None,
                          "暫停全自動" if self.d["paused"] else "恢復全自動")

    def _run_dept_cloud_first(self, script, args, name):
        """雲端優先跑某部門腳本；無 cloud.json 才退回本機。"""
        if self._activate_on_cloud(script, args, name):
            return
        self._goto_control(); self.run_script([script] + args, name + "(本機)")

    def _cloud_op(self, script, args, name):
        """控制台日常操作：在雲端『背景』執行，輸出回控制台自己的視窗、不跳頁；無雲端則本機跑。"""
        cfg = load_cloud_cfg()
        if not cfg:
            self.run_script([script] + args, name + "(本機)")
            return
        argstr = " ".join(args)
        remote = (f"cd {cfg['remote_root']} && nohup ./run.sh {script} {argstr} "
                  f"> logs/manual_op.log 2>&1 & echo '已在雲端背景啟動：{name}（進度看雲端營運頁的 cron/日誌或下方）'")
        self.log.insert("end", f"\n=== {name}：送往雲端執行… ===\n"); self.log.see("end")

        def worker():
            try:
                p = _run([str(PY), str(CLOUD_SSH), "run", remote], env=self._cloud_env(cfg),
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
                out = (p.stdout or "").strip().splitlines()
                msg = out[-1] if out else "已送出"
            except Exception as e:  # noqa: BLE001
                msg = f"失敗：{str(e)[:80]}"
            self.after(0, lambda: (self.log.insert("end", msg + "\n"), self.log.see("end")))
            self.after(1800, self.fetch_cloud)
        threading.Thread(target=worker, daemon=True).start()

    def run_script(self, args, name):
        threading.Thread(target=lambda: self._run_blocking(args, name), daemon=True).start()

    def _run_blocking(self, args, name):
        self.log.insert("end", f"\n=== {name} 開始執行… ===\n"); self.log.see("end")
        try:
            p = _popen([str(PY)] + args, cwd=str(ROOT),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace")
            for line in p.stdout:
                self.log.insert("end", line); self.log.see("end")
            p.wait()
            self.log.insert("end", f"=== {name} 完成 (exit {p.returncode}) ===\n")
        except Exception as e:
            self.log.insert("end", f"[錯誤] {e}\n")
        self.after(0, self.refresh_status)

    def _lib_counts(self):
        """統一的倉庫/已上架計數：線上時倉庫以雲端為準；已上架以 YouTube 真實頻道影片數為準。"""
        cloud = self._cloud if (getattr(self, "_cloud_state", "") == "online" and self._cloud) else None
        if cloud:
            q = cloud.get("queue", 0)
        else:
            q = len(set(p.stem for p in OUT.glob("S_*.mp4")) | set(p.stem for p in OUT.glob("L_*.mp4")))
        vids = self.stats.get("videos")
        if isinstance(vids, int):
            pub = vids                       # 頻道真實影片數（最準）
        elif cloud:
            pub = cloud.get("published_total", 0)
        elif LEDGER.exists():
            try:
                pub = len(json.loads(LEDGER.read_text(encoding="utf-8")))
            except Exception:
                pub = 0
        else:
            pub = 0
        return q, pub, bool(cloud)

    def refresh_status(self):
        q, pub, is_cloud = self._lib_counts()
        paused = load_directives().get("paused", False)
        state = "⏸ 已暫停" if paused else "▶ 自動運轉中"
        src = "☁ " if is_cloud else ""
        self.status_lbl.config(text=f"{src}倉庫 {q} 支 ｜ 已上架 {pub} 支 ｜ {state}")

    def _stamp_updated(self):
        from datetime import datetime
        try:
            self.updated_lbl.config(text="🕒 最後更新 " + datetime.now().strftime("%H:%M:%S"))
        except Exception:
            pass

    def auto_tick(self):
        # 每 8 秒：刷新所有「本地」資料（讀檔，便宜），讓畫面永遠是最新的
        self.refresh_status()
        for fn in (self.render_dashboard, self.render_departments, self._refresh_hr, self.render_cloud):
            try:
                fn()
            except Exception:
                pass
        # 待拍板卡片含按鈕：只有「內容真的變了」才重畫，避免每 8 秒閃爍 / 點空
        try:
            sig_p = json.dumps(self._load_pending(), ensure_ascii=False, sort_keys=True)
            if sig_p != getattr(self, "_sig_pending", None):
                self._sig_pending = sig_p
                self.render_pending()
            sig_d = json.dumps(load_directives().get("directives", []), ensure_ascii=False, sort_keys=True)
            if sig_d != getattr(self, "_sig_dir", None):
                self._sig_dir = sig_d
                self.refresh_directives()
        except Exception:
            pass
        # 每約 3 分鐘（22×8s）自動抓一次 YouTube 數據（省 API quota，不每 8 秒打）
        self._tick += 1
        if self._tick % 22 == 0:
            self.fetch_stats()
        # 每約 90 秒抓一次雲端狀態（錯開 YouTube 抓取；輕量、不打 API）
        if self._tick % 11 == 5:
            self.fetch_cloud()
        self._stamp_updated()
        self.after(8000, self.auto_tick)


if __name__ == "__main__":
    App().mainloop()
