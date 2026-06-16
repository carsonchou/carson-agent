#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refresh_library.py — 【完整更新片庫·現有片】把已發布影片的標題換成新 CTR 公式（M）。

只動「能改」的 metadata：標題（可選描述）。影片畫面/旁白是已上傳像素，不能改（要改＝重做新片）。
安全機制：
  - videos().update(part=snippet) 會覆蓋整個 snippet → 先抓現有 snippet，只換 title/description，
    其餘（categoryId/tags…）原樣保留。
  - 套用前先把舊標題全部備份到 STUDIO/title_backup_{ts}.json（可一鍵還原）。
  - --dry 先產全部新標題、印出對照，不動線上任何東西。
用法：
  python scripts/refresh_library.py --dry              # 只產新標題、印對照
  python scripts/refresh_library.py                    # 備份後套用新標題
  python scripts/refresh_library.py --restore <file>   # 從備份還原標題
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import os
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
LEDGER = STUDIO / "uploaded_ledger.json"
TW = timezone(timedelta(hours=8))
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"  # 改標題要懂公式與分寸，用較強模型

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass

# 標題公式 M（濃縮自 playbook，守誠實鐵則）
FORMULA = (
    "高 CTR 標題公式（擇一套用、自然，數字一律用含回撤的誠實值，禁『躺賺/穩賺/保證』）：\n"
    "①精確數字＋括號代價「網格回測勝率87.5%（但有個代價你必須知道）」②疑問句實測「派網機器人真的能賺嗎？我給它$1000跑10天」\n"
    "③反共識先破後立「大家都說網格穩賺？我用回測打臉」④痛點百分比「90%玩網格在賠，問題出在這1個參數」\n"
    "⑤實驗格式「我丟1萬給機器人跑30天，沒看盤，結果公開（含回撤）」⑥好奇缺口「回測贏實盤虧，這個數字一秒拆穿過擬合」")


def tw_ts():
    return datetime.now(TW).strftime("%Y%m%d_%H%M")


def load_ledger():
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def gen_titles(pairs):
    """pairs: [(vid, old_title)]。一次請 Claude 重寫全部，回 {vid: new_title}。"""
    listing = "\n".join(f"{i}. {old}" for i, (_, old) in enumerate(pairs))
    prompt = f"""你是量化阿森頻道（量化/網格/定投/派網Pionex/回測/風控，繁中）的標題優化師。{FORMULA}

下面是頻道現有影片的舊標題。請逐支重寫成更高點擊慾的新標題，規則：
- **主題必須與原標題一致**（只是換更強的框架，不可偏題）。
- 套用上面公式，但彼此用不同開法、不要每支都同一句型（避免 Shorts 動態牆重複感）。
- 不誇大、不喊單、不保證收益；數字用含回撤的誠實值。
- 長度適中（適合手機顯示），可含 1 個數字或懸念。

舊標題清單：
{listing}

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄），i 對應上面編號：
[{{"i":0,"title":"新標題"}}, ...]"""
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": MODEL, "max_tokens": 4000,
                            "messages": [{"role": "user", "content": prompt}]}, timeout=180)
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
    m = re.search(r"\[.*\]", txt, re.S)
    arr = []
    if m:
        try:
            arr = json.loads(m.group(0))
        except Exception:
            for om in re.finditer(r"\{[^{}]*\}", txt, re.S):
                try:
                    arr.append(json.loads(om.group(0)))
                except Exception:
                    continue
    out = {}
    for o in arr:
        try:
            i = int(o["i"]); t = (o.get("title") or "").strip()
            if 0 <= i < len(pairs) and t:
                out[pairs[i][0]] = t
        except Exception:
            continue
    return out


def restore(yt, path):
    backup = json.loads(Path(path).read_text(encoding="utf-8"))
    ok = 0
    for vid, old in backup.items():
        try:
            r = yt.videos().list(part="snippet", id=vid).execute()
            items = r.get("items", [])
            if not items:
                continue
            sn = items[0]["snippet"]; sn["title"] = old
            yt.videos().update(part="snippet", body={"id": vid, "snippet": sn}).execute()
            ok += 1
            print(f"[restore] {vid} → {old}")
        except Exception as e:  # noqa: BLE001
            print(f"[err] {vid}: {e}", file=sys.stderr)
    print(f"== 還原 {ok}/{len(backup)} ==")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只產新標題印對照，不動線上")
    ap.add_argument("--restore", default=None, help="從備份檔還原標題")
    ap.add_argument("--limit", type=int, default=0, help="只處理前 N 支（0=全部）")
    args = ap.parse_args()
    if not API_KEY and not args.restore:
        print("[FATAL] 無 ANTHROPIC_API_KEY", file=sys.stderr); return 2

    from daily_publish import get_service
    yt = get_service()

    if args.restore:
        return restore(yt, args.restore)

    ledger = load_ledger()
    if not ledger:
        print("[FATAL] 找不到 uploaded_ledger.json（沒有已發布影片清單）", file=sys.stderr); return 2
    vids = list(ledger.values())
    if args.limit:
        vids = vids[:args.limit]

    # 抓現有 snippet
    pairs, snippets = [], {}
    for i in range(0, len(vids), 50):
        rr = yt.videos().list(part="snippet", id=",".join(vids[i:i+50])).execute()
        for it in rr.get("items", []):
            snippets[it["id"]] = it["snippet"]
            pairs.append((it["id"], it["snippet"].get("title", "")))
    if not pairs:
        print("[info] 線上抓不到任何影片（可能已刪）。"); return 0

    print(f"== 現有已發布影片：{len(pairs)} 支，產新標題中… ==")
    newmap = gen_titles(pairs)
    if not newmap:
        print("[FATAL] 產不出新標題", file=sys.stderr); return 3

    if args.dry:
        print("\n===== 新標題對照（--dry，未套用）=====")
        for vid, old in pairs:
            nt = newmap.get(vid)
            if nt and nt != old:
                print(f"\n舊：{old}\n新：{nt}")
        print(f"\n（共 {sum(1 for v,o in pairs if newmap.get(v) and newmap[v]!=o)} 支會更動）")
        return 0

    # 備份舊標題
    backup = {vid: snippets[vid].get("title", "") for vid, _ in pairs}
    bpath = STUDIO / f"title_backup_{tw_ts()}.json"
    bpath.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[backup] 舊標題已備份 → {bpath.name}（要還原：--restore {bpath.name}）")

    ok = 0
    for vid, old in pairs:
        nt = newmap.get(vid)
        if not nt or nt == old:
            continue
        try:
            sn = snippets[vid]; sn["title"] = nt
            yt.videos().update(part="snippet", body={"id": vid, "snippet": sn}).execute()
            ok += 1
            print(f"[ok] {vid}\n   舊：{old}\n   新：{nt}")
        except Exception as e:  # noqa: BLE001
            print(f"[err] {vid}: {e}", file=sys.stderr)
    log_ops("片庫更新", f"現有片標題套新公式 {ok}/{len(pairs)} 支（備份 {bpath.name}）")
    print(f"\n== 完成：更新 {ok} 支線上標題（備份在 {bpath.name}）==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
