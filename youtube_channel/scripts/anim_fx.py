# -*- coding: utf-8 -*-
"""Tier-2 電影級動畫原語：用 PIL 逐幀畫 → ffmpeg 編成 silent mp4 clip（與 _seg_clip 同規格，供 concat -c:v copy 無損併入）。

設計鐵則：
- 每個原語回傳一支 mp4 路徑；缺素材/任何例外一律回 None（呼叫端降級回靜態卡）。絕不拋例外中斷渲染。
- 輸出規格對齊 _seg_clip：libx264 / yuv420p / -r fps / WxH / 無音軌，才能被 concat demuxer -c:v copy 併入。
- 效能：底圖只畫一次，每幀只重繪會動的那層（數字/刀/縮放）再合成；字幕/浮水印/吉祥物逐幀合成。
"""
from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path

try:
    import make_video as mv
except Exception:  # noqa: BLE001
    mv = None

try:
    from PIL import Image, ImageDraw
except Exception:  # noqa: BLE001
    Image = None
    ImageDraw = None


# --------------------------------------------------------------------------- #
# 緩動函式
# --------------------------------------------------------------------------- #
def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else (hi if x > hi else x)


def _ease_out_back(t):
    """回彈過衝：0→1，中途衝過 1 再落回，做「彈出」感。"""
    t = _clamp(t)
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + c1 * (t - 1.0) ** 2


def _ease_out_cubic(t):
    t = _clamp(t)
    return 1.0 - (1.0 - t) ** 3


def _ease_in_out(t):
    t = _clamp(t)
    return 0.5 - 0.5 * math.cos(math.pi * t)


# --------------------------------------------------------------------------- #
# 共用：素材預備 + 逐幀合成 + 編碼
# --------------------------------------------------------------------------- #
def _prep_overlay(png_path):
    """讀一張 overlay PNG（字幕框/浮水印），裁掉透明留白，回 (Image, w, h) 或 None。"""
    try:
        im = Image.open(str(png_path)).convert("RGBA")
        return im, im.width, im.height
    except Exception:  # noqa: BLE001
        return None


def _prep_mascot(mascot_path, height):
    """讀吉祥物、裁透明邊、縮到 ~0.16H，回 Image 或 None。"""
    try:
        if not mascot_path or not Path(mascot_path).exists():
            return None
        m = Image.open(str(mascot_path)).convert("RGBA")
        bb = m.getchannel("A").getbbox()
        if bb:
            m = m.crop(bb)
        th = int(height * 0.16)
        if m.height <= 0:
            return None
        scale = th / m.height
        nw = max(1, int(m.width * scale))
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
        return m.resize((nw, th), resample)
    except Exception:  # noqa: BLE001
        return None


def _active_sub(subs, t):
    """回傳在段內相對時間 t（秒）該顯示的字幕 (Image,w,h)，無則 None。subs=[(png, ls, le)]（已預備成 tuple）。"""
    for entry in subs or []:
        _prep, ls, le = entry
        if _prep is not None and ls <= t < le:
            return _prep
    return None


