#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""platform_monetization.py — 三平台原生變現門檻追蹤(E1)。

誠實追蹤 YouTube / TikTok / Instagram 三平台距離「平台原生變現」門檻還差多少,
不畫大餅、缺資料一律標示待補,不臆造數字。

資料來源(全部重用現成,不重抓):
  YouTube  — STUDIO/ypp_progress.json(ypp_tracker.py 已算好的四門檻進度:1000訂閱+4000h/
             或90天1000萬Shorts觀看=標準級廣告分潤;500訂閱+3000h/90天300萬=提前解鎖級 Super Thanks)。
  TikTok   — 無官方公開 API 可查粉絲數;STUDIO/tiktok_state.json 是 Playwright 瀏覽器 session cookie,
             不是統計數據,不能拿來當粉絲數用。粉絲數目前本機無法取得,標記「待人工/session 抓」,
             絕不硬爬網頁(避免帳號被封)。門檻:Creator Rewards Program 需 10,000 粉絲(+30天觀看數
             +滿18歲,同樣待人工核對)。Shop/Tips 開通狀態同樣無 API,標記待查。
  IG       — Instagram Graph API(官方,與 scripts/ig_health_check.py 同一組 .env 憑證
             IG_USER_ID / IG_ACCESS_TOKEN)查 followers_count;沒設定就優雅跳過(非錯誤,不報例外)。
             變現門檻(徽章/聯盟/內容變現)無單一官方統一數字、因地區/方案而異,此處只給近似值參考。

輸出:STUDIO/platform_monetization.json
達標(可開通)時 ntfy 推播 —— 只在「這次新達標、上次還沒達標」時推,不重複洗版
(比照 scripts/ig_health_check.py 的狀態變化通知模式)。
若 STUDIO/northstar.json 已存在,順手把摘要併進去一個 platform_monetization 欄位
(先讀再改,不動其他既有欄位;注意 northstar.py 目前是整檔覆寫產生,下次它排程跑完會蓋掉
這個欄位——這裡只是盡力同步,真正的完整整合待未來有需求再改 northstar.py 本體)。

用法:
  python scripts/platform_monetization.py            # 算進度、寫 json、印摘要
  python scripts/platform_monetization.py --notify   # 額外在「新達標」時推 ntfy(給排程用)
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
OUT = STUDIO / "platform_monetization.json"

import studio_common as sc  # save_json_atomic / load_json_safe


def _load_env():
    """直跑時把專案根 .env 併進 os.environ(cron 由 local_cron 載;直跑沒有→IG token 找不到)。"""
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()


# ── YouTube:重用 ypp_tracker.py 已算好的四門檻進度,不重抓 ──
def _youtube() -> dict:
    yp = sc.load_json_safe(STUDIO / "ypp_progress.json", {}) or {}
    if not yp:
        return {"available": False, "note": "STUDIO/ypp_progress.json 不存在,先跑 scripts/ypp_tracker.py"}
    out = {"available": True, "source": "ypp_progress.json", "source_updated": yp.get("updated")}
    for tier_key, fallback_label in (("early", "Super Thanks 等(提前解鎖級)"), ("standard", "廣告分潤(標準級)")):
        t = yp.get(tier_key) or {}
        out[tier_key] = {
            "name": t.get("name", fallback_label),
            "can_open": bool(t.get("met")),
            "subs": t.get("subs") or {},
            "hours": t.get("hours") or {},
            "shorts_views_90d": t.get("shorts_views_90d") or {},
        }
    return out


# ── TikTok:Creator Rewards Program 門檻(2026 官方公開條件:1萬粉絲);
#    粉絲數本機無來源(tiktok_state.json 是 Playwright cookie,非統計 API),標記待補,不硬爬 ──
TIKTOK_REWARDS_FOLLOWERS = 10_000


def _tiktok() -> dict:
    ledger = sc.load_json_safe(STUDIO / "tiktok_ledger.json", {}) or {}
    return {
        "available": False,
        "note": ("TikTok 無官方公開 API 可查粉絲數/Shop/Tips 開通狀態;tiktok_state.json 僅為瀏覽器 "
                 "session cookie、非統計數據,不能拿來當粉絲數。待 Carson 人工在 App 後台查看後填入,"
                 "或未來若申請到官方 Creator API 金鑰再接。原則:不硬爬網頁避免帳號被封。"),
        "creator_rewards_program": {
            "need_followers": TIKTOK_REWARDS_FOLLOWERS,
            "cur_followers": None,
            "gap": None,
            "can_open": None,
            "note": "另需過去30天影片觀看數達門檻 + 年滿18歲,同樣待人工核對",
        },
        "shop_tips": {"status": "unknown", "note": "待 Carson 人工查後台開通狀態"},
        "posts_uploaded": len(ledger),
    }


# ── IG:Graph API 官方查 followers_count(與 ig_health_check.py 同一組憑證,非爬蟲)──
IG_FOLLOWERS_THRESHOLD_APPROX = 1000  # 近似值:多數 IG 內容變現功能最低門檻約在此區間,依地區/方案而異,無單一官方統一數字


