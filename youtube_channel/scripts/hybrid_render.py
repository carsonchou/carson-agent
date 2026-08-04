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


# ── 渲染失敗計數 / 隔離(2026-08-04)──────────────────────────────────────────
# cloud_pending() 的判準是「有 voice.txt+mp3 但沒 mp4」,所以**永遠失敗的片會永遠留在
# 待渲染清單裡**。實測 L_個股體檢南亞1303 那支被語速健檢連續擋下 **32 次**(每 15 分鐘
# 一次、整夜不停),每輪都排在最前面,把渲染名額吃掉。
# 「不會壞、只會少做一件事」的反面:**會叫、但叫了 32 次還是沒人處理**——一樣是白燒。
# 連續失敗 _FAIL_QUARANTINE 次就隔離,不再重試,並在 ops_log 留一筆給人看。
# 解除方式:修好那支之後,從 STUDIO/render_failures.json 拿掉該 slug(或整支渲成功會自動清)。
_FAILS = ROOT / "STUDIO" / "render_failures.json"
_FAIL_QUARANTINE = 3


def _load_fails() -> dict:
    try:
        return json.loads(_FAILS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_fails(d: dict) -> None:
    try:
        _FAILS.parent.mkdir(parents=True, exist_ok=True)
        _FAILS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _note_fail(slug: str) -> None:
    d = _load_fails()
    n = int(d.get(slug, 0)) + 1
    d[slug] = n
    _save_fails(d)
    if n == _FAIL_QUARANTINE:
        log_ops("渲染隔離", f"連續失敗 {n} 次 → 暫停重試(修好後從 render_failures.json 移除):{slug[:44]}")


def _note_ok(slug: str) -> None:
    d = _load_fails()
    if d.pop(slug, None) is not None:
        _save_fails(d)


def _quarantined(slug: str) -> bool:
    return int(_load_fails().get(slug, 0)) >= _FAIL_QUARANTINE


def run_cloud(maxn: int) -> int:
    todo = [x for x in cloud_pending() if not _quarantined(x)][:maxn]
    done = 0
    for slug in todo:
        # 單例鎖心跳:一輪 --max 20 可能跑超過 _PROC_LOCK_STALE,不更新的話鎖會被判過期、
        # 下一個排程實例就會接手 → 又變成兩個一起渲。每支片更新一次 mtime 即可。
        try:
            if _PROC_LOCK.exists():
                _PROC_LOCK.write_text(f"{os.getpid()} {_now():.0f}", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        if not _claim_local(slug):
            continue
        try:
            if _render_local(slug):
                done += 1
                _note_ok(slug)
                log_ops("雲端渲染", f"渲染完成：{slug}")
            else:
                _note_fail(slug)
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


# 🔴 2026-07-28 產線事故修復:**行程級單例鎖**。
# 本檔原本只有 per-slug 鎖(output/{slug}.lock,防兩邊渲同一支),但**沒有任何東西限制
# 同時有幾個 hybrid_render 在跑**。crontab 那行靠 `flock -n /tmp/hr_cloud.lock` 防重入——
# 那是 **Linux 指令,搬到本機 Windows 後根本不存在**,而 local_cron 的 SKIP_MARKERS 也沒有
# 收 "flock"(檔頭 docstring 宣稱會略過 flock,**與實作不符**),於是每 15 分鐘就疊加一個實例。
# 實測 2026-07-28 09:40:同時 20 個 hybrid_render + 16 個 make_video + 27 個 ffmpeg,
# 15.7GB 記憶體只剩 0.4GB(3%),產線連續噴 MemoryError 與 ffmpeg 逾時 600s、當天渲染全數失敗。
# per-slug 鎖擋不住這種:每個實例各自挑不同影片,誰也沒違規,合起來把機器壓垮。
_PROC_LOCK = OUT / ".hybrid_render.proc.lock"
_PROC_LOCK_STALE = 3600     # 秒;超過視為上個實例已崩潰,可接手


def _acquire_proc_lock() -> bool:
    """同時只准一個 hybrid_render 在跑。回 True=拿到鎖。心跳用 mtime,崩潰後 1 小時自動可接手。"""
    try:
        if _PROC_LOCK.exists() and (_now() - _PROC_LOCK.stat().st_mtime) < _PROC_LOCK_STALE:
            return False
        _PROC_LOCK.parent.mkdir(parents=True, exist_ok=True)
        _PROC_LOCK.write_text(f"{os.getpid()} {_now():.0f}", encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001 — 鎖機制自己壞掉不可以擋住渲染(fail-open,回到舊行為)
        return True


def _release_proc_lock() -> None:
    try:
        if _PROC_LOCK.exists():
            _PROC_LOCK.unlink()
    except Exception:  # noqa: BLE001
        pass


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
    if not _acquire_proc_lock():
        _age = _now() - _PROC_LOCK.stat().st_mtime
        print(f"[hybrid] 已有實例在跑({_age:.0f}s 前),本次跳過(防記憶體耗盡)。")
        return 0
    import atexit
    atexit.register(_release_proc_lock)
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
