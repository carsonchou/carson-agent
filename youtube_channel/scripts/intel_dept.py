#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intel_dept.py — 【⑯ 競品情報部】盯同類頻道在紅什麼 + 自動深度學習循環。

兩段：
  A. 搜尋情報（原有）：YouTube Search 找量化/網格/Pionex/定投等高觀看競品 → 產情報報告。
  B. ★自動深度學習（新增，無限循環的引擎）：挑出『沒看過』的競品影片 →
     抓字幕（無字幕自動轉 Whisper）→ Claude 拆解出『新招』→
     append 進 competitor_analysis.md ＋ 智慧合併進 STUDIO/competitor_playbook.md。
     produce_batch.load_playbook() 每次製作即時讀 playbook → 工廠自動吸收最新競品心法。

排程每天跑，hands-off。失敗全 soft（單支壞不影響整體）。
輸出：STUDIO/REPORTS/{date}_競品情報.md、STUDIO/intel.json、competitor_analysis.md(增節)、competitor_playbook.md(增補)。
用法：python scripts/intel_dept.py [--max-learn 3] [--no-learn]
"""
from __future__ import annotations
import argparse, glob, json, os, re, shutil, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace"); sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"; REPORTS = STUDIO / "REPORTS"; ORDERS = STUDIO / "production_orders.json"
PLAYBOOK = STUDIO / "competitor_playbook.md"
SEED_FILE = ROOT / "scripts" / "competitor_playbook_seed.md"  # tracked 完整 A–L 種子，雲端建檔用
ANALYSIS = ROOT / "competitor_analysis.md"
SEEN_FILE = STUDIO / "intel_seen.json"
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass

# 大量供給用：核心競品題材 + 鄰近題材（理財/ETF/被動收入/AI），確保每天能撈到足量未看過的新片。
DEFAULT_KW = ["網格交易", "Pionex 教學", "派網 機器人", "定投策略", "DCA 定期定額", "量化交易",
              "加密貨幣 被動收入", "網格機器人", "資金費率 套利", "交易機器人 實測", "幣安 合約 教學",
              "ChatGPT 交易", "AI 量化 交易", "Python 量化", "回測 策略", "TradingView 策略",
              "加密貨幣 投資", "ETF 定投", "被動收入 投資", "技術分析 教學", "波段 當沖 教學",
              "穩定幣 理財", "套利 教學", "交易策略 回測"]
GROQ_ENV = Path.home() / ".config" / "watch" / ".env"
ANTH_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTH_MODEL = "claude-haiku-4-5-20251001"
AUTO_MARK = "## 自動增補（competitor intel，新到舊）"
MAX_AUTO = 60          # playbook 自動增補區最多保留幾條（FIFO，控制 prompt 長度；衝量時拉高）
TRANSCRIPT_CAP = 6000  # 送給 Claude 的逐字稿最長字數


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


# ───────────────────────── 工具：找 uvx / ffmpeg / groq key ─────────────────────────
def _uvx():
    return shutil.which("uvx") or str(Path.home() / ".local" / "bin" / "uvx")


def _ffmpeg_dir():
    f = shutil.which("ffmpeg")
    if f:
        return str(Path(f).parent)
    pats = glob.glob(str(Path.home() / "AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/**/ffmpeg.exe"),
                     recursive=True)
    return str(Path(pats[0]).parent) if pats else ""


def _ffmpeg_bin(ffdir):
    return str(Path(ffdir) / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))


def _groq_key():
    # 雲端 run.sh 會 source .env，金鑰進環境變數；本機則讀 ~/.config/watch/.env。
    for var in ("GROQ_API_KEY", "GROQ_KEY"):
        v = os.environ.get(var, "").strip()
        if v:
            return v
    try:
        m = re.search(r"gsk_[A-Za-z0-9]+", GROQ_ENV.read_text(encoding="utf-8"))
        return m.group(0) if m else ""
    except Exception:
        return ""


def _load_seen():
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_seen(seen):
    try:
        SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ───────────────────────── 逐字稿：字幕優先，無字幕轉 Whisper ─────────────────────────
def _parse_vtt(p):
    txt = p.read_text(encoding="utf-8", errors="replace")
    out, prev = [], None
    for line in txt.splitlines():
        s = line.strip()
        if not s or s == "WEBVTT" or "-->" in s or s.isdigit() or s.startswith(("NOTE", "Kind:", "Language:")):
            continue
        s = re.sub(r"<[^>]+>", "", s)
        if s and s != prev:
            out.append(s); prev = s
    return " ".join(out)


def transcribe(vid):
    """回傳 (text, source)。先抓字幕，無字幕走 Whisper；全失敗回 ('','none')。"""
    url = f"https://www.youtube.com/watch?v={vid}"
    uvx = _uvx()
    tmp = Path(tempfile.mkdtemp(prefix="intel_"))
    try:
        # 1. 原生/自動字幕
        try:
            subprocess.run([uvx, "yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
                            "--sub-langs", "zh-TW.*,zh-Hant.*,zh.*,zh-Hans.*,en.*", "--sub-format", "vtt",
                            "-o", str(tmp / "%(id)s.%(ext)s"), url],
                           capture_output=True, timeout=180)
        except Exception:
            pass
        vtts = list(tmp.glob(f"{vid}*.vtt"))
        if vtts:
            t = _parse_vtt(vtts[0])
            if len(t) > 200:
                return t, "captions"
        # 2. Whisper fallback
        key, ffdir = _groq_key(), _ffmpeg_dir()
        if not key or not ffdir:
            return "", "none"
        try:
            subprocess.run([uvx, "yt-dlp", "-f", "bestaudio", "--ffmpeg-location", ffdir,
                            "-o", str(tmp / f"{vid}.%(ext)s"), url], capture_output=True, timeout=300)
            aud = next((p for p in tmp.glob(f"{vid}.*")
                        if p.suffix.lower() in (".webm", ".m4a", ".opus", ".mp3", ".mp4", ".ogg")), None)
            if not aud:
                return "", "none"
            mp3 = tmp / f"{vid}.mp3"
            subprocess.run([_ffmpeg_bin(ffdir), "-y", "-i", str(aud), "-vn", "-ac", "1", "-ar", "16000",
                            "-b:a", "64k", str(mp3)], capture_output=True, timeout=240)
            if not mp3.exists():
                return "", "none"
            if mp3.stat().st_size > 24_000_000:  # 超過 Groq 25MB：只取前 25 分鐘（unattended 求穩不切片合併）
                seg = tmp / f"{vid}_seg.mp3"
                subprocess.run([_ffmpeg_bin(ffdir), "-y", "-i", str(mp3), "-t", "1500", "-c", "copy", str(seg)],
                               capture_output=True, timeout=120)
                if seg.exists():
                    mp3 = seg
            with open(mp3, "rb") as fh:
                r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                  headers={"Authorization": f"Bearer {key}"},
                                  files={"file": (mp3.name, fh, "audio/mpeg")},
                                  data={"model": "whisper-large-v3", "language": "zh",
                                        "response_format": "text"}, timeout=240)
            if r.status_code == 200 and len(r.text) > 200:
                return r.text.strip(), "whisper"
        except Exception as e:
            print(f"[warn] whisper {vid}: {e}", file=sys.stderr)
        return "", "none"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ───────────────────────── Claude：拆解 + playbook 智慧合併 ─────────────────────────
def _claude(prompt, max_tokens=1600):
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": ANTH_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": ANTH_MODEL, "max_tokens": max_tokens,
                            "messages": [{"role": "user", "content": prompt}]}, timeout=150)
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def _json_from(txt):
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else None


def analyze(video, transcript):
    """回傳 dict：{breakdown(markdown), new_tactics[list], is_competitor(bool)}；失敗回 None。"""
    cur_pb = ""
    try:
        cur_pb = PLAYBOOK.read_text(encoding="utf-8")[:2600]
    except Exception:
        pass
    prompt = (
        "你是『量化阿森｜Carson Quant』(繁中 faceless AI 量化交易教學頻道，靠 Pionex 派網聯盟返佣變現)的競品分析師。\n"
        f"分析這支競品影片的逐字稿，拆解可借鏡之處。\n標題：{video['title']}\n頻道：{video['channel']}\n觀看：{video.get('views',0)}\n"
        f"逐字稿(可能簡繁混/有錯字，照語意)：\n{transcript[:TRANSCRIPT_CAP]}\n\n"
        "我們現有的爆款心法 playbook(避免重複，只抓『它有但這裡沒有』的新招)：\n"
        f"{cur_pb}\n\n"
        "只輸出 JSON(不要其他文字、不要 markdown 圍欄)：\n"
        '{"is_competitor":true/false,'
        '"breakdown":"繁中 markdown 拆解：開場鉤子/結構/變現是否Pionex/可借鏡/弱點，約120-200字",'
        '"new_tactics":["可折進 playbook 的全新招式一句話(繁中，具體可操作)，最多3條；若無全新招給空陣列"]}'
    )
    try:
        return _json_from(_claude(prompt, 1500))
    except Exception as e:
        print(f"[warn] analyze {video['id']}: {e}", file=sys.stderr)
        return None


def merge_playbook(candidate_tactics):
    """把候選新招中『真正新穎』的，append 進 playbook 自動增補區(FIFO 上限 MAX_AUTO)。回傳實際新增條數。"""
    candidate_tactics = [t.strip() for t in candidate_tactics if t and len(t.strip()) > 8]
    if not candidate_tactics:
        return 0
    # 雲端 STUDIO/ 是 gitignore 空的：playbook 不存在就先用 tracked 種子建檔，否則每天靜默 no-op、永遠不累積。
    if not PLAYBOOK.exists():
        seed = SEED_FILE.read_text(encoding="utf-8").strip() if SEED_FILE.exists() else ""
        if not seed:
            return 0
        PLAYBOOK.parent.mkdir(parents=True, exist_ok=True)
        PLAYBOOK.write_text(seed + "\n", encoding="utf-8")
    pb = PLAYBOOK.read_text(encoding="utf-8")
    # 用 Claude 過濾出真正未涵蓋的(對照整份 playbook)
    novel = candidate_tactics
    try:
        prompt = ("以下是現有 playbook：\n" + pb[:3000] +
                  "\n\n以下是候選新招：\n" + json.dumps(candidate_tactics, ensure_ascii=False) +
                  "\n\n只保留『playbook 尚未涵蓋、確實新穎且可操作』的，潤成精煉一句話(繁中)。"
                  '只輸出 JSON：{"novel":["...","..."]}（若全部已涵蓋給空陣列）')
        r = _json_from(_claude(prompt, 800))
        if r and isinstance(r.get("novel"), list):
            novel = [x.strip() for x in r["novel"] if x and len(x.strip()) > 8]
    except Exception as e:
        print(f"[warn] merge filter: {e}", file=sys.stderr)
    if not novel:
        return 0
    # 拆出既有增補區
    if AUTO_MARK in pb:
        head, _, tail = pb.partition(AUTO_MARK)
        existing = [ln[2:].strip() for ln in tail.splitlines() if ln.strip().startswith("- ")]
    else:
        head, existing = pb.rstrip() + "\n\n", []
    # 去重(與既有增補區 + 與核心 playbook 文字)
    fresh = [n for n in novel if n not in existing and n[:18] not in pb]
    if not fresh:
        return 0
    date = tw_today()
    merged = [f"- {n}（{date}）" for n in fresh] + [f"- {e}" for e in existing]
    merged = merged[:MAX_AUTO]
    new_pb = head.rstrip() + "\n\n" + AUTO_MARK + "\n" + "\n".join(merged) + "\n"
    PLAYBOOK.write_text(new_pb, encoding="utf-8")
    return len(fresh)


def append_analysis(date, entries):
    """把本輪拆解 append 進 competitor_analysis.md。"""
    if not entries:
        return
    L = [f"\n---\n\n# ⟳ 自動競品學習｜{date}（intel_dept 自動產）\n"]
    for v, br in entries:
        L.append(f"## {v['channel']}｜{v['title']}（👁{v.get('views',0):,}）\n{br}\n")
    try:
        with open(ANALYSIS, "a", encoding="utf-8") as f:
            f.write("\n".join(L))
    except Exception as e:
        print(f"[warn] append analysis: {e}", file=sys.stderr)


def deep_learn(pool, max_learn, pace=2.0):
    """B 段：對沒看過的競品逐支轉錄+拆解，更新 analysis 與 playbook。
    pace=每支之間的間隔秒數（避 YouTube 429 限流，衝量必備）。"""
    if not ANTH_KEY:
        print("[info] 無 ANTHROPIC_API_KEY，跳過深度學習。"); return
    seen = _load_seen()
    todo = [v for v in pool if v["id"] not in seen][:max_learn]
    if not todo:
        log_ops("競品情報", "深度學習：無新影片(都看過了)"); print("[info] 無新競品可學。"); return
    log_ops("競品情報", f"深度學習 {len(todo)} 支新競品（pace {pace}s）…")
    entries, tactics, learned, skipped = [], [], 0, 0
    for idx, v in enumerate(todo):
        if idx and pace:
            time.sleep(pace)  # 節流避 429；下載本身也有自然間隔
        t, src = transcribe(v["id"])
        seen.add(v["id"])  # 不論成敗都標記，避免下次重撞壞片
        if len(t) < 200:
            skipped += 1; print(f"[skip] {v['id']} 無逐字稿({src})"); continue
        res = analyze(v, t)
        if not res:
            skipped += 1; continue
        if not res.get("is_competitor", True):  # 非同類題材不汙染 playbook，但已記 seen 不重撞
            print(f"[skip] {v['id']} 非競品題材"); continue
        learned += 1
        entries.append((v, res.get("breakdown", "").strip()))
        tactics += res.get("new_tactics", []) or []
        print(f"[learn] {v['channel']}｜{v['title'][:30]}（{src}，新招 {len(res.get('new_tactics',[]) or [])}）")
        if learned % 10 == 0:
            _save_seen(seen); log_ops("競品情報", f"深度學習進度：已拆 {learned} 支…")
    _save_seen(seen)
    date = tw_today()
    append_analysis(date, entries)
    added = merge_playbook(tactics)
    log_ops("競品情報", f"深度學習完成：拆 {len(entries)} 支、playbook 新增 {added} 條")
    print(f"[ok] 深度學習：拆 {len(entries)} 支競品，playbook 新增 {added} 條新招。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-learn", type=int, default=3, help="本輪最多深度學習幾支新競品")
    ap.add_argument("--pace", type=float, default=2.0, help="每支之間間隔秒數（避 429 限流）")
    ap.add_argument("--no-learn", action="store_true", help="只搜尋情報、不做深度學習")
    args = ap.parse_args()

    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception as e:
        print(f"[FATAL] 無法連 YouTube：{e}", file=sys.stderr); return 2
    kws = list(DEFAULT_KW)
    try:
        if ORDERS.exists():
            pk = json.loads(ORDERS.read_text(encoding="utf-8")).get("preferred_keywords") or []
            kws = list(dict.fromkeys(pk + kws))  # 偏好關鍵字優先、去重保留全部
    except Exception:
        pass
    # 搜尋廣度隨 max_learn 放大：衝量(>=20)時搜全部關鍵字、每組抓 50 筆且 order=date(每天最新、供給不重複)，
    # 餵飽大量深度學習；少量學習時只抓最熱前段省 quota。
    big = args.max_learn >= 20
    kw_cap = len(kws) if big else min(len(kws), max(6, (args.max_learn + 4) // 5))
    per = 50 if big else 8
    order = "date" if big else "viewCount"
    log_ops("競品情報", f"搜尋 {kw_cap} 組關鍵字（order={order}, per={per}）…")
    found, vids = set(), []
    for kw in kws[:kw_cap]:
        try:
            r = yt.search().list(q=kw, part="snippet", type="video", order=order,
                                 maxResults=per, relevanceLanguage="zh-Hant", regionCode="TW").execute()
            for it in r.get("items", []):
                vid = it["id"].get("videoId")
                if vid and vid not in found:
                    found.add(vid)
                    vids.append({"id": vid, "title": it["snippet"]["title"][:70],
                                 "channel": it["snippet"]["channelTitle"][:30], "kw": kw})
        except Exception as e:
            print(f"[warn] 搜尋「{kw}」失敗：{e}", file=sys.stderr)
    ids = [v["id"] for v in vids]
    stats = {}
    for i in range(0, len(ids), 50):
        try:
            rr = yt.videos().list(part="statistics", id=",".join(ids[i:i+50])).execute()
            for it in rr.get("items", []):
                stats[it["id"]] = int(it.get("statistics", {}).get("viewCount", 0))
        except Exception:
            pass
    for v in vids:
        v["views"] = stats.get(v["id"], 0)
    vids.sort(key=lambda x: x["views"], reverse=True)
    top = vids[:15]      # 報告只列最熱前 15
    pool = vids          # 學習候選池＝全部去重結果（deep_learn 內部再濾掉已看過、取 max_learn 支）
    date = tw_today()
    REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ⑯ 競品情報報告｜{date}", "",
         "> 同類頻道近期高觀看影片（依觀看排序）。誠實：YouTube Search 結果，唯讀、耗少量 quota。", "",
         "## 熱門競品 Top（標題＝可借鏡的角度/鉤子）"]
    for v in top:
        L.append(f"- 👁 {v['views']:>8,}｜{v['title']}　—　@{v['channel']}（搜:{v['kw']}）")
    if not top:
        L.append("-（本次未取得資料，可能 quota 或網路問題）")
    L += ["", "## 情報洞察（規則式）"]
    if top:
        avg = sum(v["views"] for v in top) // max(1, len(top))
        L.append(f"- 競品前段觀看均值約 {avg:,}，可見此題材有量；我們衝量＋差異化（誠實實測角度）切入。")
        L.append("- 借鏡高觀看標題的『數字/反直覺/痛點』結構，但內容守誠信鐵則（不喊單、不保證）。")
    (REPORTS / f"{date}_競品情報.md").write_text("\n".join(L), encoding="utf-8")
    (STUDIO / "intel.json").write_text(json.dumps({"date": date, "top": top}, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    seen_now = _load_seen()
    fresh_n = sum(1 for v in pool if v["id"] not in seen_now)
    log_ops("競品情報", f"完成 競品 {len(top)} 支 → {date}_競品情報.md（候選池 {len(pool)}、未看過 {fresh_n}）")
    print(f"[ok] 競品情報完成：報告 top {len(top)}、候選池 {len(pool)} 支、其中未看過 {fresh_n} 支。")

    # ── B 段：自動深度學習循環（看片→拆解→更新 playbook，工廠自動吸收）──
    if not args.no_learn:
        try:
            deep_learn(pool, args.max_learn, args.pace)
        except Exception as e:
            print(f"[warn] 深度學習例外（不影響情報報告）：{e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
