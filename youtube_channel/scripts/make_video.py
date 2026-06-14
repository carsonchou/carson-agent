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

# 預設背景漸層色盤（深色科技風，符合量化頻道調性）。RGB。
GRADIENT_TOP = (12, 18, 32)      # 深藍黑
GRADIENT_BOTTOM = (28, 44, 78)   # 靛藍

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

    dest = dest_dir / f"broll_{index:02d}.mp4"
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
    return dest


# --------------------------------------------------------------------------- #
# 字卡圖片產生（PIL，不靠 ImageMagick）
# --------------------------------------------------------------------------- #


def _load_font(size: int, bold: bool = False):
    """盡量載入一個支援中文的 TrueType 字型；可選粗體；失敗則回傳預設點陣字型。"""
    from PIL import ImageFont

    bold_first = [r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]  # Linux 粗體
    candidates = (bold_first if bold else []) + [
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


def pick_accent(seed: str):
    import hashlib
    h = int(hashlib.md5((seed or "x").encode("utf-8")).hexdigest(), 16)
    return ACCENT_PALETTE[h % len(ACCENT_PALETTE)]


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
    line_h = int(tsize("測", big_font)[1] * 1.42) or int(md * 0.11)
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
        draw.rounded_rectangle([bx2 - w - pad * 2, by2 - h - pad * 2, bx2, by2], radius=int(md * 0.012), fill=(255, 255, 255, 30))
        draw.text((bx2 - w - pad, by2 - h - pad - 2), watermark, fill=(228, 234, 247, 240), font=wm_font)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")
    return dest


def render_candle_card(width: int, height: int, *, big_text: str, watermark: str, accent, seed: str, dest: Path) -> Path:
    """靜態 K 線主視覺卡：滿版擬真 K 線圖 + 半透明面板大標 + 黃底線 + 浮水印，烤成單張 PNG（渲染快）。"""
    from PIL import ImageDraw

    img = _render_candles_strip(width, height, accent, seed).convert("RGB")  # 滿版 K 線
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
    line_h = int(tsize("測", big_font)[1] * 1.42) or int(md * 0.11)
    block_h = line_h * len(lines)
    bw = min(max((tsize(ln, big_font)[0] for ln in lines), default=10), max_w)
    px = (width - bw) // 2 - int(md * 0.05)
    py = (height - block_h) // 2 - int(md * 0.05)
    draw.rounded_rectangle([px, py, width - px, py + block_h + int(md * 0.10)],
                           radius=int(md * 0.03), fill=(8, 12, 24, 180))
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
        draw.rounded_rectangle([bx2 - w - pad * 2, by2 - h - pad * 2, bx2, by2], radius=int(md * 0.012), fill=(255, 255, 255, 30))
        draw.text((bx2 - w - pad, by2 - h - pad - 2), watermark, fill=(228, 234, 247, 240), font=wm_font)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")
    return dest


def render_concept_card(width: int, height: int, *, heading: str, narration: str,
                        watermark: str, accent, seed: str, dest: Path,
                        default_key: Optional[str] = None) -> Optional[Path]:
    """主題數據圖卡：依旁白選一張對得上的圖（網格/複利/回撤…），
    標題放頂部小條（不蓋圖），下方留給字幕。
    段落判不到主題時，改用 default_key（整支影片主題）；仍為 None 才回 None（退回 K 線卡）。"""
    if _concept is None:
        return None
    from PIL import ImageDraw
    text = f"{heading} {narration}"
    key = _concept.classify(text) or default_key
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
    for i, seg in enumerate(segments):
        clip = None
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

        body_clips.append(clip)

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

    intro_clip = _candle_segment(title, "intro", INTRO_DURATION)
    outro_clip = _candle_segment(branding.get("watermark_text", "感謝收看"), "outro", OUTRO_DURATION)

    # 主體拼接（覆蓋配音總長）
    body = concatenate_videoclips(body_clips, method="compose")

    # 字幕：燒在 body 上（body 時間軸 = 配音時間軸）
    if not no_subtitles:
        voice_text = read_voice_text(slug_paths)
        if not voice_text:
            voice_text = " ".join(s.narration for s in segments if s.narration).strip()
        units = split_subtitle_units(voice_text)
        cues = build_subtitle_cues(units, audio_duration)
        stats["subtitle_count"] = len(cues)
        if cues:
            sub_overlays = []
            for cue in cues:
                sub_png = _render_subtitle_image(width, height, cue.text, tmp_dir, accent=accent)
                if sub_png is None:
                    continue
                ov = (
                    ImageClip(str(sub_png))
                    .set_start(cue.start)
                    .set_duration(max(cue.end - cue.start, 0.1))
                    .set_position(("center", int(height * 0.80)))
                )
                sub_overlays.append(ov)
            if sub_overlays:
                body = CompositeVideoClip([body, *sub_overlays], size=(width, height))

    # 配上音訊（只在 body 段落，intro/outro 無聲）
    audio = AudioFileClip(str(slug_paths.audio))
    body = body.set_audio(audio).set_duration(audio_duration)

    final = concatenate_videoclips([intro_clip, body, outro_clip], method="compose")
    final = final.set_fps(fps)

    slug_paths.out_mp4.parent.mkdir(parents=True, exist_ok=True)

    # 寫出 H.264 mp4
    try:
        final.write_videofile(
            str(slug_paths.out_mp4),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            preset="veryfast",
            threads=os.cpu_count() or 4,
            bitrate="3500k",
            temp_audiofile=str(tmp_dir / "temp_audio.m4a"),
            remove_temp=True,
            logger=None,
        )
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

    fsize = max(30, min(int(height * 0.042), int(width * 0.060)))
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
    draw.rounded_rectangle([0, 0, iw - 1, ih - 1], radius=rad, fill=(8, 12, 24, 185),
                           outline=(accent[0], accent[1], accent[2], 150), width=max(2, int(fsize * 0.045)))

    y = pad_y
    for ln, (lw, _lh) in zip(lines, sizes):
        tx = (iw - lw) // 2
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (2, 2), (-2, -2)):
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
