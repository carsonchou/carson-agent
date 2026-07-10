#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""set_private_by_ids.py — 把 STUDIO/_private_batch_ids.json 裡的 videoId 清單設為 private。
Carson 明確授權的稽核弱片批次(Group A+D 68 + Group B 差3 = 71)。可逆(--privacy public 還原)。
預設 dry-run;--apply 才真的 videos().update。全程讀回驗證。認證沿用 token_manage.json(youtube.force-ssl)。
"""
from __future__ import annotations
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
from google.oauth2.credentials import Credentials  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
TOKEN = ROOT / "token_manage.json"
IDS_FILE = STUDIO / "_private_batch_ids.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _svc():
    return build("youtube", "v3", credentials=Credentials.from_authorized_user_file(str(TOKEN), SCOPES))


def _info(svc, ids):
    out = {}
    for i in range(0, len(ids), 50):
        r = svc.videos().list(part="status,snippet,statistics", id=",".join(ids[i:i + 50])).execute()
        for it in r.get("items", []):
            out[it["id"]] = (it["status"]["privacyStatus"],
                             int(it.get("statistics", {}).get("viewCount", 0)),
                             it["snippet"]["title"])
    return out


def main() -> int:
    apply = "--apply" in sys.argv
    privacy = "private"
    for a in sys.argv:
        if a.startswith("--privacy="):
            privacy = a.split("=", 1)[1]
    ids = json.loads(IDS_FILE.read_text(encoding="utf-8"))
    svc = _svc()
    info = _info(svc, ids)
    todo, skip = [], []
    for vid in ids:
        st = info.get(vid)
        if st is None:
            skip.append((vid, "查無/已刪")); continue
        priv, views, title = st
        if priv != "public":
            skip.append((vid, f"已{priv}")); continue
        todo.append((vid, views, title))
    print(f"[{'APPLY' if apply else 'DRY-RUN'}] 目標 {len(ids)} | 待設{privacy} {len(todo)} | 跳過 {len(skip)}")
    for vid, why in skip[:12]:
        print(f"  skip {vid} {why}")
    # 觀看數最高的幾支眼球檢查(防誤傷正在衝的)
    for vid, views, title in sorted(todo, key=lambda x: -x[1])[:8]:
        print(f"  待處理(觀看{views}) {vid} {title[:36]}")
    if not apply:
        print("(dry-run;確認清單後加 --apply 才寫入)")
        return 0
    done, fails = 0, []
    for vid, _v, _t in todo:
        try:
            svc.videos().update(part="status", body={"id": vid, "status": {"privacyStatus": privacy}}).execute()
            done += 1
        except Exception as e:  # noqa: BLE001
            fails.append((vid, str(e)[:80]))
    print(f"[done] 設 {privacy} {done}/{len(todo)}")
    for vid, e in fails:
        print(f"  FAIL {vid} {e}")
    # 讀回驗證
    back = _info(svc, [t[0] for t in todo])
    ok = sum(1 for vid, _v, _t in todo if back.get(vid, ("?",))[0] == privacy)
    print(f"[verify] 讀回確認 {privacy}: {ok}/{len(todo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
