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
import signal
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

# 爆款腳本心法（蒸餾自 31 支繁中/英文對標競品實證，見 STUDIO/script_playbook.md）。
# 把市場領袖驗證過的鉤子/比喻/誠實護城河/置入手法寫進每一支腳本，這是頻道的差異化武器。
# 注意：這只是「預設/種子」。實際每次製作會即時讀 STUDIO/competitor_playbook.md（競品情報部會更新它），
# 讀不到才退回這份預設 —— 確保競品 playbook 一更新，下一支腳本就吃到最新版。
_DEFAULT_PLAYBOOK = (
    "【爆款腳本心法｜蒸餾自 31 支繁中/英文對標競品實證，務必融入】\n"
    "・開場鉤子（前 2 秒就要，禁制式問候，擇一套用）：①反差去推銷「這不是喊單頻道，我只做能回測驗證的東西」"
    "（Terry 661K 最毒招，先否定自己→可信度爆表）②反共識先破後立「大家都說網格穩賺？我用回測打臉這句」"
    "（懶錢包 102萬）③精確數字+括號懸念「這組網格參數回測勝率 87%（但有個代價你必須知道）」（Rayner 1.79M）"
    "④挑釁反問「你的網格機器人，是設計來盤整賺錢、還是趁你睡覺把本金歸零？」⑤暴利數字+懷疑「這支 bot 標 900% ROI…"
    "是真的還是僥倖？我幫你拆」。\n"
    "・生活化比喻（faceless 無真人魅力，比喻＝記憶命脈；固定同一套世界觀貫穿全頻道）：網格交易＝菜市場大媽／開雜貨店"
    "（便宜囤貨、貴了出貨，賺價差不賭漲跌）；定投 DCA＝每月往存錢罐丟零錢／搭手扶梯慢慢上樓；過擬合＝背考古題背到滾瓜爛熟、"
    "上考場一換題就掛；複利＝滾雪球；最大回撤＝雲霄飛車半路的那段下坡。能用比喻就別丟術語。\n"
    "・差異化硬度：講參數／結論一律用『回測數據』背書（呼應量化定位）；對手全靠個人經驗截圖、無系統化回測，這是你的護城河。\n"
    "・誠實護城河（賽道最稀缺、最圈粉）：主動揭露回撤／勝率／『這策略我也會虧的情況是…』『全市場回測只約 35% 標的會賺，所以要選』；"
    "對手通病＝只曬贏單、報喜不報憂、標題說被動收入內容卻是高槓桿合約——你反著做就贏信任。\n"
    "・Pionex 置入：把『用派網機器人執行這套』寫進『如何實際操作』的必經步驟裡（不是硬插廣告）；片尾單一明確 CTA，全片只收割一次。\n"
    "・結構節奏：先秀成品（回測曲線／結果畫面）再回頭教；同一組乾淨數字（如本金 1 萬＋某參數）從頭走到尾降認知負擔；零廢話、高資訊密度。")

# 完整 A–L 競品心法種子（tracked，會隨 repo 上雲端；STUDIO/ 被 gitignore 拿不到，故種子必須在此）。
SEED_FILE = ROOT / "scripts" / "competitor_playbook_seed.md"


def _seed_playbook() -> str:
    """讀 tracked 的完整 A–L 種子；讀不到才退回上面的精簡內嵌版。"""
    try:
        if SEED_FILE.exists():
            txt = SEED_FILE.read_text(encoding="utf-8").strip()
            if txt:
                return txt
    except Exception:
        pass
    return _DEFAULT_PLAYBOOK


# 每次製作即時讀的競品 playbook 外部檔（競品情報部更新它 → 下次製作自動吃最新版）。
PLAYBOOK_FILE = ROOT / "STUDIO" / "competitor_playbook.md"


_PB_STAMPED = False  # 每個 process 只蓋一次指紋章，避免洗版 log


def _stamp_playbook(txt: str, source: str) -> None:
    """在 cron.log 蓋指紋章：讓你從雲端 log 就看得出這輪製作讀到哪一版 playbook。"""
    global _PB_STAMPED
    if _PB_STAMPED:
        return
    _PB_STAMPED = True
    dates = re.findall(r"20\d{2}-\d{2}-\d{2}", txt)
    latest = max(dates) if dates else "無日期"
    try:
        log_ops("讀心法", f"來源={source}｜{len(txt)}字｜最新招式={latest}")
    except Exception:
        pass


