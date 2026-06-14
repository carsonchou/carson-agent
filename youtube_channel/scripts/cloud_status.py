#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cloud_status.py — 雲端營運狀態探針（在 DigitalOcean droplet 上跑）。

輸出一行 JSON（前綴 @@CLOUDJSON@@），給本機「決策中心」的 ☁ 雲端分頁解析顯示。
只讀本機檔案 + 系統指標，不打 YouTube API（省配額、毫秒級回應）。

用法：python scripts/cloud_status.py    （由 control_center 透過 SSH 遠端呼叫）
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"
LOGS = ROOT / "logs"
LEDGER = STUDIO / "uploaded_ledger.json"
BUFFER = STUDIO / "scheduled_buffer.json"
TW = timezone(timedelta(hours=8))


def _today_tw() -> str:
    return datetime.now(TW).strftime("%Y-%m-%d")


def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _strategy_oneline():
    """從最新一份 *_決策.md 抓『戰略判斷』一句話。"""
    rep = STUDIO / "REPORTS"
    if not rep.exists():
        return ""
    files = sorted(rep.glob("*_決策.md"), reverse=True)
    if not files:
        return ""
    try:
        import re
        m = re.search(r"\*\*戰略判斷\*\*：(.+)", files[0].read_text(encoding="utf-8"))
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


def _dept_reports_today():
    """今天已產出的部門報告 suffix 清單（給本機部門狀態反映雲端真實出勤）。"""
    rep = STUDIO / "REPORTS"
    if not rep.exists():
        return []
    today = _today_tw()
    out = []
    for p in rep.glob(f"{today}_*.md"):
        name = p.stem[len(today) + 1:]
        if name:
            out.append(name)
    return out


def _ops_tail(n=14):
    f = STUDIO / "ops_log.txt"
    if f.exists():
        try:
            return f.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
        except Exception:
            return []
    return []


def _mp4_slugs():
    return set(p.stem for p in OUT.glob("S_*.mp4")) | set(p.stem for p in OUT.glob("L_*.mp4"))


def _produced_today() -> int:
    today = _today_tw()
    n = 0
    for p in list(OUT.glob("S_*.mp4")) + list(OUT.glob("L_*.mp4")):
        try:
            if datetime.fromtimestamp(p.stat().st_mtime, TW).strftime("%Y-%m-%d") == today:
                n += 1
        except Exception:
            pass
    return n


def _ledger_count() -> int:
    if LEDGER.exists():
        try:
            return len(json.loads(LEDGER.read_text(encoding="utf-8")))
        except Exception:
            return 0
    return 0


def _buffer():
    """讀 scheduled_buffer.json（schedule_publish 寫入），回傳尚未公開的排程清單（依時間排序）。"""
    if not BUFFER.exists():
        return []
    try:
        items = json.loads(BUFFER.read_text(encoding="utf-8"))
    except Exception:
        return []
    now_utc = datetime.now(timezone.utc)
    upcoming = []
    for b in items:
        pa = b.get("publishAt", "")
        try:
            dt = datetime.strptime(pa, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if dt > now_utc:
            upcoming.append({"slug": b.get("slug", ""), "vid": b.get("vid", ""),
                             "at_tw": dt.astimezone(TW).strftime("%m-%d %H:%M"), "_sort": dt.timestamp()})
    upcoming.sort(key=lambda x: x["_sort"])
    for u in upcoming:
        u.pop("_sort", None)
    return upcoming


def _render_running() -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", "produce_batch"], capture_output=True, text=True)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def _cron_installed() -> bool:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return r.returncode == 0 and "run.sh" in r.stdout
    except Exception:
        return False


def _cron_recent(n=6):
    f = LOGS / "cron.log"
    if not f.exists():
        return [], None
    try:
        lines = [ln for ln in f.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        mtime = datetime.fromtimestamp(f.stat().st_mtime, TW).strftime("%m-%d %H:%M")
        return lines[-n:], mtime
    except Exception:
        return [], None


def _host():
    info = {}
    try:
        du = shutil.disk_usage("/")
        info["disk_pct"] = round(du.used / du.total * 100, 1)
        info["disk_free_gb"] = round(du.free / 1e9, 1)
    except Exception:
        pass
    try:
        info["load1"] = round(os.getloadavg()[0], 2)
    except Exception:
        pass
    try:
        mem = {}
        for ln in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = ln.partition(":")
            mem[k] = int(v.strip().split()[0])  # kB
        total, avail = mem.get("MemTotal", 0), mem.get("MemAvailable", 0)
        if total:
            info["mem_pct"] = round((total - avail) / total * 100, 1)
            info["mem_total_gb"] = round(total / 1e6, 1)
    except Exception:
        pass
    try:
        up = float(Path("/proc/uptime").read_text().split()[0])
        d, h = int(up // 86400), int((up % 86400) // 3600)
        info["uptime"] = f"{d}天{h}時" if d else f"{h}時"
    except Exception:
        pass
    return info


def _errors_recent() -> int:
    """只計真正致命的異常；排除會自動重試成功的暫時性警告（如 TTS『第 N 次失敗』）。"""
    n = 0
    ops = STUDIO / "ops_log.txt"
    for f in (ops, LOGS / "cron.log"):
        if not f.exists():
            continue
        try:
            for ln in f.read_text(encoding="utf-8", errors="replace").splitlines()[-120:]:
                if "次失敗" in ln or "[warn]" in ln or "[note]" in ln:
                    continue  # 重試警告／提示，會自癒，不算異常
                if any(k in ln for k in ("FATAL", "Traceback", "⚠️", "連續失敗", "配音失敗")):
                    n += 1
        except Exception:
            pass
    return n


def main() -> int:
    buf = _buffer()
    data = {
        "ok": True,
        "ts": datetime.now(TW).strftime("%Y-%m-%d %H:%M:%S"),
        "tz": "Asia/Taipei",
        "queue": len(_mp4_slugs()),
        "produced_today": _produced_today(),
        "published_total": _ledger_count(),
        "buffer_count": len(buf),
        "buffer": buf[:12],
        "next_publish": buf[0]["at_tw"] if buf else None,
        "render_running": _render_running(),
        "cron_installed": _cron_installed(),
        "errors_recent": _errors_recent(),
    }
    cron_lines, cron_mtime = _cron_recent()
    data["cron_recent"] = cron_lines
    data["cron_log_mtime"] = cron_mtime
    data.update(_host())
    # ── 控制面資料（讓本機決策中心整合成雲端遙控器：顯示雲端的待拍板/員額/指令/戰略）──
    data["pending"] = _read_json(STUDIO / "pending_decisions.json", [])
    data["directives_doc"] = _read_json(STUDIO / "boss_directives.json",
                                        {"directives": [], "format_override": "auto",
                                         "privacy": "public", "paused": False})
    data["headcount"] = _read_json(STUDIO / "headcount.json", {})
    data["boss_decisions"] = _read_json(STUDIO / "boss_decisions.json", {})
    data["strategy"] = _strategy_oneline()
    data["dept_reports_today"] = _dept_reports_today()
    data["ops_tail"] = _ops_tail()
    # base64 包裝：純 ASCII 通過 SSH pty 不會被破壞中文（控制中心端會 b64 解回）
    payload = base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")
    sys.stdout.write("@@CLOUDJSON64@@" + payload + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
