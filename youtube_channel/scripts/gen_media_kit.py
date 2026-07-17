#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_media_kit.py — 【變現基建】媒體包（Media Kit）產生器。

用途：pre-YPP 階段沒有 YouTube 廣告分潤，要靠贊助/接案變現，第一步永遠是
「一頁式媒體包」給對方看數據、受眾、代表作、合作方案。這支腳本純本機、
零外部呼叫，直接讀現成的 STUDIO 數據 json 組出來——不臆造任何數字，
缺什麼就留佔位讓 Carson 手動補（例如 YouTube Studio 後台才有的訂閱總數）。

資料源：
  channel_config.json          頻道定位／受眾／語氣
  STUDIO/uploaded_ledger.json  總片數（依 S_/L_ 前綴粗分 Shorts/長片）
  STUDIO/traffic_signals.json  近28天頻道數據＋熱門關鍵字＋Top影片
  STUDIO/quality_scores.json   已發布片單的 views/retention（挑代表作）
  STUDIO/finance.json          聯盟返佣實際入帳（證明「這頻道真的能導購」）

輸出：STUDIO/REPORTS/媒體包_{date}.md（純文字，方便 Carson 改）
      STUDIO/REPORTS/媒體包_{date}.html（排版好、可直接貼給對方看）
本檔只「產生檔案」，絕不寄信、不外發——那一步永遠由 Carson 按。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
CFG = ROOT / "channel_config.json"

TZ8 = timezone(timedelta(hours=8))
PLACEHOLDER = "〔待補：Carson 從 YouTube Studio 後台填〕"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):
        print(f"[{stage}] {msg}")


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def pct(n) -> str:
    return f"{n:.1f}%" if isinstance(n, (int, float)) else PLACEHOLDER


def num(n) -> str:
    return f"{n:,.0f}" if isinstance(n, (int, float)) else PLACEHOLDER


def gather():
    """把各資料源拉成媒體包要用的扁平結構，缺的欄位一律留佔位，不編數字。"""
    cfg = load(CFG, {}) or {}
    ledger = load(STUDIO / "uploaded_ledger.json", {}) or {}
    traffic = load(STUDIO / "traffic_signals.json", {}) or {}
    quality = load(STUDIO / "quality_scores.json", {}) or {}
    finance = load(STUDIO / "finance.json", {}) or {}
    tiktok_ledger = load(STUDIO / "tiktok_ledger.json", {}) or {}
    ig_ledger = load(STUDIO / "ig_ledger.json", {}) or {}

    keys = list(ledger.keys())
    n_shorts = sum(1 for k in keys if k.startswith("S_"))
    n_longs = sum(1 for k in keys if k.startswith("L_"))
    n_other = len(keys) - n_shorts - n_longs

    channel_28d = traffic.get("channel_28d", {}) or {}
    published = quality.get("published") or []
    with_views = [v for v in published if isinstance(v.get("views"), (int, float))]
    total_tracked_views = sum(v["views"] for v in with_views)
    avg_retention = (
        sum(v["retention"] for v in with_views if isinstance(v.get("retention"), (int, float)))
        / max(1, sum(1 for v in with_views if isinstance(v.get("retention"), (int, float))))
    ) if with_views else None

    top = sorted(with_views, key=lambda v: v["views"], reverse=True)[:6]

    fin_summary = finance.get("summary", {}) or {}

    # 跨平台觸及(A5):TikTok/IG 目前本機只有「已發布支數」(ledger 記 title→id/timestamp)，
    # 沒有逐支觀看/曝光數快取——不硬爬各平台後台湊數字，觸及數欄位誠實留 0／待接，
    # 不能拿發文數冒充觸及數。YouTube 那塊沿用上面已算好的 total_tracked_views(唯一有真數據的來源)。
    tiktok_posts = len(tiktok_ledger)
    ig_posts = len(ig_ledger)
    tiktok_reach = None  # 待接:無官方 API/本機快取可查逐支觀看數
    ig_reach = None  # 待接:同上(Graph API insights 需逐支呼叫，量大暫不做，避免多打)
    cross_platform_total_reach = total_tracked_views + (tiktok_reach or 0) + (ig_reach or 0)

    return {
        "cfg": cfg,
        "n_videos": len(keys),
        "n_shorts": n_shorts,
        "n_longs": n_longs,
        "n_other": n_other,
        "views_28d": channel_28d.get("views"),
        "avg_pct_28d": channel_28d.get("avg_pct"),
        "subs_gained_28d": channel_28d.get("subs_gained"),
        "win_keywords": traffic.get("win_keywords") or [],
        "total_tracked_views": total_tracked_views,
        "n_tracked": len(with_views),
        "avg_retention": avg_retention,
        "top": top,
        "affiliate_revenue": fin_summary.get("affiliate"),
        "tiktok_posts": tiktok_posts,
        "ig_posts": ig_posts,
        "tiktok_reach": tiktok_reach,
        "ig_reach": ig_reach,
        "cross_platform_total_reach": cross_platform_total_reach,
    }


