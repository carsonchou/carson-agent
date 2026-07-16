#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xlsx_dashboard_sample.py — v2 xlsx 儀表板規格(§6)的 openpyxl 佐證樣張。

證明 openpyxl 能做到:多工作表、深色表頭、凍結窗格、自動篩選、
台股紅綠 3 色階條件格式(高報酬=紅、回撤反向)、icon set 燈號、data bar、
數字格式、代號留字串、斑馬內文。數據標 SAMPLE(端點取自訂閱週報真實值)。

輸出:xlsx_dashboard_sample.xlsx
"""
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.formatting.rule import ColorScaleRule, IconSetRule, DataBarRule

HERE = Path(__file__).resolve().parent
OUT = HERE / "dashboard_sample.xlsx"

# token(對齊 REDESIGN_SPEC_product.md §2.1)
BG_HEAD = "0B0E14"; GOLD = "E3B93E"; ZEBRA = "F4F6F9"
UP = "E5484D"; DN = "2FB877"; MID = "F2F2F2"  # 條件格式:低綠→中→高紅(台股)

thin = Side(style="thin", color="D6DBE3")
BORDER = Border(bottom=thin)

# 真實端點(取自 sample_weekly_2026-07-15.md);代號留字串
ROWS = [
    # 代號, 名稱, 市場, 20年年化%, 最大回撤%, 估值百分位, 最長套牢(年), 近5年殖利率%
    ("2330", "台積電", "上市", 25.1, -46.5, 98, 10.7, 2.0),
    ("2454", "聯發科", "上市", 20.4, -69.4, 99, 5.4, 6.2),
    ("2603", "長榮",   "上市", 15.5, -70.5, 55, 9.9, 27.6),
    ("2317", "鴻海",   "上市", 10.4, -75.0, 92, 9.0, 4.5),
    ("2412", "中華電", "上市", 8.5, -27.4, 79, 4.8, 4.4),
    ("2882", "國泰金", "上市", 7.2, -72.0, 83, 10.3, 6.0),
    ("00878", "國泰永續高股息", "上市", 22.0, -22.3, 0, 1.4, 9.4),
    ("2408", "南亞科", "上市", 2.3, -98.5, 98, 25.9, 3.9),
]
HEAD = ["代號", "名稱", "市場", "20年年化%", "最大回撤%", "估值位階(百分位)", "最長套牢(年)", "近5年殖利率%"]


def style_header(ws, ncol):
    ws.row_dimensions[1].height = 28
    for c in range(1, ncol + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = PatternFill(start_color=BG_HEAD, end_color=BG_HEAD, fill_type="solid")
        cell.font = Font(color=GOLD, bold=True, size=11)
        cell.alignment = Alignment(horizontal="center", vertical="center")


def build_overview(wb):
    ws = wb.active
    ws.title = "總覽"
    ws.append(HEAD)
    style_header(ws, len(HEAD))
    for i, r in enumerate(ROWS, start=2):
        ws.append(list(r))
        if i % 2 == 0:  # 斑馬內文
            for c in range(1, len(HEAD) + 1):
                ws.cell(row=i, column=c).fill = PatternFill(start_color=ZEBRA, end_color=ZEBRA, fill_type="solid")
        ws.cell(row=i, column=1).alignment = Alignment(horizontal="left")
        for c in (4, 5, 6, 7, 8):
            ws.cell(row=i, column=c).border = BORDER
    last = len(ROWS) + 1

    # 數字格式
    for c, fmt in ((4, '0.0"%"'), (5, '0.0"%"'), (7, '0.0"年"'), (8, '0.0"%"'), (6, '0"P"')):
        for row in range(2, last + 1):
            ws.cell(row=row, column=c).number_format = fmt

    # 凍結窗格(表頭 + 首欄)、自動篩選
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:H{last}"

    # 台股 3 色階:年化報酬 低綠→中→高紅(高報酬=紅)
    ws.conditional_formatting.add(
        f"D2:D{last}",
        ColorScaleRule(start_type="min", start_color=DN, mid_type="percentile", mid_value=50,
                       mid_color=MID, end_type="max", end_color=UP))
    # 最大回撤(更負=更糟):反向,低(更負)=紅、高(近0)=綠
    ws.conditional_formatting.add(
        f"E2:E{last}",
        ColorScaleRule(start_type="min", start_color=UP, mid_type="percentile", mid_value=50,
                       mid_color=MID, end_type="max", end_color=DN))
    # 估值位階燈號:icon set 三燈(位置指示,非買賣)
    ws.conditional_formatting.add(
        f"F2:F{last}", IconSetRule("3TrafficLights1", "percent", [0, 60, 95], showValue=True))
    # 殖利率 data bar(暗金)
    ws.conditional_formatting.add(
        f"H2:H{last}", DataBarRule(start_type="min", end_type="max", color=GOLD))

    widths = [8, 16, 6, 12, 12, 16, 14, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    # 頂部備註列(凍結區外説明)——放在最後一列下方
    note = last + 2
    ws.cell(row=note, column=1,
            value="SAMPLE 示意樣張|色階:高報酬=紅、回撤反向(台股慣例)|燈號僅標估值位置非買賣|來源:FinMind/Yahoo 含息還原")
    ws.cell(row=note, column=1).font = Font(color="8A94A6", size=9, italic=True)


def build_dca(wb):
    ws = wb.create_sheet("定投對照")
    head = ["代號", "名稱", "單筆All-in總報酬%", "每月定投總報酬%", "同期0050總報酬%"]
    ws.append(head); style_header(ws, len(head))
    dca = [
        ("2330", "台積電", 1746.9, 669.2, 751.5),
        ("2412", "中華電", 68.1, 48.2, 751.5),
        ("2408", "南亞科", 1691.3, 672.7, 751.5),
        ("2882", "國泰金", 317.1, 151.1, 751.5),
        ("00878", "國泰永續高股息", 230.6, 122.3, 430.9),
    ]
    for i, r in enumerate(dca, start=2):
        ws.append(list(r))
        for c in (3, 4, 5):
            ws.cell(row=i, column=c).number_format = '#,##0.0"%"'
    last = len(dca) + 1
    ws.freeze_panes = "C2"; ws.auto_filter.ref = f"A1:E{last}"
    for col in ("C", "D", "E"):
        ws.conditional_formatting.add(f"{col}2:{col}{last}", DataBarRule(start_type="min", end_type="max", color=GOLD))
    for i, w in enumerate([8, 16, 18, 18, 18], start=1):
        ws.column_dimensions[chr(64 + i)].width = w


if __name__ == "__main__":
    wb = openpyxl.Workbook()
    build_overview(wb)
    build_dca(wb)
    wb.save(str(OUT))
    print(f"[xlsx] OK -> {OUT}  ({OUT.stat().st_size/1024:.0f} KB, {len(wb.sheetnames)} sheets: {wb.sheetnames})")
