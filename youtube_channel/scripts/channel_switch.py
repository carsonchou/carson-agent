#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""channel_switch.py — 【多頻道 / 多帳號切換機】一台機器管所有 YouTube 頻道。

## 它解決什麼
整個工作室(~20 支腳本)都寫死讀 `token_manage.json` 一顆 token = 只服務一個頻道。
要經營多個頻道(每頻一個獨立 Google 帳號),不可能去改那 20 支腳本。

本機的做法:**每個頻道的 token 存在自己的資料夾裡,「切換」= 把該頻道的 token
換進現役槽位**。切完之後,既有 20 支腳本一行都不用改,自動就對著新頻道跑。

    channels/
      registry.json              誰是誰、現在是誰在線上
      <slug>/token_manage.json   該頻道的憑證(權威版本)
      <slug>/token_analytics.json
      <slug>/token.json
    ↕ 切換 = 複製
    token_manage.json 等現役槽位(工作室腳本讀的就是這幾顆)

## 🔴 絕不能弄丟憑證(memory 記過一次覆蓋事故)
1. **`--adopt` 必須最先跑**:把現在線上的 token 收編成一個已註冊頻道。
   沒收編就 `--use`,等於把現役憑證直接蓋掉且無法還原 → 本機**拒絕執行**。
2. 每次切換前,現役槽位會先備份回它所屬頻道的資料夾(避免 refresh 過的新版本遺失)。
3. 所有寫入走 atomic(先寫 .tmp 再 replace),中途斷電不會留下半個檔。
4. `--whoami` 直接打 API 問「這顆 token 到底是誰」,不信任註冊表的記載——
   標籤會寫錯,API 不會。

## ⚠️ 政策風險(建立多頻道前必讀)
YouTube 2025-07-15 inauthentic content 定義點名「模板化 / 影片間變化極小 /
可大規模複製」為人工審查否決項。用同一套模板複製出多個頻道、配多個 Google 帳號,
同時踩「重複內容」與「垃圾內容」政策,最壞情況是全部連坐。
本工具只負責**安全地切換**,不會讓上述風險變小。每次 --add 都會再提醒一次。

用法:
  python channel_switch.py --adopt 量化阿森 --title "量化阿森"   # 第一步,收編現役
  python channel_switch.py --list                                # 看全部頻道 + 誰在線上
  python channel_switch.py --whoami                              # 問 API:現役 token 是誰
  python channel_switch.py --add 金融股 --title "金融股頻道"      # 新帳號授權(會開瀏覽器)
  python channel_switch.py --use 金融股                          # 切過去
  python channel_switch.py --verify                              # 全頻道憑證健檢
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
CHANNELS = ROOT / "channels"
REGISTRY = CHANNELS / "registry.json"
CLIENT_SECRETS = ROOT / "client_secrets.json"
TW = timezone(timedelta(hours=8))

# 現役槽位:工作室各腳本實際會去讀的檔名 → 該槽位需要的 scope。
# 要新增槽位,照這張表加,切換邏輯不必動。
SLOTS = {
    "token_manage.json": ["https://www.googleapis.com/auth/youtube.force-ssl"],
    "token_analytics.json": ["https://www.googleapis.com/auth/youtube.force-ssl",
                             "https://www.googleapis.com/auth/yt-analytics.readonly"],
    "token.json": ["https://www.googleapis.com/auth/youtube.upload",
                   "https://www.googleapis.com/auth/youtube.readonly"],
}


def now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M:%S")


# ── 註冊表 ──────────────────────────────────────────────────────────────────
def load_reg() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {"active": None, "channels": {}}


def save_reg(r: dict) -> None:
    CHANNELS.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(REGISTRY)


def chan_dir(slug: str) -> Path:
    return CHANNELS / slug


