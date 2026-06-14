#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""produce_batch.py — 自動補產（創作靈感+影片+Shorts部門）。

用 Claude API 寫新腳本 → 免費 Edge TTS 配音 → 渲染成片，把片庫補到目標量。
與每日上架排程接成無限迴圈：補產填庫、上架排程(含審核)出貨。

用法：python scripts\\produce_batch.py [--shorts 4] [--long 1] [--target 15]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ops import log_ops
import audit_video
OUT = ROOT / "output"
# 跨平台 venv python 路徑（Windows: Scripts/python.exe；Linux/雲端: bin/python）
_py_win = ROOT / ".venv" / "Scripts" / "python.exe"
_py_nix = ROOT / ".venv" / "bin" / "python"
PY = _py_win if _py_win.exists() else (_py_nix if _py_nix.exists() else Path(sys.executable))
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-haiku-4-5-20251001"  # 便宜、寫腳本夠用

GUARD = ("誠信鐵則：不編造個人損益、不保證收益、不喊單、絕不用『保證賺/穩賺不賠/一定賺』等詞；"
         "聯盟軟推＋風險聲明；教學與觀念為主。頻道＝量化阿森｜Carson Quant，繁體中文，"
         "主題＝量化／自動交易（網格、定投、派網 Pionex、回測、風控）。")

# 量化內容嚴謹標準（蒸餾自 domain-quant-trading skill）：確保用語/公式正確、避開錯誤觀念，
# 內容紮實可信＝頻道差異化。寫到相關主題時務必正確引用，不確定就不要硬講數字。
QUANT_STANDARD = (
    "【量化內容嚴謹標準｜務必正確，這是頻道專業度的命脈】\n"
    "・指標定義要正確：夏普比率=(報酬-無風險利率)/報酬標準差，>1.5 算好；最大回撤=峰值到谷值最大跌幅，<20% 較健康；"
    "卡瑪比率=年化報酬/最大回撤，>1 較佳；勝率高不等於賺，要搭配盈虧比看期望值(期望值=勝率×平均獲利-敗率×平均虧損)。\n"
    "・策略本質要講對：趨勢跟蹤在震盪市虧、均值回歸/網格在單邊趨勢市虧——這就是網格遇單邊行情會賠的根因，別講反。\n"
    "・回測五大陷阱要講對(這是高價值題材)：①過度擬合(參數對歷史過度優化，回測夏普>3常是假的)②前視偏差(用到未來數據，信號要延遲一天)"
    "③生存者偏差(只用現存股票會高估)④忽略交易成本(手續費~0.1%+滑價~0.2%，高換手會被吃光)⑤沒做樣本外測試(資料要切訓練/驗證/測試)。\n"
    "・風控觀念：單筆停損約2%、單一策略不超過總資金20%、Kelly 公式 f*=(p×b-q)/b 實務用 Half-Kelly。\n"
    "・誠實：歷史績效不代表未來；舉例用『假設/示意』，不暗示真實獲利。")


def existing_titles():
    out = []
    for f in OUT.glob("*.md"):
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0]
            out.append(first.replace("# 🎬", "").strip())
        except Exception:
            pass
    return out


def queue_size():
    """片庫量＝已成片(mp4)或已備妥待渲染(voice.txt)的去重 slug 數，
    讓雲端『只產腳本配音』模式也能正確計量、不會無限爆產。"""
    slugs = set()
    for f in OUT.glob("S_*.mp4"):
        slugs.add(f.stem)
    for f in OUT.glob("L_*.mp4"):
        slugs.add(f.stem)
    for f in OUT.glob("S_*.voice.txt"):
        slugs.add(f.name[:-len(".voice.txt")])
    for f in OUT.glob("L_*.voice.txt"):
        slugs.add(f.name[:-len(".voice.txt")])
    return len(slugs)


def slugify(title, prefix):
    # 移除半形與全形標點/空白，保留中英數字，檔名乾淨且不過長
    s = re.sub(r'[\\/:*?"<>|\s,.!;:~`@#$%^&*()\[\]{}+=\'。、！？；：「」『』（）【】〈〉《》…．·｜｜，－—‧]+', "", title)[:26]
    return f"{prefix}_{s}"


