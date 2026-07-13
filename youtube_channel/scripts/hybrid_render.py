#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hybrid_render.py — 安全雙模式渲染（雲端保底 + PC 加速，鎖防雙渲染）。

機制：produce_batch --no-render 只在雲端產配音排隊；待渲染 = output/{slug}.voice.txt+{slug}.mp3 但無 {slug}.mp4。
  雲端鎖檔 output/{slug}.lock（含時間戳）＝認領標記；誰先寫鎖誰渲，另一邊跳過。鎖 >25 分視為過期(渲染崩潰)可重認領。

模式：
  --cloud   在雲端跑（cron 每 15 分）：渲染本機待辦，本機鎖，渲完刪鎖。
  --pc      在 PC 跑：SFTP 連雲端→認領(寫雲端鎖)→拉 voice/mp3/md→本機渲染→推回 mp4→刪雲端鎖。
            （PC 強、可平行多認領；雲端保底所以 PC 關也沒事）
  --loop --interval N  常駐巡邏。
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = ROOT / ".venv" / "bin" / "python"
if not PY.exists():
    PY = Path(sys.executable)
OUT = ROOT / "output"
LOCK_STALE = 1500  # 秒；鎖超過此時間視為過期(渲染崩潰)
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


def _now():
    import time as _t
    return _t.time()


def _render_local(slug: str, env=None) -> bool:
    env = env or os.environ.copy()
    if slug.startswith("S_"):
        env.pop("PEXELS_API_KEY", None)
        args = ["--slug", slug, "--width", "1080", "--height", "1920", "--fps", "15"]
    else:
        args = ["--slug", slug]
    subprocess.run([str(PY), "scripts/make_video.py", *args], cwd=str(ROOT), env=env)
    mp4 = OUT / f"{slug}.mp4"
    return mp4.exists() and mp4.stat().st_size > 100 * 1024


# ───────────────────────── 雲端模式（本機檔案＋本機鎖）─────────────────────────
def cloud_pending():
    """P0 止血(2026-07-13，同 render_watcher.pending_slugs 的根因)：mp3 比 mp4 新(配音
    被重生/補寫覆寫過，但成片未跟著重渲)也要當成待渲染，避免發布跟旁白不同步的舊成片。"""
    out = []
    for vt in sorted(OUT.glob("*.voice.txt")):
        slug = vt.name[:-len(".voice.txt")]
        if not slug.startswith(("S_", "L_")):
            continue
        mp3 = OUT / f"{slug}.mp3"
        if not mp3.exists():
            continue
        mp4 = OUT / f"{slug}.mp4"
        if mp4.exists():
            try:
                if mp3.stat().st_mtime <= mp4.stat().st_mtime:
                    continue
            except Exception:  # noqa: BLE001
                continue
        out.append(slug)
    return out


def _claim_local(slug) -> bool:
    lock = OUT / f"{slug}.lock"
    if lock.exists():
        try:
            if _now() - lock.stat().st_mtime < LOCK_STALE:
                return False
        except Exception:
            return False
    try:
        lock.write_text(f"cloud {_now():.0f}", encoding="utf-8")
        return True
    except Exception:
        return False


def run_cloud(maxn: int) -> int:
    todo = cloud_pending()[:maxn]
    done = 0
    for slug in todo:
        if not _claim_local(slug):
            continue
        try:
            if _render_local(slug):
                done += 1
                log_ops("雲端渲染", f"渲染完成：{slug}")
        finally:
            try:
                (OUT / f"{slug}.lock").unlink()
            except Exception:
                pass
    print(f"[cloud] 渲染 {done}/{len(todo)} 支")
    return done


# ───────────────────────── PC 模式（SFTP 連雲端）─────────────────────────
def _sftp():
    cfg = json.load(open(ROOT / "cloud.json", encoding="utf-8"))
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(cfg["ip"], username=cfg.get("user", "root"), password=cfg["password"], timeout=30)
    return c, c.open_sftp(), cfg.get("remote_root", "/root/yt")


def run_pc(maxn: int) -> int:
    c, sf, rr = _sftp()
    rout = rr + "/output"
    try:
        files = sf.listdir(rout)
    except Exception as e:
        print(f"[pc] 連雲端 output 失敗：{e}"); c.close(); return 0
    fset = set(files)
    pend = []
    for f in sorted(files):
        if f.endswith(".voice.txt"):
            slug = f[:-len(".voice.txt")]
            if not slug.startswith(("S_", "L_")):
                continue
            if f"{slug}.mp4" in fset or f"{slug}.mp3" not in fset:
                continue
            pend.append(slug)
    done = 0
    for slug in pend:
        if done >= maxn:
            break
        lockp = f"{rout}/{slug}.lock"
        # 認領：鎖不存在或過期才認
        try:
            st = sf.stat(lockp)
            if _now() - st.st_mtime < LOCK_STALE:
                continue  # 別人正在渲
        except IOError:
            pass
        try:
            with sf.open(lockp, "w") as lf:
                lf.write(f"pc {_now():.0f}".encode())
        except Exception:
            continue
        try:
            # 拉 voice/mp3/md 到本機
            for ext in (".voice.txt", ".mp3", ".md"):
                rp = f"{rout}/{slug}{ext}"
                if f"{slug}{ext}" in fset:
                    sf.get(rp, str(OUT / f"{slug}{ext}"))
            print(f"[pc] 認領+渲染：{slug[:40]}")
            if _render_local(slug):
                sf.put(str(OUT / f"{slug}.mp4"), f"{rout}/{slug}.mp4")
                done += 1
                print(f"[pc] ✅ 推回 mp4：{slug[:40]}")
            else:
                print(f"[pc] ⚠ 渲染失敗：{slug[:40]}")
        finally:
            try:
                sf.remove(lockp)
            except Exception:
                pass
    sf.close(); c.close()
    print(f"[pc] 本輪 PC 渲染 {done}/{len(pend)} 支（雲端保底其餘）")
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", action="store_true", help="雲端模式：渲本機待辦")
    ap.add_argument("--pc", action="store_true", help="PC 模式：SFTP 認領雲端待辦來渲")
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=600)
    args = ap.parse_args()
    if not (args.cloud or args.pc):
        print("請指定 --cloud 或 --pc"); return 2
    fn = run_cloud if args.cloud else run_pc
    if not args.loop:
        fn(args.max); return 0
    print(f"[hybrid] 常駐 {'PC' if args.pc else 'cloud'} 模式，每 {args.interval}s 巡一次。")
    while True:
        try:
            fn(args.max)
        except Exception as e:
            print(f"[hybrid] 本輪錯誤（續）：{str(e)[:80]}")
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
