#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yt_transcript.py — 抓 YouTube 影片逐字稿（字幕），讓 Claude 能「讀懂」影片內容。

用法：
  python scripts/yt_transcript.py <YouTube 連結或影片ID>
  python scripts/yt_transcript.py https://youtu.be/FDNLTE-OK_I

優先用 youtube-transcript-api（快、乾淨），失敗退 yt-dlp 抓自動字幕。
語言偏好：繁中 → 簡中 → 英文 → 任何可得。純視覺/無字幕影片抓不到（會誠實說）。
"""
from __future__ import annotations

import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LANG_PREF = ["zh-Hant", "zh-TW", "zh-Hans", "zh", "zh-CN", "en", "en-US"]


def video_id(s: str) -> str:
    s = s.strip()
    m = re.search(r"(?:v=|/shorts/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    return s


def _seg_text(seg):
    t = getattr(seg, "text", None)
    if t is None and isinstance(seg, dict):
        t = seg.get("text")
    return (t or "").replace("\n", " ")


def via_api(vid: str):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        ytt = YouTubeTranscriptApi()
        fetched, lang = None, "?"
        # 先依語言偏好直接抓
        try:
            fetched = ytt.fetch(vid, languages=LANG_PREF)
            lang = getattr(fetched, "language_code", "?")
        except Exception:
            # 退而求其次：列出所有字幕，挑偏好或第一個
            tl = ytt.list(vid)
            tr = None
            for code in LANG_PREF:
                try:
                    tr = tl.find_transcript([code]); break
                except Exception:
                    continue
            if tr is None:
                for t in tl:
                    tr = t; break
            if tr is None:
                return None, "無可用字幕"
            fetched = tr.fetch()
            lang = getattr(tr, "language_code", "?")
        segs = getattr(fetched, "snippets", fetched)
        text = " ".join(_seg_text(s) for s in segs if _seg_text(s))
        return (lang, text), None
    except Exception as e:  # noqa: BLE001
        return None, f"api 失敗：{e}"


def via_ytdlp(vid: str):
    try:
        import tempfile, os, glob
        import yt_dlp
        d = tempfile.mkdtemp()
        opts = {
            "skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": LANG_PREF + ["zh.*", "en.*"], "subtitlesformat": "vtt",
            "outtmpl": os.path.join(d, "%(id)s.%(ext)s"), "quiet": True, "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={vid}"])
        vtts = glob.glob(os.path.join(d, "*.vtt"))
        if not vtts:
            return None, "yt-dlp 找不到字幕"
        # 依語言偏好挑檔
        vtts.sort(key=lambda p: next((i for i, c in enumerate(LANG_PREF) if c in os.path.basename(p)), 99))
        raw = open(vtts[0], encoding="utf-8", errors="replace").read()
        # 清掉 vtt 時間軸/標記
        lines = []
        for ln in raw.splitlines():
            if "-->" in ln or ln.strip().isdigit() or ln.startswith(("WEBVTT", "Kind:", "Language:")) or not ln.strip():
                continue
            ln = re.sub(r"<[^>]+>", "", ln)
            lines.append(ln.strip())
        # 去連續重複（自動字幕常重複）
        out, prev = [], None
        for ln in lines:
            if ln != prev:
                out.append(ln); prev = ln
        lang = next((c for c in LANG_PREF if c in os.path.basename(vtts[0])), "?")
        return (lang, " ".join(out)), None
    except Exception as e:  # noqa: BLE001
        return None, f"yt-dlp 失敗：{e}"


def get_transcript(url_or_id: str):
    vid = video_id(url_or_id)
    res, err = via_api(vid)
    if res:
        return vid, res[0], res[1]
    res2, err2 = via_ytdlp(vid)
    if res2:
        return vid, res2[0], res2[1]
    return vid, None, f"{err}；{err2}"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python scripts/yt_transcript.py <YouTube 連結或ID>", file=sys.stderr)
        return 2
    vid, lang, text = get_transcript(sys.argv[1])
    if not text:
        print(f"[無字幕] {vid}：{lang}\n（此影片可能無字幕，或純視覺演示型，逐字稿抓不到。）")
        return 1
    print(f"=== 逐字稿 [{vid}] 語言={lang} 字數≈{len(text)} ===\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
