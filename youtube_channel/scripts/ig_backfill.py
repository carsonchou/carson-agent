#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ig_backfill.py — 把『已上 YouTube 的庫存 Shorts』補發到 IG/FB/Threads。
   各平台內容發布 API 都有 ~25 篇/24h 上限,所以每輪有上限,排 cron 每天自動補一批直到清空。

   來源＝STUDIO/uploaded_ledger.json 裡 S_ 開頭、mp4 還在、且不在該平台 ledger 的。
   用法:python scripts/ig_backfill.py [--max 18] [--platforms ig,fb,threads] [--all] [--dry-run]
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
UP_LEDGER = ROOT / "STUDIO" / "uploaded_ledger.json"
LEDGER_PATH = {
    "ig": ROOT / "STUDIO" / "ig_ledger.json",
    "fb": ROOT / "STUDIO" / "fb_ledger.json",
    "threads": ROOT / "STUDIO" / "threads_ledger.json",
}
MODULE_NAME = {"ig": "ig_reels_upload", "fb": "fb_reels_upload", "threads": "threads_upload"}
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT / "scripts"))
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass
try:
    from studio_common import save_json_atomic
except Exception:
    def save_json_atomic(path, data, keep_bak=True):  # noqa: ARG001
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_env():
    """直跑時把專案根 .env 併進 os.environ(cron 由 local_cron 載;直跑沒有→IG token 讀不到→誤判整平台未設定跳過)。"""
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()


def _load(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


import datetime as _dt
RENDER_CUTOFF = _dt.datetime(2026, 6, 25).timestamp()  # 早於此=舊渲染,不補(--all 可略過此限制)


def _platform_configured(platform: str) -> bool:
    """該平台 token 是否到位;沒到位就整平台跳過,不要列一堆待發清單然後每支必敗。
    ig 主路徑改走 litterbox 直傳(見 ig_reels_upload._upload_filehost),不再需要預先設好
    公開影片網址(IG_VIDEO_BASE/tunnel)才算「有設定」——那條只在 litterbox 失敗時當備援。"""
    if platform == "ig":
        return bool(os.environ.get("IG_USER_ID") and os.environ.get("IG_ACCESS_TOKEN"))
    try:
        return __import__(MODULE_NAME[platform]).configured()
    except Exception:
        return False


def pending(platform: str, skip_cutoff: bool = False) -> list:
    if not _platform_configured(platform):
        return []
    up = _load(UP_LEDGER)
    led = _load(LEDGER_PATH[platform])
    try:
        import studio_common as _sc
        _banned = _sc.is_banned_skeleton
    except Exception:  # noqa: BLE001
        def _banned(_t):
            return False
    out = []
    for slug in up:
        if not slug.startswith("S_"):
            continue
        if slug.endswith("_ytcta"):
            continue  # 衍生片尾卡檔,非原片
        if slug in led:
            continue
        if _banned(slug):
            continue  # 洗版骨架舊片(爆倉還活著等),不跨發到 IG
        mp4 = OUT / f"{slug}.mp4"
        if not mp4.exists():
            continue
        if not skip_cutoff and mp4.stat().st_mtime < RENDER_CUTOFF:  # 舊渲染(無新字幕/舊音)不補
            continue
        out.append(slug)
    return out


def _backfill_platform(platform: str, max_n: int, dry_run: bool, skip_cutoff: bool) -> None:
    if not _platform_configured(platform):
        print(f"[skip] [{platform}] 尚未設定(缺 token 或公開影片網址)，整平台跳過(非錯誤)")
        return
    if platform == "ig":
        # 主路徑是 litterbox 直傳,不受 tunnel 死活影響 → litterbox 可達就不管 tunnel。
        # 只有 litterbox 也不可達時,才退回舊的 tunnel 健康檢查當整批開閘門(別對每支硬打失敗)。
        try:
            mod = __import__("ig_reels_upload")
            if hasattr(mod, "litterbox_reachable") and mod.litterbox_reachable():
                pass  # litterbox 可用,不看 tunnel,照常整批發
            elif not mod.tunnel_healthy():
                print("[skip] [ig] litterbox 不可達且 tunnel 也不通,本輪整批跳過(非錯誤,下輪 cron 再試)")
                return
        except Exception as e:  # noqa: BLE001
            print(f"[skip] [ig] 健康檢查失敗，本輪跳過：{e}")
            return
    todo = pending(platform, skip_cutoff)
    print(f"[info] [{platform}] 待補發：{len(todo)} 支，本輪上限 {max_n}")
    if dry_run:
        for s in todo[:max_n]:
            print(f"  [{platform}] -", s)
        print(f"[dry-run] [{platform}] 本輪會發前 {min(max_n, len(todo))} 支，剩 {max(0, len(todo) - max_n)} 支留下輪")
        return
    if not todo:
        print(f"[ok] [{platform}] 沒有待補發的 Shorts，已跟上。")
        return

    mod = __import__(MODULE_NAME[platform])
    ledger_path = LEDGER_PATH[platform]
    led = _load(ledger_path)
    done = 0
    for slug in todo[:max_n]:
        print(f"\n=== [{platform}] 補發 ({done + 1}/{min(max_n, len(todo))}) {slug} ===")
        try:
            mid = mod.publish(slug)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] [{platform}] 失敗 {slug}: {e}", file=sys.stderr)
            mid = None
        if mid:
            led[slug] = mid
            save_json_atomic(ledger_path, led)
            done += 1
            time.sleep(3)  # 禮貌間隔
        else:
            print(f"[skip] [{platform}] {slug} 這輪沒成功,下輪再試")
    remain = len(pending(platform, skip_cutoff))
    log_ops(f"{platform.upper()}補發", f"本輪補發 {done} 支，剩 {remain} 支待補")
    print(f"\n[done] [{platform}] 本輪補發 {done} 支，剩 {remain} 支留下輪。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=18, help="本輪每平台最多補發幾支(各平台限 ~25/24h)")
    ap.add_argument("--platforms", type=str, default="ig", help="逗號分隔:ig,fb,threads")
    ap.add_argument("--all", action="store_true", help="略過 RENDER_CUTOFF,整庫 S_ 都可回填")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    for p in platforms:
        if p not in LEDGER_PATH:
            print(f"[FATAL] 未知平台：{p}(可用 ig,fb,threads)", file=sys.stderr)
            return 2

    for p in platforms:
        _backfill_platform(p, args.max, args.dry_run, args.all)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