def _ig_followers():
    """回 (followers_count 或 None, 錯誤/備註訊息或 None)。"""
    uid = os.environ.get("IG_USER_ID", "").strip()
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not uid or not token:
        return None, "缺 IG_USER_ID / IG_ACCESS_TOKEN(.env 未設定,優雅跳過,非錯誤)"
    try:
        import requests
        r = requests.get(f"https://graph.instagram.com/{uid}",
                          params={"fields": "followers_count", "access_token": token}, timeout=20)
        d = r.json()
        if "followers_count" in d:
            return int(d["followers_count"]), None
        return None, str(d.get("error", {}).get("message", d))[:160]
    except Exception as e:  # noqa: BLE001
        return None, f"網路錯誤:{e}"


def _instagram() -> dict:
    cur, err = _ig_followers()
    health = sc.load_json_safe(STUDIO / "ig_health_state.json", {}) or {}
    ledger = sc.load_json_safe(STUDIO / "ig_ledger.json", {}) or {}
    note = "資料來源:Instagram Graph API followers_count(近似門檻,因地區/方案而異、無單一官方統一數字)"
    if err:
        note = err
    return {
        "available": cur is not None,
        "cur_followers": cur,
        "need_followers": IG_FOLLOWERS_THRESHOLD_APPROX,
        "gap": (IG_FOLLOWERS_THRESHOLD_APPROX - cur) if cur is not None else None,
        "can_open": bool(cur is not None and cur >= IG_FOLLOWERS_THRESHOLD_APPROX),
        "note": note,
        "affiliate_status": "unknown(需 Carson 於 IG 專業版後台自行確認開通狀態,Graph API 無法查此欄位)",
        "token_status": health.get("status", "unknown"),
        "posts_uploaded": len(ledger),
    }


def _get(d: dict, keys: tuple):
    cur = d
    for k in keys:
        cur = (cur or {}).get(k) if isinstance(cur, dict) else None
    return cur


def _fmt(data: dict) -> str:
    lines = ["[三平台原生變現門檻]（誠實顯示距離，不畫大餅）"]
    yt = data["youtube"]
    if yt.get("available"):
        for k in ("early", "standard"):
            t = yt.get(k, {})
            s, h = t.get("subs", {}), t.get("hours", {})
            status = "✅ 可開通" if t.get("can_open") else "進行中"
            lines.append(f"【YouTube {t.get('name')}】{status}｜訂閱 {s.get('cur')}/{s.get('need')}｜"
                         f"時數 {h.get('cur')}/{h.get('need')}h")
    else:
        lines.append(f"【YouTube】{yt.get('note')}")

    tk = data["tiktok"]["creator_rewards_program"]
    lines.append(f"【TikTok Creator Rewards】需 {tk['need_followers']} 粉絲｜{data['tiktok']['note']}")

    ig = data["instagram"]
    if ig.get("available"):
        status = "✅ 達門檻(近似值)" if ig.get("can_open") else "進行中"
        lines.append(f"【Instagram】{status}｜粉絲 {ig['cur_followers']}/{ig['need_followers']}(近似門檻)")
    else:
        lines.append(f"【Instagram】未設定或查不到｜{ig.get('note')}")
    return "\n".join(lines)


def _merge_northstar(data: dict) -> None:
    """northstar.json 有彙整檔的話,順手併一個摘要欄位進去;先讀再寫,不動其他既有欄位。"""
    path = STUDIO / "northstar.json"
    ns = sc.load_json_safe(path, None)
    if not isinstance(ns, dict):
        return
    ns["platform_monetization"] = {
        "updated": data["updated"],
        "youtube_standard_can_open": _get(data, ("youtube", "standard", "can_open")),
        "youtube_early_can_open": _get(data, ("youtube", "early", "can_open")),
        "instagram_can_open": _get(data, ("instagram", "can_open")),
        "tiktok_followers_available": False,
    }
    try:
        sc.save_json_atomic(path, ns)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    data = {
        "updated": time.strftime("%Y-%m-%d %H:%M"),
        "youtube": _youtube(),
        "tiktok": _tiktok(),
        "instagram": _instagram(),
    }
    prev = sc.load_json_safe(OUT, {}) or {}
    sc.save_json_atomic(OUT, data)
    _merge_northstar(data)

    summary = _fmt(data)
    print(summary)
    print(f"[ok] 已寫入 {OUT}")

    if "--notify" in sys.argv:
        checks = [
            (("youtube", "standard", "can_open"), "YouTube 標準級(廣告分潤)"),
            (("youtube", "early", "can_open"), "YouTube 提前解鎖級(Super Thanks)"),
            (("instagram", "can_open"), "Instagram(近似門檻)"),
        ]
        newly = [label for keys, label in checks if bool(_get(data, keys)) and not bool(_get(prev, keys))]
        if newly:
            try:
                import notify
                notify.push("量化阿森｜平台變現可開通", "🎉 可開通：" + "、".join(newly) + "\n\n" + summary, tag="tada")
                print(f"[notify] 已推播新達標:{newly}")
            except Exception as e:  # noqa: BLE001
                print(f"[warn] ntfy 推播失敗:{e}", file=sys.stderr)
        else:
            print("[notify] 無新達標,不推播")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
