#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""binge_chain.py — 個股體檢連載的「下一集」追劇鏈:每集描述最上方放下一集連結。

## 為什麼(2026-08-21,Carson 指令:讓人影片一部一部接著看)
個股體檢 EP1~EP87 完美連號、全部有 videoId,但**沒有任何一集連到下一集**——
觀眾看完 EP5 就斷了,要自己去翻頻道。而數據說追劇是本頻道訂閱的主要來源:
    訂閱幾乎全來自長片;EP0/系列說明片轉化 5.81%/8.33%(一般片 0.67%)
    RELATED_VIDEO 來源近 30 天 +1196%(觀眾確實會從一支跳到下一支,只是沒有路)
「下一集」連結放**描述第一行**:影片播完觀眾打開描述,第一眼就是下一集。
YouTube 也會把描述前排連結算進影片間的關聯訊號。

## 為什麼不用 end screen
YouTube Data API **沒有** end screen 端點(只能在 Studio 手動設)。
描述連結 + 播放清單是 API 能自動化的最強替代。

## 安全設計(同 fix_period_disclaimer 的手法)
- **插入不取代**:videos.list 取回完整 snippet,只在 description 前面插一行,
  title/tags/categoryId 原樣送回(videos.update 是整包覆蓋,漏帶=清空)。
- 原 snippet 備份 STUDIO/desc_backup/<vid>.json(共用備份區)。
- 冪等:已含「▶ 下一集」標記就跳過;--refresh 可強制更新(當下一集變了)。
- EP 對映來自 checkup_ep_ledger.json 的 assigned(發布時指派的正式編號,非猜的)。
- 最新一集(沒有下一集)自動跳過,等新集發布後下次跑自然補上——所以要排每日排程。
- 預設 dry-run;--max 控配額(51 units/支)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
MARK = "▶ 下一集"


def _ep_chain():
    """回 [(ep, slug, videoId)],依 EP 排序。key 可能是截斷 slug,用前綴比對回 ledger。"""
    ep = json.loads((STUDIO / "checkup_ep_ledger.json").read_text(encoding="utf-8"))["assigned"]
    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))

    def vid_of(k):
        if k in led:
            return led[k]
        hits = [v for s, v in led.items() if s.startswith(k) or k.startswith(s)]
        return hits[0] if len(hits) == 1 else None

    rows = [(n, k, vid_of(k)) for k, n in sorted(ep.items(), key=lambda x: x[1])]
    return [r for r in rows if r[2]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max", type=int, default=40, help="本輪最多幾支(51 units/支)")
    ap.add_argument("--refresh", action="store_true", help="已有下一集行也重寫(下一集變了時用)")
    args = ap.parse_args()

    import daily_publish as dp
    chain = _ep_chain()
    print(f"EP 鏈:{len(chain)} 集(EP{chain[0][0]}~EP{chain[-1][0]})")

    yt = dp.get_service()
    bk = STUDIO / "desc_backup"
    bk.mkdir(exist_ok=True)
    n = skip = 0
    # 由新往舊做:最新幾集的觀眾還在,鏈上去馬上有用;老片的鏈是長尾。
    pairs = list(zip(chain, chain[1:]))          # (本集, 下一集)
    for (ep_n, _slug, vid), (nx_n, nx_slug, nx_vid) in reversed(pairs):
        if n >= args.max:
            print(f"[quota] 達本輪上限 {args.max},其餘下次續(冪等)")
            break
        try:
            r = yt.videos().list(part="snippet", id=vid).execute()
            items = r.get("items") or []
            if not items:
                skip += 1
                continue
            sn = items[0]["snippet"]
            desc = sn.get("description") or ""
            line = f"{MARK}(EP{nx_n}):https://youtu.be/{nx_vid}"
            if MARK in desc:
                if not args.refresh or line in desc:
                    skip += 1
                    continue
                # refresh:換掉舊的下一集行(只動那一行)
                desc = "\n".join(line if l.startswith(MARK) else l
                                 for l in desc.splitlines())
                new_desc = desc
            else:
                new_desc = line + "\n" + desc
            if len(new_desc) > 4990:
                skip += 1
                continue
            print(f"  ✏ EP{ep_n} → EP{nx_n}  ({vid})")
            if not args.apply:
                n += 1
                continue
            (bk / f"{vid}.json").write_text(json.dumps(sn, ensure_ascii=False), encoding="utf-8")
            body = {"id": vid, "snippet": {
                "title": sn.get("title"), "description": new_desc,
                "categoryId": sn.get("categoryId"), "tags": sn.get("tags", []),
            }}
            if sn.get("defaultLanguage"):
                body["snippet"]["defaultLanguage"] = sn["defaultLanguage"]
            yt.videos().update(part="snippet", body=body).execute()
            n += 1
        except Exception as exc:  # noqa: BLE001
            print(f"     [warn] EP{ep_n}: {str(exc)[:110]}", file=sys.stderr)
    print(f"\n{'已鏈' if args.apply else '將鏈'} {n} 集(跳過 {skip})")
    if args.apply and n:
        try:
            from ops import log_ops
            log_ops("追劇鏈", f"下一集連結 {n} 集")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