def build_markdown(d: dict, date_str: str) -> str:
    cfg = d["cfg"]
    name = cfg.get("channel_name", "量化阿森｜Carson Quant")
    handle = cfg.get("channel_handle", "@carsonquant")
    niche = cfg.get("niche", "")
    audience = cfg.get("target_audience", "")
    tone = cfg.get("tone", "")
    tagline = (cfg.get("branding") or {}).get("intro_tagline", "")

    top_lines = []
    for v in d["top"]:
        vid = v.get("videoId")
        link = f"https://youtube.com/watch?v={vid}" if vid else ""
        title = (v.get("title") or "").strip()
        top_lines.append(
            f"- **{title}** — {num(v.get('views'))} 次觀看｜完播 {pct(v.get('retention'))}"
            + (f"｜{link}" if link else "")
        )
    top_block = "\n".join(top_lines) if top_lines else f"- {PLACEHOLDER}（尚無已同步 analytics 的代表作）"

    kw = "、".join(d["win_keywords"][:8]) if d["win_keywords"] else PLACEHOLDER

    md = f"""# {name} — 媒體合作資訊（Media Kit）

*更新日期：{date_str}｜頻道：{handle}｜本檔由 `scripts/gen_media_kit.py` 自動產生，數據直讀頻道後台快取，如需最新請重新執行*

---

## 一句話定位

> {tagline or niche}

**利基**：{niche}
**語氣**：{tone}

---

## 頻道快照（誠實版——目前是穩定成長中的小頻道，不是百萬網紅）

| 指標 | 數值 |
|---|---|
| 總影片數 | {num(d['n_videos'])}（Shorts {num(d['n_shorts'])}／長片 {num(d['n_longs'])}／其他系列 {num(d['n_other'])}） |
| 訂閱總數 | {PLACEHOLDER} |
| 近 28 天頻道觀看數 | {num(d['views_28d'])} |
| 近 28 天平均完播率 | {pct(d['avg_pct_28d'])} |
| 近 28 天新增訂閱 | {num(d['subs_gained_28d'])} |
| 已同步 analytics 片單觀看數合計 | {num(d['total_tracked_views'])}（{d['n_tracked']} 支影片有數據，其餘尚待 YouTube 後台同步） |
| 已同步片單平均完播率 | {pct(d['avg_retention'])} |
| 目前吃流量的關鍵字 | {kw} |

**更新頻率**：近乎每日產出（Shorts + 長片並行），內容全誠實回測/實測導向，不喊單、不誇大報酬（廣告主友善的合規紅線）。

---

## 跨平台總觸及（誠實版——YouTube 有真數據，TikTok／IG 觸及數待接）

| 平台 | 已發布支數 | 觸及數（觀看/曝光） |
|---|---|---|
| YouTube | {num(d['n_videos'])} | {num(d['total_tracked_views'])}（僅計已同步 analytics 的 {d['n_tracked']} 支） |
| TikTok | {num(d['tiktok_posts'])} | 0（待接：無官方 API/本機快取可查逐支觀看數） |
| Instagram | {num(d['ig_posts'])} | 0（待接：Graph API insights 需逐支呼叫，量大暫未做） |
| **跨平台總觸及（目前僅 YouTube 有實數，TikTok/IG 待接前以 0 計）** | — | **{num(d['cross_platform_total_reach'])}** |

---

## 受眾輪廓

{audience or PLACEHOLDER}

---

## 代表作（依已同步數據挑出的高完播/高觀看片）

{top_block}

---

## 為什麼跟我們合作

- **每支影片都是「我先幫你試」的實測/回測敘事**——不是純業配腔，觀眾信任度高、轉換路徑自然。
- **已驗證能導購**：現有 Pionex 聯盟返佣已產生實際入帳（{('約 NT$' + num(d['affiliate_revenue'])) if d['affiliate_revenue'] else PLACEHOLDER}），證明這頻道的觀眾真的會點連結、真的會行動。
- **內容產線可規模化**：頻道背後是一套自動化內容產線，能穩定、高頻率地產出符合品牌調性的置入內容，不受限於單人創作者的產能天花板。
- **利基精準**：鎖定 25-45 歲、有資金、想自動化交易但怕被割韭菜的台灣散戶——量化工具、券商、AI 生產力工具的高意向受眾。

---

## 合作方案與報價區間（成長期頻道報價，依實際檔期／曝光量／獨家程度議定）

| 方案 | 內容 | 參考價位 |
|---|---|---|
| Shorts 口播置入 | 60秒內短片中段口播 + 說明欄連結，1支 | 洽談（可先以聯盟返佣/試用交換起步） |
| 長片開頭/中段置入 | 10分鐘教學長片中安插「如何實際操作」段落 + 說明欄置頂連結 + 片尾 CTA | 洽談 |
| 專題實測片 | 用贊助方工具/平台做一支完整回測或實測影片（最高轉換路徑） | 洽談 |
| 說明欄常駐連結 | 既有影片庫（{num(d['n_videos'])} 支）追加聯盟連結，長尾曝光 | 依連結表現分潤 |
| TG 名單導流 | 私訊機器人磁鐵（策略包/回測模板）內置推薦 | 洽談 |

> 目前頻道規模仍在成長期，報價保守；建議優先以「聯盟返佣 + 低成本試單」開始合作，用實績（點擊/轉換數據）逐步談長期/固定費合作。

---

## 聯絡方式

- 頻道：{handle}（YouTube 搜尋「{name}」）
- 聯絡窗口：{PLACEHOLDER}
- 合作提案請參考：`STUDIO/REPORTS/接案開發信模板.md`

---

*免責：本媒體包所有數據取自頻道自有後台快取，如需第三方驗證（如 Social Blade / YouTube 官方 Analytics 截圖），請另外附上。*
"""
    return md