def load_orders():
    p = ROOT / "STUDIO" / "production_orders.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def pull_topic(kind):
    """從 STUDIO/topic_bank.json 取一個未用、符合格式的題目並標記為已用；無則回 None。"""
    bank_path = ROOT / "STUDIO" / "topic_bank.json"
    if not bank_path.exists():
        return None
    try:
        bank = json.loads(bank_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    for t in bank:
        if not t.get("used") and t.get("format", "short") == kind:
            t["used"] = True
            try:
                bank_path.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            return t
    return None


def call_claude(kind, avoid):
    orders = load_orders()
    # 先從題庫抽指定題目（擴題庫後放量也不重複）；題庫空了才自由發揮
    topic = pull_topic(kind)
    assign = ""
    if topic:
        assign = (f"\n【本支指定題目（題庫派發，務必照此主題寫，標題可潤飾更有點擊慾）】："
                  f"{topic.get('title','')}　切入點：{topic.get('angle','')}")
    bias = ""
    if orders:
        pk = "、".join(orders.get("preferred_keywords", [])[:8])
        pm = "；".join(orders.get("produce_more", [])[:6])
        av = "、".join(orders.get("avoid_topics", [])[:8])
        if pk or pm:
            bias = f"\n【決策部門指令】優先方向：{pm}。偏好關鍵字：{pk}。" + (f"避免題材：{av}。" if av else "")
    if kind == "short":
        spec = ("一支 15–45 秒直式 Shorts。voice_text 90–160 字、前 2 秒就是鉤子、講清一個觀念、"
                "結尾一句『想看完整版？追蹤量化阿森』。segments 給 1–2 段。")
    else:
        spec = ("一支 8–10 分鐘長片。voice_text 1300–1700 字（HOOK→正文 4–5 段→軟性 CTA 訂閱+派網→下集預告）。"
                "segments 給 4–5 段。")
    prompt = f"""你是量化阿森頻道的專業腳本寫手。{GUARD}
{QUANT_STANDARD}
請產生{spec}{assign}{bias}
【高點擊標題框架，擇一套用且自然】：①「如何…」具體承諾（含時間/數字，如「3 分鐘看懂…」）②「你一直做錯」揭錯（如「網格參數你設錯了…」）③「祕密/真相揭露」（如「高手不講的…」）④反直覺結論。標題要有好奇缺口但不誇大、不保證收益。
請避免重複這些既有題目：{avoid[:50]}
只輸出 JSON（不要任何其他文字、不要 markdown 圍欄），格式：
{{"title":"有點擊慾的標題","voice_text":"完整旁白逐字稿(口語、適合中文TTS)","segments":[{{"heading":"段落小標","broll":["english keyword","english keyword"]}}],"description":"SEO 描述（1-2 句精簡、含關鍵字，結尾含風險聲明『投資有風險，不構成投資建議』）","hashtags":["#Shorts","#量化交易","#..."]}}
hashtags 規則：給 4-6 個「精準且利基相關」的標籤(第一個必為 #Shorts)，不要硬塞 20 個——精準勝過熱門，乾淨又利於演算法分類。"""
    body = {"model": MODEL, "max_tokens": 3500, "messages": [{"role": "user", "content": prompt}]}
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json=body, timeout=150)
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError("Claude 回應非 JSON")
    return json.loads(m.group(0))


def build_md(d):
    title = d["title"]
    voice = d.get("voice_text", "")
    lines = [f"# 🎬 {title}", "", "> 頻道：量化阿森｜Carson Quant｜自動產製", "", "---", "",
             "## ⚡ HOOK（0-5 秒）", "", f"**旁白：** {voice[:55]}", "",
             "**建議畫面：** stock market chart、trading screen", "", "## 📦 主體", ""]
    segs = d.get("segments") or [{"heading": "重點", "broll": ["finance", "chart"]}]
    for i, seg in enumerate(segs, 1):
        kws = "、".join(seg.get("broll") or ["finance", "data"])
        lines += [f"### 段落 {i}：{seg.get('heading', '重點')}", "",
                  f"**旁白：** {seg.get('heading', '')}", "",
                  f"**建議畫面 / B-roll：** {kws}", ""]
    lines += ["## 🏁 結尾（OUTRO）", "", "**旁白：** 追蹤量化阿森，我們下支見。", "", "---", "",
              "## 📝 YouTube 影片描述", "",
              d.get("description", "量化交易教學與觀念分享。投資有風險，不構成投資建議。"), "",
              f"**Hashtags：** {' '.join(d.get('hashtags') or ['#量化交易', '#自動交易'])}", ""]
    return "\n".join(lines)


