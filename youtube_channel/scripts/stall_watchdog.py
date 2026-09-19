#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stall_watchdog.py — 管線停擺偵測守衛(治「壞了不吭聲」的系統性 meta-fix)。

背景:2026-07 一連串問題(TikTok cron 用錯 python 靜默跳過、IG tunnel 死掉、產線卡)的共同病根是
**靜默失敗**——cron 顯示「✓ 完成」卻沒真做事,ledger/output 悄悄停更好幾天才被發現。
這支守衛每天檢查各管道「最後一次真的有動」的時間,超過門檻=疑似停擺→ntfy 推 Carson,別再默默壞掉。

檢查(看『最後活動時戳』,非看 cron 有沒有跑——因為 cron 跑了不代表有做事):
  產片(output/*.voice.txt)、渲染(output/*.mp4)、YT發布(uploaded_ledger)、
  TikTok(tiktok_ledger)、IG(ig_ledger)。
排程:cron 每天一次(建議 10:00,各管道當天該動的都動完了)。手動:python scripts/stall_watchdog.py [--dry]
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass
try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):  # noqa: ARG001
        pass

H = 3600
# (名稱, 判定用的最新時戳來源, 停擺門檻小時) — 門檻=正常間隔 + 緩衝
CHECKS = [
    ("產片(短片腳本)", "glob", "S_*.voice.txt", 20),
    ("渲染(短片成片)", "glob", "S_*.mp4", 22),
    # 🔴 2026-07-17 補長片盲區:本 watchdog 存在的理由就是治「靜默失敗」，卻只盯 S_*——
    # 長片產線整條死掉、短片照跑時,它全綠、daily_health 全綠、local_cron 記「✓ 完成」、
    # 決策中心不列異常 = 完全無人知道。而 2026-07-17 起長片是頻道主力格式(只有長片計入
    # YPP 的 4,000 watch hours),產能已連兩天掛掉(07-16 批次被外力砍、07-17 queue_size
    # bug 整批跳過),可發庫存一度只剩 3 天。把賭注押在長片、卻不監控長片,是說不過去的。
    # 門檻放寬到 30h:長片每天 06:07 產(--long 5)、12:30 有保底補產,超過 30h 沒新腳本
    # 就是連兩批都沒跑成 = 距離斷炊剩 1-2 天,該叫了。
    ("產片(長片腳本)", "glob", "L_*.voice.txt", 30),
    ("渲染(長片成片)", "glob", "L_*.mp4", 30),
    ("YT 發布", "ledger", "uploaded_ledger.json", 30),
    ("TikTok 跨發", "ledger", "tiktok_ledger.json", 30),
    ("IG 跨發", "ledger", "ig_ledger.json", 40),
]


def _newest_glob(pattern: str) -> float:
    """output/ 下符合 pattern(排除 _ytcta 衍生)的最新 mtime;無檔回 0。"""
    latest = 0.0
    for p in OUT.glob(pattern):
        if p.name.endswith("_ytcta.voice.txt") or p.name.endswith("_ytcta.mp4"):
            continue
        try:
            latest = max(latest, p.stat().st_mtime)
        except Exception:  # noqa: BLE001
            pass
    return latest


def _ledger_mtime(fn: str) -> float:
    p = STUDIO / fn
    try:
        return p.stat().st_mtime if p.exists() else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def _check_truncation():
    """P0 止血(2026-07-13)：每日順帶掃斷尾壞檔(成品比旁白短很多)，尤其揪已發布到
    YouTube 的——04_0056 事故(旁白218.9s/成品61.7s)就是這樣悄悄過關的，audit_video 只
    在『產製當下』把關，已發布的舊片不會再被複查，靠這裡補上事後巡檢。回傳
    (published_bad, all_bad)：published_bad 是已發布仍異常的清單(最急)。"""
    try:
        import audit_truncation as _at
        rows = _at.audit_all()
    except Exception as exc:  # noqa: BLE001
        print(f"[stall_watchdog] 截斷檢查略過(audit_truncation 不可用：{exc})")
        return [], []
    bad = [r for r in rows if r["status"] not in ("正常",)]
    published_bad = [r for r in bad if r.get("video_id")]
    return published_bad, bad


def main() -> int:
    dry = "--dry" in sys.argv
    now = time.time()
    stalled = []
    lines = []
    for name, kind, arg, thr_h in CHECKS:
        ts = _newest_glob(arg) if kind == "glob" else _ledger_mtime(arg)
        age_h = (now - ts) / H if ts else 9999
        ok = age_h <= thr_h
        lines.append(f"  [{'ok ' if ok else 'STALL'}] {name}: 最後活動 {age_h:.1f}h 前(門檻{thr_h}h)")
        if not ok:
            stalled.append(f"{name}(停{age_h:.0f}h)")
    print("[stall_watchdog] 管線活動檢查:")
    print("\n".join(lines))

    published_bad, all_bad = _check_truncation()
    if all_bad:
        print(f"[stall_watchdog] 斷尾/異常成片 {len(all_bad)} 支(已發布 {len(published_bad)} 支)：")
        for r in all_bad[:10]:
            pub = f" videoId={r['video_id']}" if r.get("video_id") else ""
            print(f"    [{r['status']}] {r['slug'][:40]} ratio={r['ratio']}{pub}")
    else:
        print("[stall_watchdog] 斷尾檢查：零異常")

    if not stalled and not all_bad:
        log_ops("停擺守衛", "各管道正常,無停擺,無斷尾壞檔")
        print("[stall_watchdog] 全部正常")
        return 0

    msgs = []
    if stalled:
        msgs.append("⚠️ 管線疑似停擺:" + "、".join(stalled) +
                    "。cron 可能『跑了✓完成卻沒真做事』(靜默失敗),去查對應 log/ledger。")
    if published_bad:
        names = "、".join(f"{r['slug'][:20]}(videoId={r['video_id']})" for r in published_bad[:5])
        msgs.append(f"🚨 已發布但疑似斷尾/異常 {len(published_bad)} 支：{names}"
                    "。旁白沒剪完就上架了,去查 scripts/audit_truncation.py 全清單。")
    elif all_bad:
        msgs.append(f"⚠️ 偵測到 {len(all_bad)} 支斷尾/異常成片(未發布)，production 產線本身有問題，"
                    "去查 scripts/audit_truncation.py。")
    msg = " ".join(msgs)
    print(f"[stall_watchdog][ALERT] {msg}")
    log_ops("停擺守衛", msg)
    if not dry:
        try:
            from notify import push
            push("量化阿森·停擺守衛", msg[:190], tag="rotating_light")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
