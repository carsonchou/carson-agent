#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""send_quota_reply.py — 回覆 YouTube API Services 合規審查(配額分配)。

## 背景
2026-08-13 22:26(台北)收到 YouTube API Quota 團隊來信,要求提供
average video size / video length / upload frequency 以評估 videos.insert
的每分鐘配額。7 個工作天內須回覆(最晚 2026-08-22)。

## 為什麼要專用腳本而不是手貼
① 必須**串回原 thread**:In-Reply-To / References 帶上原信 Message-ID,
   否則對方收到的是孤兒新信,案件對不上(回信地址裡的 +1k2odjfk3ge2z1n 是 case id)。
② 內容是**對外正式合規文件**,寄什麼必須留檔可回溯(本檔即為記錄)。

## 安全設計
- 預設 dry-run,只印將寄出的內容與 header;要 `--send` 才真的寄。
- 收件地址、Message-ID **不寫死猜測**,執行時從信箱 IMAP 讀回原信 header
  (讀不到就中止,絕不亂猜地址寄出去)。
- 內文從 STUDIO/REPORTS/2026-08-13_API配額回覆草稿.md 的英文區塊抽出,
  單一事實來源;抽不到就中止。
"""
from __future__ import annotations

import argparse
import imaplib
import os
import re
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFT = ROOT / "STUDIO" / "REPORTS" / "2026-08-13_API配額回覆草稿.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _load_env():
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def find_original(addr: str, pw: str) -> dict:
    """從 INBOX 找最新一封 YouTube API Quota 來信,回其 header。找不到回 {}。"""
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        M.login(addr, pw)
        M.select("INBOX")
        typ, data = M.search(None, '(SUBJECT "YouTube API")')
        ids = data[0].split()
        if not ids:
            return {}
        for uid in reversed(ids[-5:]):
            t, d = M.fetch(uid, "(BODY.PEEK[HEADER.FIELDS "
                                "(FROM REPLY-TO SUBJECT MESSAGE-ID DATE)])")
            raw = d[0][1].decode("utf-8", "replace")
            if "quota" not in raw.lower():
                continue
            def _h(name):
                m = re.search(rf"(?im)^{name}:\s*(.+)$", raw)
                return m.group(1).strip() if m else ""
            reply_to = _h("Reply-To") or _h("From")
            m = re.search(r"<([^>]+@[^>]+)>", reply_to)
            return {
                "to": m.group(1) if m else reply_to,
                "subject": _h("Subject"),
                "message_id": _h("Message-ID"),
                "date": _h("Date"),
            }
        return {}
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass


def extract_body() -> str:
    """從草稿抽英文正文(『## 建議回覆內容』到『## 中文對照』之間),轉成純文字 email。"""
    md = DRAFT.read_text(encoding="utf-8")
    m = re.search(r"## 建議回覆內容[^\n]*\n(.*?)\n---\n\n## 中文對照", md, re.S)
    if not m:
        return ""
    body = m.group(1)
    body = re.sub(r"(?m)^Subject: .*\n", "", body)          # Subject 另外帶
    body = re.sub(r"(?m)^### ", "", body)                    # 標題層級記號
    body = body.replace("**", "").replace("`", "")           # markdown 強調
    body = _tables_to_text(body)                             # 表格→純文字(見該函式)
    return body.strip()


def _tables_to_text(md: str) -> str:
    """markdown 表格 → 純文字條列。

    純文字 email 在非等寬字體下,markdown 表格的 | 會完全錯位、非常難讀,
    而這是要給 Google 審查員看的正式文件。轉成
    「  - 欄1值 — 欄2名: 值; 欄3名: 值」的條列,任何字體下都對齊。
    """
    out, i = [], 0
    lines = md.split("\n")
    while i < len(lines):
        ln = lines[i]
        is_row = ln.strip().startswith("|") and ln.strip().endswith("|")
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if is_row and re.match(r"^\s*\|[\s:|-]+\|\s*$", nxt):
            hdr = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                label = cells[0] if cells else ""
                parts = [f"{hdr[j]}: {cells[j]}" for j in range(1, min(len(hdr), len(cells)))
                         if cells[j] and cells[j] != "—"]
                out.append(f"  - {label} — " + "; ".join(parts) if parts else f"  - {label}")
                i += 1
            continue
        out.append(ln)
        i += 1
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="真的寄出(預設只預覽)")
    args = ap.parse_args()

    _load_env()
    addr = os.environ.get("GMAIL_ADDRESS", "").strip()
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not addr or not pw:
        print("[FATAL] 缺 GMAIL_ADDRESS / GMAIL_APP_PASSWORD")
        return 1

    body = extract_body()
    if not body or len(body) < 500:
        print(f"[FATAL] 草稿正文抽取失敗(len={len(body)}),中止")
        return 1

    orig = find_original(addr, pw)
    if not orig.get("to") or not orig.get("message_id"):
        print("[FATAL] 找不到原信 header(收件地址/Message-ID),不亂猜地址,中止")
        return 1

    msg = EmailMessage()
    msg["From"] = addr
    msg["To"] = orig["to"]
    subj = orig["subject"]
    msg["Subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
    msg["In-Reply-To"] = orig["message_id"]
    msg["References"] = orig["message_id"]
    msg.set_content(body)

    print("=" * 60)
    print("To      :", msg["To"])
    print("Subject :", msg["Subject"])
    print("In-Reply-To:", msg["In-Reply-To"])
    print("原信日期:", orig.get("date"))
    print("正文字數:", len(body))
    print("=" * 60)
    print(body[:1200])
    print("… (共 %d 字元)" % len(body))

    if not args.send:
        print("\n[dry-run] 未寄出。確認無誤後加 --send。")
        return 0

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=45, local_hostname="localhost") as s:
        s.login(addr, pw)
        s.send_message(msg)
    print("\n[ok] ✅ 已寄出至", msg["To"])
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from ops import log_ops
        log_ops("API配額", f"已回覆 YouTube API 合規審查(配額分配)→ {msg['To']}")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
