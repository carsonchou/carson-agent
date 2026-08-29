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
# 黑窗彈跳修復(2026-08-07):這支被 local_cron 用 CREATE_NO_WINDOW 無視窗啟動,
# 但 _render_local 起的 make_video.py 子程序沒帶同一個旗標——父程序沒主控台時,
# 子程序沒指定旗標會自己新開一個可見主控台。每次渲染就跳一次(每 15 分鐘一班)。
_NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


def _now():
    import time as _t
    return _t.time()


def _media_dur(path) -> float:
    """媒體時長(秒);量不到回 0.0。純唯讀,失敗一律回 0 讓呼叫端放行。"""
    # ⚠️ 別用 imageio_ffmpeg.get_ffmpeg_exe().replace("ffmpeg","ffprobe") 推 ffprobe 路徑:
    # 那支叫 ffmpeg-win64-vX.Y.Z.exe,字串替換連目錄名一起換掉 → 路徑不存在 → 這裡永遠回 0
    # → 呼叫端「量不到就放行」→ **閘門靜默全放行**。第一版就是這樣寫的,測出來三支全判正常。
    import subprocess as _sp
    try:
        r = _sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(path)],
                    capture_output=True, text=True, timeout=30)
        v = float((r.stdout or "").strip() or 0)
        if v > 0:
            return v
    except Exception:  # noqa: BLE001
        pass
    # ffprobe 不在 PATH:退回 ffmpeg -i 解 stderr 的 Duration(同 audit_truncation 的作法)
    try:
        import re as _re
        try:
            import imageio_ffmpeg
            _ff = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            _ff = "ffmpeg"
        r = _sp.run([_ff, "-i", str(path)], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=30)
        m = _re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr or "")
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def _render_local(slug: str, env=None) -> bool:
    env = env or os.environ.copy()
    if slug.startswith("S_"):
        env.pop("PEXELS_API_KEY", None)
        args = ["--slug", slug, "--width", "1080", "--height", "1920", "--fps", "15"]
    else:
        args = ["--slug", slug]
    subprocess.run([str(PY), "scripts/make_video.py", *args], cwd=str(ROOT), env=env, **_NO_WINDOW)
    mp4 = OUT / f"{slug}.mp4"
    if not (mp4.exists() and mp4.stat().st_size > 100 * 1024):
        return False
    # 🔴 2026-08-29:原本到上面那行就 return——「檔案在、超過 100KB」就算成功。
    # 那個判準看不見**斷尾**:實測 L_個股體檢聯強2347 的成片音軌只有 461.7s,而旁白
    # mp3 是 569.9s(wordtimes 也走到 560.8s)—— **結尾 108 秒的旁白從沒進畫面**,
    # 而編排層回報「渲染完成」。同批還有聯穎3550(599.0/673.4)。
    # make_video 與 render_ffmpeg 各自都有截斷閘門,而且實測是好的
    # (拿聯強那支去跑 _probe_render_output 會正確回「片長過短」)——問題是那些閘門
    # 驗的是「渲染當下的音檔」,而音檔事後被重配過(memory:改稿重配音三坑之一=截斷 mp3)。
    # 也就是說:**在子程序內部驗,驗不到子程序跑完之後才發生的事。**
    # 這裡改成編排層自己量產物:成片音軌要 >= 旁白的 95%。這道獨立於「跑了哪條渲染路徑」,
    # 也擋得住「音檔後來變長但成片沒跟著重渲」。判不出來就放行(不擋產線)。
    try:
        _v = _media_dur(mp4)
        _a = _media_dur(OUT / f"{slug}.mp3")
        if _v > 0 and _a > 0 and _v < (_a * 0.95):
            log_ops("hybrid_render/斷尾",
                    f"{slug[:40]}:成片 {_v:.1f}s < 旁白 {_a:.1f}s×0.95,判定斷尾不算完成")
            return False
    except Exception:  # noqa: BLE001
        pass
    return True


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
    # 🔴 2026-08-22:原本「鎖 >LOCK_STALE(25分) 就可重認領」**只看鎖檔時間**——長片本來
    #    就渲超過 25 分鐘,慢一點的渲染會被判成崩潰、鎖被搶走,於是同一支片跑出分身
    #    (實況:泰藝 8289 同時兩個 make_video 跑了 239/165 分鐘,把全機記憶體吃到剩 749MB)。
    #    改走 studio_common 的 PID 感知認領:接手必須「鎖過期」**且**「原程序真的不在了」。
    try:
        import studio_common as _sc
        return _sc.claim_render(slug, stale_sec=int(LOCK_STALE))
    except Exception:  # noqa: BLE001
        pass
    lock = OUT / f"{slug}.lock"
    if lock.exists():
        try:
            if _now() - lock.stat().st_mtime < LOCK_STALE:
                return False
        except Exception:
            return False
    try:
        lock.write_text(f"cloud {_now():.0f} pid={os.getpid()}", encoding="utf-8")
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
        # 🔴 記憶體守門(2026-08-20 事故)。本檔上面那道 _PROC_LOCK 防的是「多個實例同時渲」,
        # 但**擋不到別的程式把記憶體吃光**:實測某晚重渲 8 支全數失敗,錯誤碼
        # 3221226091(FATAL_USER_CALLBACK_EXCEPTION)與 1073807364(DBG_TERMINATE_PROCESS),
        # 看起來像渲染壞了,真因是可用實體記憶體只剩 805 MB / 16 GB——被 node(40 個進程
        # 3.5GB)與多個 claude session 吃光,而長片渲染要 1~2GB。
        # 硬跑的代價是每支片跑到一半才崩:十幾分鐘 CPU 白燒,而且失敗訊息會把人引去查錯地方。
        # 判準與 rerender_jitter_fix 共用 studio_common.render_mem_ok(閘門只有一份)。
        try:
            import studio_common as _sc
            _ok, _fm = _sc.render_mem_ok()
            if not _ok:
                print(f"[hybrid] 可用記憶體僅 {_fm} MB(需 {_sc.RENDER_MIN_FREE_MB} MB),"
                      f"本輪停止;待辦保留,下次排程續。", flush=True)
                break
        except Exception:  # noqa: BLE001
            pass
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
# 🔴 2026-08-29 鎖改成**分模式**。原本 --cloud 與 --pc 共用同一把全域鎖,而鎖是在
# 分派模式**之前**取得的 —— 一個 `--pc --loop` 常駐實例會把每 15 分鐘的 `--cloud` cron
# 班全部餓死。實況:Windows 排程工作 CarsonQuant_PCRender(每次登入自啟,
# 見 scripts/_setup_pc_autorender.ps1)跑 `--pc --loop --interval 600`,而 --pc 是
# SFTP 連**雲端 droplet** 的模式,那台早就欠費停權、cloud.json 也不存在了。
# 於是它每 600 秒連線失敗一次、印個錯、繼續睡、**繼續握著鎖**,CPU 用量 0,
# 而 11:30 與 11:45 兩班 cloud 渲染都秒退「已有實例在跑」——待渲染的片就一直積著。
# 兩邊渲的是完全不同的來源(cloud=本機待辦 / pc=雲端待辦),本來就不該互斥;
# 真正要防的「兩個實例同時渲爆記憶體」是**同模式**的重入,分開就好。
# (local_cron.py:176 早就把 crontab 裡的 --pc 濾掉了 —— 但沒人記得還有個 Windows
#  排程工作也在跑它。memory studio-black-window-popups-fix 記過:Windows 排程是
#  另一個容易被遺忘的面,改東西要記得掃它。)
_PROC_LOCK_STALE = 3600     # 秒;超過視為上個實例已崩潰,可接手
_PROC_LOCK = OUT / ".hybrid_render.proc.lock"   # 預設值,main() 依模式覆寫


