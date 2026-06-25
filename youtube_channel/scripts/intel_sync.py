#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intel_sync.py — 本機每日大量競品學習 → 推 playbook 回雲端工廠。

雲端 IP 會被 YouTube 429 限流，故把重活(每天看大量競品)放本機跑(住宅 IP)，
學完把 STUDIO/competitor_playbook.md + competitor_analysis.md SFTP 推回 droplet，
雲端發片工廠下一輪製作即時吸收(produce_batch.load_playbook 讀的就是這檔)。

用法：python scripts/intel_sync.py [--max-learn 100] [--pace 2.5] [--no-push]
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
ANALYSIS = ROOT / "competitor_analysis.md"
AUTO_MARKER = "\n---\n\n# ⟳ 自動競品學習｜"  # intel_dept 每輪追加塊的開頭錨點
_py_win = ROOT / ".venv" / "Scripts" / "python.exe"
_py_nix = ROOT / ".venv" / "bin" / "python"
PY = _py_win if _py_win.exists() else (_py_nix if _py_nix.exists() else Path(sys.executable))


def run_learn(max_learn, pace):
    """本機跑 intel_dept 深度學習(衝量)。"""
    cmd = [str(PY), str(SCRIPTS / "intel_dept.py"), "--max-learn", str(max_learn), "--pace", str(pace)]
    print(f"[sync] 本機學習：{' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def trim_analysis(keep_days=4):
    """只保留導讀 + 檔內「最新 keep_days 天」的自動學習塊，防止 competitor_analysis.md 無限長大。

    重點：用「檔內現有最新 N 個日期」而非「距今 N 天」來保留——學習若中斷好幾天(例如出國)，
    按日曆砍會把整份明細清空只剩導讀；用最新 N 天則永遠保住最近的實際資料，不會誤刪。
    playbook 招式不在這檔(在 STUDIO/competitor_playbook.md)，這裡只精簡明細，招式完全不動。
    """
    try:
        if not ANALYSIS.exists():
            return
        txt = ANALYSIS.read_text(encoding="utf-8")
        parts = txt.split(AUTO_MARKER)
        if len(parts) <= 1:
            return  # 還沒有自動塊，無需截斷
        preamble, blocks = parts[0], parts[1:]

        def bdate(b):
            m = re.match(r"(20\d{2}-\d{2}-\d{2})", b)
            return m.group(1) if m else ""

        dates = sorted({bdate(b) for b in blocks if bdate(b)}, reverse=True)
        keep = set(dates[:keep_days])
        kept = [b for b in blocks if bdate(b) in keep]
        dropped = len(blocks) - len(kept)
        if dropped <= 0:
            print(f"[trim] analysis.md：現有 {len(dates)} 天 ≤ 上限 {keep_days} 天，不截斷。", flush=True)
            return
        new_txt = preamble + "".join(AUTO_MARKER + b for b in kept)
        ANALYSIS.write_text(new_txt, encoding="utf-8")
        size = ANALYSIS.stat().st_size
        msg = f"留最近{keep_days}天｜丟{dropped}個舊塊｜現{size:,}B"
        print(f"[trim] analysis.md 已截斷：{msg}", flush=True)
        try:
            from ops import log_ops
            log_ops("情報精簡", msg)
        except Exception:
            pass
    except Exception as e:
        print(f"[trim] 略過(不影響學習與 playbook)：{e}", file=sys.stderr)


def push_to_cloud():
    """把 playbook + analysis 推回雲端工廠（SFTP，冪等覆蓋）。"""
    cfg = ROOT / "cloud.json"
    if not cfg.exists():
        print("[sync] 無 cloud.json，略過推雲端（本機學習已保存）。"); return False
    try:
        import paramiko
    except Exception:
        print("[sync] 無 paramiko，略過推雲端。"); return False
    c = json.loads(cfg.read_text(encoding="utf-8"))
    ip, user, pw = c["ip"], c.get("user", "root"), c["password"]
    rroot = c.get("remote_root", "/root/yt")
    files = [
        (ROOT / "STUDIO" / "competitor_playbook.md", f"{rroot}/STUDIO/competitor_playbook.md"),
        (ROOT / "competitor_analysis.md", f"{rroot}/competitor_analysis.md"),
    ]
    last_err = None
    for attempt in range(1, 4):  # IPv4 出口偶爾抖，最多試 3 次，每次隔 5s
        cli = None
        try:
            cli = paramiko.SSHClient()
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            cli.connect(ip, username=user, password=pw, timeout=30)
            sf = cli.open_sftp()
            for local, remote in files:
                if local.exists():
                    sf.put(str(local), remote)
                    print(f"[sync] 推上雲端：{local.name} -> {remote}（{local.stat().st_size} B）")
            sf.close(); cli.close()
            tail = "" if attempt == 1 else f"（第 {attempt} 次才成功）"
            print(f"[sync] 雲端工廠已更新，下一輪製作即吸收。{tail}")
            return True
        except Exception as e:
            last_err = e
            try:
                if cli is not None:
                    cli.close()
            except Exception:
                pass
            if attempt < 3:
                print(f"[sync] 推雲端第 {attempt} 次失敗（{e}）；5s 後重試…", file=sys.stderr)
                time.sleep(5)
    print(f"[sync] 推雲端 3 次都失敗（本機學習已保存，不影響）：{last_err}", file=sys.stderr)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-learn", type=int, default=100)
    ap.add_argument("--pace", type=float, default=2.5)
    ap.add_argument("--no-push", action="store_true", help="只學不推雲端")
    ap.add_argument("--keep-days", type=int, default=4,
                    help="competitor_analysis.md 只保留最新 N 天的自動塊(防無限長大)；0=不截斷")
    a = ap.parse_args()
    run_learn(a.max_learn, a.pace)
    if a.keep_days > 0:
        trim_analysis(a.keep_days)
    if not a.no_push:
        push_to_cloud()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
