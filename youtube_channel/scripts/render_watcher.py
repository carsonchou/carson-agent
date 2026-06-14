#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_watcher.py — 【混合架構 PC 端】把雲端產好的腳本渲染成片並上架。

混合架構分工：
  ☁️ 雲端 VPS（24h）：決策→寫腳本→配音（produce_batch.py --no-render），不渲染、不上架。
  💻 你的電腦（開機時）：本程式守在這，看到「有腳本+配音但還沒成片」的就渲染→過審→上架。
     電腦關機時雲端照樣累積腳本；一開機就把積壓的補完。

待渲染判定：output/ 下有 {slug}.voice.txt + {slug}.mp3，但沒有 {slug}.mp4。
渲染規則同 produce_batch：Shorts(S_)=直式 1080x1920 概念圖（不用 Pexels）；長片(L_)=橫式+Pexels。
渲完呼叫 daily_publish.py（審核閘門 + 自動上架）。

可選 git 同步（--sync）：開跑前 git pull 取雲端新腳本，結束後 git push 回報 ledger。
缺 git/無遠端時自動略過，不影響渲染。

用法：
  python scripts/render_watcher.py            # 跑一輪（渲完待渲染的 + 上架一次）
  python scripts/render_watcher.py --loop --interval 900   # 常駐，每 15 分鐘巡一次
  python scripts/render_watcher.py --sync     # 每輪前後做 git pull/push
（建議在 PC 用工作排程器每 15-30 分鐘觸發一次，或 --loop 常駐。）
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():  # Linux/其他環境退回當前直譯器
    PY = Path(sys.executable)
OUT = ROOT / "output"

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(dept, msg):
        try:
            p = ROOT / "STUDIO" / "ops_log.txt"
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                from datetime import datetime
                f.write(f"{datetime.now().strftime('%H:%M')} [{dept}] {msg}\n")
        except Exception:
            pass


def pending_slugs():
    """有腳本+配音但還沒成片的 slug（去重、排序）。"""
    out = []
    for vt in sorted(OUT.glob("*.voice.txt")):
        slug = vt.name[:-len(".voice.txt")]
        if not slug.startswith(("S_", "L_")):
            continue
        if (OUT / f"{slug}.mp4").exists():
            continue
        if not (OUT / f"{slug}.mp3").exists():
            continue  # 配音還沒好，跳過（雲端 TTS 可能還在跑）
        out.append(slug)
    return out


def render_one(slug: str) -> bool:
    """渲染單一 slug。S_=直式概念圖（無 Pexels）；L_=橫式（用 Pexels）。"""
    env = os.environ.copy()
    if slug.startswith("S_"):
        env.pop("PEXELS_API_KEY", None)
        args = ["--slug", slug, "--width", "1080", "--height", "1920"]
    else:
        # 長片用 Pexels（沿用使用者環境變數，若有）
        pex = env.get("PEXELS_API_KEY")
        if not pex:
            try:  # Windows：嘗試讀使用者層級變數
                import subprocess as _sp
                pex = _sp.check_output(
                    ["powershell.exe", "-NoProfile", "-Command",
                     "[Environment]::GetEnvironmentVariable('PEXELS_API_KEY','User')"],
                    text=True,
                ).strip()
                if pex:
                    env["PEXELS_API_KEY"] = pex
            except Exception:
                pass
        args = ["--slug", slug]
    mp4 = OUT / f"{slug}.mp4"
    subprocess.run([str(PY), "scripts/make_video.py", *args], cwd=str(ROOT), env=env)
    ok = mp4.exists() and mp4.stat().st_size > 100 * 1024
    log_ops("渲染看守", f"{'渲染完成' if ok else '渲染失敗'}：{slug}")
    return ok


def git(*cmd) -> bool:
    """執行 git 指令；非 git 倉庫或失敗時回 False（不中斷）。"""
    try:
        r = subprocess.run(["git", *cmd], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"[git] {' '.join(cmd)} → {r.stderr.strip()[:120]}")
            return False
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[git] 略過（{e}）")
        return False


def run_once(sync: bool) -> int:
    if sync:
        git("pull", "--rebase", "--autostash")
    todo = pending_slugs()
    if not todo:
        print("[watcher] 沒有待渲染的腳本（雲端還沒產或都渲完了）。")
    else:
        print(f"[watcher] 待渲染 {len(todo)} 支：{todo[:6]}{'…' if len(todo) > 6 else ''}")
        done = 0
        for slug in todo:
            if render_one(slug):
                done += 1
        print(f"[watcher] 本輪渲染完成 {done}/{len(todo)} 支。")
        log_ops("渲染看守", f"本輪渲染 {done}/{len(todo)} 支")

    # 渲完就跑審核+上架（daily_publish 自帶審核閘門，只上未上架的）
    priv = "public"
    try:
        import json
        bd = ROOT / "STUDIO" / "boss_directives.json"
        if bd.exists():
            priv = json.loads(bd.read_text(encoding="utf-8")).get("privacy", "public")
    except Exception:
        pass
    subprocess.run([str(PY), "scripts/daily_publish.py", "--max", "6", "--privacy", priv],
                   cwd=str(ROOT))

    if sync:
        git("add", "-A")
        git("commit", "-m", "render_watcher: rendered + published")
        git("push")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="常駐，定時巡邏")
    ap.add_argument("--interval", type=int, default=900, help="巡邏間隔秒數（預設 900=15 分）")
    ap.add_argument("--sync", action="store_true", help="每輪前後做 git pull/push 與雲端同步")
    args = ap.parse_args()

    if not args.loop:
        return run_once(args.sync)

    print(f"[watcher] 常駐模式啟動，每 {args.interval}s 巡一次。Ctrl-C 停止。")
    try:
        while True:
            run_once(args.sync)
            time.sleep(max(60, args.interval))
    except KeyboardInterrupt:
        print("\n[watcher] 已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