def _copy(src: Path, dst: Path) -> None:
    """atomic 複製:先寫 .tmp 再 replace,中途中斷不會留下半個 token。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copy2(src, tmp)
    tmp.replace(dst)


def live_slots() -> dict[str, Path]:
    return {n: ROOT / n for n in SLOTS if (ROOT / n).exists()}


# ── 身分查核 ────────────────────────────────────────────────────────────────
def identify(token_file: Path, scopes: list[str]) -> dict | None:
    """打 API 問這顆 token 屬於哪個頻道。**不信任註冊表的標籤,只信 API。**"""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        cr = Credentials.from_authorized_user_file(str(token_file), scopes)
        if not cr.valid and cr.expired and cr.refresh_token:
            cr.refresh(Request())
            # refresh 後的新版本要寫回,否則下次還是用舊的去 refresh
            token_file.write_text(cr.to_json(), encoding="utf-8")
        yt = build("youtube", "v3", credentials=cr, cache_discovery=False)
        r = yt.channels().list(part="snippet,statistics", mine=True).execute()
        items = r.get("items") or []
        if not items:
            return None
        it = items[0]
        sn, st = it.get("snippet", {}), it.get("statistics", {})
        return {"channel_id": it["id"], "title": sn.get("title"),
                "handle": sn.get("customUrl"),
                "subs": st.get("subscriberCount"), "videos": st.get("videoCount")}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}


# ── 指令 ────────────────────────────────────────────────────────────────────
def cmd_adopt(slug: str, title: str | None):
    """把現在線上的 token 收編成一個已註冊頻道。**必須最先做的一步。**"""
    reg = load_reg()
    slots = live_slots()
    if not slots:
        print("[!] 現役槽位沒有任何 token,沒東西可收編。")
        return 1
    if slug in reg["channels"]:
        print(f"[!] 「{slug}」已經在註冊表裡了。要重新收編請先改名或用 --use。")
        return 1

    d = chan_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    copied = []
    for name, p in slots.items():
        _copy(p, d / name)
        copied.append(name)

    ident = None
    if "token_manage.json" in slots:
        ident = identify(d / "token_manage.json", SLOTS["token_manage.json"])

    reg["channels"][slug] = {
        "slug": slug,
        "title": title or (ident or {}).get("title") or slug,
        "channel_id": (ident or {}).get("channel_id"),
        "handle": (ident or {}).get("handle"),
        "tokens": copied,
        "adopted_at": now(),
    }
    reg["active"] = slug
    save_reg(reg)
    print(f"✅ 已收編現役憑證為頻道「{slug}」,複製了 {len(copied)} 顆 token:{', '.join(copied)}")
    if ident and not ident.get("error"):
        print(f"   API 查核:{ident['title']}({ident.get('handle') or '無 handle'})"
              f" 訂閱 {ident.get('subs')} 影片 {ident.get('videos')}")
    elif ident:
        print(f"   ⚠️ API 查核失敗:{ident['error']}(token 已備份,可稍後 --verify 重查)")
    print(f"   現在線上的是:{slug}")
    return 0


def cmd_add(slug: str, title: str | None):
    reg = load_reg()
    if slug in reg["channels"]:
        print(f"[!] 「{slug}」已存在。")
        return 1
    if not CLIENT_SECRETS.exists():
        print(f"[!] 找不到 {CLIENT_SECRETS}")
        return 1

    print("⚠️  提醒:用同一套模板複製多個頻道 + 多個 Google 帳號,同時踩 YouTube")
    print("    inauthentic content(模板化/可大規模複製)與重複內容政策,最壞情況全部連坐。")
    print()
    print(f"接下來會開瀏覽器做 OAuth 授權。**請用「{slug}」那個頻道的 Google 帳號登入**,")
    print("不要用量化阿森的主帳號——授權錯帳號會把該帳號註冊成這個 slug。")
    print()

    from google_auth_oauthlib.flow import InstalledAppFlow
    d = chan_dir(slug)
    d.mkdir(parents=True, exist_ok=True)

    # **一次授權涵蓋全部 scope**,不要每個槽位各跑一次同意畫面。
    # 原本一槽一次 = 三次同意畫面 = 三次選錯帳號的機會;現在只有一次。
    # 拿到的 credential 帶著聯集 scope,寫進三個槽位都能用
    # (Credentials.from_authorized_user_file 讀取時只檢查有沒有涵蓋所需 scope)。
    union = sorted({s for scopes in SLOTS.values() for s in scopes})
    print("── 一次授權,涵蓋:")
    for s in union:
        print(f"     {s.rsplit('/', 1)[-1]}")
    print("   瀏覽器要開了。**請選新頻道那個 Google 帳號**,不要選量化阿森的主帳號。\n")
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), union)
        creds = flow.run_local_server(port=0, prompt="consent")
    except Exception as e:  # noqa: BLE001
        print(f"[!] 授權失敗:{type(e).__name__}: {str(e)[:200]}")
        print("    常見原因:①OAuth 同意畫面還在『測試中』,新帳號沒被加進測試使用者名單")
        print("              ②使用者按了取消 ③回呼連接埠被防火牆擋住")
        return 1

    got = []
    for name in SLOTS:
        tmp = (d / name).with_suffix(".json.tmp")
        tmp.write_text(creds.to_json(), encoding="utf-8")
        tmp.replace(d / name)
        got.append(name)
    print(f"   ✓ 已存 {len(got)} 個槽位:{', '.join(got)}")

    ident = identify(d / got[0], SLOTS[got[0]])
    if ident and ident.get("error"):
        print(f"[!] 授權拿到了但 API 查核失敗:{ident['error']}")
    elif ident:
        # 同一個頻道被註冊兩次是常見誤操作(授權時登錯帳號),擋下來
        for s, c in reg["channels"].items():
            if c.get("channel_id") and c["channel_id"] == ident["channel_id"]:
                print(f"[!] 這顆 token 指向的頻道「{ident['title']}」已經註冊為「{s}」了。")
                print("    很可能是授權時登錯帳號。已存的 token 留在", d, "但不寫進註冊表。")
                return 1
        print(f"   API 查核:{ident['title']}({ident.get('handle') or '無 handle'})")

    reg["channels"][slug] = {
        "slug": slug,
        "title": title or (ident or {}).get("title") or slug,
        "channel_id": (ident or {}).get("channel_id"),
        "handle": (ident or {}).get("handle"),
        "tokens": got,
        "added_at": now(),
    }
    save_reg(reg)
    print(f"✅ 已新增頻道「{slug}」({len(got)} 顆 token)。切過去:--use {slug}")
    return 0


def cmd_use(slug: str):
    reg = load_reg()
    if slug not in reg["channels"]:
        print(f"[!] 註冊表裡沒有「{slug}」。先跑 --list 看有哪些。")
        return 1
    if reg["active"] == slug:
        print(f"「{slug}」已經在線上了,不用切。")
        return 0

    # 🔴 現役槽位有 token 但沒人認領 → 一切就永久蓋掉。擋下來。
    slots = live_slots()
    if slots and not reg.get("active"):
        print("[!] 現役槽位有 token,但註冊表不知道它屬於誰。")
        print("    直接切換會把它蓋掉且無法還原。請先收編:")
        print("      python channel_switch.py --adopt <取個名字>")
        return 1

    # 切走之前,把現役槽位存回它所屬的頻道——token 會被 refresh 更新,
    # 不存回去的話那個較新的版本就丟了。
    cur = reg.get("active")
    if cur and cur in reg["channels"]:
        back = 0
        for name, p in slots.items():
            _copy(p, chan_dir(cur) / name)
            back += 1
        print(f"   已把現役 {back} 顆 token 存回「{cur}」")

    d = chan_dir(slug)
    moved = []
    for name in SLOTS:
        src = d / name
        if src.exists():
            _copy(src, ROOT / name)
            moved.append(name)
    if not moved:
        print(f"[!]「{slug}」資料夾裡沒有任何 token,切換中止(現役槽位未動)。")
        return 1

    reg["active"] = slug
    reg["channels"][slug]["last_used"] = now()
    save_reg(reg)
    c = reg["channels"][slug]
    print(f"✅ 已切換到「{slug}」({c.get('title')}),換上 {len(moved)} 顆 token。")

    ident = identify(ROOT / "token_manage.json", SLOTS["token_manage.json"]) \
        if (ROOT / "token_manage.json").exists() else None
    if ident and not ident.get("error"):
        exp = c.get("channel_id")
        if exp and ident["channel_id"] != exp:
            print(f"   🔴 查核不符!現役 token 指向 {ident['title']}({ident['channel_id']}),"
                  f"註冊表說應該是 {exp}。別在這個狀態下發布任何東西。")
            return 2
        print(f"   查核通過:現在對著 {ident['title']} 操作"
              f"(訂閱 {ident.get('subs')} 影片 {ident.get('videos')})")
    return 0


def cmd_list():
    reg = load_reg()
    chans = reg.get("channels") or {}
    if not chans:
        print("註冊表是空的。第一步:python channel_switch.py --adopt <名字>")
        slots = live_slots()
        if slots:
            print(f"(現役槽位目前有 {len(slots)} 顆未收編的 token:{', '.join(slots)})")
        return 0
    print(f"\n{'':2s}{'slug':14s}{'頻道名':22s}{'handle':18s}{'token':7s}{'最後使用':20s}")
    print("-" * 84)
    for slug, c in chans.items():
        mark = "▶" if slug == reg.get("active") else " "
        print(f"{mark:2s}{slug:14s}{(c.get('title') or '')[:20]:22s}"
              f"{(c.get('handle') or '—'):18s}{len(c.get('tokens') or []):<7d}"
              f"{c.get('last_used') or c.get('added_at') or c.get('adopted_at') or '—':20s}")
    print("-" * 84)
    print(f"▶ = 現在線上({reg.get('active') or '無'})　共 {len(chans)} 個頻道")
    return 0


def cmd_whoami():
    """不看註冊表,直接問 API:現役 token 到底是誰。標籤會寫錯,API 不會。"""
    reg = load_reg()
    print(f"註冊表說現在是:{reg.get('active') or '(無)'}")
    any_ok = False
    for name, scopes in SLOTS.items():
        p = ROOT / name
        if not p.exists():
            print(f"  {name:22s} (不存在)")
            continue
        ident = identify(p, scopes)
        if not ident:
            print(f"  {name:22s} ⚠️ 這顆 token 查不到任何頻道")
        elif ident.get("error"):
            print(f"  {name:22s} ⚠️ {ident['error']}")
        else:
            any_ok = True
            print(f"  {name:22s} → {ident['title']}({ident.get('handle') or '無 handle'})"
                  f" id={ident['channel_id']}")
    if any_ok:
        exp = (reg.get("channels") or {}).get(reg.get("active") or "", {}).get("channel_id")
        if exp:
            print(f"\n註冊表登記的 channel_id:{exp}")
    return 0


def cmd_verify():
    reg = load_reg()
    chans = reg.get("channels") or {}
    if not chans:
        print("註冊表是空的。")
        return 0
    print("逐頻道憑證健檢(會 refresh,可能需要幾秒)…\n")
    bad = 0
    for slug, c in chans.items():
        d = chan_dir(slug)
        have = [n for n in SLOTS if (d / n).exists()]
        miss = [n for n in SLOTS if not (d / n).exists()]
        line = f"  {slug:14s} token {len(have)}/{len(SLOTS)}"
        if miss:
            line += f"  缺:{','.join(miss)}"
        print(line)
        if not have:
            print("      🔴 一顆都沒有,這個頻道無法使用")
            bad += 1
            continue
        ident = identify(d / have[0], SLOTS[have[0]])
        if not ident or ident.get("error"):
            print(f"      🔴 憑證失效:{(ident or {}).get('error', '查不到頻道')}")
            bad += 1
        elif c.get("channel_id") and ident["channel_id"] != c["channel_id"]:
            print(f"      🔴 身分不符:token 指向 {ident['title']},註冊表說是 {c.get('title')}")
            bad += 1
        else:
            print(f"      ✓ {ident['title']} 訂閱 {ident.get('subs')} 影片 {ident.get('videos')}")
    print(f"\n{'全部正常' if not bad else f'⚠️ {bad} 個頻道有問題'}")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adopt", metavar="SLUG", help="把現役 token 收編成頻道(第一步)")
    ap.add_argument("--add", metavar="SLUG", help="新增頻道(開瀏覽器授權新 Google 帳號)")
    ap.add_argument("--use", metavar="SLUG", help="切換到某頻道")
    ap.add_argument("--title", help="頻道顯示名稱(配合 --adopt/--add)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--whoami", action="store_true", help="問 API:現役 token 是誰")
    ap.add_argument("--verify", action="store_true", help="全頻道憑證健檢")
    a = ap.parse_args()

    if a.adopt:
        return cmd_adopt(a.adopt, a.title)
    if a.add:
        return cmd_add(a.add, a.title)
    if a.use:
        return cmd_use(a.use)
    if a.whoami:
        return cmd_whoami()
    if a.verify:
        return cmd_verify()
    if a.list:
        return cmd_list()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