def load_playbook() -> str:
    """每次製作即時讀競品 playbook：有外部檔且非空就用它（吃最新更新），否則退回完整 A–L 種子。"""
    try:
        if PLAYBOOK_FILE.exists():
            txt = PLAYBOOK_FILE.read_text(encoding="utf-8").strip()
            if txt:
                _stamp_playbook(txt, "競品外部檔")
                return txt
    except Exception:
        pass
    seed = _seed_playbook()
    _stamp_playbook(seed, "種子退回")
    return seed


# 進修部門每週產的洞察（資料驅動），製作時即時讀來補強。
TRAINING_FILE = ROOT / "STUDIO" / "training_insights.md"


def load_training() -> str:
    """讀本週進修洞察（製作/選題相關），有就回傳一段提示、沒有回空字串。"""
    try:
        if TRAINING_FILE.exists():
            txt = TRAINING_FILE.read_text(encoding="utf-8").strip()
            if txt:
                return "\n\n【本週進修重點｜資料驅動，務必融入】\n" + txt
    except Exception:
        pass
    return ""


def existing_titles():
    out = []
    # 按修改時間倒序：最近生成的在前面，讓 avoid[:N] 優先涵蓋近期題材
    for f in sorted(OUT.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0]
            t = first.replace("# 🎬", "").strip()
            if t:
                out.append(t)
        except Exception:
            pass
    # 從已上架 ledger 讀標題，防止每日重複生成近似題材
    ledger_path = ROOT / "STUDIO" / "uploaded_ledger.json"
    if ledger_path.exists():
        try:
            import re as _re
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            for slug_key in ledger:
                title = _re.sub(r"^[SL]_", "", slug_key)
                title = _re.sub(r"\d{3,5}$", "", title)
                if title:
                    out.append(title)
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


