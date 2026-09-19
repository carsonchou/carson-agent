#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""set_channel_front.py — 頻道門面:預告片 + 簡介。**寫入前備份,寫入後回讀。**

## 為什麼要動這兩個
2026-08-31 量到 289 次觀看換到 1 個訂閱。訂閱的決策點有兩個:Short 本身,
以及**點進頻道之後看到的東西**。而頻道現在:

- **沒有設 `unsubscribedTrailer`** —— 非訂閱者進頻道時本來會自動播一支,
  那是最大的一個轉化面,現在是空的。
- **簡介寫著「每個數字都來自 FReD 資料庫」** —— 而新的十題是逐篇讀原文
  抽出來的,不是 FReD。這個頻道賣的就是精確,簡介裡有一句不精確的話,
  而且正好是關於「我們怎麼確保精確」的那一句。
  (同型:[[yt-integrity-methodology-claims-blindspot]] —— 方法論宣稱是
   守門結構上看不見的那一類。)

## 🔴 這個 API 會靜默失敗
`channels.update` 對**頻道名稱**會回 HTTP 200 而**完全不改**(實測,已寫進
memory)。所以這支一定要:
  1. 先把現值存成備份檔(可還原)
  2. 寫入
  3. **回讀比對**,不一致就回報失敗 —— 不准拿 200 當成功

## 不做的事
頻道名稱與 @代號**不在這支的範圍內**:它們只能在 Studio UI 改,而且
名稱要等 2026-09-03。那兩個要 Carson 親手點。

用法:
  python set_channel_front.py --dry-run
  python set_channel_front.py --apply
  python set_channel_front.py --restore _backup/channel_front_<ts>.json
"""
import argparse
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

#: 預告片:ep0(25 個宣稱的戰績)。理由是它一支就把這個頻道**是什麼**
#: 講完了,而其他每一支都只是其中一個案例。
TRAILER_KEY = "ep0"

DESCRIPTION = """Famous studies, tested again - with the numbers.

Every episode takes one claim people repeat as fact, shows what the original study measured, and what happened when somebody checked.

How it works:
- Newer episodes are built by reading the two papers directly. Older ones come from the FORRT Replication Database, and say so.
- Both papers are cited with their DOIs, so you can go and look.
- Citation counts are rounded down and always said as "more than", so the figure on screen is never larger than the real one.
- Where a number could not be got out of the original document, the description names which one.
- "It did not replicate" is not one story. Sometimes the finding was never there. Sometimes it is real but much smaller than the headline. Sometimes the original analysis was the problem, not the result. Sometimes the argument is still running.
- Findings that survived a larger test get their own episodes.
- No voice actor, no stock footage. The charts are the data."""


def svc():
    from upload import svc as _s
    return _s()


def current(y):
    r = y.channels().list(part="brandingSettings,snippet", mine=True).execute()
    return r["items"][0]


#: YouTube 頻道簡介上限。**姊妹工具 `rebrand.py:66` 自己就印過這個數字**,
#: 而這支從來沒查過 —— 實測寫到 1115 字元,超出 115。切點正好落在
#: 第五條 bullet 中間:靜默截斷的話簡介會停在半個字、最後兩條消失;
#: 回 400 的話備份已寫但預告片也沒設。
#: (memory `read-the-sibling-tool-first`:我新寫的工具的阻斷項,
#:  解法往往已經寫在同 repo 隔壁那支上過正式機的工具裡。)
DESC_LIMIT = 1000

if len(DESCRIPTION) > DESC_LIMIT:
    raise SystemExit(
        f"⛔ 簡介 {len(DESCRIPTION)} 字元,超過 YouTube 的 {DESC_LIMIT} 上限 "
        f"{len(DESCRIPTION) - DESC_LIMIT} 字。截斷會停在半句話,"
        f"而截斷點在第 {DESCRIPTION[:DESC_LIMIT].count(chr(10) + '-') + 1} 條 bullet 上。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore")
    a = ap.parse_args()

    import quota
    y = svc()

    if a.restore:
        bak = json.loads(pathlib.Path(a.restore).read_text(encoding="utf-8"))
        body = {"id": bak["id"], "brandingSettings": bak["brandingSettings"]}
        y.channels().update(part="brandingSettings", body=body).execute()
        quota.spend(50, "channel restore")
        print(f"已還原 {a.restore}")
        return 0

    c = current(y)
    quota.spend(1, "channel read")
    ch = dict(c["brandingSettings"].get("channel") or {})
    print(f"目前:title={ch.get('title')!r}")
    print(f"      trailer={ch.get('unsubscribedTrailer') or '(沒有設)'}")

    led = json.loads((ROOT / "uploaded.json").read_text(encoding="utf-8"))
    vid = led.get(TRAILER_KEY)
    if not vid:
        raise SystemExit(f"⛔ 帳本裡找不到 {TRAILER_KEY} —— 不能設一支不存在的預告片")
    # 🔴 預告片必須是 **public**。設一支 private/unlisted 的等於頻道首頁
    #    有一個播不出來的洞,而且 API 不會抱怨。
    st = y.videos().list(part="status,snippet", id=vid).execute()
    quota.spend(1, "trailer check")
    if not st.get("items"):
        raise SystemExit(f"⛔ {vid} 查不到")
    pv = st["items"][0]["status"]["privacyStatus"]
    if pv != "public":
        raise SystemExit(f"⛔ {TRAILER_KEY}({vid})是 {pv},不是 public —— 不設")
    print(f"預告片將設為 {TRAILER_KEY} = {vid}")
    print(f"  「{st['items'][0]['snippet']['title']}」")

    if not a.apply:
        print("\n--dry-run:沒有寫入。加 --apply 才會真的改。")
        print("\n新的簡介:\n" + DESCRIPTION)
        return 0

    bdir = ROOT / "_backup"; bdir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = bdir / f"channel_front_{ts}.json"
    bak.write_text(json.dumps({"id": c["id"],
                               "brandingSettings": c["brandingSettings"]},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"備份 → {bak}")

    ch["unsubscribedTrailer"] = vid
    ch["description"] = DESCRIPTION
    body = {"id": c["id"], "brandingSettings":
            {**c["brandingSettings"], "channel": ch}}
    y.channels().update(part="brandingSettings", body=body).execute()
    quota.spend(50, "channel update")

    # 🔴 **回讀,不要信 200。** 同一個 API 對頻道名稱就是回 200 而不改的。
    time.sleep(3)
    after = current(y).get("brandingSettings", {}).get("channel", {})
    quota.spend(1, "channel readback")
    ok = True
    if after.get("unsubscribedTrailer") != vid:
        print(f"⛔ 預告片沒寫進去:回讀是 "
              f"{after.get('unsubscribedTrailer') or '(空的)'}")
        ok = False
    if (after.get("description") or "").strip() != DESCRIPTION.strip():
        print("⛔ 簡介沒寫進去(回讀與送出的不一致)")
        ok = False
    if ok:
        print("✓ 回讀確認:預告片與簡介都寫進去了")
        return 0
    print(f"   還原用:python set_channel_front.py --restore {bak}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
