#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_resume.py — 產出 Mercor / Upwork 用的 PDF 履歷。

## 為什麼需要這支（2026-08-30）
Mercor 註冊第一步就是 **Upload resume**，而 `PROFILE_EN.md` 是 Markdown 文字，
不是可上傳的檔案。查了才發現這個缺口 —— 材料「備好了」但**最關鍵的那個檔不存在**，
所以那份指南實際上還是卡住的。

## 內容從哪裡來
全部取自 `PROFILE_EN.md`，不新增任何未經溯源的敘述。
沿用該檔的三條誠信約束：
  1. 測試數只寫實際跑出來的（不寫 623/637/639）
  2. 不暗示有商業客戶 —— 一律 "my own production system"
  3. 每個數字都能在 `PORTFOLIO.md` 溯源

## 測試數字是參數不是常數
`--tests N` 由呼叫端傳入，預設 None 就**不印測試數那一行**。
理由：那個數字會過期（PROFILE_EN.md 寫的 431 是 2026-08-20 的），
而履歷上一個過期的數字被追問時答不出來，比沒寫還糟。
→ 送出前重跑測試、拿當下的真值傳進來。

## 用法
    python build_resume.py --tests 431 --out Carson_Chou_Resume.pdf
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, ListFlowable, ListItem, Paragraph,
                                SimpleDocTemplate, Spacer)

ROOT = Path(__file__).resolve().parent

NAME = "Chou Ting-Rui (Carson)"
CONTACT = "Taiwan · Remote · moneycometomywallet@gmail.com"
TITLE = "Python Automation &amp; Data Pipeline Engineer"

SUMMARY = (
    "I build systems that run themselves &mdash; data comes in, gets processed, ships out, "
    "and pages me when something breaks. My focus is <b>correctness under silent failure</b>: "
    "data pipelines, payment webhooks and scheduled jobs, where the main risk is not a crash "
    "but a wrong number that nobody notices for three months."
)

# 這段是 PROFILE_EN.md 第五節專為評測職缺寫的版本 —— Mercor 要的是
# 「能判斷程式碼對不對」,不是「能交付專案」,所以把失敗模式放在最前面。
FAILURE_MODES = [
    "A <font face='Courier'>.get(key, 0)</font> that returns None because the key exists with a null value.",
    "A validation gate that quietly lets bad data through because someone made it &ldquo;more tolerant&rdquo;.",
    "A timeout heuristic that kills healthy long-running jobs because it checks file mtime and never checks liveness.",
]

PROJECTS = [
    ("Video Rendering Pipeline &mdash; 13&times; faster, zero hardware cost",
     "Rendering took 294 seconds per clip. The obvious fix was a faster GPU. I measured first, and the "
     "measurement contradicted the assumption: CPU time across the entire render was about 0.2 seconds "
     "&mdash; the processor sat idle for five minutes. The bottleneck was I/O, not compute: frames were "
     "being piped one at a time into the encoder over stdin. I rewrote that layer as a pure ffmpeg "
     "architecture (concat demuxer, single filtergraph, one encode pass). "
     "<b>294s &rarr; 22.5s on identical hardware.</b> The previous implementation is retained as an "
     "automatic fallback &mdash; I do not ship a single point of failure."),
    ("Taiwan Equity Market Data Service",
     "Consolidates Taiwanese stock market data from several official sources into one queryable system "
     "across eight independent domains &mdash; institutional flows, margin trading, shareholder "
     "distribution, fundamentals, valuation, quotes, news, technical indicators. Every external parser "
     "has its own tests: government sites redesign their pages regularly, and tests turn a silent data "
     "corruption into a loud failure on day one. Includes health checks and an MCP query interface."),
    ("Payment Webhook &amp; Subscription Delivery Backend",
     "Signature verification, multi-source event normalisation, transaction ledger, product delivery, "
     "subscriber management. Two design decisions worth noting: unknown plan codes still deliver "
     "&mdash; if a paying customer hits a tier the system has never seen they get their product, and "
     "we investigate afterwards; and pricing has exactly one source of truth, enforced by a test, so "
     "marketing copy and charged amounts cannot drift apart."),
]

SKILLS = ("Python · pandas · NumPy · ETL &amp; data pipelines · Web scraping · Playwright · "
          "FFmpeg · REST APIs · Webhooks · Stripe · pytest · Task scheduling · SQL · "
          "Financial data · Backtesting · Windows/Linux automation")


def build(out: Path, tests: int | None) -> None:
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=9.2, leading=12.6,
                          alignment=TA_LEFT, spaceAfter=4)
    h_name = ParagraphStyle("name", parent=ss["Title"], fontSize=19, leading=22,
                            spaceAfter=1, alignment=TA_LEFT)
    h_sub = ParagraphStyle("sub", parent=body, fontSize=9.6, textColor="#444444", spaceAfter=1)
    h_sec = ParagraphStyle("sec", parent=ss["Heading2"], fontSize=10.4, leading=13,
                           spaceBefore=9, spaceAfter=3, textColor="#111111")
    h_prj = ParagraphStyle("prj", parent=body, fontSize=9.6, spaceAfter=1,
                           textColor="#000000")

    doc = SimpleDocTemplate(str(out), pagesize=A4,
                            leftMargin=17 * mm, rightMargin=17 * mm,
                            topMargin=15 * mm, bottomMargin=14 * mm,
                            title=f"{NAME} — Resume", author=NAME)
    f = [Paragraph(NAME, h_name),
         Paragraph(TITLE, h_sub),
         Paragraph(CONTACT, h_sub),
         HRFlowable(width="100%", thickness=0.7, color="#999999",
                    spaceBefore=5, spaceAfter=6),
         Paragraph(SUMMARY, body)]

    f += [Paragraph("Failure modes I look for", h_sec),
          ListFlowable([ListItem(Paragraph(x, body), leftIndent=10) for x in FAILURE_MODES],
                       bulletType="bullet", bulletFontSize=6, leftIndent=11)]

    f += [Paragraph("Selected work (own production systems)", h_sec)]
    for title, desc in PROJECTS:
        f += [Paragraph(f"<b>{title}</b>", h_prj), Paragraph(desc, body), Spacer(1, 3)]

    if tests:
        f += [Paragraph("Testing", h_sec),
              Paragraph(
                  f"<b>{tests} automated tests currently passing</b> across my data and webhook "
                  "layers. Every external-source parser is covered, because upstream sites change "
                  "their HTML without warning &mdash; with tests you find out the day it breaks, not "
                  "three months later when you notice the data was wrong the whole time. I also design "
                  "fail-closed: when the system cannot determine something it refuses rather than "
                  "guessing. Errors should be loud, not silent.", body)]

    f += [Paragraph("Skills", h_sec), Paragraph(SKILLS, body)]
    doc.build(f)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", type=int, default=None,
                    help="目前實際通過的測試數。**不確定就不要傳** —— 履歷上一個過期的數字"
                         "被追問時答不出來,比沒寫還糟。")
    ap.add_argument("--out", default=str(ROOT / "Carson_Chou_Resume.pdf"))
    a = ap.parse_args()
    out = Path(a.out)
    build(out, a.tests)
    print(f"已產出 {out}  ({out.stat().st_size:,} bytes)")
    if not a.tests:
        print("⚠️ 沒有傳 --tests,PDF 裡不會有測試數那一段（這是刻意的）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
