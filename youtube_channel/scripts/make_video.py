#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_video.py — 把配音 mp3 自動組成一支 faceless mp4
=====================================================

頻道：量化阿森｜Carson Quant（faceless 全自動 YouTube 產線）

用途
----
吃一份「配音 mp3」（tts_pipeline.py 產出）＋對應的「腳本 .md」（generate_script.py
產出），自動組裝成一支 faceless 影片 mp4：抓 B-roll 素材或退化成字卡投影片，
依配音時長拼接，燒上字幕，加頻道 intro/outro 字卡，輸出 H.264 mp4。

    output/<slug>.mp3 + output/<slug>.md  ->  output/<slug>.mp4

依賴 (Dependencies)
-------------------
    pip install moviepy

- moviepy：影片合成（底層依賴 ffmpeg）。**moviepy 需要系統安裝 ffmpeg**：
    * Windows 安裝 ffmpeg（擇一）：
        - winget install Gyan.FFmpeg
        - 下載 https://www.gyan.dev/ffmpeg/builds/ 的 release-full，解壓後把
          bin\\ffmpeg.exe 所在資料夾加入 PATH。
- Pillow（PIL）：moviepy 安裝時會一併帶入，用來把字卡文字畫成圖片
  （不靠 ImageMagick / TextClip，避免 Windows 上常見的字型設定地獄）。

可選：
- requests：若設定環境變數 PEXELS_API_KEY，會用它抓 Pexels Video 免費素材。
  沒裝 requests 或沒 key，自動退化成純色／漸層字卡投影片，照樣產得出 mp4。

視覺組裝策略（可降級）
----------------------
1. 解析 <slug>.md，取出每段的【畫面/B-roll 關鍵字】與字卡文字（段落小標 + 旁白）。
2. 若有 PEXELS_API_KEY：用 Pexels Video API 依關鍵字抓免費直拍/橫拍素材，
   依配音總時長把各段素材拼接（每段分到的時長 = 配音總長 / 段數）。
3. 降級方案（無 key／抓不到／無 requests）：用漸層背景 + 該段字卡文字做成
   投影片式畫面（slideshow），無素材也能產出完整測試片。
4. 把配音逐字稿燒成字幕（burned-in subtitles）；目前無逐字時間軸，故依配音
   總長「平均分配」字幕段（粗略但可用），log 會標註 [估算]。
5. 加頻道 intro/outro 字卡（取 channel_config.json 的 branding.intro_tagline /
   outro_tagline 與 watermark_text）。

環境變數
--------
    PEXELS_API_KEY    （選用）有設才會去抓 Pexels 影片素材；沒設就走字卡降級。

檔名約定
--------
    輸入 output/<slug>.mp3 + output/<slug>.md  →  輸出 output/<slug>.mp4
可用 --slug 直接指定，或用 --audio / --script / --out 個別覆寫。

設定檔
------
不指定 --config 時，預設自動讀專案根目錄的 channel_config.json，
從 branding 區塊取 intro_tagline / outro_tagline / watermark_text。

CLI 用法請見檔案底部 build_parser() 或執行 --help。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# Windows 主控台預設常是 cp950（Big5），直接 print 中文（slug/標題/段落）會
# UnicodeEncodeError 而中斷。把 stdout/stderr 重設為 UTF-8（errors="replace"
# 保底），確保中文都能安全印出（單獨執行與被 run_all.py 呼叫皆適用）。
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

# --------------------------------------------------------------------------- #
# 路徑常數
# --------------------------------------------------------------------------- #

# 專案根目錄 = 本檔案所在的 scripts/ 的上一層 (youtube_channel/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "channel_config.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

# 影片預設參數
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 24

# intro / outro 字卡時長（秒）
INTRO_DURATION = 3.0
OUTRO_DURATION = 4.0

# 每段字幕估算的最長秒數上限（避免單段字幕停留過久）
SUBTITLE_MAX_SECONDS = 6.0

# Pexels API
PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"
PEXELS_TIMEOUT = 30

# 預設背景漸層色盤（暗金 cinematic：近黑深藍底，壓暗低調高級）。RGB。
GRADIENT_TOP = (7, 10, 18)       # 近黑深藍（電影感頂部，比舊 (12,18,32) 更沉）
GRADIENT_BOTTOM = (18, 28, 50)   # 深靛藍（壓暗，發光克制）
# 暗金 cinematic 暖色（光暈/網格的金調來源；紅=警示/虧、綠=獲利 等語意色不受此影響）
GOLD = (255, 209, 102)

# 概念圖引擎（每段依旁白主題畫對應數據圖）；缺套件時優雅降級回 K 線卡。
try:
    import concept_visuals as _concept
except Exception as _exc:  # noqa: BLE001
    _concept = None
    print(f"[info] concept_visuals 未載入（{_exc}），畫面退回 K 線卡。", file=sys.stderr)


# --------------------------------------------------------------------------- #
# 資料結構
# --------------------------------------------------------------------------- #


@dataclass
class Segment:
    """腳本中的一個視覺段落（對應一張字卡 / 一段 B-roll）。"""

    heading: str          # 段落小標（字卡大字）
    narration: str        # 該段旁白（拿來估字幕、字卡副文字）
    broll: List[str] = field(default_factory=list)  # B-roll 關鍵字


# --------------------------------------------------------------------------- #
# 設定載入
# --------------------------------------------------------------------------- #


def load_branding(config_path: Optional[Path]) -> dict:
    """從 channel_config.json 取 branding 區塊；失敗則回傳合理預設。"""
    fallback = {
        "intro_tagline": "歡迎回到本頻道。",
        "outro_tagline": "感謝收看，我們下次見。",
        "watermark_text": "Carson Quant",
    }
    path = config_path or (DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else None)
    if path is None:
        print(f"[info] 找不到設定檔，branding 使用內建預設值。", file=sys.stderr)
        return fallback
    if not Path(path).exists():
        print(f"[info] 找不到設定檔 {path}，branding 使用內建預設值。", file=sys.stderr)
        return fallback
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[warn] 設定檔 {path} 讀取失敗（{exc}），branding 改用預設值。", file=sys.stderr)
        return fallback
    branding = cfg.get("branding", {}) if isinstance(cfg, dict) else {}
    merged = dict(fallback)
    merged.update({k: v for k, v in branding.items() if v})
    return merged


# --------------------------------------------------------------------------- #
# 解析腳本 .md
# --------------------------------------------------------------------------- #

# 對應 generate_script.render_markdown 的標記
_RE_SECTION_HEAD = re.compile(r"^###\s+段落\s*\d+[：:]\s*(.+?)\s*$")
_RE_NARRATION = re.compile(r"^\*\*旁白[：:]\*\*\s*(.*)$")
_RE_BROLL = re.compile(r"^\*\*建議畫面.*?B-?roll.*?[：:]\*\*\s*(.*)$")
_RE_TITLE = re.compile(r"^#\s+(?:🎬\s*)?(.+?)\s*$")


def _split_broll(text: str) -> List[str]:
    """把 B-roll 關鍵字字串切成 list（容忍中英文分隔符）。"""
    text = text.strip()
    if not text or text.startswith("（"):  # 「（待補 B-roll 關鍵字）」之類佔位
        return []
    parts = re.split(r"[、,，/|]+", text)
    out: List[str] = []
    for p in parts:
        p = p.strip().strip("（）()")
        if p and not p.startswith("待補") and "B-roll" not in p:
            out.append(p)
    return out


def parse_script_md(md_path: Path) -> Tuple[str, List[Segment]]:
    """
    解析腳本 .md，回傳 (影片標題, [Segment, ...])。

    擷取邏輯（對應 generate_script.py 的 render_markdown 輸出）：
      - 影片標題：第一個 `# 🎬 ...` 標題。
      - 主體各段：`### 段落 N：小標` 之下的 `**旁白：**` 與 `**建議畫面 / B-roll：**`。

    容錯：即使 md 是手改過的、欄位順序不同或缺漏，也盡量抓得到段落。
    若完全抓不到主體段落，至少回傳一個以標題為內容的 fallback 段落，
    確保後續一定能產出畫面。
    """
    if not md_path.exists():
        raise FileNotFoundError(f"找不到腳本檔：{md_path}")
    text = md_path.read_text(encoding="utf-8-sig")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    title = md_path.stem
    title_found = False

    segments: List[Segment] = []
    cur: Optional[Segment] = None

    def flush() -> None:
        nonlocal cur
        if cur is not None:
            segments.append(cur)
        cur = None

    for line in lines:
        stripped = line.strip()

        if not title_found:
            m = _RE_TITLE.match(stripped)
            if m:
                title = m.group(1).strip()
                title_found = True
                continue

        m = _RE_SECTION_HEAD.match(stripped)
        if m:
            flush()
            cur = Segment(heading=m.group(1).strip(), narration="")
            continue

        if cur is None:
            continue

        m = _RE_NARRATION.match(stripped)
        if m:
            cur.narration = (cur.narration + " " + m.group(1).strip()).strip()
            continue

        m = _RE_BROLL.match(stripped)
        if m:
            cur.broll = _split_broll(m.group(1))
            continue

    flush()

    if not segments:
        # 完全沒抓到主體 → 用標題做一張字卡，至少能出片。
        print("[warn] 腳本中未解析到主體段落，改用單張標題字卡。", file=sys.stderr)
        segments = [Segment(heading=title, narration="")]

    return title, segments


# --------------------------------------------------------------------------- #
# 字幕：把純配音稿切成字幕段（目前無時間軸 → 依總長平均分配）
# --------------------------------------------------------------------------- #


def read_voice_text(slug_paths: "SlugPaths") -> str:
    """讀取對應的純配音稿 <slug>.voice.txt（若存在）。

    字幕優先用 voice.txt（純旁白、無畫面標註），抓不到再退回用各段 narration。
    """
    vp = slug_paths.voice_txt
    if vp.exists():
        try:
            return vp.read_text(encoding="utf-8-sig").strip()
        except OSError as exc:
            print(f"[warn] 讀取配音稿 {vp} 失敗（{exc}），字幕改用腳本旁白。", file=sys.stderr)
    return ""


def split_subtitle_units(text: str) -> List[str]:
    """把一段文字切成適合上字幕的小單位（依中英文句末標點 / 逗號斷句）。"""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    # 先在句末／停頓標點後斷開，保留標點。
    # 注意：用 lambda 回呼避免 re.sub 的 replacement 模板解析 \x 跳脫
    #（Python 3.9 對 r"\1\x00" 這種替換字串會丟 re.error: bad escape \x）。
    sep = "\x00"
    marked = re.sub(r"([。！？；…，、!?;,]+)", lambda mm: mm.group(1) + sep, text)
    units = [u.strip() for u in marked.split(sep) if u.strip()]
    # 太短的單位往後黏，避免字幕一閃而過；太長的硬切
    merged: List[str] = []
    buf = ""
    for u in units:
        if len(buf) + len(u) <= 24:
            buf = (buf + u).strip()
        else:
            if buf:
                merged.append(buf)
            buf = u
        if len(buf) >= 18:
            merged.append(buf)
            buf = ""
    if buf:
        merged.append(buf)
    # 對仍過長的硬切到 ~28 字
    out: List[str] = []
    for m in merged:
        while len(m) > 30:
            out.append(m[:28])
            m = m[28:]
        if m:
            out.append(m)
    return out


@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str


def build_subtitle_cues(units: List[str], total_duration: float) -> List[SubtitleCue]:
    """
    依配音總長把字幕單位「平均（依字數加權）」分配時間。

    這是估算法：沒有逐字時間軸，故假設語速恆定，每個字幕單位分到的時間
    與其字元數成正比。log 會在外層標註 [估算]。
    """
    if not units or total_duration <= 0:
        return []
    weights = [max(len(u), 1) for u in units]
    total_w = sum(weights)
    cues: List[SubtitleCue] = []
    t = 0.0
    for u, w in zip(units, weights):
        dur = total_duration * (w / total_w)
        dur = min(dur, SUBTITLE_MAX_SECONDS) if len(units) > 1 else dur
        cues.append(SubtitleCue(start=t, end=t + dur, text=u))
        t += dur
    # 把最後一段對齊到總長（修正捨入誤差）
    if cues:
        cues[-1].end = total_duration
    return cues


_SUB_PUNCT = set("。！？!?…，、；,;：:「」『』（）()「」《》\"' 　\n\t.")


def load_word_cues(slug_paths: "SlugPaths", vt: str, total_duration: float):
    """用 TTS 真實時間戳(<slug>.wordtimes.json)精準對齊字幕，解決「按字數估算、假設語速恆定」造成的漂移。
    文字取原始 voice.txt(乾淨標點)、時間取 SentenceBoundary 句級真實時戳(按句序對齊，句內依字數分配)。
    無 sidecar / 句數對不上太多 / 任何例外 → 回 None(呼叫端退回 build_subtitle_cues 估算法)。"""
    try:
        wt_path = slug_paths.audio.parent / f"{slug_paths.audio.stem}.wordtimes.json"
        if not wt_path.exists():
            return None
        import json as _json
        marks = _json.loads(wt_path.read_text(encoding="utf-8"))
        if not marks or total_duration <= 0:
            return None
        sents = [m for m in marks if m.get("type") == "SentenceBoundary" and float(m.get("d", 0)) > 0]
        if not sents:
            return None
        # 原始 voice.txt 依句末標點切句(保留原文/標點)，按順序對齊到 TTS 的句級時戳
        orig = [s.strip() for s in re.split(r"(?<=[。！？!?])", vt) if s.strip()]
        if not orig:
            return None
        cues: List[SubtitleCue] = []
        m = min(len(orig), len(sents))
        for i in range(m):
            ts = float(sents[i]["t"])
            te = ts + float(sents[i]["d"])
            if te <= ts:
                continue
            units = split_subtitle_units(orig[i])
            if not units:
                continue
            weights = [max(len(u), 1) for u in units]
            tw = sum(weights)
            t = ts
            for u, w in zip(units, weights):
                d = (te - ts) * (w / tw)
                cues.append(SubtitleCue(start=round(t, 3), end=round(t + d, 3), text=u))
                t += d
        # 原文句數 > TTS 句數(罕見)→ 剩餘句用「末句尾→總長」估時補上，不漏字幕
        if len(orig) > len(sents) and cues:
            rest = []
            for s in orig[len(sents):]:
                rest += split_subtitle_units(s)
            if rest:
                t0 = cues[-1].end
                span = max(0.6, total_duration - t0)
                weights = [max(len(u), 1) for u in rest]
                tw = sum(weights)
                t = t0
                for u, w in zip(rest, weights):
                    d = span * (w / tw)
                    cues.append(SubtitleCue(start=round(t, 3), end=round(t + d, 3), text=u))
                    t += d
        if not cues:
            return None
        # 單調化 + 末句對齊總長
        for i in range(1, len(cues)):
            if cues[i].start < cues[i - 1].end:
                cues[i].start = cues[i - 1].end
            if cues[i].end <= cues[i].start:
                cues[i].end = cues[i].start + 0.4
        cues[-1].end = max(cues[-1].end, min(total_duration, cues[-1].start + 0.4))
        return cues
    except Exception:  # noqa: BLE001
        return None


