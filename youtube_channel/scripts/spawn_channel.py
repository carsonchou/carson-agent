#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""spawn_channel.py — 【開新頻道·工作室分身】複製一套獨立的產線實例給新頻道用。

## 為什麼是「複製實例」而不是「改成多頻道架構」
實測(2026-08-16)本工作室的耦合程度:
  - **97 支腳本寫死 STUDIO 路徑**、14 支讀 channel_config.json、STUDIO 下 118 個狀態檔
真要改成多頻道 = 重構 97 支腳本,而且動的是每天在跑的正式產線,風險與工期都不成比例。

但這 97 支的寫法全都是:
    ROOT = Path(__file__).resolve().parent.parent
    STUDIO = ROOT / "STUDIO"
**路徑相對於腳本自己**。所以把目錄複製一份,第二份自動指向自己的 STUDIO,
一行程式都不用改。這是本檔存在的理由。

## 複製什麼、不複製什麼(實測體積)
    scripts/   6.8 MB     **複製**(每套自己一份,才能各自改)
    assets/    738 MB     **junction 共用**(字體/吉祥物/BGM 兩邊共用同一份,省 738MB)
    STUDIO/    97.7 MB    **不複製**——那是主頻道的歷史(920 支已發布片、4492 個題目)。
                          新頻道繼承它會以為自己已經發過 920 支片。
                          只複製其中「設定類」的檔案(見 CONFIG_FILES)。
    output/    24 GB      **絕不複製**(算繪產出)

## 為什麼 state 類檔案「不建空檔」而不是「建空的」
工作室每一個 load 都是 `try: json.loads(...) except: return 預設`。
檔案不存在 = 乾淨的新頻道初始狀態,比建一個空殼更不容易出意外
(空殼會讓「有沒有資料」與「資料是空的」兩種情況混在一起)。

## 🔴 安全
- 目的地已存在就中止,**絕不覆蓋**
- 全程只讀來源、只寫目的地,不動主頻道任何檔案
- 預設 --dry-run,要加 --apply 才真的動手
- token 不複製(新頻道要走自己的 OAuth,見 channel_switch.py --add)

用法:
  python scripts/spawn_channel.py --slug arena --name "AI 預測擂台" --handle ai-arena-tw \\
      --niche "AI 能力實測" --dest D:\\carson-agent\\yt_arena
  加 --apply 才真的建立。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

SRC = Path(__file__).resolve().parent.parent

# 複製整個目錄(程式與設定)
COPY_DIRS = ["scripts", "config", "deploy"]
# 共用(建 junction,不佔空間)。素材是通用資源,兩個頻道用同一份字體/BGM 沒問題。
LINK_DIRS = ["assets"]
# 這些單檔要複製(OAuth 需要 client_secrets;.gitignore 保護 token)
COPY_FILES = ["client_secrets.json", ".gitignore"]
# STUDIO 裡屬於「設定」而非「歷史」的,複製過去當起點
CONFIG_FILES = ["design_system.json", "headcount.json",
                "boss_directives.json", "production_orders.json"]
# 明確不複製的歷史狀態(列出來是為了讓下一個人知道這是刻意的,不是漏掉)
SKIP_STATE = ["uploaded_ledger.json", "quality_scores.json", "topic_bank.json",
              "metrics_history.json", "traffic_signals.json", "finance.json",
              "northstar.json", "ypp_progress.json"]