def call_claude(kind, avoid, topic_override=None):
    orders = load_orders()
    # 時事優先：有指定題目（金融時事）就用它，否則從題庫抽；題庫空了才自由發揮
    topic = topic_override or pull_topic(kind)
    assign = ""
    if topic and topic_override:
        assign = (f"\n【🔥金融時事·優先製作，務必照此主題】：{topic.get('title','')}　切入點：{topic.get('angle','')}"
                  "（這是即時財經時事：緊扣新聞點，再連到頻道的量化/網格/派網/風控觀點；"
                  "只講已知事實、不誇大、不預測價格漲跌、不喊單、不保證收益）")
    elif topic:
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
    playbook = load_playbook()  # 每支腳本都即時讀最新競品 playbook
    training = load_training()  # 每週進修部門的資料驅動洞察
    avoid_block = "\n".join(f"  · {t}" for t in (avoid or [])[:60]) if avoid else "  （無）"
    prompt = f"""你是量化阿森頻道的專業腳本寫手。{GUARD}
{QUANT_STANDARD}
{playbook}{training}
請產生{spec}{assign}{bias}
【配音友善·務必遵守（影響聽感與留存）】voice_text 要口語、**短句為主（每句約 15-25 字就用句號斷開）**；
少用括號/破折號/冒號/刪節號；數字盡量寫成口語念法（如「百分之八」別寫「8%」、「一萬元」別寫「$10000」、「零點五」別寫「0.5」）；
一句話別塞太多數據（最多一個數字），讓人聽得清、TTS 念得順、斷點自然。
【高點擊標題框架，擇一套用且自然】：①「如何…」具體承諾（含時間/數字，如「3 分鐘看懂…」）②「你一直做錯」揭錯（如「網格參數你設錯了…」）③「祕密/真相揭露」（如「高手不講的…」）④反直覺結論。標題要有好奇缺口但不誇大、不保證收益。
請避免重複以下已有題目（換切角可以，換字重說同主題不行）：
{avoid_block}
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


def _tts_engine():
    try:
        d = json.loads((ROOT / "STUDIO" / "design_system.json").read_text(encoding="utf-8"))
        return (d.get("tts_engine") or "edge").lower()
    except Exception:
        return "edge"


def _run_tts(slug):
    """配音：依 design_system 選引擎；MiniMax(付費自然音)失敗自動退回免費 edge，不中斷生產。"""
    vp = f"output/{slug}.voice.txt"
    mp3 = OUT / f"{slug}.mp3"
    if _tts_engine() == "minimax":
        subprocess.run([str(PY), "scripts/tts_minimax.py", vp], cwd=str(ROOT))
        if mp3.exists() and mp3.stat().st_size > 0:
            return
        log_ops("配音", f"⚠️ MiniMax 配音失敗，退回 edge：{slug}")
    subprocess.run([str(PY), "scripts/tts_edge.py", vp], cwd=str(ROOT))


def _run_render(args, env, timeout=720):
    """跑 make_video，逾時就連同子程序(ffmpeg)整組殺掉 —— 防殭屍 ffmpeg 卡死整批製作。"""
    kw = {"cwd": str(ROOT), "env": env}
    if os.name == "posix":
        kw["start_new_session"] = True  # 自成 process group，逾時可整組 kill
    p = subprocess.Popen([str(PY)] + args, **kw)
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        log_ops("補產·渲染", f"⚠️ 渲染逾時 {timeout}s 強制中止：{args[2] if len(args) > 2 else ''}")
        print(f"[TIMEOUT] 渲染逾時，強制中止 {timeout}s", file=sys.stderr)
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)  # 連 ffmpeg 子程序一起殺
            else:
                p.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass


def make_one(kind, no_render=False, topic_override=None):
    d = call_claude(kind, existing_titles(), topic_override)
    prefix = "S" if kind == "short" else "L"
    slug = slugify(d["title"], prefix)
    if (OUT / f"{slug}.voice.txt").exists() or (OUT / f"{slug}.mp4").exists():
        slug = f"{slug}{int(time.time()) % 10000}"
    (OUT / f"{slug}.voice.txt").write_text(d["voice_text"], encoding="utf-8")
    (OUT / f"{slug}.md").write_text(build_md(d), encoding="utf-8")

    _run_tts(slug)

    # 雲端模式：只產腳本＋配音，渲染交給 PC 端 render_watcher（混合架構）。
    if no_render:
        mp3_ok = (OUT / f"{slug}.mp3").exists()
        log_ops("補產·雲端", f"{'已備妥待渲染' if mp3_ok else '配音失敗'}：{slug}")
        print(f"[{'queued' if mp3_ok else 'FAIL'}] {kind} {slug}（待 PC 渲染）")
        return slug if mp3_ok else None

    env = os.environ.copy()
    if kind == "short":
        env.pop("PEXELS_API_KEY", None)  # Shorts 走乾淨字卡
        _run_render(["scripts/make_video.py", "--slug", slug, "--width", "1080", "--height", "1920"], env, timeout=720)
    else:
        _run_render(["scripts/make_video.py", "--slug", slug], env, timeout=2400)  # 長片渲染久，給 40 分鐘
    ok = (OUT / f"{slug}.mp4").exists() and (OUT / f"{slug}.mp4").stat().st_size > 100 * 1024
    if ok:  # 產製即審核：壞片/違規早發現
        passed, reasons = audit_video.audit(slug)
        if not passed:
            log_ops("補產·審核", f"⚠️ {slug} 審核未過：{'；'.join(reasons)[:60]}")
            _FATAL = ("片長過短", "無視訊軌", "無音軌", "檔案過小")
            if any(any(tag in r for tag in _FATAL) for r in reasons):
                # 結構性壞片（0s/無影音軌）：清除佔位檔案，讓 queue_size 正確，觸發重試
                for ext in (".mp4", ".mp3", ".voice.txt"):
                    try:
                        (OUT / f"{slug}{ext}").unlink(missing_ok=True)
                    except Exception:
                        pass
                log_ops("補產·品管", f"結構性壞片已清除：{slug}")
                ok = False
            elif "缺風險聲明" in " ".join(reasons):
                # 唯一缺失：在 md 末尾補聲明即可，不需退件
                try:
                    md_path = OUT / f"{slug}.md"
                    md_text = md_path.read_text(encoding="utf-8")
                    if "風險" not in md_text and "不構成投資建議" not in md_text:
                        md_path.write_text(md_text.rstrip() + "\n\n投資有風險，不構成投資建議。", encoding="utf-8")
                    passed, reasons = audit_video.audit(slug)
                    if not passed:
                        log_ops("補產·合規", f"自動補風險聲明後仍未過：{slug}")
                except Exception:
                    pass
    print(f"[{'ok' if ok else 'FAIL'}] {kind} {slug}")
    return slug if ok else None


def _publish_now(slug: str):
    """消息面即時發布（過審才發）。重用 daily_publish 的上傳/ledger，繞過每日排程。"""
    try:
        import daily_publish as dp
    except Exception as exc:  # noqa: BLE001
        log_ops("時事發布", f"⚠️ 無法載入發布模組：{str(exc)[:60]}")
        return
    try:
        passed, reasons = audit_video.audit(slug)
        if not passed:
            log_ops("時事發布", f"審核未過未發：{slug}｜{'；'.join(reasons)[:50]}")
            print(f"[時事發布] 審核未過，未發布：{slug}")
            return
        priv = "public"  # 時事要即時公開；若老闆設了全域隱私則遵循
        try:
            bp = ROOT / "STUDIO" / "boss_directives.json"
            if bp.exists():
                v = json.loads(bp.read_text(encoding="utf-8")).get("privacy")
                if v in ("public", "unlisted", "private"):
                    priv = v
        except Exception:
            pass
        yt = dp.get_service()
        vid = dp.upload_one(yt, slug, priv)
        led = dp.load_ledger(); led[slug] = vid; dp.save_ledger(led)
        log_ops("時事發布", f"時事片即時發布 https://youtu.be/{vid}")
        print(f"[時事發布] 已即時發布：https://youtu.be/{vid}")
    except Exception as exc:  # noqa: BLE001
        log_ops("時事發布", f"⚠️ 即時發布失敗：{str(exc)[:70]}")
        print(f"[時事發布] 失敗：{exc}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shorts", type=int, default=4)
    ap.add_argument("--long", type=int, default=1)
    ap.add_argument("--target", type=int, default=15)
    ap.add_argument("--no-render", action="store_true",
                    help="雲端模式：只產腳本+配音，渲染交給 PC 端 render_watcher")
    ap.add_argument("--topic", default=None, help="指定題目（金融時事優先製作，繞過排程/題庫，立刻產 1 支）")
    ap.add_argument("--angle", default=None, help="切入點（搭配 --topic）")
    ap.add_argument("--publish", action="store_true", help="產完立刻發布（時事片用：消息面要即時上架，不等排程）")
    ap.add_argument("--manual", action="store_true", help="手動補產：照 --shorts/--long 數量，不被人事部員額覆蓋")
    args = ap.parse_args()

    # 🔥 金融時事優先：給了 --topic 就立刻產 1 支相關 Short，不管排程/片庫上限。
    if args.topic:
        if not API_KEY:
            print("[FATAL] 找不到 ANTHROPIC_API_KEY 環境變數。", file=sys.stderr)
            return 2
        slug_made = None
        for t in range(2):
            try:
                slug_made = make_one("short", no_render=args.no_render,
                                     topic_override={"title": args.topic, "angle": args.angle or ""})
                if slug_made:
                    break
            except Exception as exc:  # noqa: BLE001
                print(f"[err 時事第{t+1}次] {exc}", file=sys.stderr)
        log_ops("時事製作", f"{'已產出時事片' if slug_made else '⚠️ 時事片失敗'}：{args.topic[:40]}")
        print(f"[{'ok' if slug_made else 'FAIL'}] 金融時事 Short：{args.topic[:40]}")
        # 消息面要即時：產完立刻發布（仍過審核閘門；只在有真的渲染出檔時）
        if slug_made and args.publish and not args.no_render:
            _publish_now(slug_made)
        return 0 if slug_made else 3

    # 員額即產能：人事部在 headcount.json 設的 ②Shorts／①影片 員額 = 每日產出量（加員額＝加產能）。
    # --manual（特助手動補產 N 支）時跳過員額覆蓋，照指定數量產。
    hc_path = ROOT / "STUDIO" / "headcount.json"
    if hc_path.exists() and not args.manual:
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