def make_one(kind, no_render=False):
    d = call_claude(kind, existing_titles())
    prefix = "S" if kind == "short" else "L"
    slug = slugify(d["title"], prefix)
    if (OUT / f"{slug}.voice.txt").exists() or (OUT / f"{slug}.mp4").exists():
        slug = f"{slug}{int(time.time()) % 10000}"
    (OUT / f"{slug}.voice.txt").write_text(d["voice_text"], encoding="utf-8")
    (OUT / f"{slug}.md").write_text(build_md(d), encoding="utf-8")

    subprocess.run([str(PY), "scripts/tts_edge.py", f"output/{slug}.voice.txt"], cwd=str(ROOT))

    # 雲端模式：只產腳本＋配音，渲染交給 PC 端 render_watcher（混合架構）。
    if no_render:
        mp3_ok = (OUT / f"{slug}.mp3").exists()
        log_ops("補產·雲端", f"{'已備妥待渲染' if mp3_ok else '配音失敗'}：{slug}")
        print(f"[{'queued' if mp3_ok else 'FAIL'}] {kind} {slug}（待 PC 渲染）")
        return mp3_ok

    env = os.environ.copy()
    if kind == "short":
        env.pop("PEXELS_API_KEY", None)  # Shorts 走乾淨字卡
        subprocess.run([str(PY), "scripts/make_video.py", "--slug", slug, "--width", "1080", "--height", "1920"],
                       cwd=str(ROOT), env=env)
    else:
        subprocess.run([str(PY), "scripts/make_video.py", "--slug", slug], cwd=str(ROOT), env=env)
    ok = (OUT / f"{slug}.mp4").exists() and (OUT / f"{slug}.mp4").stat().st_size > 100 * 1024
    if ok:  # 產製即審核：壞片/違規早發現
        passed, reasons = audit_video.audit(slug)
        if not passed:
            log_ops("補產·審核", f"⚠️ {slug} 審核未過：{'；'.join(reasons)[:60]}")
    print(f"[{'ok' if ok else 'FAIL'}] {kind} {slug}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shorts", type=int, default=4)
    ap.add_argument("--long", type=int, default=1)
    ap.add_argument("--target", type=int, default=15)
    ap.add_argument("--no-render", action="store_true",
                    help="雲端模式：只產腳本+配音，渲染交給 PC 端 render_watcher")
    args = ap.parse_args()

    # 員額即產能：人事部在 headcount.json 設的 ②Shorts／①影片 員額 = 每日產出量（加員額＝加產能）。
    hc_path = ROOT / "STUDIO" / "headcount.json"
    if hc_path.exists():
        try:
            hc = json.loads(hc_path.read_text(encoding="utf-8"))
            if isinstance(hc.get("②"), int):
                args.shorts = max(0, hc["②"])
            if isinstance(hc.get("①"), int):
                args.long = max(0, hc["①"])
            print(f"[info] 依人事部員額編制 → 今日產出 Shorts {args.shorts} 支、長片 {args.long} 支")
        except Exception:
            pass

    bpath = ROOT / "STUDIO" / "boss_directives.json"
    if bpath.exists():
        try:
            if json.loads(bpath.read_text(encoding="utf-8")).get("paused"):
                print("[info] 老闆已暫停全自動，今日不補產。")
                return 0
        except Exception:
            pass

    if not API_KEY:
        print("[FATAL] 找不到 ANTHROPIC_API_KEY 環境變數。", file=sys.stderr)
        return 2

    q = queue_size()
    print(f"目前片庫：{q} 支 / 目標 {args.target}")
    if q >= args.target:
        print("片庫充足，本次不補產。")
        return 0

    def attempt(kind):
        for t in range(2):  # 自我修復：失敗自動重試一次
            try:
                if make_one(kind, no_render=args.no_render):
                    return True
            except Exception as exc:  # noqa: BLE001
                print(f"[err {kind} 第{t+1}次] {exc}", file=sys.stderr)
        log_ops("補產部門", f"⚠️ {kind} 連續失敗，跳過")
        return False

    log_ops("補產部門", f"開始補產（庫存 {q}/{args.target}）…")
    made = sum(1 for _ in range(args.shorts) if attempt("short"))
    made += sum(1 for _ in range(args.long) if attempt("long"))
    log_ops("補產部門", f"完成 補產{made}支，片庫{queue_size()}支")
    print(f"本次補產 {made} 支，片庫現 {queue_size()} 支。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