def make_junction(link: Path, target: Path) -> bool:
    """Windows 目錄 junction(不需管理員權限,不像 symlink)。"""
    try:
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                           capture_output=True, text=True)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def build_config(src_cfg: dict, name: str, handle: str, niche: str) -> dict:
    """從主頻道 config 生新頻道 config:結構照抄,身分欄位換掉,
    **會洩漏主頻道人設的欄位一律清空**並標記待填,不留舊文案冒充新頻道。"""
    cfg = json.loads(json.dumps(src_cfg))          # deep copy
    cfg["channel_name"] = name
    cfg["channel_handle"] = f"@{handle.lstrip('@')}"
    cfg["niche"] = niche
    TODO = "TODO_待填"
    for path in (("branding", "intro_tagline"), ("branding", "outro_tagline"),
                 ("branding", "watermark_text"), ("cta", "subscribe_text"),
                 ("cta", "comment_prompt"), ("tone",), ("target_audience",)):
        d = cfg
        for k in path[:-1]:
            d = d.setdefault(k, {})
        d[path[-1]] = TODO
    # 聯盟連結不繼承——那是主頻道談的,新頻道亂掛等於對觀眾不實
    cfg["affiliates"] = {}
    cfg.pop("affiliate", None)
    if isinstance(cfg.get("cta"), dict):
        cfg["cta"]["affiliate_links"] = []
    cfg["_spawned_from"] = src_cfg.get("channel_name")
    cfg["_note"] = ("由 spawn_channel.py 產生。標記 TODO_待填 的欄位必須改過才可發布——"
                    "沿用主頻道的人設文案會讓兩個頻道看起來像同一套模板量產,"
                    "那正是 YouTube inauthentic content 審查的點名項。")
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--name", required=True, help="頻道顯示名稱")
    ap.add_argument("--handle", required=True, help="@handle(不含 @)")
    ap.add_argument("--niche", default="TODO_待填")
    ap.add_argument("--dest", required=True, help="新實例目錄(必須不存在)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    dest = Path(a.dest).resolve()
    print(f"來源:{SRC}")
    print(f"目的:{dest}\n")
    if dest.exists():
        print(f"[!] {dest} 已存在。為避免覆蓋,中止。")
        return 1
    if dest == SRC or SRC in dest.parents:
        print("[!] 目的地不可為來源本身或其子目錄。")
        return 1

    plan = []
    for d in COPY_DIRS:
        p = SRC / d
        if p.exists():
            n = sum(1 for _ in p.rglob("*") if _.is_file())
            plan.append(("複製目錄", d, f"{n} 檔"))
    for d in LINK_DIRS:
        if (SRC / d).exists():
            plan.append(("junction 共用", d, "0 位元組"))
    for f in COPY_FILES:
        if (SRC / f).exists():
            plan.append(("複製檔案", f, ""))
    for f in CONFIG_FILES:
        if (SRC / "STUDIO" / f).exists():
            plan.append(("複製設定", f"STUDIO/{f}", ""))
    plan.append(("新建", "channel_config.json", f"{a.name} / @{a.handle}"))
    plan.append(("不複製", "STUDIO 歷史狀態", "、".join(SKIP_STATE[:4]) + "…"))
    plan.append(("不複製", "output/ 算繪產出", "24 GB"))
    plan.append(("不複製", "token_*.json", "新頻道走自己的 OAuth"))

    for kind, what, note in plan:
        print(f"  {kind:14s} {what:32s} {note}")

    if not a.apply:
        print("\n--dry-run:什麼都沒做。要真的建立請加 --apply")
        return 0

    dest.mkdir(parents=True)
    for d in COPY_DIRS:
        p = SRC / d
        if p.exists():
            shutil.copytree(p, dest / d,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            print(f"  ✓ 複製 {d}/")
    for d in LINK_DIRS:
        if (SRC / d).exists():
            ok = make_junction(dest / d, SRC / d)
            print(f"  {'✓' if ok else '✗'} junction {d}/ → {SRC / d}"
                  + ("" if ok else "  (失敗,改用複製或手動處理)"))
    for f in COPY_FILES:
        if (SRC / f).exists():
            shutil.copy2(SRC / f, dest / f)
            print(f"  ✓ 複製 {f}")
    (dest / "STUDIO").mkdir(exist_ok=True)
    for f in CONFIG_FILES:
        src = SRC / "STUDIO" / f
        if src.exists():
            shutil.copy2(src, dest / "STUDIO" / f)
            print(f"  ✓ 複製 STUDIO/{f}")

    src_cfg = json.loads((SRC / "channel_config.json").read_text(encoding="utf-8"))
    cfg = build_config(src_cfg, a.name, a.handle, a.niche)
    (dest / "channel_config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ 產生 channel_config.json")

    todo = [k for k, v in cfg.items() if v == "TODO_待填"]
    todo += [f"{a}.{b}" for a in ("branding", "cta") if isinstance(cfg.get(a), dict)
             for b, v in cfg[a].items() if v == "TODO_待填"]
    print(f"\n完成。新實例:{dest}")
    print(f"\n⚠️ 發布前必須改掉 {len(todo)} 個 TODO_待填 欄位:")
    for t in todo:
        print(f"     {t}")
    print("\n下一步:")
    print(f"  1. Carson 在 YouTube 建好頻道「{a.name}」")
    print(f"  2. cd {dest} && python scripts/channel_switch.py --add {a.slug} --title \"{a.name}\"")
    print("     (會開瀏覽器,**要選新頻道那個帳號**授權)")
    print(f"  3. python scripts/channel_switch.py --whoami   ← 確認 token 真的綁到新頻道")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
