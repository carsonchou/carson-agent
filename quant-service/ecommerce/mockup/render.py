#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render.py — 把 mockup HTML 用 headless Chromium 印成 A4 PDF(深色印底)。

這支就是 v2 渲染管線的最小可行版:HTML+CSS → Playwright Chromium → page.pdf。
關鍵:print_background=True(印深色底)、prefer_css_page_size(吃 .page 的 A4 尺寸)、
margin=0(邊界由 CSS 自管)。繁中走系統字型(Microsoft JhengHei / Noto Serif TC)。

用法:python render.py [輸入.html] [輸出.pdf]
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
src = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "subscription_weekly_sample.html"
out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".pdf")


def render(src: Path, out: Path) -> Path:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(src.resolve().as_uri(), wait_until="networkidle")
        pg.emulate_media(media="print")
        pg.pdf(
            path=str(out),
            prefer_css_page_size=True,   # 用 .page 的 210mm×297mm
            print_background=True,        # 深色底真的印進去
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        b.close()
    return out


if __name__ == "__main__":
    p = render(src, out)
    kb = p.stat().st_size / 1024
    print(f"[render] OK → {p}  ({kb:.0f} KB)")
