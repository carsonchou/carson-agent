#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""channel_brand.py — 設定頻道門面(名稱/說明/關鍵字/國家/語言)。

## 為什麼要一支專門的
`channels.update` 的 brandingSettings 是**整包覆寫**:只送你想改的那一個欄位,
其餘欄位會被清掉。所以一定要「先讀回整包 → 只動目標欄位 → 整包寫回」。
這支就是把那個順序固定下來,免得每次手寫都要重想一次。

## API 改得到 / 改不到(2026-08-17 實測)
  改得到:description、keywords、country、defaultLanguage
  改不到:**title(頻道名稱)**、**@handle**、大頭貼、橫幅、頻道預設「是否為兒童內容」

🔴 **title 是最陰的一個:API 會收下請求、回 200、不報任何錯,但值根本沒變。**
   實測 channels.update(brandingSettings) 送 title='AI 實測室',回應與後續 list
   讀回來都還是舊值 'Ai dancing'。頻道名稱綁在 Google/品牌帳戶層級,
   只能在 Studio(youtube.com/customize)或 Google 帳戶設定改。
   → 本檔因此**每次寫入後一定從 API 回讀比對**,不信任 update 的回應。
      沒有這道回讀,就會發生「回報已改名、其實沒動」。

  handle 改在 https://www.youtube.com/handle

## 安全
- 預設 --dry-run,只印出「改前 → 改後」的差異,不寫入
- --channel 指定要操作哪個頻道(讀 channels/<slug>/token_manage.json),
  **不指定就用現役 token**——這是為了避免「以為在設副頻道、其實改到主頻道」

用法:
  python scripts/channel_brand.py --channel ch2                       # 看現況
  python scripts/channel_brand.py --channel ch2 --title "新名字" --apply
  python scripts/channel_brand.py --channel ch2 --title "X" --desc-file d.txt \\
      --keywords "AI 動畫,短影音" --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
FIELDS = ("title", "description", "keywords", "country", "defaultLanguage")


def svc(channel: str | None):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = (ROOT / "channels" / channel / "token_manage.json") if channel \
        else (ROOT / "token_manage.json")
    if not tok.exists():
        print(f"[!] 找不到 {tok}")
        sys.exit(1)
    cr = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request())
        tok.write_text(cr.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", help="channels/<slug>/;不給就用現役 token")
    ap.add_argument("--title")
    ap.add_argument("--desc")
    ap.add_argument("--desc-file", help="從檔案讀說明(多行用這個)")
    ap.add_argument("--keywords", help="逗號分隔;含空白的詞會自動加引號")
    ap.add_argument("--country")
    ap.add_argument("--lang")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    yt = svc(a.channel)
    it = yt.channels().list(part="snippet,brandingSettings,statistics",
                            mine=True).execute()["items"][0]
    bs = it.get("brandingSettings") or {}
    ch = bs.setdefault("channel", {})
    sn = it["snippet"]
    st = it.get("statistics", {})

    print(f"頻道:{sn['title']}({sn.get('customUrl') or '無 handle'})"
          f"  訂閱 {st.get('subscriberCount')} 影片 {st.get('videoCount')}")
    print(f"目標:{'channels/' + a.channel if a.channel else '現役 token(主頻道)'}\n")

    desc = a.desc
    if a.desc_file:
        desc = Path(a.desc_file).read_text(encoding="utf-8")
    kw = a.keywords
    if kw:
        # YouTube keywords 是空白分隔;含空白的詞必須加引號,否則會被拆成兩個
        kw = " ".join(f'"{w}"' if " " in w else w
                      for w in (x.strip() for x in kw.split(",")) if w)

    want = {"title": a.title, "description": desc, "keywords": kw,
            "country": a.country, "defaultLanguage": a.lang}
    changes = []
    for k in FIELDS:
        v = want.get(k)
        if v is None:
            continue
        old = ch.get(k, "")
        if old != v:
            changes.append((k, old, v))

    if not changes:
        print("沒有要改的欄位。目前設定:")
        for k in FIELDS:
            print(f"  {k:16s} {ch.get(k, '(空)')}")
        return 0

    print("將變更:")
    for k, old, new in changes:
        print(f"  {k}")
        print(f"     改前 {old!r}")
        print(f"     改後 {new!r}")

    if not a.apply:
        print("\n--dry-run:未寫入。加 --apply 才真的改。")
        return 0

    for k, _, new in changes:
        ch[k] = new
    r = yt.channels().update(part="brandingSettings",
                             body={"id": it["id"], "brandingSettings": bs}).execute()
    got = r.get("brandingSettings", {}).get("channel", {})
    print("\n已寫入。API 回讀確認:")
    for k, _, new in changes:
        ok = "✓" if got.get(k) == new else "⚠️ 回讀不符"
        print(f"  {ok} {k} = {got.get(k)!r}")
    print("\n注意:@handle、大頭貼、橫幅、頻道預設兒童內容設定 API 改不到,要在 Studio 設。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
