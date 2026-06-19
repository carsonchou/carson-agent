#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dedup_channel.py — 偵測頻道重複影片並刪除，每組保留最早上架的一支。"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

# 在 repo: scripts/yt/dedup_channel.py → parent×3 = repo root
# 在伺服器: scripts/dedup_channel.py → parent×2 = /root/yt
_here = Path(__file__).resolve()
ROOT = _here.parent.parent if _here.parent.name == "scripts" else _here.parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LEDGER = ROOT / "STUDIO" / "uploaded_ledger.json"
OUTPUT = ROOT / "output"
TOKEN = ROOT / "token.json"  # /root/yt/token.json
SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
]


def get_service():
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def normalize(slug: str) -> str:
    s = re.sub(r"^[SL]_", "", slug)
    s = re.sub(r"\d{3,5}$", "", s)  # 去掉末尾 3-5 位數字（碰撞後綴）
    return s


def char_sim(a: str, b: str) -> float:
    sa, sb = set(normalize(a)), set(normalize(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa), len(sb))


def find_dup_groups(slugs: list[str], threshold: float = 0.68) -> list[list[str]]:
    groups: list[list[str]] = []
    visited: set[str] = set()
    for s in slugs:
        if s in visited:
            continue
        group = [s]
        visited.add(s)
        for t in slugs:
            if t in visited:
                continue
            if char_sim(s, t) >= threshold:
                group.append(t)
                visited.add(t)
        groups.append(group)
    return groups


def main() -> None:
    ledger: dict = json.loads(LEDGER.read_text(encoding="utf-8"))
    slugs = list(ledger.keys())

    groups = find_dup_groups(slugs)
    dup_groups = [g for g in groups if len(g) > 1]

    to_delete: list[str] = []
    print(f"=== 重複組（共 {len(dup_groups)} 組）===")
    for g in dup_groups:
        keep = g[0]
        deletes = g[1:]
        print(f"\n✅ 保留：{keep}  ({ledger.get(keep, '?')})")
        for d in deletes:
            print(f"  ❌ 刪除：{d}  ({ledger.get(d, '?')})")
            to_delete.append(d)

    print(f"\n總計：保留 {len(dup_groups)} 支，刪除 {len(to_delete)} 支")

    if not to_delete:
        print("[OK] 沒有重複，無需操作。")
        return

    # 嘗試呼叫 YouTube API 刪除
    try:
        yt = get_service()
    except Exception as exc:
        print(f"[WARN] 無法初始化 YouTube service：{exc}")
        print("[INFO] 以下是需要手動刪除的 YouTube 連結：")
        for slug in to_delete:
            vid = ledger.get(slug)
            if vid:
                print(f"  https://youtu.be/{vid}  ({slug})")
        return

    from googleapiclient.errors import HttpError

    deleted_ok = 0
    delete_fail = 0

    for slug in to_delete:
        vid = ledger.get(slug)
        if not vid:
            print(f"[skip] {slug}：無 video ID，直接移除 ledger")
            del ledger[slug]
            continue
        try:
            yt.videos().delete(id=vid).execute()
            print(f"[DEL] {slug} -> {vid}")
            del ledger[slug]
            # 清掉本地殘留檔
            for ext in ("mp4", "md"):
                f = OUTPUT / f"{slug}.{ext}"
                if f.exists():
                    f.unlink()
            deleted_ok += 1
        except HttpError as exc:
            code = exc.resp.status if hasattr(exc, "resp") else "?"
            print(f"[FAIL {code}] {slug}: {str(exc)[:100]}", file=sys.stderr)
            if "forbidden" in str(exc).lower() or code == 403:
                print(
                    "[WARN] Token 沒有刪除權限（只有 upload scope）。\n"
                    "       需重新授權或手動至 YouTube Studio 刪除。",
                    file=sys.stderr,
                )
                # 繼續列出剩餘連結讓使用者手動刪
                print("\n[INFO] 剩餘待手動刪除：")
                remaining = to_delete[to_delete.index(slug):]
                for s in remaining:
                    v = ledger.get(s)
                    if v:
                        print(f"  https://youtu.be/{v}  ({s})")
                break
            delete_fail += 1

    LEDGER.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"\n[結果] 刪除成功 {deleted_ok}，失敗 {delete_fail}，"
        f"現剩 {len(ledger)} 支已上架。"
    )
    print(f"[INFO] 需補產非重複新片：{deleted_ok} 支")


if __name__ == "__main__":
    main()
