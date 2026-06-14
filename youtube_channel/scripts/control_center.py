#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""control_center.py — 量化阿森 決策中心（桌面 GUI，升級版）。

分頁：🏠總覽儀表板 / 📋每日匯報 / 🧠我的決策 / 🎛控制台。
老闆雙擊桌面捷徑打開：一眼看達標進度與工廠狀態、下決策、控制。
決策寫入 STUDIO/boss_directives.json，由決策/補產/上架部門讀取遵循。
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
DIRECTIVES = STUDIO / "boss_directives.json"
LEDGER = STUDIO / "uploaded_ledger.json"
PENDING = STUDIO / "pending_decisions.json"
BOSS_DEC = STUDIO / "boss_decisions.json"
OPS = STUDIO / "ops_log.txt"
TOKEN = ROOT / "token_manage.json"
OUT = ROOT / "output"
CHANNEL_URL = "https://www.youtube.com/channel/UCqP5JQXlQR5ZDLtEiBt4kLA"
STUDIO_URL = "https://studio.youtube.com/channel/UCqP5JQXlQR5ZDLtEiBt4kLA"

FONT = ("Microsoft JhengHei", 11)
FONT_B = ("Microsoft JhengHei", 13, "bold")
FONT_BIG = ("Microsoft JhengHei", 26, "bold")
NAVY = "#0e162e"
CARD = "#1b2a4a"
ACCENT = "#ffd23f"
GREEN = "#58e08c"
RED = "#ff6060"
TEXTCOL = "#eef2ff"
SUB = "#9fb3d0"

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
    {"tag": "⑤", "name": "流量部門（SEO）",    "head": 2, "kind": "seo",      "owner": "併入腳本產出",
     "act": "seo_info",      "boost": "⑤流量SEO：標題標籤更積極優化點擊"},
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
        self.geometry("1080x760")
        self.configure(bg=NAVY)
        self.d = load_directives()
        self.stats = {"subs": None, "views": None, "videos": None}
        self._tick = 0          # auto_tick 計數（用來決定多久抓一次 YouTube 數據）
        self._fetching = False   # 避免重複併發抓取

        head = tk.Frame(self, bg=NAVY)
        head.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(head, text="量化阿森 決策中心", font=("Microsoft JhengHei", 20, "bold"),
                 bg=NAVY, fg=ACCENT).pack(side="left")
        right = tk.Frame(head, bg=NAVY); right.pack(side="right")
        self.status_lbl = tk.Label(right, text="", font=FONT, bg=NAVY, fg=TEXTCOL)
        self.status_lbl.pack(anchor="e")
        self.updated_lbl = tk.Label(right, text="🕒 最後更新 --:--:--", font=("Microsoft JhengHei", 9),
                                    bg=NAVY, fg=SUB)
        self.updated_lbl.pack(anchor="e")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=NAVY, borderwidth=0)
        style.configure("TNotebook.Tab", font=FONT, padding=(16, 8))
        style.configure("Y.Horizontal.TProgressbar", troughcolor=CARD, background=ACCENT, borderwidth=0)
        style.configure("G.Horizontal.TProgressbar", troughcolor=CARD, background=GREEN, borderwidth=0)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=16, pady=8)
        self.tab_dashboard(nb)
        self.tab_departments(nb)
        self.tab_hr(nb)
        self.tab_reports(nb)
        self.tab_decisions(nb)
        self.tab_control(nb)

        self.refresh_status()
        self.fetch_stats()           # 開啟時自動抓一次
        self.after(8000, self.auto_tick)  # 每 8 秒刷新本地狀態

    # ---------- Tab 0: 總覽（戰情室） ----------
    def _section(self, parent, text):
        """區段標題：左側 accent 直條 + 標題，視覺層次更分明（專業感）。"""
        bar = tk.Frame(parent, bg=NAVY); bar.pack(fill="x", padx=16, pady=(12, 3))
        tk.Frame(bar, bg=ACCENT, width=4, height=18).pack(side="left", padx=(0, 8))
        tk.Label(bar, text=text, font=FONT_B, bg=NAVY, fg=TEXTCOL).pack(side="left")
        return bar

    def _kpi_card(self, parent, key):
        c = tk.Frame(parent, bg=CARD); c.pack(side="left", expand=True, fill="both", padx=5)
        val = tk.Label(c, text="—", font=("Microsoft JhengHei", 24, "bold"), bg=CARD, fg=ACCENT)
        val.pack(pady=(12, 0))
        sub = tk.Label(c, text="", font=("Microsoft JhengHei", 9), bg=CARD, fg=GREEN)
        sub.pack()
        tk.Label(c, text=self._kpi_labels[key], font=("Microsoft JhengHei", 10), bg=CARD, fg=SUB).pack(pady=(0, 10))
        self.kpi[key] = val
        self.kpi_sub[key] = sub

    def tab_dashboard(self, nb):
        f = tk.Frame(nb, bg=NAVY)
        nb.add(f, text="🏠 總覽")

        # ── KPI 卡片列（4 張：訂閱 / 總觀看 / 留存 / 淨利）──
        self._kpi_labels = {"subs": "訂閱數", "views": "總觀看", "retention": "平均觀看率", "net": "淨利 NT$"}
        self.kpi = {}; self.kpi_sub = {}
        row = tk.Frame(f, bg=NAVY); row.pack(fill="x", padx=12, pady=(14, 2))
        for key in ("subs", "views", "retention", "net"):
            self._kpi_card(row, key)
        tk.Button(f, text="🔄 刷新數據", font=("Microsoft JhengHei", 9), bg=CARD, fg=TEXTCOL, bd=0,
                  command=self.fetch_stats).pack(anchor="e", padx=16, pady=(4, 0))

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
            self.after(0, self.render_dashboard)
        threading.Thread(target=worker, daemon=True).start()

    def render_dashboard(self):
        # 讀快取（由 fetch_stats 每 3 分鐘更新；避免每 8 秒打 Analytics API）
        analytics = getattr(self, "_analytics", None)
        net = getattr(self, "_net", None)

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
            text=f"{len(DEPTS)} 部門　｜　片庫 {q} 支　｜　累計上架 {pub} 支　｜　"
                 + ("⏸ 已暫停" if paused else "▶ 全自動運轉中"))
        # 戰略 + 待拍板
        one, _ = latest_decision()
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
        # 工廠心跳
        try:
            self.ops_box.delete("1.0", "end")
            self.ops_box.insert("1.0", read_ops_tail(12))
            self.ops_box.see("end")
        except Exception:
            pass

    def run_full_cycle(self):
        if not messagebox.askyesno("確認", "立即依序執行：決策 → 補產 → 上架 → 回顧檢討？\n（會花幾分鐘，可在控制台看輸出）"):
            return
        self._goto_control()

        def chain():
            for args, name in [(["scripts/decision_dept.py"], "決策"),
                               (["scripts/produce_batch.py", "--shorts", "4", "--long", "1"], "補產"),
                               (["scripts/daily_publish.py", "--max", "6", "--privacy", load_directives().get("privacy", "public")], "上架"),
                               (["scripts/retro_dept.py"], "回顧檢討"),
                               (["scripts/hr_dept.py"], "人事監察")]:
                self._run_blocking(args, name)
            self.after(0, self.fetch_stats)
        threading.Thread(target=chain, daemon=True).start()

    # ---------- Tab: 部門總覽 ----------
    def tab_departments(self, nb):
        f = tk.Frame(nb, bg=NAVY)
        nb.add(f, text="🏢 部門")

        toprow = tk.Frame(f, bg=NAVY); toprow.pack(fill="x", padx=16, pady=(14, 4))
        self.dept_summary = tk.Label(toprow, text="", font=FONT_B, bg=NAVY, fg=ACCENT, justify="left")
        self.dept_summary.pack(side="left")
        tk.Button(toprow, text="🔄 重新整理", font=FONT, bg=CARD, fg=TEXTCOL, bd=0, padx=12, pady=4,
                  command=self.render_departments).pack(side="right")
        # 一鍵壓榨 / 一鍵最大化壓榨（全公司）
        allrow = tk.Frame(f, bg=NAVY); allrow.pack(fill="x", padx=16, pady=(0, 2))
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
            tk.Label(r, text=f"{d['tag']} {d['name']}", font=FONT, bg=bgc, fg=TEXTCOL,
                     width=18, anchor="w").pack(side="left", padx=2, pady=5)
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

        def rep(suffix):
            return (REPORTS / f"{today}_{suffix}.md").exists()

        def out_today(prefix):
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
                setrow(tag, "✅ 併入腳本(標題/標籤/描述)", GR); running += 1
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
            else:  # 後備（理論上不會到）
                setrow(tag, "🔧 規劃中・尚未自動化", SUBC)

        # 員額即時刷新（人事部調整後馬上反映）
        hc = load_headcount()
        for tag, lbl in getattr(self, "dept_head_lbls", {}).items():
            try:
                lbl.config(text=f"{hc.get(tag, 0)} 人")
            except Exception:
                pass
        total = sum(hc.values())
        state = "⏸ 已暫停" if paused else "▶ 自動運轉中"
        self.dept_summary.config(
            text=f"🏢 全工作室 {len(DEPTS)} 部門 ・ AI 員額 {total} 人 ・ 運轉 {running} 部門 ・ {state}")

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
        """⚡激活：立刻叫該部門跑一次（真的執行對應腳本，輸出串到控制台）。"""
        name = f"{d['tag']} {d['name']}"
        act = d.get("act")
        priv = load_directives().get("privacy", "public")
        if act == "produce_long":
            self._goto_control(); self.run_script(["scripts/produce_batch.py", "--long", "1", "--shorts", "0"], name + "・激活")
        elif act == "produce_short":
            self._goto_control(); self.run_script(["scripts/produce_batch.py", "--shorts", "4", "--long", "0"], name + "・激活")
        elif act == "decision":
            self._goto_control(); self.run_script(["scripts/decision_dept.py"], name + "・激活")
        elif act == "publish":
            self._goto_control(); self.run_script(["scripts/daily_publish.py", "--max", "6", "--privacy", priv], name + "・激活")
        elif act == "retro":
            self._goto_control(); self.run_script(["scripts/retro_dept.py"], name + "・激活")
        elif act == "hr":
            self._goto_control(); self.run_script(["scripts/hr_dept.py"], name + "・激活")
        elif act == "finance":
            self._goto_control(); self.run_script(["scripts/finance_dept.py"], name + "・激活")
        elif act == "organize":
            self._goto_control(); self.run_script(["scripts/organize_dept.py"], name + "・激活")
        elif act == "promo":
            self._goto_control(); self.run_script(["scripts/promo_dept.py"], name + "・激活")
        elif act == "comment":
            self._goto_control(); self.run_script(["scripts/comment_dept.py"], name + "・激活")
        elif act == "thumb":
            self._goto_control(); self.run_script(["scripts/thumbnail_dept.py"], name + "・激活")
        elif act == "intel":
            self._goto_control(); self.run_script(["scripts/intel_dept.py"], name + "・激活")
        elif act == "data":
            self.fetch_stats()
            messagebox.showinfo("已激活", f"{name} 已重新抓取最新頻道數據（KPI 即將更新）。")
        elif act == "reports":
            try:
                subprocess.Popen(["explorer", str(REPORTS)])
            except Exception:
                pass
            messagebox.showinfo("總監管部門", "已打開《每日營運匯報》資料夾。\n總監管的產出就是每日匯報。")
        elif act == "seo_info":
            messagebox.showinfo("流量部門（SEO）",
                                "SEO 已內建在每支腳本產出（標題／標籤／描述／Hashtag），不需單獨激活。\n想長期更積極 → 按 🔥壓榨。")
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
            messagebox.showinfo("🔥 已壓榨", f"{res[0]} 壓榨強度 Lv{res[1]}（上限 {MAX_BOOST_LV}）。\n決策部門明早起會更積極。")

    def max_squeeze_dept(self, d):
        """🔥🔥 最大化壓榨：該部門直接拉到最大強度。"""
        name = f"{d['tag']} {d['name']}"
        if not d.get("boost"):
            messagebox.showinfo(name, "這個部門不適用壓榨（唯讀/無產能調節）。")
            return
        res = self._apply_boost(d, MAX_BOOST_LV)
        if res:
            messagebox.showinfo("🔥🔥 最大化壓榨", f"{res[0]} 已拉到最大 Lv{res[1]}！這個部門火力全開。")

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
        messagebox.showinfo("🔥 一鍵壓榨完成", f"已對 {n} 個部門 +1 壓榨。全公司加碼運轉。")

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
        messagebox.showinfo("🔥🔥 火力全開", f"已把 {n} 個部門全部拉到最大 Lv{MAX_BOOST_LV}！\n全公司進入最大化衝刺。")

    # ---------- Tab: 人事部（監察 + 編制） ----------
    # 員額有真實作用：①②的員額 = 每日產出量（produce_batch 讀 headcount.json）。
    HEAD_REAL = {"①": "每日長片數", "②": "每日 Shorts 數"}

    def tab_hr(self, nb):
        f = tk.Frame(nb, bg=NAVY)
        nb.add(f, text="🧑‍💼 人事部")

        top = tk.Frame(f, bg=NAVY); top.pack(fill="x", padx=16, pady=(14, 2))
        self.hr_summary = tk.Label(top, text="", font=FONT_B, bg=NAVY, fg=ACCENT)
        self.hr_summary.pack(side="left")
        tk.Button(top, text="🔄 重新整理", font=FONT, bg=CARD, fg=TEXTCOL, bd=0, padx=12, pady=4,
                  command=self._refresh_hr).pack(side="right")
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
            tk.Label(cell, text=f"{d['tag']} {d['name']}", font=("Microsoft JhengHei", 10), bg=CARD, fg=TEXTCOL,
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
        if delta > 0 and tag in self.HEAD_REAL:
            messagebox.showinfo("➕ 招募完成",
                                f"{tag} 員額 +1（現 {hc[tag]} 人）。\n此部門員額＝{self.HEAD_REAL[tag]}，下一輪補產會依此擴大產能。")

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
    def tab_reports(self, nb):
        f = tk.Frame(nb, bg=NAVY)
        nb.add(f, text="📋 每日匯報")
        left = tk.Frame(f, bg=NAVY); left.pack(side="left", fill="y", padx=(0, 8), pady=8)
        tk.Label(left, text="選擇匯報", font=FONT_B, bg=NAVY, fg=TEXTCOL).pack(anchor="w")
        self.rep_list = tk.Listbox(left, width=34, height=30, font=("Microsoft JhengHei", 10),
                                   bg=CARD, fg=TEXTCOL, selectbackground=ACCENT, selectforeground=NAVY, bd=0)
        self.rep_list.pack(fill="y", expand=True, pady=6)
        self.rep_list.bind("<<ListboxSelect>>", self.show_report)
        tk.Button(left, text="🔄 重新整理", font=FONT, command=self.load_reports, bg=CARD, fg=TEXTCOL, bd=0).pack(fill="x")
        self.rep_text = scrolledtext.ScrolledText(f, font=("Microsoft JhengHei", 11), wrap="word",
                                                  bg="#0a1020", fg=TEXTCOL, bd=0, padx=14, pady=12)
        self.rep_text.pack(side="left", fill="both", expand=True, pady=8)
        self.load_reports()

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
        f = tk.Frame(nb, bg=NAVY)
        nb.add(f, text="🧠 我的決策")
        pad = {"padx": 16, "pady": 6}

        toprow = tk.Frame(f, bg=NAVY); toprow.pack(fill="x", padx=16, pady=(12, 2))
        tk.Label(toprow, text="📌 待你拍板的決策（決策部門提出，點選項即生效）", font=FONT_B, bg=NAVY, fg=ACCENT).pack(side="left")
        tk.Button(toprow, text="🔄 重新整理", font=FONT, bg=CARD, fg=TEXTCOL, bd=0, padx=12, pady=4,
                  command=self.refresh_decisions_tab).pack(side="right")
        # 待拍板區：有界、可捲動 —— 決策不設上限，再多也能往下捲，不會擠爆畫面
        pwrap = tk.Frame(f, bg=NAVY); pwrap.pack(fill="x", padx=16)
        self._pcanvas = tk.Canvas(pwrap, bg=NAVY, highlightthickness=0, height=240)
        pscroll = ttk.Scrollbar(pwrap, orient="vertical", command=self._pcanvas.yview)
        self._pcanvas.configure(yscrollcommand=pscroll.set)
        pscroll.pack(side="right", fill="y")
        self._pcanvas.pack(side="left", fill="both", expand=True)
        self.pending_frame = tk.Frame(self._pcanvas, bg=NAVY)
        self._pcanvas_win = self._pcanvas.create_window((0, 0), window=self.pending_frame, anchor="nw")
        self.pending_frame.bind(
            "<Configure>", lambda e: self._pcanvas.configure(scrollregion=self._pcanvas.bbox("all")))
        self._pcanvas.bind(
            "<Configure>", lambda e: self._pcanvas.itemconfig(self._pcanvas_win, width=e.width))
        # 滑鼠滾輪捲動（游標在區內時）
        self._pcanvas.bind("<Enter>", lambda e: self._pcanvas.bind_all(
            "<MouseWheel>", lambda ev: self._pcanvas.yview_scroll(int(-ev.delta / 120), "units")))
        self._pcanvas.bind("<Leave>", lambda e: self._pcanvas.unbind_all("<MouseWheel>"))
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
        messagebox.showinfo("已送出", "指令已記錄，明早決策部門會納入考量。")

    def save_fmt(self):
        self.d = load_directives()
        self.d["format_override"] = self.fmt_var.get()
        save_directives(self.d)

    def clear_directives(self):
        if messagebox.askyesno("確認", "清空所有給工廠的指令？"):
            self.d = load_directives()
            self.d["directives"] = []
            save_directives(self.d)
            self.refresh_directives()

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
        messagebox.showinfo("已記錄你的決定", f"你選了「{opt}」。\n決策部門明天起會遵守這個決定。")
        self.render_pending()
        try:
            self.render_dashboard()
        except Exception:
            pass

    # ---------- Tab 3: 控制台 ----------
    def tab_control(self, nb):
        f = tk.Frame(nb, bg=NAVY)
        nb.add(f, text="🎛 控制台")
        self._ctrl_frame = f
        tk.Label(f, text="立即手動執行（平常不用，排程會自動跑）", font=FONT_B, bg=NAVY, fg=ACCENT).pack(anchor="w", padx=16, pady=(14, 4))
        row = tk.Frame(f, bg=NAVY); row.pack(anchor="w", padx=16, pady=4)
        self._btn(row, "🧠 立即決策", lambda: self.run_script(["scripts/decision_dept.py"], "決策部門"))
        self._btn(row, "🎬 立即補產", lambda: self.run_script(["scripts/produce_batch.py", "--shorts", "4", "--long", "1"], "補產部門"))
        self._btn(row, "🚀 立即上架", lambda: self.run_script(["scripts/daily_publish.py", "--max", "6", "--privacy", load_directives().get("privacy", "public")], "上架部門"))
        self._btn(row, "🔁 回顧檢討", lambda: self.run_script(["scripts/retro_dept.py"], "回顧檢討部門"))
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
        note = simpledialog.askstring("備註", "備註（可空）：", parent=self) or ""
        self.run_script(["scripts/finance_dept.py", "--add", etype, "--amount", str(amt), "--note", note], "財務記帳")
        messagebox.showinfo("已記帳", f"已記一筆「{kind}」NT$ {amt:.0f}。\n財務報告已更新（⑭ 財務部狀態會刷新）。")

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

    def run_script(self, args, name):
        threading.Thread(target=lambda: self._run_blocking(args, name), daemon=True).start()

    def _run_blocking(self, args, name):
        self.log.insert("end", f"\n=== {name} 開始執行… ===\n"); self.log.see("end")
        try:
            p = subprocess.Popen([str(PY)] + args, cwd=str(ROOT),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace")
            for line in p.stdout:
                self.log.insert("end", line); self.log.see("end")
            p.wait()
            self.log.insert("end", f"=== {name} 完成 (exit {p.returncode}) ===\n")
        except Exception as e:
            self.log.insert("end", f"[錯誤] {e}\n")
        self.after(0, self.refresh_status)

    def refresh_status(self):
        q = len(list(OUT.glob("S_*.mp4")) + list(OUT.glob("L_*.mp4")))
        pub = len(json.loads(LEDGER.read_text(encoding="utf-8"))) if LEDGER.exists() else 0
        paused = load_directives().get("paused", False)
        state = "⏸ 已暫停" if paused else "▶ 自動運轉中"
        self.status_lbl.config(text=f"片庫 {q} 支 ｜ 已上架 {pub} 支 ｜ {state}")

    def _stamp_updated(self):
        from datetime import datetime
        try:
            self.updated_lbl.config(text="🕒 最後更新 " + datetime.now().strftime("%H:%M:%S"))
        except Exception:
            pass

    def auto_tick(self):
        # 每 8 秒：刷新所有「本地」資料（讀檔，便宜），讓畫面永遠是最新的
        self.refresh_status()
        for fn in (self.render_dashboard, self.render_departments, self._refresh_hr):
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
        self._stamp_updated()
        self.after(8000, self.auto_tick)


if __name__ == "__main__":
    App().mainloop()