def _pid_alive(pid: int) -> bool:
    """這個 PID 還活著嗎。查不到一律回 True(fail-safe:寧可多等,不要兩個實例同時渲)。"""
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False          # 開不了 handle = 進程不存在
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == 259   # STILL_ACTIVE
    except Exception:  # noqa: BLE001
        return True


def _acquire_proc_lock() -> bool:
    """同時只准一個 hybrid_render 在跑。回 True=拿到鎖。

    鎖檔內容是「PID 時間戳」。舊版**只看 mtime**:上一個實例崩潰後,
    鎖要空等 _PROC_LOCK_STALE(1 小時)才會被判過期,這段時間所有渲染排程一律跳過
    ——而鎖裡明明就寫著 PID,問一下作業系統就知道那個進程早就不在了。
    (memory yt-quota-budget-2026-07 記著「重啟排程器要先刪 lock」,就是被這個逼出來的
    手動步驟;2026-08-20 又踩到一次:系統上沒有任何渲染進程,鎖卻還有 8 分鐘才過期。)
    現在先問 PID 死活,死了就立刻接手;查不到時 fail-safe 退回原本的時間判斷
    ——寧可多等一小時,也不要兩個實例同時渲(那會直接吃爆記憶體)。
    """
    try:
        if _PROC_LOCK.exists() and (_now() - _PROC_LOCK.stat().st_mtime) < _PROC_LOCK_STALE:
            try:
                _pid = int((_PROC_LOCK.read_text(encoding="utf-8").split() or ["0"])[0])
            except Exception:  # noqa: BLE001
                _pid = 0
            if _pid and not _pid_alive(_pid):
                print(f"[hybrid] 鎖的持有者 PID {_pid} 已不存在,直接接手(不必等過期)。", flush=True)
            else:
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
    # --pc 是 SFTP 連雲端 droplet 的模式。cloud.json 不在 = 沒有雲端可連(droplet 已停權,
    # 產線 2026-07 就搬回本機了)。與其讓它每 600 秒失敗一次、握著鎖空轉,直接退出。
    if args.pc and not (ROOT / "cloud.json").exists():
        print("[hybrid] --pc 需要 cloud.json(SFTP 連雲端),檔案不存在 → 雲端模式已停用,直接結束。\n"
              "         本機待辦請用 --cloud(crontab 每 15 分鐘那班)。\n"
              "         若這是開機自啟的 Windows 排程工作 CarsonQuant_PCRender,它已無用途,"
              "可用系統管理員權限執行:Unregister-ScheduledTask -TaskName CarsonQuant_PCRender -Confirm:$false",
              file=sys.stderr)
        return 0
    global _PROC_LOCK
    _PROC_LOCK = OUT / f".hybrid_render.{'cloud' if args.cloud else 'pc'}.proc.lock"
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