def _composite_fixed(frame, *, subs_prepped, t, width, height, mascot_img=None, wm_prepped=None):
    """把固定層（字幕/吉祥物/浮水印）合成到單幀上。frame=RGBA Image（會被就地改）。"""
    # 吉祥物（右下，坐在底條之上）
    if mascot_img is not None:
        try:
            x = width - mascot_img.width - int(width * 0.015)
            y = height - mascot_img.height - int(height * 0.09)
            frame.alpha_composite(mascot_img, (x, y))
        except Exception:  # noqa: BLE001
            pass
    # 浮水印（右下角）
    if wm_prepped is not None:
        try:
            im, w, h = wm_prepped
            m = int(width * 0.022)
            frame.alpha_composite(im, (width - w - m, height - h - m))
        except Exception:  # noqa: BLE001
            pass
    # 字幕（底部置中，比照 _seg_clip 的 y=H*0.78-h）
    sub = _active_sub(subs_prepped, t)
    if sub is not None:
        try:
            frame.alpha_composite(sub, ((width - sub.width) // 2, int(height * 0.78) - sub.height))
        except Exception:  # noqa: BLE001
            pass
    return frame


def _encode(frames_dir, out, *, width, height, fps, ff):
    """把 frame_%05d.png 幀序列編成 silent mp4（對齊 _seg_clip 規格）。回 out 路徑或 None。
    編完（成功或失敗）即刪除該段幀 PNG 目錄，降低峰值磁碟（旗艦長片動畫幀多，防塞爆）。"""
    result = None
    try:
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
               "-framerate", str(fps), "-i", str(Path(frames_dir) / "frame_%05d.jpg"),
               "-an", "-vf", f"scale={width}:{height}:flags=lanczos,setsar=1",
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               "-r", str(fps), "-vsync", "cfr", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if r.returncode == 0 and Path(out).exists() and Path(out).stat().st_size > 0:
            result = str(out)
        else:
            print(f"[anim_fx] 編碼失敗：{r.stderr[-200:]}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[anim_fx] 編碼例外：{exc}", file=sys.stderr)
    finally:
        try:
            import shutil
            shutil.rmtree(frames_dir, ignore_errors=True)  # 清該段幀 PNG（mp4 已在 tmp_dir，保留供 concat）
        except Exception:  # noqa: BLE001
            pass
    return result


def _prep_subs(subs):
    """把 [(png, ls, le)] 預讀成 [(Image, ls, le)]，讀不到的丟掉。"""
    out = []
    for entry in (subs or []):
        try:
            png, ls, le = entry
            im = Image.open(str(png)).convert("RGBA")
            out.append((im, ls, le))
        except Exception:  # noqa: BLE001
            continue
    return out


def _new_frames_dir(tmp_dir, idx):
    d = Path(tmp_dir) / f"anim_{idx:03d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_frame(canvas, fdir, fi):
    """存單幀為 JPEG（編碼比 PNG 快 3-5x，降低逐幀 I/O 瓶頸；中間幀最終由 ffmpeg 重編成 h264，q90 無感）。"""
    canvas.convert("RGB").save(str(Path(fdir) / f"frame_{fi:05d}.jpg"), "JPEG", quality=90)


# --------------------------------------------------------------------------- #
# A. 字卡彈出 + 緩推鏡（universal：吃現有卡片 PNG，每片受惠）
# --------------------------------------------------------------------------- #
def card_popup_clip(card_png, *, dur, subs, width, height, fps, tmp_dir, idx,
                    watermark_png=None, pop=True) -> str | None:
    """把一張現成卡片 PNG（已含背景/標題/吉祥物/浮水印）做「放大回彈彈出 + 緩推鏡」，逐幀合字幕。
    pop=False 時只做緩推鏡（intro/outro 或不想彈的段）。任何失敗回 None。"""
    if Image is None:
        return None
    try:
        base = Image.open(str(card_png)).convert("RGBA")
        if base.size != (width, height):
            base = base.resize((width, height))
        frames = max(1, int(round(dur * fps)))
        subs_p = _prep_subs(subs)
        wm_p = _prep_overlay(watermark_png) if watermark_png else None
        fdir = _new_frames_dir(tmp_dir, idx)
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
        pop_frames = min(frames, max(1, int(0.42 * fps)))  # 彈出時長 ~0.42s
        for fi in range(frames):
            t = fi / fps
            if pop and fi < pop_frames:
                p = fi / max(1, pop_frames)
                scale = 0.70 + (_ease_out_back(p)) * 0.30   # 0.70→~1.0（含過衝）
                alpha = _ease_out_cubic(p)
            else:
                # 緩推鏡：1.0→1.05 線性微推
                q = (fi - (pop_frames if pop else 0)) / max(1, frames - (pop_frames if pop else 0))
                scale = 1.0 + 0.05 * _clamp(q)
                alpha = 1.0
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
            nw, nh = max(1, int(width * scale)), max(1, int(height * scale))
            layer = base.resize((nw, nh), resample)
            if alpha < 1.0:
                a = layer.getchannel("A").point(lambda v: int(v * alpha))
                layer.putalpha(a)
            ox, oy = (width - nw) // 2, (height - nh) // 2
            canvas.alpha_composite(layer, (ox, oy))
            _composite_fixed(canvas, subs_prepped=subs_p, t=t, width=width, height=height, wm_prepped=wm_p)
            _save_frame(canvas, fdir, fi)
        return _encode(fdir, Path(tmp_dir) / f"piece_anim_{idx:03d}.mp4",
                       width=width, height=height, fps=fps, ff=_ff())
    except Exception as exc:  # noqa: BLE001
        print(f"[anim_fx] card_popup 例外：{exc}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# 共用：暗金底 + 吉祥物預備
# --------------------------------------------------------------------------- #
def _base_bg(width, height, accent, seed):
    """暗金底（重用 make_video._card_background），失敗回純深色。回 RGBA Image。"""
    try:
        return mv._card_background(width, height, accent, seed=seed).convert("RGBA")
    except Exception:  # noqa: BLE001
        return Image.new("RGBA", (width, height), (10, 14, 26, 255))


def _fit_font(text, max_w, start, min_size, bold=True):
    """自適應字級不爆框。"""
    size = start
    while size > min_size:
        f = mv._load_font(size, bold=bold)
        try:
            tmp = Image.new("RGBA", (10, 10))
            b = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=f, stroke_width=int(size * 0.04))
            if (b[2] - b[0]) <= max_w:
                return f, b
        except Exception:  # noqa: BLE001
            return f, None
        size = int(size * 0.9)
    return mv._load_font(min_size, bold=bold), None


# --------------------------------------------------------------------------- #
# B. 數字爆現 smash（HOOK/神話數字）
# --------------------------------------------------------------------------- #
def number_smash_clip(number, *, dur, subs, width, height, fps, accent, seed, tmp_dir, idx,
                      mascot_png=None, watermark_png=None, debunk=False, sub_label=None) -> str | None:
    """巨大數字快速放大過衝 + 微震 + 光暈脈衝；debunk 片後半轉紅。逐幀合字幕/吉祥物。失敗回 None。"""
    if Image is None or mv is None or not number:
        return None
    try:
        bg = _base_bg(width, height, accent, seed)
        frames = max(1, int(round(dur * fps)))
        subs_p = _prep_subs(subs)
        wm_p = _prep_overlay(watermark_png) if watermark_png else None
        mas = _prep_mascot(mascot_png, height)
        fdir = _new_frames_dir(tmp_dir, idx)
        # 數字圖層只畫一次（滿版透明），之後每幀縮放/位移/變色
        num_font, _ = _fit_font(number, int(width * 0.82), int(height * 0.30), 60, bold=True)
        # 量測
        tmp = Image.new("RGBA", (10, 10))
        nb = ImageDraw.Draw(tmp).textbbox((0, 0), number, font=num_font, stroke_width=max(4, int(height * 0.008)))
        nw, nh = nb[2] - nb[0], nb[3] - nb[1]
        gold = (255, 205, 66)
        red = (255, 84, 84)
        smash_frames = min(frames, max(1, int(0.34 * fps)))
        rng_seed = sum(ord(c) for c in (seed or "x"))
        for fi in range(frames):
            t = fi / fps
            canvas = bg.copy()
            d = ImageDraw.Draw(canvas)
            if fi < smash_frames:
                p = fi / max(1, smash_frames)
                scale = 0.30 + _ease_out_back(p) * 0.75      # 0.30→~1.0（過衝到 ~1.1）
                shake = int((1 - p) * height * 0.02)
                sx = ((rng_seed + fi * 7) % 5 - 2) * shake // 2
                sy = ((rng_seed + fi * 13) % 5 - 2) * shake // 2
            else:
                scale = 1.0
                sx = sy = 0
            col = gold
            if debunk and fi >= frames * 0.5:
                col = red
            # 畫到一張暫圖再縮放，位置置中
            layer = Image.new("RGBA", (max(1, nw + 40), max(1, nh + 40)), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            sw = max(4, int(height * 0.008))
            ld.text((20 - nb[0], 20 - nb[1]), number, font=num_font, fill=col + (255,),
                    stroke_width=sw, stroke_fill=(60, 42, 0, 255) if col == gold else (70, 0, 0, 255))
            lw, lh = layer.size
            ns = max(1, int(lw * scale)), max(1, int(lh * scale))
            layer = layer.resize(ns, getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC))
            lx = (width - layer.width) // 2 + sx
            ly = int(height * 0.34) + sy
            # 光暈脈衝（數字後方）
            if fi < smash_frames:
                gp = _ease_out_cubic(fi / max(1, smash_frames))
                rr = int(min(width, height) * (0.18 + 0.12 * gp))
                gl = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                gd = ImageDraw.Draw(gl)
                cx, cy = width // 2, int(height * 0.34) + layer.height // 2
                gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                           fill=(col[0], col[1], col[2], int(40 * (1 - gp))))
                canvas.alpha_composite(gl)
            canvas.alpha_composite(layer, (lx, ly))
            # 小標（如「他吹的神話」）在數字上方
            if sub_label:
                lf = mv._load_font(int(height * 0.045), bold=True)
                lb = d.textbbox((0, 0), sub_label, font=lf)
                d.text(((width - (lb[2] - lb[0])) // 2, int(height * 0.24)), sub_label,
                       font=lf, fill=(170, 180, 200, 255))
            _composite_fixed(canvas, subs_prepped=subs_p, t=t, width=width, height=height,
                             mascot_img=mas, wm_prepped=wm_p)
            _save_frame(canvas, fdir, fi)
        return _encode(fdir, Path(tmp_dir) / f"piece_anim_{idx:03d}.mp4",
                       width=width, height=height, fps=fps, ff=_ff())
    except Exception as exc:  # noqa: BLE001
        print(f"[anim_fx] number_smash 例外：{exc}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# C. 紅刀劃數字（《拆穿》招牌）
# --------------------------------------------------------------------------- #
def knife_slash_clip(number, *, dur, subs, width, height, fps, accent, seed, tmp_dir, idx,
                     mascot_png=None, watermark_png=None, sub_label=None) -> str | None:
    """金色數字，紅刀由左下→右上劃過（progress 0→1），刀過處數字變暗+刀光。失敗回 None。

    🔴 2026-07-30 `sub_label` 預設值原本寫死成「他吹的神話」,已改成 None。
    為什麼:那句話是在斷言**某個外部的人講過這個數字**。而 render_ffmpeg 呼叫本函式時
    **根本沒傳這個參數**(見 render_ffmpeg.py 的 knife 分支)→ 一路吃預設值,
    等於每支 debunk 片都印,連「到底有沒有外部宣稱」都沒判斷過。
    更關鍵:這裡的 number 是 detect_fx 用 _MYTH_RE 從**我們自己的 heading/narration**
    抓的第一個帶 %／倍 的數字——本頻道旁白全部由自家 fact_key 產生,不可能是別人的宣稱。
    同型事故:縮圖把自家回測結果 824% 印成「他吹的神話」劃紅刀(commit f0e4138 已修);
    以及 _draw_vertical_card 預設值寫死憑空印績效。**捏造性文字不可以是預設值。**
    要印就由呼叫端明確傳入,且該處必須自己保證那真的是外部宣稱。
    """
    if Image is None or mv is None or not number:
        return None
    try:
        bg = _base_bg(width, height, accent, seed)
        frames = max(1, int(round(dur * fps)))
        subs_p = _prep_subs(subs)
        wm_p = _prep_overlay(watermark_png) if watermark_png else None
        mas = _prep_mascot(mascot_png, height)
        fdir = _new_frames_dir(tmp_dir, idx)
        num_font, _ = _fit_font(number, int(width * 0.66), int(height * 0.26), 60, bold=True)
        tmp = Image.new("RGBA", (10, 10))
        sw = max(4, int(height * 0.008))
        nb = ImageDraw.Draw(tmp).textbbox((0, 0), number, font=num_font, stroke_width=sw)
        nw, nh = nb[2] - nb[0], nb[3] - nb[1]
        cx, cy = width // 2, int(height * 0.42)
        nx, ny = cx - nw // 2, cy - nh // 2
        gold = (255, 205, 66)
        # 刀路：左下 → 右上，通過數字中心
        x0, y0 = int(cx - nw * 0.75), int(cy + nh * 0.9)
        x1, y1 = int(cx + nw * 0.75), int(cy - nh * 0.9)
        slash_start, slash_end = int(frames * 0.28), int(frames * 0.62)
        for fi in range(frames):
            t = fi / fps
            canvas = bg.copy()
            d = ImageDraw.Draw(canvas)
            if sub_label:
                lf = mv._load_font(int(height * 0.045), bold=True)
                lb = d.textbbox((0, 0), sub_label, font=lf)
                d.text(((width - (lb[2] - lb[0])) // 2, int(height * 0.20)), sub_label,
                       font=lf, fill=(170, 180, 200, 255))
            # 刀過後數字變暗
            p = _clamp((fi - slash_start) / max(1, slash_end - slash_start))
            cut = p >= 0.5
            num_col = (150, 120, 40, 255) if cut else gold + (255,)
            d.text((nx - nb[0], ny - nb[1]), number, font=num_font, fill=num_col,
                   stroke_width=sw, stroke_fill=(60, 42, 0, 255))
            # 裂痕（刀過半後）
            if cut:
                d.line([(nx, cy + int(nh * 0.1)), (nx + nw, cy - int(nh * 0.1))],
                       fill=(20, 22, 30, 200), width=max(3, int(height * 0.006)))
            # 紅刀（progress 內才畫，畫到目前進度）
            if slash_start <= fi <= frames:
                pp = _clamp((fi - slash_start) / max(1, slash_end - slash_start))
                ex = int(x0 + (x1 - x0) * pp)
                ey = int(y0 + (y1 - y0) * pp)
                d.line([(x0, y0), (ex, ey)], fill=(236, 44, 44, 255), width=max(6, int(height * 0.014)))
                d.line([(x0, y0), (ex, ey)], fill=(255, 255, 255, 210), width=max(2, int(height * 0.004)))
                # 刀尖光點
                gr = max(4, int(height * 0.012))
                d.ellipse([ex - gr, ey - gr, ex + gr, ey + gr], fill=(255, 255, 255, 230))
            _composite_fixed(canvas, subs_prepped=subs_p, t=t, width=width, height=height,
                             mascot_img=mas, wm_prepped=wm_p)
            _save_frame(canvas, fdir, fi)
        return _encode(fdir, Path(tmp_dir) / f"piece_anim_{idx:03d}.mp4",
                       width=width, height=height, fps=fps, ff=_ff())
    except Exception as exc:  # noqa: BLE001
        print(f"[anim_fx] knife_slash 例外：{exc}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# D. montage 快切（列舉/轉場段）
# --------------------------------------------------------------------------- #
def montage_clip(items, *, dur, subs, width, height, fps, accent, seed, tmp_dir, idx,
                 mascot_png=None, watermark_png=None, hold=0.42) -> str | None:
    """N 張子卡（大字項目）在節拍上硬切，逐幀合字幕。items 為字串列表。失敗回 None。"""
    if Image is None or mv is None or not items:
        return None
    try:
        items = [str(x).strip() for x in items if str(x).strip()][:6] or ["…"]
        frames = max(1, int(round(dur * fps)))
        subs_p = _prep_subs(subs)
        wm_p = _prep_overlay(watermark_png) if watermark_png else None
        mas = _prep_mascot(mascot_png, height)
        fdir = _new_frames_dir(tmp_dir, idx)
        hold_frames = max(1, int(hold * fps))
        # 預畫每個項目的底卡（含大字），之後只做輕微縮放脈衝
        cards = []
        for k, it in enumerate(items):
            c = _base_bg(width, height, accent, f"{seed}_{k}")
            d = ImageDraw.Draw(c)
            f, b = _fit_font(it, int(width * 0.82), int(height * 0.22), 60, bold=True)
            bb = d.textbbox((0, 0), it, font=f, stroke_width=max(3, int(height * 0.006)))
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            d.text(((width - tw) // 2 - bb[0], int(height * 0.40) - bb[1]), it, font=f,
                   fill=(238, 244, 253, 255), stroke_width=max(3, int(height * 0.006)),
                   stroke_fill=(6, 9, 15, 255))
            # 強調底線
            d.rectangle([(width - tw) // 2, int(height * 0.40) + th + 14,
                         (width + tw) // 2, int(height * 0.40) + th + 24], fill=accent + (255,))
            cards.append(c)
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
        for fi in range(frames):
            t = fi / fps
            k = (fi // hold_frames) % len(cards)
            local = (fi % hold_frames) / max(1, hold_frames)
            scale = 1.0 + 0.03 * (1 - local)   # 每張切入時微微一頓
            base = cards[k]
            if abs(scale - 1.0) > 1e-3:
                nw, nh = int(width * scale), int(height * scale)
                lay = base.resize((nw, nh), resample)
                canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
                canvas.alpha_composite(lay, ((width - nw) // 2, (height - nh) // 2))
            else:
                canvas = base.copy()
            _composite_fixed(canvas, subs_prepped=subs_p, t=t, width=width, height=height,
                             mascot_img=mas, wm_prepped=wm_p)
            _save_frame(canvas, fdir, fi)
        return _encode(fdir, Path(tmp_dir) / f"piece_anim_{idx:03d}.mp4",
                       width=width, height=height, fps=fps, ff=_ff())
    except Exception as exc:  # noqa: BLE001
        print(f"[anim_fx] montage 例外：{exc}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# ffmpeg 路徑（與 render_ffmpeg 一致）
# --------------------------------------------------------------------------- #
def _ff():
    import os
    try:
        import render_ffmpeg as rf
        return rf._ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return os.environ.get("IMAGEIO_FFMPEG_EXE") or "ffmpeg"


# --------------------------------------------------------------------------- #
# 特效意圖判定
# --------------------------------------------------------------------------- #
_MYTH_RE = re.compile(r"[\d０-９]+[\d,\.]*\s*[%％倍萬趴]|[一二三四五六七八九十百千兩]+\s*[%倍萬成趴]")
_LIST_RE = re.compile(r"[A-Za-z0-9]{2,}(?:、|，|/)[A-Za-z0-9一-鿿]{1,}(?:、|，|/)")


def detect_fx(heading, narration, *, is_debunk=False, explicit=None):
    """回傳 (fx, payload)。fx ∈ popup/smash/knife/montage。payload 視 fx 而定。"""
    text = f"{heading or ''} {narration or ''}"
    if explicit in ("smash", "knife", "montage", "popup"):
        fx = explicit
    else:
        fx = None
        # 列舉（頓號分隔 ≥2 個項目）→ montage
        if _LIST_RE.search(text) or text.count("、") >= 2:
            fx = "montage"
        elif _MYTH_RE.search(text):
            fx = "knife" if is_debunk else "smash"
        else:
            fx = "popup"
    payload = None
    if fx in ("smash", "knife"):
        m = _MYTH_RE.search(text)
        payload = (m.group(0).replace(" ", "") if m else None)
        if not payload:
            fx = "popup"
    elif fx == "montage":
        # 抽頓號/逗號/斜線分隔的短項目（用真正含分隔符的那個來源，標題沒有就用旁白）
        src = heading if re.search(r"[、，/]", heading or "") else (narration or heading or "")
        items = [x.strip() for x in re.split(r"[、，/]", src) if x.strip()]
        items = [x for x in items if 1 <= len(x) <= 8][:6]
        if len(items) < 2:
            fx = "popup"
        payload = items
    return fx, payload