def _srt_ts(sec: float) -> str:
    """秒 → SRT 時間碼 HH:MM:SS,mmm。"""
    if sec < 0:
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt_for_slug(slug: str, out_dir=None):
    """為 output/<slug> 產生 .srt 字幕軌（上傳 YouTube 用，非燒錄）。

    重用既有 split_subtitle_units()+build_subtitle_cues()（估算時間軸）。
    來源：<slug>.voice.txt（優先）或 <slug>.md 的「**旁白：**」行；時長取自 <slug>.mp4（ffprobe）。
    價值＝中文金融術語(夏普/回撤/網格)字幕 100% 正確，勝過 YouTube 自動字幕亂猜。
    成功回傳 srt 路徑，失敗回 None（非致命）。
    """
    import subprocess
    base = Path(out_dir) if out_dir else (Path(__file__).resolve().parent.parent / "output")
    mp4 = base / f"{slug}.mp4"
    if not mp4.exists():
        return None
    voice = ""
    vt = base / f"{slug}.voice.txt"
    if vt.exists():
        try:
            voice = vt.read_text(encoding="utf-8-sig").strip()
        except OSError:
            voice = ""
    if not voice:
        md = base / f"{slug}.md"
        if md.exists():
            try:
                txt = md.read_text(encoding="utf-8", errors="ignore")
                voice = " ".join(re.findall(r"\*\*旁白：\*\*\s*(.+)", txt)).strip()
            except OSError:
                voice = ""
    if not voice:
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(mp4)],
            capture_output=True, text=True, timeout=30)
        dur = float((out.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return None
    if dur <= 0:
        return None
    cues = build_subtitle_cues(split_subtitle_units(voice), dur)
    if not cues:
        return None
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(f"{i}\n{_srt_ts(c.start)} --> {_srt_ts(c.end)}\n{c.text}\n")
    srt = base / f"{slug}.srt"
    try:
        srt.write_text("\n".join(blocks), encoding="utf-8")
    except OSError:
        return None
    return srt


# --------------------------------------------------------------------------- #
# Pexels 影片素材抓取（選用，包 try/except）
# --------------------------------------------------------------------------- #


def fetch_pexels_clip(
    keywords: List[str],
    *,
    api_key: str,
    width: int,
    height: int,
    dest_dir: Path,
    index: int,
) -> Optional[Path]:
    """
    依關鍵字向 Pexels Video API 抓一支免費素材，下載到 dest_dir，回傳本地路徑。
    任何失敗（沒裝 requests／網路錯誤／無結果）都回傳 None，讓上層降級。
    """
    try:
        import requests  # 延遲匯入：沒裝也不影響降級路徑
    except ImportError:
        print("[warn] 未安裝 requests，無法抓 Pexels 素材，改用字卡降級。", file=sys.stderr)
        return None

    if not keywords:
        return None

    query = " ".join(keywords[:3])
    orientation = "landscape" if width >= height else "portrait"
    # ── b-roll 快取:跨影片相同情境詞(trading/market/bitcoin…)免重抓 API+重下載,省配額/頻寬/時間 ──
    import hashlib as _hl
    _cache_dir = PROJECT_ROOT / "assets" / "broll_cache"
    _ck = _hl.md5(f"{query.lower()}|{orientation}|{width}x{height}".encode("utf-8")).hexdigest()[:16]
    _cf = _cache_dir / f"{_ck}.mp4"
    dest = dest_dir / f"broll_{index:02d}.mp4"
    if _cf.exists() and _cf.stat().st_size > 0 and not os.environ.get("BROLL_NO_CACHE"):
        try:
            import shutil as _sh
            _sh.copy2(_cf, dest)
            return dest
        except Exception:  # noqa: BLE001
            pass
    params = {
        "query": query,
        "per_page": 5,
        "orientation": orientation,
        "size": "medium",
    }
    headers = {"Authorization": api_key}

    try:
        resp = requests.get(
            PEXELS_VIDEO_SEARCH, params=params, headers=headers, timeout=PEXELS_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001 - 任何網路例外都降級
        print(f"[warn] Pexels 搜尋失敗（{type(exc).__name__}: {exc}），改用字卡降級。", file=sys.stderr)
        return None

    if resp.status_code != 200:
        print(f"[warn] Pexels 回傳 HTTP {resp.status_code}（query='{query}'），改用字卡降級。", file=sys.stderr)
        return None

    try:
        data = resp.json()
        videos = data.get("videos", []) or []
    except (ValueError, json.JSONDecodeError):
        print(f"[warn] Pexels 回應解析失敗（query='{query}'），改用字卡降級。", file=sys.stderr)
        return None

    if not videos:
        print(f"[info] Pexels 無結果（query='{query}'），此段改用字卡。", file=sys.stderr)
        return None

    # 從第一支影片選一個解析度最接近目標寬度、且不超過目標太多的 mp4 檔。
    video_files = videos[0].get("video_files", []) or []
    mp4s = [vf for vf in video_files if vf.get("file_type") == "video/mp4" and vf.get("link")]
    if not mp4s:
        return None

    def score(vf: dict) -> int:
        w = vf.get("width") or 0
        return abs((w or 0) - width)

    best = sorted(mp4s, key=score)[0]
    link = best["link"]

    try:
        with requests.get(link, stream=True, timeout=PEXELS_TIMEOUT) as r:
            if r.status_code != 200:
                print(f"[warn] Pexels 下載 HTTP {r.status_code}，此段改用字卡。", file=sys.stderr)
                return None
            with dest.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Pexels 下載失敗（{type(exc).__name__}: {exc}），此段改用字卡。", file=sys.stderr)
        return None

    if not dest.exists() or dest.stat().st_size == 0:
        return None
    try:  # 存進快取供之後相同情境詞的影片直接複用
        _cache_dir.mkdir(parents=True, exist_ok=True)
        import shutil as _sh
        _sh.copy2(dest, _cf)
    except Exception:  # noqa: BLE001
        pass
    return dest


# --------------------------------------------------------------------------- #
# 字卡圖片產生（PIL，不靠 ImageMagick）
# --------------------------------------------------------------------------- #


_DESIGN_CACHE = None


def _design_system() -> dict:
    """美編部門的品牌設計系統（字體/配色）。讀 STUDIO/design_system.json，失敗回空 dict。"""
    global _DESIGN_CACHE
    if _DESIGN_CACHE is None:
        try:
            _DESIGN_CACHE = json.loads((PROJECT_ROOT / "STUDIO" / "design_system.json").read_text(encoding="utf-8"))
        except Exception:
            _DESIGN_CACHE = {}
    return _DESIGN_CACHE


def _brand_font_paths(bold: bool):
    """美編部門指定的品牌字體（優先於系統預設字，擺脫 AI 預設感）。"""
    ds = _design_system()
    out = []
    for k in (["font_bold", "font"] if bold else ["font"]):
        v = ds.get(k)
        if v:
            out.append(v if Path(v).is_absolute() else str(PROJECT_ROOT / v))
    return out


def _load_font(size: int, bold: bool = False):
    """盡量載入一個支援中文的 TrueType 字型；可選粗體；失敗則回傳預設點陣字型。"""
    from PIL import ImageFont

    bold_first = [r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]  # Linux 粗體
    candidates = _brand_font_paths(bold) + (bold_first if bold else []) + [
        r"C:\Windows\Fonts\msjh.ttc",     # 微軟正黑體
        r"C:\Windows\Fonts\msyh.ttc",     # 微軟雅黑
        r"C:\Windows\Fonts\mingliu.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",   # Linux(Ubuntu fonts-noto-cjk)
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",   # Linux 其他發行版
        "/System/Library/Fonts/PingFang.ttc",                        # macOS
    ]
    for c in candidates:
        try:
            if Path(c).exists():
                return ImageFont.truetype(c, size=size)
        except Exception:  # noqa: BLE001
            continue
    try:
        return ImageFont.load_default()
    except Exception:  # noqa: BLE001
        return None


# 強調色調色盤（每支影片依 slug 取一色，畫面有變化、更像有設計）
ACCENT_PALETTE = [
    (255, 210, 63),   # 金黃
    (90, 184, 255),   # 天藍
    (88, 224, 140),   # 翠綠
    (255, 122, 122),  # 珊瑚紅
    (190, 150, 255),  # 紫
    (255, 165, 80),   # 橙
]
# 美編部門可由 design_system.json 覆寫品牌配色
try:
    _ds_pal = _design_system().get("accent_palette")
    if _ds_pal:
        ACCENT_PALETTE = [tuple(c) for c in _ds_pal if isinstance(c, (list, tuple)) and len(c) == 3] or ACCENT_PALETTE
except Exception:
    pass


# 語意警示詞：命中則 accent 鎖珊瑚紅（虧損/爆倉/風險調性），否則鎖暗金 cinematic
_WARN_ACCENT_RE = re.compile(r"虧|賠|崩|爆倉|暴跌|套牢|歸零|腰斬|割|韭菜|翻車|騙|風險|警示|畢業")


def pick_accent(seed: str):
    """暗金 cinematic 鎖色：中性/預設一律鎖金（全片色調一致、電影感），
    只有 seed 命中語意警示詞才切珊瑚紅。紅綠語意色由各圖表(K線/概念圖)自行處理、不受此影響。"""
    s = seed or "x"
    try:
        if _WARN_ACCENT_RE.search(s):
            return (239, 113, 122)     # 珊瑚紅（警示/虧損調性）
        return tuple(ACCENT_PALETTE[0])  # 鎖金（design_system 首色＝品牌金 (255,209,102)）
    except Exception:  # noqa: BLE001
        return (255, 209, 102)


def _ken_burns(clip, width: int, height: int, zoom: float = 0.06):
    """對片段套用緩慢推近(Ken Burns)，輸出固定 width×height、置中裁切。讓畫面活起來。"""
    from moviepy.editor import CompositeVideoClip
    dur = clip.duration or 1.0
    zoomed = clip.resize(lambda t: 1.0 + zoom * (t / dur)).set_position(("center", "center"))
    return CompositeVideoClip([zoomed], size=(width, height)).set_duration(dur)


def _card_background(width: int, height: int, accent, seed: str = "x"):
    """品牌動態字卡背景：漸層 + 光暈 + 網格 + 發光價格走勢線（量化頻道識別）。回傳 PIL RGB Image。"""
    import hashlib

    import numpy as np
    from PIL import Image, ImageDraw

    bg = _gradient_background(width, height).astype(np.float32)  # (H,W,3)
    # 徑向光暈（偏上方）
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = width * 0.5, height * 0.32
    r = np.sqrt(((xx - cx) / (width * 0.62)) ** 2 + ((yy - cy) / (height * 0.42)) ** 2)
    glow = np.clip(1.0 - r, 0.0, 1.0) ** 2.2
    acc = np.array(accent, dtype=np.float32)
    # 暗金 cinematic：先鋪一層極淡金色暖光暈（克制），即使 accent 是警示紅、底仍帶電影金調
    gold = np.array(GOLD, dtype=np.float32)
    bg = bg + glow[:, :, None] * (gold - bg) * 0.06
    bg = bg + glow[:, :, None] * (acc - bg) * 0.15
    img = Image.fromarray(np.clip(bg, 0, 255).astype("uint8"), mode="RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    md = min(width, height)
    ac = (int(accent[0]), int(accent[1]), int(accent[2]))

    # 1) 網格（量化/網格交易識別，極淡）
    step = max(40, int(md * 0.075))
    for gx in range(0, width, step):
        draw.line([(gx, 0), (gx, height)], fill=(*ac, 16), width=1)
    for gy in range(0, height, step):
        draw.line([(0, gy), (width, gy)], fill=(*ac, 16), width=1)

    # 2) 發光價格走勢線（上半部，形狀依 seed 變化）→ 每支影片不同、像真的交易圖
    rng = np.random.RandomState(int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16) % (2 ** 32))
    npt = 24
    xs = np.linspace(width * 0.03, width * 0.97, npt)
    walk = rng.randn(npt).cumsum()
    walk = (walk - walk.min()) / ((walk.max() - walk.min()) or 1)  # 0..1
    base_y = height * 0.30
    amp = height * 0.17
    ys = base_y - walk * amp
    pts = [(int(a), int(b)) for a, b in zip(xs, ys)]
    # 線下漸層面積
    poly = pts + [(int(xs[-1]), int(base_y + amp * 0.6)), (int(xs[0]), int(base_y + amp * 0.6))]
    draw.polygon(poly, fill=(*ac, 26))
    # 走勢線本體
    draw.line(pts, fill=(*ac, 220), width=max(3, int(md * 0.005)), joint="curve")
    # 端點光點
    ex, ey = pts[-1]
    rr = int(md * 0.013)
    draw.ellipse([ex - rr, ey - rr, ex + rr, ey + rr], fill=(255, 255, 255, 235),
                 outline=(*ac, 255), width=max(2, int(md * 0.004)))
    return img


def _gradient_background(width: int, height: int):
    """產生一張深色垂直漸層背景（numpy array, RGB）。"""
    import numpy as np

    top = np.array(GRADIENT_TOP, dtype=np.float32)
    bottom = np.array(GRADIENT_BOTTOM, dtype=np.float32)
    ratios = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]  # (H,1)
    col = top[None, :] * (1 - ratios) + bottom[None, :] * ratios       # (H,3)
    img = np.repeat(col[:, None, :], width, axis=1)                    # (H,W,3)
    return img.astype("uint8")


def _wrap_text(text: str, max_chars_per_line: int) -> List[str]:
    """簡單斷行：中文按字數，英文盡量在空白斷。"""
    text = text.strip()
    if not text:
        return []
    lines: List[str] = []
    cur = ""
    for ch in text:
        cur += ch
        if len(cur) >= max_chars_per_line and ch in " 　,，。、!！?？；;":
            lines.append(cur.strip())
            cur = ""
        elif len(cur) >= max_chars_per_line + 4:
            lines.append(cur.strip())
            cur = ""
    if cur.strip():
        lines.append(cur.strip())
    return lines


def _render_candles_strip(strip_w: int, height: int, accent, seed: str = "x"):
    """畫一張寬幅擬真 K 線圖（紅綠蠟燭 + 網格 + 發光），供滾動當主視覺背景。回傳 PIL RGB Image。"""
    import hashlib

    import numpy as np
    from PIL import Image, ImageDraw

    # 深色底（垂直漸層）
    top = np.array(GRADIENT_TOP, dtype=np.float32)
    bot = np.array(GRADIENT_BOTTOM, dtype=np.float32)
    ratios = np.linspace(0, 1, height, dtype=np.float32)[:, None]
    col = top[None, :] * (1 - ratios) + bot[None, :] * ratios
    # 暗金 cinematic：頂端極淡金色暖化（僅最頂、克制），與字卡底同調
    gold = np.array(GOLD, dtype=np.float32)
    warm = (1.0 - ratios) ** 3 * 0.05
    col = col + warm * (gold[None, :] - col)
    img = Image.fromarray(np.repeat(col[:, None, :], strip_w, axis=1).astype("uint8"), "RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    ac = (int(accent[0]), int(accent[1]), int(accent[2]))
    md = min(strip_w, height)

    # 網格
    step = max(48, int(height * 0.085))
    for gy in range(0, height, step):
        draw.line([(0, gy), (strip_w, gy)], fill=(*ac, 18), width=1)
    for gx in range(0, strip_w, step):
        draw.line([(gx, 0), (gx, height)], fill=(*ac, 12), width=1)

    rng = np.random.RandomState(int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16) % (2 ** 32))
    spacing = max(22, int(height * 0.045))
    body_w = int(spacing * 0.6)
    ncandle = strip_w // spacing
    # 價格隨機walk，限制在中間 60% 高度
    price = rng.randn(ncandle).cumsum()
    price = (price - price.min()) / ((price.max() - price.min()) or 1)
    pad = height * 0.2
    centers = (height - pad) - price * (height - 2 * pad)
    vol = height * 0.05
    UP = (88, 220, 140)
    DN = (255, 96, 96)
    for i in range(ncandle):
        cx = int(i * spacing + spacing * 0.5)
        c = centers[i]
        o = c + rng.uniform(-vol, vol)
        cl = c + rng.uniform(-vol, vol)
        hi = min(o, cl) - rng.uniform(vol * 0.3, vol * 1.2)
        lo = max(o, cl) + rng.uniform(vol * 0.3, vol * 1.2)
        up = cl <= o  # 收盤在上(值較小)=漲
        color = UP if up else DN
        # 影線
        draw.line([(cx, int(hi)), (cx, int(lo))], fill=(*color, 210), width=max(2, int(body_w * 0.16)))
        # 實體
        y1, y2 = sorted((int(o), int(cl)))
        if y2 - y1 < 3:
            y2 = y1 + 3
        draw.rectangle([cx - body_w // 2, y1, cx + body_w // 2, y2], fill=(*color, 235))

    # ── 發光霓虹趨勢線 + 線下漸層面積填充 + 末端脈動亮點（讓畫面像「活的盤面」、最抓眼）──
    pts = [(int(i * spacing + spacing * 0.5), int(centers[i])) for i in range(ncandle)]
    if len(pts) >= 2:
        # 面積填充：線下到底部，accent 半透明（疊兩層做上深下淡漸層感）
        base_y = int(height * 0.97)
        draw.polygon(pts + [(pts[-1][0], base_y), (pts[0][0], base_y)], fill=(*ac, 30))
        midcut = [(x, y) for (x, y) in pts]
        draw.polygon(midcut + [(pts[-1][0], pts[-1][1] + int(height * 0.10)),
                               (pts[0][0], pts[0][1] + int(height * 0.10))], fill=(*ac, 34))
        # 多層描線做霓虹發光（外寬淡→內細亮）
        for w_, a_ in ((18, 38), (11, 72), (6, 140)):
            draw.line(pts, fill=(*ac, a_), width=w_, joint="curve")
        draw.line(pts, fill=(238, 255, 250, 255), width=3, joint="curve")  # 亮核
        # 末端脈動亮點
        ex, ey = pts[-1]
        draw.ellipse([ex - 20, ey - 20, ex + 20, ey + 20], fill=(*ac, 70))
        draw.ellipse([ex - 9, ey - 9, ex + 9, ey + 9], fill=(245, 255, 252, 255), outline=(*ac, 255), width=2)
    return img


def make_candle_bg_clip(width: int, height: int, duration: float, accent, seed: str = "x"):
    """滾動的擬真 K 線主視覺背景 clip：寬幅 K 線圖橫向緩慢平移，看起來像即時盤面。"""
    from moviepy.editor import ImageClip
    import numpy as np

    strip_w = int(width * 2.2)
    strip = _render_candles_strip(strip_w, height, accent, seed)
    arr = np.array(strip)
    clip = ImageClip(arr).set_duration(duration)
    max_shift = strip_w - width
    dur = duration or 1.0

    def pos(t):
        return (-int(max_shift * (t / dur)), 0)  # 由左往右平移露出新蠟燭

    from moviepy.editor import CompositeVideoClip
    moving = clip.set_position(pos)
    return CompositeVideoClip([moving], size=(width, height)).set_duration(dur)


def render_text_overlay(width: int, height: int, *, big_text: str, watermark: str, accent, dest: Path):
    """透明背景的文字疊層：大標(半透明深色面板襯底+黃底線) + 浮水印 pill。疊在 K 線主視覺上。"""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    md = min(width, height)
    big_font = _load_font(int(md * 0.086), bold=True)
    wm_font = _load_font(int(md * 0.026), bold=True)
    max_w = width - int(width * 0.14)
    ac = (int(accent[0]), int(accent[1]), int(accent[2]))

    def tsize(s, font):
        try:
            b = draw.textbbox((0, 0), s, font=font)
            return (b[2] - b[0], b[3] - b[1])
        except Exception:  # noqa: BLE001
            return (len(s) * 10, 16)

    lines = _wrap_to_width(draw, big_text, big_font, max_w) if big_font else [big_text]
    try:
        _asc, _desc = big_font.getmetrics()
        line_h = int((_asc + _desc) * 1.2)  # 用字體真實行高，避免不同字體行距被低估、行疊在一起
    except Exception:  # noqa: BLE001
        line_h = int(tsize("測", big_font)[1] * 1.55) or int(md * 0.12)
    block_h = line_h * len(lines)
    bw = min(max((tsize(ln, big_font)[0] for ln in lines), default=10), max_w)
    # 半透明深色面板襯底（讓字在繁忙 K 線上仍清楚）
    px = (width - bw) // 2 - int(md * 0.05)
    py = (height - block_h) // 2 - int(md * 0.05)
    draw.rounded_rectangle([px, py, width - px, py + block_h + int(md * 0.10)],
                           radius=int(md * 0.03), fill=(8, 12, 24, 175))
    y = (height - block_h) // 2 - int(md * 0.01)
    last_w = 0
    for ln in lines:
        w, _ = tsize(ln, big_font)
        x = (width - w) // 2
        last_w = w
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (2, 2)):
            draw.text((x + dx, y + dy), ln, fill=(0, 0, 0, 235), font=big_font)
        draw.text((x, y), ln, fill=(248, 250, 255), font=big_font)
        y += line_h
    uw = min(int(width * 0.32), max(last_w // 2, int(width * 0.12)))
    ux = (width - uw) // 2
    draw.rectangle([ux, y + int(md * 0.012), ux + uw, y + int(md * 0.012) + max(4, int(md * 0.013))], fill=accent)

    if watermark:
        w, h = tsize(watermark, wm_font)
        pad = int(md * 0.012)
        bx2 = width - int(width * 0.03)
        by2 = height - int(height * 0.03)
        _safe_round_rect(draw, [bx2 - w - pad * 2, by2 - h - pad * 2, bx2, by2], int(md * 0.012), fill=(255, 255, 255, 30))
        draw.text((bx2 - w - pad, by2 - h - pad - 2), watermark, fill=(228, 234, 247, 240), font=wm_font)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")
    return dest


def _safe_round_rect(draw, box, radius, **kw):
    """Pillow 9.5 的 rounded_rectangle 對 radius 接近框高/寬會拋 y1>=y0；此包裝 clamp 半徑，
    再失敗就退回普通矩形，確保雲端(Pillow 9.5)不因圓角崩掉整張卡。"""
    x0, y0, x1, y1 = box
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    r = max(0, min(int(radius), (x1 - x0) // 2 - 1, (y1 - y0) // 2 - 1))
    try:
        if r >= 2:
            draw.rounded_rectangle([x0, y0, x1, y1], radius=r, **kw)
        else:
            draw.rectangle([x0, y0, x1, y1], **kw)
    except Exception:  # noqa: BLE001
        try:
            draw.rectangle([x0, y0, x1, y1], **kw)
        except Exception:  # noqa: BLE001
            pass


def render_candle_card(width: int, height: int, *, big_text: str, watermark: str, accent, seed: str, dest: Path) -> Path:
    """靜態 K 線主視覺卡：滿版擬真 K 線圖 + 半透明面板大標 + 黃底線 + 浮水印，烤成單張 PNG（渲染快）。"""
    from PIL import ImageDraw

    img = _render_candles_strip(width, height, accent, seed).convert("RGB")  # 滿版 K 線
    draw = ImageDraw.Draw(img, "RGBA")
    md = min(width, height)
    big_font = _load_font(int(md * 0.094), bold=True)
    wm_font = _load_font(int(md * 0.026), bold=True)
    max_w = width - int(width * 0.14)
    ac = (int(accent[0]), int(accent[1]), int(accent[2]))

    def tsize(s, font):
        try:
            b = draw.textbbox((0, 0), s, font=font)
            return (b[2] - b[0], b[3] - b[1])
        except Exception:  # noqa: BLE001
            return (len(s) * 10, 16)

    lines = _wrap_to_width(draw, big_text, big_font, max_w) if big_font else [big_text]
    try:
        _asc, _desc = big_font.getmetrics()
        line_h = int((_asc + _desc) * 1.2)  # 用字體真實行高，避免不同字體行距被低估、行疊在一起
    except Exception:  # noqa: BLE001
        line_h = int(tsize("測", big_font)[1] * 1.55) or int(md * 0.12)
    block_h = line_h * len(lines)
    bw = min(max((tsize(ln, big_font)[0] for ln in lines), default=10), max_w)
    px = (width - bw) // 2 - int(md * 0.05)
    py = (height - block_h) // 2 - int(md * 0.05)
    pyb = py + block_h + int(md * 0.10)
    # 標題後方強調色光暈（吸睛磁鐵：軟性放射狀 halo）
    gcx, gcy = width // 2, (py + pyb) // 2
    for rr_, a_ in ((int(md * 0.50), 14), (int(md * 0.38), 20), (int(md * 0.27), 28)):
        draw.ellipse([gcx - rr_, gcy - int(rr_ * 0.62), gcx + rr_, gcy + int(rr_ * 0.62)], fill=(*ac, a_))
    # 深色玻璃面板 + accent 細邊框
    _safe_round_rect(draw, [px, py, width - px, pyb], int(md * 0.03),
                     fill=(9, 13, 26, 205), outline=(*ac, 140), width=2)
    y = (height - block_h) // 2 - int(md * 0.01)
    last_w = 0
    for ln in lines:
        w, _ = tsize(ln, big_font)
        x = (width - w) // 2
        last_w = w
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (2, 2)):
            draw.text((x + dx, y + dy), ln, fill=(0, 0, 0, 235), font=big_font)
        draw.text((x, y), ln, fill=(248, 250, 255), font=big_font)
        y += line_h
    # 發光強調底線（外暈 + 亮核）
    uw = min(int(width * 0.34), max(last_w // 2, int(width * 0.14)))
    ux = (width - uw) // 2
    uy = y + int(md * 0.014)
    uh = max(5, int(md * 0.016))
    # _safe_round_rect：雲端 Pillow 9.5 對 radius 接近框高會崩（K 線卡失敗退字卡的元兇）
    _safe_round_rect(draw, [ux - 6, uy - 4, ux + uw + 6, uy + uh + 4], uh, fill=(*ac, 70))
    _safe_round_rect(draw, [ux, uy, ux + uw, uy + uh], uh // 2, fill=accent)

    if watermark:
        w, h = tsize(watermark, wm_font)
        pad = int(md * 0.012)
        bx2 = width - int(width * 0.03)
        by2 = height - int(height * 0.03)
        _safe_round_rect(draw, [bx2 - w - pad * 2, by2 - h - pad * 2, bx2, by2], int(md * 0.012), fill=(255, 255, 255, 30))
        draw.text((bx2 - w - pad, by2 - h - pad - 2), watermark, fill=(228, 234, 247, 240), font=wm_font)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")
    return dest


def render_concept_card(width: int, height: int, *, heading: str, narration: str,
                        watermark: str, accent, seed: str, dest: Path,
                        default_key: Optional[str] = None,
                        force_key: Optional[str] = None) -> Optional[Path]:
    """主題數據圖卡：依旁白選一張對得上的圖（網格/複利/回撤…），
    標題放頂部小條（不蓋圖），下方留給字幕。
    force_key 有值＝硬指定該圖（用於強制回測對比 beat，不管旁白分類）；
    否則段落判不到主題時改用 default_key（整支影片主題）；仍為 None 才回 None（退回 K 線卡）。"""
    if _concept is None:
        return None
    from PIL import ImageDraw
    text = f"{heading} {narration}"
    key = force_key or _concept.classify(text) or default_key
    if key is None:
        return None
    img = _concept.render_concept_chart(width, height, text, accent, seed, dest=None, force=key)
    if img is None:
        return None
    img = img.convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    md = min(width, height)
    ac = (int(accent[0]), int(accent[1]), int(accent[2]))

    # 頂部標題條
    head = (heading or "").strip()
    if head:
        head_font = _load_font(int(md * 0.058), bold=True)
        max_w = width - int(width * 0.10)
        lines = _wrap_to_width(draw, head, head_font, max_w) if head_font else [head]
        try:
            lh = int((draw.textbbox((0, 0), "測", font=head_font)[3]) * 1.42)
        except Exception:  # noqa: BLE001
            lh = int(md * 0.075)
        top_pad = int(height * 0.045)
        block_h = lh * len(lines)
        # 半透明底板
        draw.rectangle([0, 0, width, top_pad + block_h + int(md * 0.05)], fill=(8, 12, 24, 150))
        y = top_pad
        last_w = 0
        for ln in lines:
            try:
                w = int(draw.textlength(ln, font=head_font))
            except Exception:  # noqa: BLE001
                w = len(ln) * 12
            x = (width - w) // 2
            last_w = w
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                draw.text((x + dx, y + dy), ln, fill=(0, 0, 0, 230), font=head_font)
            draw.text((x, y), ln, fill=(248, 250, 255), font=head_font)
            y += lh
        # 標題底線（accent）
        uw = min(int(width * 0.30), max(last_w // 2, int(width * 0.12)))
        ux = (width - uw) // 2
        draw.rectangle([ux, y + int(md * 0.006), ux + uw, y + int(md * 0.006) + max(4, int(md * 0.011))], fill=ac)

    # 浮水印
    if watermark:
        wm_font = _load_font(int(md * 0.026), bold=True)
        try:
            wb = draw.textbbox((0, 0), watermark, font=wm_font)
            w, h = wb[2] - wb[0], wb[3] - wb[1]
        except Exception:  # noqa: BLE001
            w, h = len(watermark) * 10, 16
        pad = int(md * 0.012)
        bx2 = width - int(width * 0.03)
        by2 = height - int(height * 0.03)
        draw.rounded_rectangle([bx2 - w - pad * 2, by2 - h - pad * 2, bx2, by2],
                               radius=int(md * 0.012), fill=(255, 255, 255, 30))
        draw.text((bx2 - w - pad, by2 - h - pad - 2), watermark, fill=(228, 234, 247, 240), font=wm_font)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")
    return dest


def render_card_image(
    width: int,
    height: int,
    *,
    big_text: str,
    small_text: str = "",
    watermark: str = "",
    dest: Path,
    accent=(255, 210, 63),
) -> Path:
    """精緻字卡：漸層+強調色光暈底 + 粗體大標(置中, 強調底線) + 簡潔副文 + 浮水印 pill。"""
    from PIL import ImageDraw

    img = _card_background(width, height, accent, seed=big_text or watermark or "x")
    draw = ImageDraw.Draw(img, "RGBA")

    md = min(width, height)
    big_font = _load_font(int(md * 0.082), bold=True)
    small_font = _load_font(int(md * 0.032))
    wm_font = _load_font(int(md * 0.026), bold=True)
    max_w = width - int(width * 0.12)

    def tsize(s, font):
        try:
            b = draw.textbbox((0, 0), s, font=font)
            return (b[2] - b[0], b[3] - b[1])
        except Exception:  # noqa: BLE001
            return (len(s) * 10, 16)

    # 左側強調色直條
    draw.rectangle([0, 0, int(width * 0.012), height], fill=accent)

    # 大標題（粗體、置中、自動折行、黑邊）
    big_lines = _wrap_to_width(draw, big_text, big_font, max_w) if big_font else [big_text]
    line_h = int(tsize("測", big_font)[1] * 1.42) or int(md * 0.11)
    block_h = line_h * len(big_lines)
    y = (height - block_h) // 2 - int(height * 0.05)
    last_w = 0
    for ln in big_lines:
        w, _ = tsize(ln, big_font)
        x = (width - w) // 2
        last_w = w
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (2, 2)):
            draw.text((x + dx, y + dy), ln, fill=(0, 0, 0, 210), font=big_font)
        draw.text((x, y), ln, fill=(245, 248, 255), font=big_font)
        y += line_h

    # 標題下方強調色短底線（用單純矩形，避免圓角退化）
    uw = min(int(width * 0.34), max(last_w // 2, int(width * 0.12)))
    ux = (width - uw) // 2
    uy = y + int(md * 0.012)
    draw.rectangle([ux, uy, ux + uw, uy + max(4, int(md * 0.013))], fill=accent)

    # 副文字（簡潔、最多 2 行、淺色）
    if small_text:
        y += int(md * 0.055)
        sl = (_wrap_to_width(draw, small_text, small_font, max_w) if small_font else [small_text])[:2]
        lh = int(tsize("測", small_font)[1] * 1.5) or int(md * 0.05)
        for ln in sl:
            w, _ = tsize(ln, small_font)
            draw.text(((width - w) // 2, y), ln, fill=(198, 212, 234, 235), font=small_font)
            y += lh

    # 浮水印（右下、pill 底）
    if watermark:
        w, h = tsize(watermark, wm_font)
        pad = int(md * 0.012)
        bx2 = width - int(width * 0.03)
        bx1 = bx2 - w - pad * 2
        by2 = height - int(height * 0.03)
        by1 = by2 - h - pad * 2
        draw.rounded_rectangle([bx1, by1, bx2, by2], radius=int(md * 0.012), fill=(255, 255, 255, 28))
        draw.text((bx1 + pad, by1 + pad - 2), watermark, fill=(226, 233, 246, 240), font=wm_font)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(dest, format="PNG")
    return dest


# --------------------------------------------------------------------------- #
# slug 路徑推導
# --------------------------------------------------------------------------- #


@dataclass
class SlugPaths:
    slug: str
    output_dir: Path
    audio: Path
    script_md: Path
    voice_txt: Path
    out_mp4: Path


def resolve_slug_paths(args: argparse.Namespace) -> SlugPaths:
    """從 --slug 或 --audio/--script 推導所有相關檔名（遵守 output/<slug>.* 約定）。"""
    out_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR

    slug: Optional[str] = args.slug
    audio = Path(args.audio) if args.audio else None
    script_md = Path(args.script) if args.script else None

    if slug is None:
        # 從 audio 或 script 反推 slug
        if audio is not None:
            slug = audio.stem
        elif script_md is not None:
            slug = script_md.stem
        else:
            raise SystemExit("[FATAL] 請提供 --slug，或用 --audio/--script 指定輸入檔。")

    if audio is None:
        audio = out_dir / f"{slug}.mp3"
    if script_md is None:
        script_md = out_dir / f"{slug}.md"

    voice_txt = out_dir / f"{slug}.voice.txt"
    out_mp4 = Path(args.out) if args.out else out_dir / f"{slug}.mp4"

    return SlugPaths(
        slug=slug,
        output_dir=out_dir,
        audio=audio,
        script_md=script_md,
        voice_txt=voice_txt,
        out_mp4=out_mp4,
    )


# --------------------------------------------------------------------------- #
# 音訊時長
# --------------------------------------------------------------------------- #


def probe_audio_duration(audio_path: Path) -> float:
    """取得 mp3 配音總時長（秒）。優先用 moviepy（ffmpeg），失敗回傳 0。"""
    if not audio_path.exists():
        raise FileNotFoundError(f"找不到配音檔：{audio_path}")
    try:
        from moviepy.editor import AudioFileClip
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"無法匯入 moviepy（{exc}）。請 `pip install moviepy` 並安裝 ffmpeg。"
        ) from exc
    clip = AudioFileClip(str(audio_path))
    try:
        return float(clip.duration or 0.0)
    finally:
        clip.close()


# --------------------------------------------------------------------------- #
# 輸出驗證（P5-a 產線止血：絕不讓 0KB/無視訊軌/超短片悄悄留在 output/）
# --------------------------------------------------------------------------- #


def _probe_render_output(path: Path, min_duration: float = 1.0):
    """輕量 ffprobe 驗證輸出 mp4：檔案存在且非空、有視訊軌、有音軌、片長 >= min_duration。
    回傳 (ok: bool, reason: str)；探測本身失敗一律視為不合格（保守，寧可誤殺重試也不留壞檔）。
    呼叫端應把 min_duration 設成「旁白時長*0.95」等貼近真實預期值，而非放任預設的 1.0s——
    04_0056 事故(旁白218.9s/成品僅61.7s)就是靠這道下限形同虛設才闖關成功並發布出去的。"""
    try:
        if not path.exists():
            return False, "檔案不存在"
        size = path.stat().st_size
        if size <= 0:
            return False, "0 bytes"
        import subprocess as _sp
        import imageio_ffmpeg as _iio
        ff = _iio.get_ffmpeg_exe()
        out = _sp.run([ff, "-i", str(path)], capture_output=True, text=True,
                      encoding="utf-8", errors="replace", timeout=20)
        txt = out.stderr or ""
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", txt)
        dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0
        has_v, has_a = ("Video:" in txt), ("Audio:" in txt)
        if dur < min_duration:
            return False, f"片長過短（{dur:.1f}s，預期至少{min_duration:.1f}s，疑似旁白截斷）"
        if not has_v:
            return False, "無視訊軌"
        if not has_a:
            return False, "無音軌"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"探測失敗（{exc}）"


def _cleanup_bad_output(path: Path) -> None:
    """渲染徹底失敗（重試過仍不合格）時，主動清掉殘留在 output/ 的壞檔——
    別讓 0KB/無視訊軌/超短片留到 audit_video 事後才發現、白算一次有效產量。"""
    try:
        if path.exists():
            path.unlink()
            print(f"[cleanup] 已清除壞檔殘留：{path}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 清除壞檔失敗（{exc}）：{path}", file=sys.stderr)


def _log_render_ops(stage: str, msg: str) -> None:
    """寫進既有 STUDIO/ops_log.txt 心跳時間軸；ops 模組不可用時安靜略過，絕不影響渲染主流程。"""
    try:
        import ops
        ops.log_ops(stage, msg)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# 影片組裝（moviepy）
# --------------------------------------------------------------------------- #


def _fit_clip(clip, width: int, height: int, duration: float):
    """把素材片段縮放/裁切填滿畫面，並設成指定時長（循環或裁切）。"""
    from moviepy.editor import vfx

    # 先確保有足夠長度：太短就 loop，太長就 subclip
    src_dur = float(getattr(clip, "duration", 0) or 0)
    if src_dur <= 0:
        clip = clip.set_duration(duration)
    elif src_dur < duration:
        clip = clip.fx(vfx.loop, duration=duration)
    else:
        clip = clip.subclip(0, duration)

    # 等比放大填滿再置中裁切（cover）
    cw, ch = clip.size
    scale = max(width / cw, height / ch)
    clip = clip.resize(scale)
    clip = clip.set_position(("center", "center"))
    return clip.set_duration(duration)


def _fmt_money(v) -> str:
    """金額口語化：>=1萬顯示『X.X萬』，否則千分位。"""
    try:
        v = float(v)
    except Exception:  # noqa: BLE001
        return str(v)
    if abs(v) >= 10000:
        s = f"{v/10000:.1f}".rstrip("0").rstrip(".")
        return s + "萬"
    return f"{int(round(v)):,}"


_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_int(s: str) -> int:
    """中文整數→int（支援到百，如 六十一、一百、三十）。"""
    s = s.strip()
    if not s:
        return 0
    if "百" in s:
        a, _, b = s.partition("百")
        h = (_CN_DIGIT.get(a, 1) if a else 1) * 100
        if b.startswith("十"):
            b = "一" + b
        return h + _cn_int(b) if b else h
    if "十" in s:
        a, _, b = s.partition("十")
        return (_CN_DIGIT.get(a, 1) if a else 1) * 10 + (_CN_DIGIT.get(b, 0) if b else 0)
    v = 0
    for ch in s:
        if ch in _CN_DIGIT:
            v = v * 10 + _CN_DIGIT[ch]
        else:
            return _CN_DIGIT.get(s, 0)
    return v


def _cn_num(s: str) -> float:
    """中文數字（含『點』小數）→ float，如 八點二→8.2、三點三四→3.34。"""
    if re.match(r"^[0-9]+(?:\.[0-9]+)?$", s):
        return float(s)
    if "點" in s:
        a, _, b = s.partition("點")
        ip = _cn_int(a) if a else 0
        frac = "".join(str(_CN_DIGIT[ch]) for ch in b if ch in _CN_DIGIT)
        try:
            return float(f"{ip}.{frac}") if frac else float(ip)
        except Exception:  # noqa: BLE001
            return float(ip)
    return float(_cn_int(s))


def _parse_experiment_numbers(text: str) -> dict:
    """從旁白抓實測數字：本金/餘額/報酬%/天數。相容口語念法（百分之八點二、本金十萬、三十天）。
    抓不到的留空 → HUD 不顯示該欄（不硬湊、守誠實紅線）。"""
    out: dict = {}
    if not text:
        return out
    t = text
    _num = r"[0-9]+(?:\.[0-9]+)?"
    _cn = r"[零〇一二兩三四五六七八九十百點]+"
    _gap = r"[^萬0-9零〇一二兩三四五六七八九十百]{0,3}"  # 填充但不吞數字
    # 本金：X萬（阿拉伯或中文）
    m = re.search(rf"(?:本金|丟|投入|拿|押){_gap}({_num})\s*萬", t)
    if m:
        out["principal"] = int(float(m.group(1)) * 10000)
    else:
        m = re.search(rf"(?:本金|丟|投入|拿|押){_gap}({_cn})\s*萬", t)
        if m:
            out["principal"] = int(_cn_num(m.group(1)) * 10000)
    # 報酬%（口語『百分之X』優先；退回『X%』）取最後一個（通常是結果），含正負語意
    # 正負詞與數字間允許短填充詞（「虧『了』百分之二十」「賠『掉』20%」）：舊版只允許空白，
    # 導致 t="虧了百分之二十" 抓不到『虧』→ HUD 燒 +20% 綠字,但旁白講的是倒賠 20%（號誌翻轉）。
    # 填充詞不得含數字/百（否則會跨過數字或吃掉「百分之」）,長度上限 2 避免亂攀遠處的正負詞。
    _sgap = r"[^0-9零〇一二兩三四五六七八九十百%]{0,2}"
    _sgn = r"正|負|賺|獲利|報酬|漲|虧|賠|跌|少"
    pcs = list(re.finditer(rf"(?:({_sgn}){_sgap})?\s*百分之\s*({_num}|{_cn})", t))
    if not pcs:
        pcs = list(re.finditer(rf"(?:(正|負|賺|漲|虧|賠|跌){_sgap})?\s*({_num})\s*%", t))
    if pcs:
        g = pcs[-1]
        try:
            val = _cn_num(g.group(2))
            if g.group(1) in ("負", "虧", "賠", "跌", "少"):
                val = -val
            out["pct"] = val
        except Exception:  # noqa: BLE001
            pass
    # 天數：第X天 / Day X / X天（阿拉伯或中文）；取最大值（結局天數，避免「第一天」蓋過「第三十天」）
    _days = [int(float(x)) for x in re.findall(rf"(?:第|[Dd]ay)\s*({_num})", t)]
    _days += [int(float(x)) for x in re.findall(rf"({_num})\s*天", t)]
    for x in re.findall(rf"(?:第)?({_cn})\s*天", t):
        try:
            _days.append(int(_cn_num(x)))
        except Exception:  # noqa: BLE001
            pass
    if _days:
        out["days"] = max(_days)
    # 餘額：剩[下]X萬（阿拉伯或中文）
    m = re.search(rf"剩[下]?{_gap}({_num})\s*萬", t)
    if m:
        out["balance"] = int(float(m.group(1)) * 10000)
    else:
        m = re.search(rf"剩[下]?{_gap}({_cn})\s*萬", t)
        if m:
            out["balance"] = int(_cn_num(m.group(1)) * 10000)
    return out


def _ep_data_numbers() -> dict:
    """讀 STUDIO/ep_data.json 的實測真數字（EP 引擎/真實帳戶權威來源），映射成 HUD 欄位。
    優先於旁白 regex：ep_data 是引擎狀態，比口播順口提及可信。抓不到檔或欄位就回空 dict。"""
    out: dict = {}
    try:
        data = json.loads((PROJECT_ROOT / "STUDIO" / "ep_data.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out
    if not isinstance(data, dict):
        return out

    def _pick(*keys):
        for k in keys:
            v = data.get(k)
            if v is not None:
                return v
        return None

    _pr = _pick("investment", "principal")
    _bal = _pick("account_value", "balance")
    _pct = _pick("return_pct", "pct")
    _days = _pick("day", "days")
    try:
        if _pr is not None:
            out["principal"] = float(_pr)
    except Exception:  # noqa: BLE001
        pass
    try:
        if _bal is not None:
            out["balance"] = float(_bal)
    except Exception:  # noqa: BLE001
        pass
    try:
        if _pct is not None:
            out["pct"] = float(_pct)
    except Exception:  # noqa: BLE001
        pass
    try:
        if _days is not None:
            out["days"] = int(float(_days))
    except Exception:  # noqa: BLE001
        pass
    return out


# ep_data.json 只描述「自動交易機器人實測企劃」那一個真錢帳戶（Pionex，本金約 101 美元）。
# 這組是「系列識別」特徵詞——用來確認本片真的是那個系列，而不是只看標題有沒有 EP/實測/實驗。
_ROBOT_SERIES_RE = re.compile(r"機器人|網格|派網|Pionex|自動交易|交易機器|\bbots?\b", re.IGNORECASE)
_RACE_TITLE_RE = re.compile(r"vs|VS|對決|對打|賽跑")


def _ep_data_applies(title: str, slug: str = "", narr_nums: Optional[dict] = None) -> bool:
    """本片是否真的屬於 ep_data.json 描述的那個真錢帳戶系列？只有 True 才可把 ep_data 數字燒上 HUD。

    為什麼不能沿用舊判定（標題命中 EP|實測|實驗|vs 就套）：那些是「題材泛用詞」不是「系列識別」。
    「臺股真相實驗室」整個系列含『實驗』、大量台股題含『實測』、長片標題大量是『A vs B』，
    全被灌上機器人帳戶的本金/餘額/報酬——畫面對觀眾說謊（已發布 32 支受害，見 scratchpad/hud_fix.md）。

    四道門檻全過才套。判不出來就退回 _parse_experiment_numbers 的旁白數字——那本來就是本片的
    正確來源，寧可漏套也絕不可誤套：
      1. A vs B 對比片一律不套：該 HUD 語意是「兩個標的賽跑」，數字必須來自本片旁白。
         機器人系列自己的對比片（如「網格vs定投 5000元」）講的也是本片的錢，不是那個帳戶。
      2. ep_data 必須自稱機器人帳戶系列（series_name）：否則不知道那些數字在講什麼，不套。
      3. 本片 title/slug 要有系列題材特徵：ep_data 的 episodes[] 已被混入台股真相實驗室的 slug，
         不可拿來當白名單比對，只能靠題材特徵。
      4. 旁白明講的本金與帳戶本金量級不符（差 5 倍以上）→ 這支不是那個帳戶的片，不套；
         避免 HUD 燒「本金 101」但旁白在講「丟十萬」這種畫面與口白自相矛盾。
    """
    if _RACE_TITLE_RE.search(title or ""):
        return False
    try:
        data = json.loads((PROJECT_ROOT / "STUDIO" / "ep_data.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(data, dict):
        return False
    if not _ROBOT_SERIES_RE.search(str(data.get("series_name") or "")):
        return False
    if not _ROBOT_SERIES_RE.search(f"{title or ''} {slug or ''}"):
        return False
    _np, _ep = (narr_nums or {}).get("principal"), _ep_data_numbers().get("principal")
    try:
        if _np and _ep and _np > 0 and _ep > 0 and (_np / _ep > 5 or _ep / _np > 5):
            return False
    except Exception:  # noqa: BLE001
        pass
    return True


def _mascot_enabled() -> bool:
    """吉祥物總開關（design_system.mascot_enabled，預設 False）。False 時完全不改變渲染輸出。"""
    try:
        return bool(_design_system().get("mascot_enabled", False))
    except Exception:  # noqa: BLE001
        return False


def _mascot_path_for(pct, *, closing: bool = False) -> Optional[str]:
    """依報酬正負/收官選吉祥物表情檔（正→happy／負→panic／收官→smug／中性→neutral）。不存在回 None。"""
    if closing:
        name = "smug"
    elif pct is None:
        name = "neutral"
    elif pct > 0:
        name = "happy"
    elif pct < 0:
        name = "panic"
    else:
        name = "neutral"
    p = PROJECT_ROOT / "assets" / "mascot" / f"{name}.png"
    return str(p) if p.exists() else None


# 逐段旁白情緒 → 吉祥物表情關鍵字（比整片單一 pct 更貼合當下畫面）
_MASCOT_PANIC_RE = re.compile(r"虧|賠|崩|爆倉|套牢|歸零|腰斬|畢業")
_MASCOT_HAPPY_RE = re.compile(r"賺|贏|獲利|暴賺|賺爛|翻倍|回本")
_MASCOT_SMUG_RE = re.compile(r"拆穿|識破|避雷|看穿|揭穿|戳破")


def _mascot_expr_for_text(text: str) -> Optional[str]:
    """依單段旁白情緒選吉祥物表情檔（smug/panic/happy/neutral）。
    smug(拆穿/戳破…) > panic(虧/爆倉…) > happy(賺/翻倍…) > neutral。
    找不到對應圖退回 neutral；neutral 也不存在回 None。任何情況不拋例外。"""
    t = text or ""
    try:
        if _MASCOT_SMUG_RE.search(t):
            name = "smug"
        elif _MASCOT_PANIC_RE.search(t):
            name = "panic"
        elif _MASCOT_HAPPY_RE.search(t):
            name = "happy"
        else:
            name = "neutral"
        p = PROJECT_ROOT / "assets" / "mascot" / f"{name}.png"
        if p.exists():
            return str(p)
        neu = PROJECT_ROOT / "assets" / "mascot" / "neutral.png"
        return str(neu) if neu.exists() else None
    except Exception:  # noqa: BLE001
        return None


def paste_mascot(base_png, mascot_path, position: str = "br", scale: float = 0.18):
    """把吉祥物 PNG 以 alpha_composite 貼到 base 的指定角落。
    base_png 可為 PNG 路徑或 PIL Image；回傳合成後的 RGBA PIL Image（不落檔，由呼叫端存）。
    position: br/bl/tr/tl；scale: 吉祥物寬佔畫面寬比例。任何失敗回原輸入（不炸渲染）。"""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return base_png
    try:
        base = base_png if hasattr(base_png, "alpha_composite") else Image.open(base_png)
        base = base.convert("RGBA")
    except Exception:  # noqa: BLE001
        return base_png
    try:
        m = Image.open(mascot_path).convert("RGBA")
    except Exception:  # noqa: BLE001
        return base
    W, H = base.size
    mw = max(1, int(W * float(scale)))
    mh = max(1, int(m.height * mw / max(1, m.width)))
    m = m.resize((mw, mh))
    pad = int(min(W, H) * 0.03)
    pos = {
        "br": (W - mw - pad, H - mh - pad),
        "bl": (pad, H - mh - pad),
        "tr": (W - mw - pad, pad),
        "tl": (pad, pad),
    }.get(position, (W - mw - pad, H - mh - pad))
    try:
        base.alpha_composite(m, pos)
    except Exception:  # noqa: BLE001
        pass
    return base


def render_brand_intro(width, height, *, title, dest: Path, tagline=None,
                       logo_path=None, mascot_path=None) -> Optional[str]:
    """品牌固定片頭：讀 assets/brand/intro_template.png 當底（不存在則用 _card_background 生），
    _load_font 壓標題（+選配標語），Image.alpha_composite 貼 logo（右上）/吉祥物（右下），存 PNG。
    回傳 PNG 路徑；當無任何品牌素材（template 不存在且無 logo/mascot）時回 None
    → 呼叫端退回既有片頭降級鏈，確保沒鋪品牌素材時輸出完全不變。"""
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001
        return None
    tmpl = PROJECT_ROOT / "assets" / "brand" / "intro_template.png"
    has_tmpl = tmpl.exists()
    has_logo = bool(logo_path) and Path(logo_path).exists()
    has_mascot = bool(mascot_path) and Path(mascot_path).exists()
    if not (has_tmpl or has_logo or has_mascot):
        return None  # 無品牌素材：不改變現有輸出
    accent = pick_accent(title or "x")
    ac = (int(accent[0]), int(accent[1]), int(accent[2]))
    try:
        if has_tmpl:
            base = Image.open(tmpl).convert("RGBA")
            if base.size != (width, height):
                base = base.resize((width, height))
        else:
            base = _card_background(width, height, accent, seed=title or "intro").convert("RGBA")
    except Exception:  # noqa: BLE001
        try:
            base = _card_background(width, height, accent, seed=title or "intro").convert("RGBA")
        except Exception:  # noqa: BLE001
            return None
    draw = ImageDraw.Draw(base, "RGBA")
    md = min(width, height)
    tfont = _load_font(int(md * 0.088), bold=True)
    max_w = width - int(width * 0.14)
    lines = _wrap_to_width(draw, (title or "").strip(), tfont, max_w) if tfont else [title or ""]
    try:
        _a, _d = tfont.getmetrics()
        lh = int((_a + _d) * 1.2)
    except Exception:  # noqa: BLE001
        lh = int(md * 0.12)
    block_h = lh * len(lines)
    y = (height - block_h) // 2 - int(height * 0.04)
    last_w = 0
    for ln in lines:
        try:
            w = int(draw.textlength(ln, font=tfont))
        except Exception:  # noqa: BLE001
            w = len(ln) * 12
        x = (width - w) // 2
        last_w = w
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (2, 2)):
            draw.text((x + dx, y + dy), ln, fill=(0, 0, 0, 235), font=tfont)
        draw.text((x, y), ln, fill=(245, 248, 255, 255), font=tfont)
        y += lh
    uw = min(int(width * 0.34), max(last_w // 2, int(width * 0.14)))
    ux = (width - uw) // 2
    draw.rectangle([ux, y + int(md * 0.012), ux + uw, y + int(md * 0.012) + max(4, int(md * 0.013))], fill=ac)
    if tagline:
        sf = _load_font(int(md * 0.034), bold=False)
        try:
            tw = int(draw.textlength(tagline, font=sf))
        except Exception:  # noqa: BLE001
            tw = len(tagline) * 10
        sx = (width - tw) // 2
        sy = y + int(md * 0.06)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            draw.text((sx + dx, sy + dy), tagline, fill=(0, 0, 0, 200), font=sf)
        draw.text((sx, sy), tagline, fill=(198, 212, 234, 240), font=sf)
    if has_logo:
        try:
            logo = Image.open(logo_path).convert("RGBA")
            lw = int(width * 0.13)
            logo = logo.resize((lw, max(1, int(logo.height * lw / max(1, logo.width)))))
            base.alpha_composite(logo, (width - lw - int(width * 0.04), int(height * 0.05)))
        except Exception:  # noqa: BLE001
            pass
    if has_mascot:
        try:
            base = paste_mascot(base, mascot_path, position="br", scale=0.20)
        except Exception:  # noqa: BLE001
            pass
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        base.convert("RGB").save(str(dest), format="PNG")
    except Exception:  # noqa: BLE001
        return None
    return str(dest)


def render_hud_strip(width, height, *, dest: Path, day=None, principal=None,
                     balance=None, pct=None, accent=(255, 210, 63)):
    """實測 EP 招牌 HUD：頂部深色條顯示 DAY／餘額／報酬%（透明底全幀 PNG，供合成）。"""
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001
        return None
    f_lbl = _load_font(int(min(width, height) * 0.026), bold=True)
    f_val = _load_font(int(min(width, height) * 0.042), bold=True)
    if not f_val:
        return None
    md = min(width, height)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    def _txt(x, y, s, font, fill, anchor):
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            d.text((x + dx, y + dy), s, font=font, fill=(0, 0, 0, 220), anchor=anchor)
        d.text((x, y), s, font=font, fill=fill, anchor=anchor)

    barh = int(height * 0.072)
    bary = int(height * 0.185)  # 避開概念卡頂部標題條(0~0.165)
    bx1, bx2 = int(width * 0.05), width - int(width * 0.05)
    # 全不透明(255)：這條 HUD 帶會疊在概念圖(concept_visuals)軸圖正上方，
    # 半透明(舊 205)會讓底下的折線穿出來變成「長條/字疊在線圖上」的破圖感(A6-b)；
    # 248 仍會漏一絲亮線(浮點/抗鋸齒殘留)，全不透明才是真的乾淨。
    d.rounded_rectangle([bx1, bary, bx2, bary + barh], radius=int(barh * 0.28),
                        fill=(10, 14, 26, 255),
                        outline=(accent[0], accent[1], accent[2], 150), width=max(2, int(md * 0.004)))
    cy = bary + barh // 2
    up, dn = cy - int(md * 0.026), cy + int(md * 0.004)
    # 依有值欄位動態均分排版（DAY／本金／餘額／報酬），置中不重疊；本金欄仿 DAY 欄補上。
    cols = []
    if day is not None:
        cols.append(("DAY", str(day), (accent[0], accent[1], accent[2], 255), (245, 248, 255, 255)))
    if principal is not None:
        cols.append(("本金", _fmt_money(principal), (180, 196, 222, 255), (245, 248, 255, 255)))
    if balance is not None:
        cols.append(("餘額", _fmt_money(balance), (180, 196, 222, 255), (245, 248, 255, 255)))
    if pct is not None:
        _pcol = (46, 204, 113, 255) if pct >= 0 else (231, 76, 60, 255)
        _sign = "+" if pct >= 0 else ""
        cols.append(("報酬", f"{_sign}{pct:g}%", (180, 196, 222, 255), _pcol))
    if cols:
        inner_x1 = bx1 + int(width * 0.035)
        inner_x2 = bx2 - int(width * 0.035)
        span = inner_x2 - inner_x1
        for ci, (lbl, val, lbl_col, val_col) in enumerate(cols):
            cxp = inner_x1 + int(span * (ci + 0.5) / len(cols))
            _txt(cxp, up, lbl, f_lbl, lbl_col, "mm")
            _txt(cxp, dn, val, f_val, val_col, "mm")
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), format="PNG")
    return dest


def render_race_split(width, height, *, dest: Path, labelA="A", labelB="B",
                      progA=0.5, progB=0.5, accent=(255, 210, 63)):
    """A vs B 賽跑對比：頂部自帶深色面板的計分板（兩條並排進度條），不侵入中央標題/字幕區。

    ⚠️ 目前沒有呼叫端，是刻意的——不要因為「有函式沒人用」就把它接回去。

    這塊不是裝飾：兩條條子掛的是本片比較的兩個標的名，條尾還印百分比，觀眾只會讀成
    「A 拿到 100%、B 只拿到 82%」。所以餵進來的 progA/progB 必須是本片真實數據，
    禁止餵段落進度、常數、或任何「看起來會動」的合成值。

    以前的呼叫端餵的是 progA=frac, progB=frac*0.82（段落進度 × 常數），畫面因此對每支
    對比片都宣稱「B 落後 A 18 個百分點」，與本片數據無關：0050 vs 00878 那支旁白講的是
    815% vs 387%（B 只有 A 的 47%），畫面卻印 82%；AI選股 vs 0050 那支真實是 A 輸，
    畫面卻讓 A 滿格贏——連輸贏方向都相反。已發布 46 支中鏢，故整條路已拆除。

    要接回去，先有「帶單位的結構化事實來源」給出兩側可比的真值（見 STUDIO fact_pool
    無單位池待辦）。實測結論：從旁白 regex 硬抓不可行——旁白裡總報酬/年化/最大回撤/
    配息稅/手續費全是百分比且長得一樣，實測 5 支綁到的有 4 支綁錯（把「手續費吃掉15%」、
    「最慘賠22.6%」、「配息稅30%」、「第一年賺20%」當成某一側的成績），而且有些片旁白
    根本沒講到那一側的總報酬——資料不存在，再好的 parser 也生不出來。
    """
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001
        return None
    md = min(width, height)
    f_lbl = _load_font(int(md * 0.030), bold=True)
    f_val = _load_font(int(md * 0.030), bold=True)
    if not f_lbl:
        return None
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    # 面板（頂部 HUD 區，避開中央）
    px1, px2 = int(width * 0.05), width - int(width * 0.05)
    py1, py2 = int(height * 0.185), int(height * 0.365)  # 避開概念卡頂部標題條
    # 全不透明(255)：這塊面板會疊在概念圖(concept_visuals)軸圖正上方，
    # 半透明(舊 205)會讓底下的折線穿出來變成「長條疊在線圖上」的破圖感(A6-b)；
    # 248 仍會漏一絲亮線(浮點/抗鋸齒殘留)，全不透明才是真的乾淨。
    d.rounded_rectangle([px1, py1, px2, py2], radius=int(md * 0.03),
                        fill=(10, 14, 26, 255),
                        outline=(accent[0], accent[1], accent[2], 150), width=max(2, int(md * 0.004)))
    tx1, tx2 = px1 + int(width * 0.05), px2 - int(width * 0.05)
    tw = tx2 - tx1
    barh = int(height * 0.030)
    rad = max(2, barh // 3)  # Pillow 9.5 嚴格：radius 必須 << 高/寬，避免 y1<y0
    rows = ((py1 + int(height * 0.052), labelA, max(0.0, min(1.0, progA)), (46, 204, 113)),
            (py1 + int(height * 0.115), labelB, max(0.0, min(1.0, progB)), (52, 152, 219)))
    for yy, lbl, prog, col in rows:
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            d.text((tx1 + dx, yy - int(md * 0.042) + dy), lbl[:10], font=f_lbl, fill=(0, 0, 0, 220))
        d.text((tx1, yy - int(md * 0.042)), lbl[:10], font=f_lbl, fill=(245, 248, 255, 255))
        # 軌道/填色都要全不透明：這兩塊疊在概念圖軸圖正上方，半透明會讓底下折線
        # 從軌道裡透出來(A6-b 的真正根因——不是面板本身漏，是軌道那層漏)。
        d.rounded_rectangle([tx1, yy, tx2, yy + barh], radius=rad, fill=(20, 26, 40, 255))
        fw = int(tw * prog)
        if fw >= 2 * rad + 2:
            d.rounded_rectangle([tx1, yy, tx1 + fw, yy + barh], radius=rad, fill=(col[0], col[1], col[2], 255))
        # 數值標籤（A6-b：長條「驚人差距」沒數字看不出差多少，補上百分比錨在條尾）
        vtxt = f"{prog * 100:.0f}%"
        vy = yy + barh // 2
        try:
            vx = tx1 + fw - int(md * 0.010) if fw >= int(md * 0.06) else tx1 + fw + int(md * 0.010)
            vanchor = "rm" if fw >= int(md * 0.06) else "lm"
            vcol = (10, 14, 26, 255) if fw >= int(md * 0.06) else (245, 248, 255, 255)
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                d.text((vx + dx, vy + dy), vtxt, font=f_val, fill=(0, 0, 0, 160), anchor=vanchor)
            d.text((vx, vy), vtxt, font=f_val, fill=vcol, anchor=vanchor)
        except Exception:  # noqa: BLE001
            pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), format="PNG")
    return dest


def build_video(
    slug_paths: SlugPaths,
    branding: dict,
    *,
    width: int,
    height: int,
    fps: int,
    audio_duration: float,
    segments: List[Segment],
    title: str,
    pexels_key: Optional[str],
    tmp_dir: Path,
    no_subtitles: bool,
) -> dict:
    """
    實際組裝影片並寫出 mp4。回傳統計 dict（給 log）。
    """
    from moviepy.editor import (
        AudioFileClip,
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
        concatenate_videoclips,
    )

    stats = {
        "broll_used": 0,
        "card_used": 0,
        "subtitle_count": 0,
        "subtitle_estimated": True,
    }

    n = len(segments)
    per_seg = audio_duration / n if n else audio_duration
    watermark = branding.get("watermark_text", "")
    accent = pick_accent(getattr(slug_paths, "slug", "") or title)  # 每支一色，畫面有變化
    vid_seed = getattr(slug_paths, "slug", "") or title             # K 線圖形種子

    # 影片級主題：優先用「標題＋各段小標」判（最乾淨的主題訊號，不被旁白順口提及干擾）；
    # 標題判不到才退回看全片旁白。當作各段「判不到主題」時的預設圖，整支更一致對題。
    video_concept = None
    if _concept is not None:
        try:
            _head_text = title + " " + " ".join(s.heading for s in segments if s.heading)
            video_concept = _concept.classify(_head_text)
            if video_concept is None:
                _all_text = " ".join(s.narration for s in segments if s.narration)
                video_concept = _concept.classify(_all_text)
        except Exception:  # noqa: BLE001
            video_concept = None

    body_clips = []
    seg_cards = []  # 每段靜態卡 PNG 路徑(broll 段=None)，供靜態切片快路徑
    for i, seg in enumerate(segments):
        clip = None
        card_png = None
        # 1) 嘗試 Pexels B-roll
        if pexels_key and seg.broll:
            local = fetch_pexels_clip(
                seg.broll,
                api_key=pexels_key,
                width=width,
                height=height,
                dest_dir=tmp_dir,
                index=i,
            )
            if local is not None:
                try:
                    raw = VideoFileClip(str(local)).without_audio()
                    clip = _fit_clip(raw, width, height, per_seg)
                    stats["broll_used"] += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"[warn] 載入 B-roll 失敗（{exc}），第 {i+1} 段改用字卡。", file=sys.stderr)
                    clip = None

        # 2) 主題數據圖卡（每段依旁白畫對得上的圖）→ 退回 K 線卡 → 退回字卡
        if clip is None:
            card_png = None
            try:
                card_png = render_concept_card(
                    width, height, heading=seg.heading or title, narration=seg.narration,
                    watermark=watermark, accent=accent, seed=f"{vid_seed}_{i}",
                    dest=tmp_dir / f"concept_{i:02d}.png", default_key=video_concept,
                )
                if card_png is not None:
                    stats["concept_used"] = stats.get("concept_used", 0) + 1
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] 概念圖失敗，退回 K 線卡：{exc}", file=sys.stderr)
                card_png = None
        if clip is None:
            try:
                if card_png is None:
                    card_png = render_candle_card(
                        width, height, big_text=seg.heading or title, watermark=watermark,
                        accent=accent, seed=f"{vid_seed}_{i}", dest=tmp_dir / f"kcard_{i:02d}.png",
                    )
                clip = ImageClip(str(card_png)).set_duration(per_seg)  # 純靜態，渲染快
            except Exception as exc:  # noqa: BLE001 - 失敗退回字卡，不影響出片
                print(f"[warn] K 線卡失敗，退回字卡：{exc}", file=sys.stderr)
                card_png = render_card_image(
                    width, height, big_text=seg.heading or title, small_text="",
                    watermark=watermark, dest=tmp_dir / f"card_{i:02d}.png", accent=accent,
                )
                clip = ImageClip(str(card_png)).set_duration(per_seg)
            stats["card_used"] += 1

        seg_cards.append(str(card_png) if card_png else None)
        body_clips.append(clip)

    # ── 實測EP招牌HUD：靜態逐段推進；非實測片零影響 ──
    # A vs B 賽跑計分板已整條拆除（理由見 render_race_split docstring）：它印在畫面上的
    # 百分比是「段落進度 × 0.82」的合成值，與本片數據無關，已發布 46 支中鏢。對比片現在
    # 不上任何 HUD——這裡不要退回去改用 render_hud_strip 補位：那組是本金/餘額/天數，
    # 對「A vs B」沒有意義，硬套就是剛修掉的那個 HUD bug（見 _ep_data_applies）。
    hud_overlays = []
    _title = title or ""
    _is_exp = bool(re.search(r"EP|實測|實驗", _title))
    if _is_exp:
        try:
            _vt = read_voice_text(slug_paths) or " ".join(s.narration for s in segments if s.narration)
            _nums = _parse_experiment_numbers(_vt)
        except Exception:  # noqa: BLE001
            _nums = {}
        # ep_data 是該系列真實帳戶的權威數字，但「只在本片真的屬於那個系列」時才蓋（見 _ep_data_applies）。
        # 舊版無條件 update → 台股/對比片被灌上不相干的帳戶數字。
        try:
            if _ep_data_applies(_title, getattr(slug_paths, "slug", ""), _nums):
                _nums.update(_ep_data_numbers())
        except Exception:  # noqa: BLE001
            pass
        _pr, _pct = _nums.get("principal"), _nums.get("pct")
        _bal, _dtot = _nums.get("balance"), _nums.get("days")
        if _bal is None and _pr is not None and _pct is not None:
            _bal = int(_pr * (1 + _pct / 100.0))
        _has_data = any(v is not None for v in (_pr, _pct, _bal, _dtot))
        _n = max(1, len(seg_cards) or len(segments))
        if _has_data:
            from PIL import Image as _PIH
            for i in range(_n):
                frac = (i + 1) / _n
                hud_png = None
                try:
                    _day = int(round((_dtot or _n) * frac)) if (_dtot or _is_exp) else None
                    _bal_i = int(_pr + (_bal - _pr) * frac) if (_pr is not None and _bal is not None) else _bal
                    _pct_i = round(_pct * frac, 2) if _pct is not None else None
                    hud_png = render_hud_strip(width, height, dest=tmp_dir / f"hud_{i:02d}.png",
                                               day=_day, principal=_pr, balance=_bal_i, pct=_pct_i, accent=accent)
                except Exception:  # noqa: BLE001
                    hud_png = None
                if hud_png is None:
                    continue
                # 靜態路徑：把 HUD 烤進該段卡（存新檔，不覆蓋原檔）
                if i < len(seg_cards) and seg_cards[i]:
                    try:
                        _b = _PIH.open(seg_cards[i]).convert("RGBA")
                        _h = _PIH.open(str(hud_png)).convert("RGBA")
                        _b.alpha_composite(_h)
                        _outp = tmp_dir / f"cardhud_{i:02d}.png"
                        _b.convert("RGB").save(str(_outp))
                        seg_cards[i] = str(_outp)
                    except Exception:  # noqa: BLE001
                        pass
                # 逐幀路徑：備一份 overlay
                try:
                    hud_overlays.append(ImageClip(str(hud_png)).set_start(i * per_seg)
                                        .set_duration(per_seg).set_position((0, 0)))
                except Exception:  # noqa: BLE001
                    pass

    # ── 吉祥物 IP（預設關閉：design_system.mascot_enabled=true 才貼；false 時此區完全跳過、輸出不變）──
    #    依整支實測報酬正負選表情，收官段用 smug；比照 HUD 烤卡手法貼進段卡角落（僅靜態切片路徑）。
    if _mascot_enabled():
        try:
            _mpct = _ep_data_numbers().get("pct")
            _mn = len(seg_cards)
            for i in range(_mn):
                if not seg_cards[i]:
                    continue
                _mp = _mascot_path_for(_mpct, closing=(i == _mn - 1))
                if not _mp:
                    continue
                try:
                    _mimg = paste_mascot(seg_cards[i], _mp, position="br", scale=0.16)
                    _mout = tmp_dir / f"cardmas_{i:02d}.png"
                    _mimg.convert("RGB").save(str(_mout))
                    seg_cards[i] = str(_mout)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

    # intro / outro 字卡
    def _candle_segment(big_text_, suffix, dur):
        try:
            cardp = render_candle_card(width, height, big_text=big_text_, watermark=watermark,
                                       accent=accent, seed=f"{vid_seed}_{suffix}", dest=tmp_dir / f"kcard_{suffix}.png")
            return ImageClip(str(cardp)).set_duration(dur)  # 純靜態，渲染快
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] K 線 {suffix} 失敗，退回字卡：{exc}", file=sys.stderr)
            cardp = render_card_image(width, height, big_text=big_text_, small_text="",
                                      watermark=watermark, dest=tmp_dir / f"card_{suffix}.png", accent=accent)
            return ImageClip(str(cardp)).set_duration(dur)

    # 品牌固定片頭：有品牌素材（intro_template/logo/mascot）才啟用；否則 None→退回既有 K 線標題卡降級鏈
    intro_clip = None
    try:
        _mpath_i = _mascot_path_for(_ep_data_numbers().get("pct")) if _mascot_enabled() else None
        _bi = render_brand_intro(width, height, title=title, dest=tmp_dir / "brand_intro.png",
                                 tagline=branding.get("intro_tagline"), mascot_path=_mpath_i)
        if _bi:
            intro_clip = ImageClip(str(_bi)).set_duration(INTRO_DURATION)
    except Exception as _bie:  # noqa: BLE001
        print(f"[warn] 品牌片頭略過，退回 K 線卡：{str(_bie)[:70]}", file=sys.stderr)
    if intro_clip is None:
        intro_clip = _candle_segment(title, "intro", INTRO_DURATION)
    # Shorts 開場改用高質感封面（取代 K 線標題卡；同一張供縮圖重用，失敗則沿用 K 線卡不影響渲染）
    _slug = str(getattr(slug_paths, "slug", "") or "")
    if _slug.startswith("S_"):
        try:
            import make_cover as _mc
            _cp = _mc.OUT / f"{_slug}.jpg"
            if not _cp.exists():
                _mc.make_cover(_slug, title)
            if _cp.exists():
                intro_clip = ImageClip(str(_cp)).set_duration(INTRO_DURATION)
        except Exception as _e:  # noqa: BLE001
            print(f"[warn] 封面開場略過，沿用 K 線卡：{str(_e)[:70]}", file=sys.stderr)
    outro_clip = _candle_segment(branding.get("watermark_text", "感謝收看"), "outro", OUTRO_DURATION)
    # 輕量動態(不爆 2vCPU、不破壞佈局):開場/結尾淡入
    try:
        intro_clip = intro_clip.crossfadein(min(0.6, INTRO_DURATION / 2))
        outro_clip = outro_clip.crossfadein(min(0.5, OUTRO_DURATION / 2))
    except Exception:  # noqa: BLE001
        pass

    # 字幕 cue 先算（兩條路徑共用）
    cues = []
    if not no_subtitles:
        voice_text = read_voice_text(slug_paths)
        if not voice_text:
            voice_text = " ".join(s.narration for s in segments if s.narration).strip()
        cues = (load_word_cues(slug_paths, voice_text, audio_duration)
                or build_subtitle_cues(split_subtitle_units(voice_text), audio_duration))
        stats["subtitle_count"] = len(cues)

    _all_static = bool(seg_cards) and all(p is not None for p in seg_cards) and len(seg_cards) == len(segments)
    if _all_static and cues:
        # ── 靜態切片快路徑（純字卡無 b-roll）：每時段把卡＋當下字幕燒成一張靜圖，
        #    用 ImageClip 拼接，徹底免逐幀合成 → 弱 CPU(2vCPU) 也能快數倍 ──
        from PIL import Image as _PILImg
        marks = {0.0, float(audio_duration)}
        for k in range(len(seg_cards) + 1):
            marks.add(min(max(k * per_seg, 0.0), audio_duration))
        for cu in cues:
            marks.add(min(max(cu.start, 0.0), audio_duration))
            marks.add(min(max(cu.end, 0.0), audio_duration))
        bounds = sorted(marks)
        sub_cache = {}
        slices = []
        for a, b in zip(bounds, bounds[1:]):
            dur = b - a
            if dur < 0.04:
                continue
            mid = (a + b) / 2.0
            seg_idx = min(int(mid / per_seg) if per_seg else 0, len(seg_cards) - 1)
            base_png = seg_cards[seg_idx]
            cue = next((c for c in cues if c.start <= mid < c.end), None)
            png_path = base_png
            if cue is not None:
                key = (seg_idx, cue.text)
                if key not in sub_cache:
                    composed = base_png
                    sub_png = _render_subtitle_image(width, height, cue.text, tmp_dir, accent=accent)
                    if sub_png is not None:
                        try:
                            base = _PILImg.open(base_png).convert("RGBA")
                            sub = _PILImg.open(str(sub_png)).convert("RGBA")
                            x = max(0, (width - sub.width) // 2)
                            y = max(0, int(height * 0.78) - sub.height)
                            base.alpha_composite(sub, (x, y))
                            outp = tmp_dir / f"slice_{seg_idx:02d}_{len(sub_cache):03d}.jpg"
                            base.convert("RGB").save(str(outp), "JPEG", quality=90)
                            composed = str(outp)
                        except Exception:  # noqa: BLE001
                            composed = base_png
                    sub_cache[key] = composed
                png_path = sub_cache[key]
            slices.append(ImageClip(png_path).set_duration(dur))
        body = concatenate_videoclips(slices, method="compose") if slices \
            else concatenate_videoclips(body_clips, method="compose")
    else:
        # ── 原逐幀路徑（有 b-roll 或無字幕時保留，確保正確性）──
        body = concatenate_videoclips(body_clips, method="compose")
        if cues:
            sub_overlays = []
            for cue in cues:
                sub_png = _render_subtitle_image(width, height, cue.text, tmp_dir, accent=accent)
                if sub_png is None:
                    continue
                _sd = max(cue.end - cue.start, 0.1)
                _ovc = ImageClip(str(sub_png))
                _yp = max(0, int(height * 0.78) - int(_ovc.h))
                ov = (
                    _ovc
                    .set_start(cue.start)
                    .set_duration(_sd)
                    .set_position(("center", _yp))
                )
                try:
                    ov = ov.crossfadein(min(0.22, _sd / 2))
                except Exception:  # noqa: BLE001
                    pass
                sub_overlays.append(ov)
            if sub_overlays or hud_overlays:
                body = CompositeVideoClip([body, *hud_overlays, *sub_overlays], size=(width, height))

    # 配上音訊（只在 body 段落，intro/outro 無聲）
    audio = AudioFileClip(str(slug_paths.audio))
    body = body.set_audio(audio).set_duration(audio_duration)

    # 無縫 loop 尾(item9):片尾淡回片頭首幀(Shorts 開場=封面),讓重播無縫→拉高 loop 完播
    # (2026 演算法:結尾 2 秒內重看算部分新觀看)。純加法+try 防呆:失敗只是不加尾,concat 照跑,絕不弄壞產線。
    # MV_NO_LOOP_TAIL=1 可一鍵關。
    _clips = [intro_clip, body, outro_clip]
    if os.environ.get("MV_NO_LOOP_TAIL") != "1":
        try:
            _loop_dur = 0.6
            _tail = intro_clip.to_ImageClip(0).set_duration(_loop_dur).crossfadein(min(0.4, _loop_dur))
            _clips.append(_tail)
        except Exception as _lte:  # noqa: BLE001
            print(f"[warn] loop 尾略過,用標準結尾:{str(_lte)[:60]}", file=sys.stderr)
    final = concatenate_videoclips(_clips, method="compose")
    final = final.set_fps(fps)

    slug_paths.out_mp4.parent.mkdir(parents=True, exist_ok=True)

    # 選編碼器:MV_CODEC 環境變數優先 → 自動偵測 GPU NVENC(本機有 GPU 就用) → 退 CPU libx264(雲端無 GPU)
    _codec, _preset, _extra = "libx264", "ultrafast", []
    _forced = os.environ.get("MV_CODEC", "").strip()
    if _forced:
        _codec = _forced
        if "nvenc" in _forced:
            _preset, _extra = "p4", ["-rc", "vbr", "-cq", "23"]
    elif not os.environ.get("MV_NO_GPU"):
        try:
            import subprocess as _sp, imageio_ffmpeg as _iio
            _ff = _iio.get_ffmpeg_exe()
            _has = "h264_nvenc" in _sp.run([_ff, "-hide_banner", "-encoders"],
                                           capture_output=True, text=True, timeout=12).stdout
            if _has and _sp.run([_ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                                 "-i", "color=c=black:s=128x128:d=0.1", "-c:v", "h264_nvenc",
                                 "-f", "null", "-"], capture_output=True, text=True, timeout=20).returncode == 0:
                _codec, _preset, _extra = "h264_nvenc", "p4", ["-rc", "vbr", "-cq", "23"]
        except Exception:  # noqa: BLE001
            pass
    print(f"[編碼] 使用 {_codec}（preset={_preset}）", file=sys.stderr)

    # 直接寫真正輸出路徑很危險：moviepy 中途被殺（batch timeout kill 整組子行程）或編碼中途炸掉，
    # 會在 output/ 留一個 0KB/截斷的 mp4，audit_video 事後才抓到、白算一次有效產量。
    # 改成先寫暫存檔，探測(視訊軌/音軌/片長)過了才搬進正式路徑；沒過 raise 讓外層重試迴圈接手，
    # 正式路徑要嘛不動、要嘛是已驗證的完整檔，絕不留半成品。
    _tmp_out = tmp_dir / f"_render_{getattr(slug_paths, 'slug', 'out')}.mp4"

    def _write(cv, pr, extra):
        final.write_videofile(
            str(_tmp_out),
            fps=fps,
            codec=cv,
            audio_codec="aac",
            preset=pr,
            threads=os.cpu_count() or 4,
            bitrate="3500k",
            ffmpeg_params=(extra or None),
            temp_audiofile=str(tmp_dir / "temp_audio.m4a"),
            remove_temp=True,
            logger=None,
        )

    # 寫出 mp4（GPU 編碼失敗自動退 CPU，確保一定出片）
    try:
        try:
            _write(_codec, _preset, _extra)
        except Exception as _enc_exc:  # noqa: BLE001
            if _codec != "libx264":
                print(f"[warn] {_codec} 編碼失敗（{_enc_exc}），退回 CPU libx264。", file=sys.stderr)
                _write("libx264", "ultrafast", [])
            else:
                raise
    finally:
        # 釋放資源
        for c in body_clips:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        for c in (intro_clip, outro_clip, body, final, audio):
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass

    # P0 止血(2026-07-13)：成品長度必須 ≥ 旁白長度(0.95 容錯)，不再只查 >=1.0s 這種形同虛設
    # 的下限——04_0056 事故的斷尾片(旁白218.9s/成品61.7s)靠舊下限一樣能 PASS。
    _expected_min = max(1.0, (INTRO_DURATION + audio_duration + OUTRO_DURATION) * 0.95)
    _ok, _reason = _probe_render_output(_tmp_out, min_duration=_expected_min)
    if not _ok:
        try:
            _tmp_out.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        _log_render_ops("make_video/moviepy驗證失敗", f"{getattr(slug_paths, 'slug', '?')}: {_reason}")
        raise RuntimeError(f"moviepy 輸出驗證失敗：{_reason}")
    slug_paths.out_mp4.parent.mkdir(parents=True, exist_ok=True)
    import shutil as _sh_move
    _sh_move.move(str(_tmp_out), str(slug_paths.out_mp4))

    stats["total_duration"] = INTRO_DURATION + audio_duration + OUTRO_DURATION
    return stats


def _wrap_to_width(draw, text: str, font, max_w: int) -> list:
    """依像素寬度把字串折成多行（適合中文逐字折行），每行不超過 max_w。"""
    lines: list = []
    cur = ""
    for ch in text:
        test = cur + ch
        try:
            w = draw.textlength(test, font=font)
        except Exception:  # noqa: BLE001
            w = len(test) * 12
        if w <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines or [text]


def _render_subtitle_image(width: int, height: int, text: str, tmp_dir: Path, accent=(255, 210, 63)) -> Optional[Path]:
    """字幕 PNG：粗體白字 + 圓角半透明底 + 細強調色邊，字級自適應、自動換行不爆框。"""
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001
        return None

    fsize = max(44, min(int(height * 0.060), int(width * 0.082)))
    font = _load_font(fsize, bold=True)
    side = int(width * 0.045)
    max_w = width - 2 * side
    pad_x = int(width * 0.024)
    pad_y = int(height * 0.013)
    line_gap = int(fsize * 0.28)

    tmp_img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp_img)
    lines = _wrap_to_width(d, text, font, max_w - pad_x * 2) if font else [text]

    sizes = []
    for ln in lines:
        try:
            b = d.textbbox((0, 0), ln, font=font)
            sizes.append((b[2] - b[0], b[3] - b[1]))
        except Exception:  # noqa: BLE001
            sizes.append((len(ln) * 12, fsize))
    block_w = max((w for w, _ in sizes), default=10)
    line_h = max((h for _, h in sizes), default=fsize)
    total_h = line_h * len(lines) + line_gap * (len(lines) - 1)

    iw = block_w + pad_x * 2
    ih = total_h + pad_y * 2
    img = Image.new("RGBA", (max(iw, 1), max(ih, 1)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rad = int(min(iw, ih) * 0.22)
    # 全不透明(255)：字幕框常跟概念圖的圖說/圖例同一 y 帶(A6-b)，半透明(舊 185)會讓
    # 底下文字「穿透」變殘影字；248 仍會漏一絲字跡，拉到全不透明才是真的完全蓋掉。
    draw.rounded_rectangle([0, 0, iw - 1, ih - 1], radius=rad, fill=(8, 12, 24, 255),
                           outline=(accent[0], accent[1], accent[2], 150), width=max(2, int(fsize * 0.045)))

    y = pad_y
    for ln, (lw, _lh) in zip(lines, sizes):
        tx = (iw - lw) // 2
        _e = max(3, int(fsize * 0.06))
        for dx, dy in ((-_e, 0), (_e, 0), (0, -_e), (0, _e), (_e, _e), (-_e, -_e), (_e, -_e), (-_e, _e)):
            draw.text((tx + dx, y + dy), ln, fill=(0, 0, 0, 255), font=font)
        draw.text((tx, y), ln, fill=(255, 255, 255, 255), font=font)
        y += line_h + line_gap

    safe = re.sub(r"[^0-9A-Za-z]+", "_", text)[:20] or "sub"
    dest = tmp_dir / f"sub_{abs(hash(text)) % 10**8}_{safe}.png"
    img.save(dest, format="PNG")
    return dest


# --------------------------------------------------------------------------- #
# dry-run：只印計畫，不產檔
# --------------------------------------------------------------------------- #


def size_bracket(duration_s: float, has_broll: bool) -> str:
    """粗估輸出檔大小級距（H.264 1080p）。純字卡 bitrate 低，B-roll 高。"""
    # 經驗值：字卡投影片 ~1.5 Mbps，B-roll ~6 Mbps
    mbps = 6.0 if has_broll else 1.5
    mb = duration_s * mbps / 8.0
    if mb < 20:
        return f"~{mb:.0f} MB（小，<20MB）"
    if mb < 80:
        return f"~{mb:.0f} MB（中，20-80MB）"
    return f"~{mb:.0f} MB（大，>80MB）"


def do_dry_run(
    slug_paths: SlugPaths,
    branding: dict,
    *,
    width: int,
    height: int,
    fps: int,
    pexels_key: Optional[str],
    no_subtitles: bool,
) -> int:
    print("=" * 64)
    print(f"slug       : {slug_paths.slug}")
    print(f"配音 mp3   : {slug_paths.audio}")
    print(f"腳本 md    : {slug_paths.script_md}")
    print(f"輸出 mp4   : {slug_paths.out_mp4}")
    print(f"解析度     : {width}x{height} @ {fps}fps")
    print("=" * 64)

    # 解析腳本
    try:
        title, segments = parse_script_md(slug_paths.script_md)
    except FileNotFoundError as exc:
        print(f"[FATAL] {exc}")
        return 2

    # 配音時長
    try:
        duration = probe_audio_duration(slug_paths.audio)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[WARN] 無法取得配音時長（{exc}）。dry-run 改以每段 8 秒估算。")
        duration = len(segments) * 8.0

    n = len(segments)
    per_seg = duration / n if n else duration

    use_pexels = bool(pexels_key)
    print(f"影片標題   : {title}")
    print(f"素材來源   : {'Pexels API（有 PEXELS_API_KEY）' if use_pexels else '字卡降級（無 PEXELS_API_KEY）'}")
    print(f"主體段數   : {n} 段（intro {INTRO_DURATION:.0f}s + 主體 {duration:.1f}s + outro {OUTRO_DURATION:.0f}s）")
    print(f"配音總長   : {duration:.1f}s")
    print("-" * 64)
    for i, seg in enumerate(segments, 1):
        kw = "、".join(seg.broll) if seg.broll else "（無關鍵字→字卡）"
        src = "B-roll" if (use_pexels and seg.broll) else "字卡"
        print(f"  [{i:>2}/{n}] {per_seg:5.1f}s | 來源={src:6s} | {seg.heading[:24]}")
        print(f"           關鍵字: {kw}")
    print("-" * 64)

    # 字幕估算
    sub_count = 0
    if not no_subtitles:
        voice_text = read_voice_text(slug_paths)
        if not voice_text:
            voice_text = " ".join(s.narration for s in segments if s.narration).strip()
        units = split_subtitle_units(voice_text)
        sub_count = len(build_subtitle_cues(units, duration))
        print(f"字幕段數   : {sub_count} 段  [估算：依配音總長平均分配，非逐字時間軸]")
    else:
        print("字幕       : （--no-subtitles，關閉）")

    total = INTRO_DURATION + duration + OUTRO_DURATION
    print(f"預估輸出長 : {total:.1f}s（{total/60:.1f} 分）")
    print(f"預估檔大小 : {size_bracket(total, has_broll=use_pexels)}")
    print("=" * 64)
    print("[DRY-RUN] 未產生任何檔案。")
    return 0


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def run(args: argparse.Namespace) -> int:
    width = args.width
    height = args.height
    fps = args.fps

    branding = load_branding(Path(args.config) if args.config else None)
    slug_paths = resolve_slug_paths(args)
    pexels_key = os.environ.get("PEXELS_API_KEY", "").strip() or None

    if args.dry_run:
        return do_dry_run(
            slug_paths,
            branding,
            width=width,
            height=height,
            fps=fps,
            pexels_key=pexels_key,
            no_subtitles=args.no_subtitles,
        )

    # 真實產片：先確認 moviepy 可用
    try:
        import moviepy.editor  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print(f"[FATAL] 無法匯入 moviepy（{exc}）。", file=sys.stderr)
        print("  請執行：pip install moviepy", file=sys.stderr)
        print("  並安裝 ffmpeg：winget install Gyan.FFmpeg", file=sys.stderr)
        return 3
    try:
        import PIL  # noqa: F401
    except Exception:  # noqa: BLE001
        print("[FATAL] 缺少 Pillow（PIL）。請執行：pip install moviepy（會帶入 Pillow）。", file=sys.stderr)
        return 3

    # 解析腳本
    try:
        title, segments = parse_script_md(slug_paths.script_md)
    except FileNotFoundError as exc:
        print(f"[FATAL] {exc}", file=sys.stderr)
        return 2

    # 配音時長
    try:
        duration = probe_audio_duration(slug_paths.audio)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[FATAL] {exc}", file=sys.stderr)
        return 2
    if duration <= 0:
        print(f"[FATAL] 配音時長為 0，無法組片：{slug_paths.audio}", file=sys.stderr)
        return 2

    print("=" * 64)
    print(f"開始組片：{slug_paths.slug}")
    print(f"  標題     : {title}")
    print(f"  配音長   : {duration:.1f}s（{len(segments)} 段）")
    print(f"  素材來源 : {'Pexels' if pexels_key else '字卡降級（無 PEXELS_API_KEY）'}")
    print(f"  解析度   : {width}x{height} @ {fps}fps")
    if not pexels_key:
        print("  [note] 未設定 PEXELS_API_KEY，全程使用字卡投影片（仍可產出完整測試片）。")
    print("=" * 64)

    # best-effort：先清掉先前殘留（行程已結束、鎖已釋放）的暫存資料夾
    import gc as _gc, shutil as _shutil
    for _old in Path(tempfile.gettempdir()).glob("carson_video_*"):
        _shutil.rmtree(_old, ignore_errors=True)

    # 手動建暫存夾，改用「容忍 Windows 檔案鎖」的清理，避免 moviepy/ffmpeg 尚未釋放
    # 的 B-roll 檔 handle 在自動清理時拋 PermissionError，連帶把已產出的 mp4 也判成失敗。
    # 自我修復：渲染失敗自動重試一次（吸收 ffmpeg/網路抖動等暫時性錯誤）
    # ── 純 ffmpeg 後端優先(本機/雲端都快 ~10x):純字卡 + b-roll 都走它;
    #    任何失敗自動回 moviepy 備案(Phase 2:b-roll 已支援) ──
    if not os.environ.get("MV_FORCE_MOVIEPY"):
        try:
            import render_ffmpeg
            if render_ffmpeg.render(slug_paths, branding, width=width, height=height,
                                    fps=fps, no_subtitles=args.no_subtitles):
                # 二次防呆：render_ffmpeg 內部已驗證過，這裡再探一次（成本極低），
                # 徹底堵死「回傳 True 但正式路徑其實是壞檔」的任何殘餘縫隙。
                # P0 止血(2026-07-13)：一併查長度與旁白是否匹配(≥95%)，別只查 >=1.0s。
                _expected_min = max(1.0, (INTRO_DURATION + duration + OUTRO_DURATION) * 0.95)
                _ok, _reason = _probe_render_output(slug_paths.out_mp4, min_duration=_expected_min)
                if _ok:
                    size_mb = slug_paths.out_mp4.stat().st_size / (1024 * 1024)
                    print("=" * 64)
                    print("[OK] 影片完成（ffmpeg 後端·快）！")
                    print(f"  檔案     : {slug_paths.out_mp4}")
                    print(f"  大小     : {size_mb:.1f} MB")
                    print("=" * 64)
                    return 0
                print(f"[warn] ffmpeg 後端輸出驗證未過（{_reason}），清除壞檔改用 moviepy 備案。", file=sys.stderr)
                _cleanup_bad_output(slug_paths.out_mp4)
                _log_render_ops("make_video/ffmpeg後端驗證失敗", f"{slug_paths.slug}: {_reason}")
            else:
                print("[info] ffmpeg 後端不適用此片，改用 moviepy 備案。", file=sys.stderr)
        except Exception as _ff_exc:  # noqa: BLE001
            print(f"[warn] ffmpeg 後端失敗（{_ff_exc}），改用 moviepy 備案。", file=sys.stderr)
            _cleanup_bad_output(slug_paths.out_mp4)

    stats = None
    last_exc = None
    for _attempt in range(2):
        tmp_dir = Path(tempfile.mkdtemp(prefix="carson_video_"))
        try:
            stats = build_video(
                slug_paths,
                branding,
                width=width,
                height=height,
                fps=fps,
                audio_duration=duration,
                segments=segments,
                title=title,
                pexels_key=pexels_key,
                tmp_dir=tmp_dir,
                no_subtitles=args.no_subtitles,
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"[warn] 渲染第 {_attempt+1}/2 次失敗：{type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            _gc.collect()
            _shutil.rmtree(tmp_dir, ignore_errors=True)
    if stats is None:
        # 兩次都沒過：正式路徑本身這次沒被寫壞（build_video 只搬「已驗證」的檔），
        # 但保險起見仍探一次——若殘留舊壞檔（例如舊版程式留下的），一併清掉，
        # 別讓 audit_video 事後才發現、白算一次有效產量。
        _expected_min = max(1.0, (INTRO_DURATION + duration + OUTRO_DURATION) * 0.95)
        _ok, _reason = _probe_render_output(slug_paths.out_mp4, min_duration=_expected_min)
        if not _ok:
            _cleanup_bad_output(slug_paths.out_mp4)
        _log_render_ops("make_video/總失敗", f"{slug_paths.slug}: {type(last_exc).__name__}: {last_exc}")
        print(f"[FATAL] 影片組裝失敗（{type(last_exc).__name__}: {last_exc}）", file=sys.stderr)
        print("  常見原因：ffmpeg 未安裝或不在 PATH（winget install Gyan.FFmpeg）。", file=sys.stderr)
        return 4

    size_mb = slug_paths.out_mp4.stat().st_size / (1024 * 1024) if slug_paths.out_mp4.exists() else 0
    print("=" * 64)
    print("[OK] 影片完成！")
    print(f"  檔案     : {slug_paths.out_mp4}")
    print(f"  大小     : {size_mb:.1f} MB")
    print(f"  總時長   : {stats.get('total_duration', 0):.1f}s")
    print(f"  B-roll   : {stats.get('broll_used', 0)} 段 / 字卡 {stats.get('card_used', 0)} 段")
    if not args.no_subtitles:
        print(f"  字幕     : {stats.get('subtitle_count', 0)} 段  [估算：依配音總長平均分配]")
    print("=" * 64)
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="make_video.py",
        description="把配音 mp3 + 腳本 md 自動組成一支 faceless mp4（B-roll 或字卡降級）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "範例：\n"
            "  # 用 slug 自動推導 output/<slug>.mp3 / .md / .voice.txt → output/<slug>.mp4\n"
            '  python scripts\\make_video.py --slug 派網網格教學\n'
            "  # 只看計畫不產檔\n"
            '  python scripts\\make_video.py --slug 派網網格教學 --dry-run\n'
            "  # 個別指定輸入並調解析度\n"
            '  python scripts\\make_video.py --audio output\\x.mp3 --script output\\x.md --width 1080 --height 1920\n'
            "\n"
            "提示：設定環境變數 PEXELS_API_KEY 可自動抓 Pexels 免費影片素材；\n"
            "      未設定時全程使用字卡投影片，照樣產得出 mp4。\n"
            "      PowerShell:  $env:PEXELS_API_KEY = 'xxxx'\n"
        ),
    )
    p.add_argument("--slug", default=None, help="影片 slug（自動推導 output/<slug>.mp3 / .md / .voice.txt / .mp4）")
    p.add_argument("--audio", default=None, help="配音 mp3 路徑（覆寫；預設 output/<slug>.mp3）")
    p.add_argument("--script", default=None, help="腳本 md 路徑（覆寫；預設 output/<slug>.md）")
    p.add_argument("-o", "--out", default=None, help="輸出 mp4 路徑（覆寫；預設 output/<slug>.mp4）")
    p.add_argument("--output-dir", default=None, help=f"輸出資料夾（預設 {DEFAULT_OUTPUT_DIR}）")
    p.add_argument("--config", default=None, help="channel_config.json 路徑（取 branding；預設讀專案根）")
    p.add_argument("--width", type=int, default=DEFAULT_WIDTH, help=f"影片寬（預設 {DEFAULT_WIDTH}）")
    p.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help=f"影片高（預設 {DEFAULT_HEIGHT}）")
    p.add_argument("--fps", type=int, default=DEFAULT_FPS, help=f"影格率（預設 {DEFAULT_FPS}）")
    p.add_argument("--no-subtitles", action="store_true", help="不燒字幕")
    p.add_argument("--dry-run", action="store_true", help="不產檔，只印段數/時長/字幕段數/預估輸出時長與檔案大小級距")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n[ABORT] 使用者中斷。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