def build_html(md_body: str, d: dict, date_str: str) -> str:
    """把 markdown 內容包成一頁深色系 HTML，直接可以拿給對方看。"""
    cfg = d["cfg"]
    name = cfg.get("channel_name", "量化阿森｜Carson Quant")
    # 用品牌色：金 #FFD166 主色，深底
    import html as _html
    import re as _re

    def md_to_html(text: str) -> str:
        lines = text.split("\n")
        out = []
        in_table = False
        in_list = False
        for line in lines:
            raw = line.rstrip()
            if raw.startswith("### "):
                out.append(f"<h3>{_html.escape(raw[4:])}</h3>")
                continue
            if raw.startswith("## "):
                if in_list:
                    out.append("</ul>"); in_list = False
                out.append(f"<h2>{_html.escape(raw[3:])}</h2>")
                continue
            if raw.startswith("# "):
                out.append(f"<h1>{_html.escape(raw[2:])}</h1>")
                continue
            if raw.startswith("---"):
                out.append("<hr/>")
                continue
            if raw.startswith("|"):
                cells = [c.strip() for c in raw.strip("|").split("|")]
                if all(_re.fullmatch(r"-+", c) for c in cells):
                    continue
                if not in_table:
                    out.append('<table>'); in_table = True
                    out.append("<tr>" + "".join(f"<th>{_html.escape(c)}</th>" for c in cells) + "</tr>")
                else:
                    out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
                continue
            else:
                if in_table:
                    out.append("</table>"); in_table = False
            if raw.startswith("- "):
                if not in_list:
                    out.append("<ul>"); in_list = True
                out.append(f"<li>{_inline(raw[2:])}</li>")
                continue
            else:
                if in_list:
                    out.append("</ul>"); in_list = False
            if raw.startswith("> "):
                out.append(f"<blockquote>{_inline(raw[2:])}</blockquote>")
                continue
            if raw.strip() == "":
                out.append("")
                continue
            if raw.startswith("*") and raw.endswith("*") and not raw.startswith("**"):
                out.append(f"<p class='meta'>{_inline(raw.strip('*'))}</p>")
                continue
            out.append(f"<p>{_inline(raw)}</p>")
        if in_table:
            out.append("</table>")
        if in_list:
            out.append("</ul>")
        return "\n".join(out)

    def _inline(s: str) -> str:
        s = _html.escape(s)
        s = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = _re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        s = _re.sub(r"(https?://\S+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', s)
        return s

    body_html = md_to_html(md_body)

    return f"""<!doctype html>
<html lang="zh-Hant"><head>
<meta charset="utf-8"/>
<title>{_html.escape(name)} — 媒體合作資訊 {date_str}</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  :root {{ --gold:#FFD166; --teal:#06D6A0; --bg:#0e0f13; --panel:#171922; --text:#eef0f4; --sub:#9aa2b1; --line:#2a2d38; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif; line-height:1.75; }}
  .wrap {{ max-width:840px; margin:0 auto; padding:48px 24px 96px; }}
  h1 {{ font-size:28px; color:var(--gold); margin:0 0 4px; }}
  h2 {{ font-size:19px; color:var(--gold); border-left:4px solid var(--gold); padding-left:10px; margin:36px 0 12px; }}
  h3 {{ font-size:16px; color:var(--teal); margin:20px 0 8px; }}
  p {{ color:var(--text); margin:8px 0; }}
  p.meta {{ color:var(--sub); font-size:13px; }}
  blockquote {{ border-left:3px solid var(--teal); margin:12px 0; padding:6px 16px; color:#dfe3ea; background:rgba(6,214,160,0.06); border-radius:0 6px 6px 0; }}
  hr {{ border:none; border-top:1px solid var(--line); margin:28px 0; }}
  ul {{ padding-left:20px; }}
  li {{ margin:6px 0; }}
  table {{ width:100%; border-collapse:collapse; margin:12px 0; font-size:14px; }}
  th, td {{ border:1px solid var(--line); padding:8px 10px; text-align:left; }}
  th {{ background:var(--panel); color:var(--gold); }}
  td {{ background:rgba(255,255,255,0.02); }}
  a {{ color:var(--teal); }}
  code {{ background:var(--panel); padding:1px 6px; border-radius:4px; color:var(--teal); }}
  strong {{ color:#fff; }}
  .wrap > p:first-of-type {{ color:var(--sub); font-size:13px; }}
</style>
</head><body>
<div class="wrap">
{body_html}
</div>
</body></html>"""


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(TZ8).strftime("%Y-%m-%d")

    d = gather()
    md = build_markdown(d, date_str)
    html = build_html(md, d, date_str)

    md_path = REPORTS / f"媒體包_{date_str}.md"
    html_path = REPORTS / f"媒體包_{date_str}.html"
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")

    log_ops("媒體包", f"已產生 {md_path.name} / {html_path.name}（{d['n_videos']} 支片、{d['n_tracked']} 支有 analytics）")
    print(f"寫入：{md_path}")
    print(f"寫入：{html_path}")


if __name__ == "__main__":
    main()
