#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_mascot.py — 用 Google Gemini 生圖生「量化阿森」吉祥物(hero + 4 表情,同一隻)。

一次性工具(非產線 cron)。流程:
  1) 生 hero(neutral)定裝圖 → 存 raw
  2) 用 hero 當參考圖(image editing)生 happy/panic/smug → 保證同一隻
  3) 去背成透明 → 裁 1024² → 存 assets/mascot/{neutral,happy,panic,smug}.png
  4) 頭部特寫 → assets/brand/logo.png

需要 GEMINI_API_KEY(env 或 youtube_channel/.env)。絕不印出金鑰。
用法:
  python scripts/gen_mascot.py                 # 全生(hero+4表情+logo)
  python scripts/gen_mascot.py --only neutral  # 只生 hero 定裝(先看造型)
  python scripts/gen_mascot.py --expr happy    # 用現有 hero 只重生某表情(回迭)
  python scripts/gen_mascot.py --raw-only      # 只生原圖不去背(檢查用)
"""
from __future__ import annotations
import argparse, base64, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
MASCOT = ASSETS / "mascot"
BRAND = ASSETS / "brand"
RAW = MASCOT / "_raw"          # 原圖(未去背)留存,回迭/logo 裁切用
for d in (MASCOT, BRAND, RAW):
    d.mkdir(parents=True, exist_ok=True)

# 候選生圖模型(要「最好」→ 先試 gemini-3-pro-image,依序退)
IMAGE_MODELS = [
    os.environ.get("GEMINI_IMAGE_MODEL", "").strip() or "gemini-3-pro-image",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image",
]
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# ---- 角色設定(base identity,每次都帶,確保同一隻)----
BASE_IDENTITY = (
    'A cute but professional mascot character named "Quant Arsen": a small rounded-square '
    "robot with a glossy dark gunmetal-and-matte-black metallic body, subtle brushed-metal "
    "texture, restrained thin gold trim edges (hex d4af37), a glowing circular arc-reactor "
    "core in the center of its chest, two expressive glowing eyes, a small antenna on top of "
    "its head. Semi-3D glossy render, soft studio rim lighting, premium dark high-end look, "
    "glow is tasteful and NOT harsh. Centered, full body, front view, plain flat solid "
    "#0b0d12 near-black background, generous even margin around the character. Mascot logo "
    "style, clean, no text, no watermark."
)
HERO_PROMPT = BASE_IDENTITY + (
    " Expression: calm neutral, eyes level and steady, arc-reactor core glowing a calm "
    "cyan-teal. Composed, trustworthy, approachable."
)
EDIT_PREFIX = (
    "Using the provided reference image of the mascot, keep the SAME EXACT character — "
    "identical body shape, colors, proportions, materials, camera angle and the same plain "
    "flat #0b0d12 background. ONLY change the following: "
)
# 每個表情的差異描述(clause);gemini 走圖編輯用 EDIT_PREFIX+clause,pollinations 走 BASE_IDENTITY+clause
EXPR_CLAUSE = {
    "happy": ("happy confident expression, eyes curved into a warm smile, a slight upward tilt "
              "of the head, arc-reactor core glowing bright green, a faint upward spark."),
    "panic": ("worried panic expression, eyes wide open, one small cartoon sweat-drop symbol "
              "beside the head, arc-reactor core glowing alarm red, a slightly tense posture."),
    "smug": ("smug vindicated cocky expression, eyes half-lidded and confident, a tiny tilt of "
             "the head, arms crossed, arc-reactor core glowing rich warm gold."),
}
SEED = int(os.environ.get("MASCOT_SEED", "77"))  # 固定 seed → 同一隻;回迭想換造型就換這個
BG_RGB = (0x0b, 0x0d, 0x12)


def _expr_prompt(name: str, editing: bool) -> str:
    clause = EXPR_CLAUSE[name]
    if editing:  # gemini 圖編輯:帶 EDIT_PREFIX + 只講差異
        return EDIT_PREFIX + clause + " Everything else identical."
    return BASE_IDENTITY + " Expression: " + clause + " Same character design as the neutral version."


def _key() -> str:
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not k:
        envf = ROOT / ".env"
        if envf.exists():
            for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
                ln = ln.strip()
                if ln.startswith("GEMINI_API_KEY"):
                    k = ln.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not k:
        print("[FATAL] 無 GEMINI_API_KEY(env 或 .env)。到 aistudio.google.com/apikey 申請。", file=sys.stderr)
        sys.exit(2)
    return k


BACKEND = os.environ.get("MASCOT_BACKEND", "pollinations").strip().lower()  # pollinations(免費) / gemini(需billing)


def _gen_pollinations(prompt: str, seed: int) -> bytes:
    """免費 Flux 生圖(無金鑰)。text-to-image,靠固定 seed + 一致角色描述維持同一隻。"""
    import requests, urllib.parse
    enc = urllib.parse.quote(prompt, safe="")
    url = (f"https://image.pollinations.ai/prompt/{enc}"
           f"?width=1024&height=1024&seed={seed}&nologo=true&model=flux&enhance=true")
    r = requests.get(url, timeout=180)
    if r.status_code != 200 or not r.content or len(r.content) < 2000:
        raise RuntimeError(f"pollinations HTTP {r.status_code} len={len(r.content)}")
    return r.content


def _gen_image(prompt: str, ref_png: bytes | None = None, seed: int = 7) -> bytes:
    """生圖,回 PNG/JPEG bytes。免費走 pollinations,gemini 走付費圖模。"""
    if BACKEND == "pollinations":
        return _gen_pollinations(prompt, seed)
    import requests
    key = _key()
    parts = [{"text": prompt}]
    if ref_png is not None:
        parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(ref_png).decode()}})
    body = {"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    last_err = ""
    for model in [m for m in IMAGE_MODELS if m]:
        url = f"{API_BASE}/{model}:generateContent?key={key}"
        try:
            r = requests.post(url, json=body, timeout=120)
            if r.status_code != 200:
                last_err = f"{model} HTTP {r.status_code}: {r.text[:180]}"
                continue
            j = r.json()
            for cand in j.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    inline = part.get("inline_data") or part.get("inlineData")
                    if inline and inline.get("data"):
                        return base64.b64decode(inline["data"])
            last_err = f"{model}: 回應無圖(可能被安全擋)。{json.dumps(j)[:180]}"
        except Exception as ex:  # noqa: BLE001
            last_err = f"{model}: {ex}"
    raise RuntimeError(f"生圖失敗(全部模型)。最後錯誤:{last_err}")


def _cutout(png_bytes: bytes):
    """去背成 RGBA。優先 rembg,否則對已知純色背景做邊界洪水填充。"""
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    # 1) rembg(若裝了)
    try:
        from rembg import remove  # type: ignore
        out = remove(img)
        return out.convert("RGBA")
    except Exception:
        pass
    # 2) 邊界顏色鍵去背(背景是 prompt 指定的 #0b0d12 近黑純色)
    from collections import deque
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()
    tol = 42

    def near_bg(r, g, b):
        return abs(r - BG_RGB[0]) <= tol and abs(g - BG_RGB[1]) <= tol and abs(b - BG_RGB[2]) <= tol

    seen = bytearray(w * h)
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            dq.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            dq.append((x, y))
    while dq:
        x, y = dq.popleft()
        if x < 0 or y < 0 or x >= w or y >= h or seen[y * w + x]:
            continue
        r, g, b, a = px[x, y]
        if not near_bg(r, g, b):
            continue
        seen[y * w + x] = 1
        px[x, y] = (r, g, b, 0)
        dq.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
    return img


def _fit_1024(img):
    """置中 pad/縮到 1024² 透明,依 alpha bbox 裁切留邊。"""
    from PIL import Image
    img = img.convert("RGBA")
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    S, margin = 1024, 0.90
    w, h = img.size
    scale = (S * margin) / max(w, h)
    img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    canvas.alpha_composite(img, ((S - img.width) // 2, (S - img.height) // 2))
    return canvas


def _save(img, path: Path):
    img.save(path, "PNG")
    print(f"[save] {path.relative_to(ROOT)}  ({img.size[0]}x{img.size[1]})")


def _make_logo(neutral_raw: bytes):
    """從 hero 原圖裁頭部特寫當 logo。"""
    from PIL import Image
    import io
    cut = _cutout(neutral_raw)
    bbox = cut.getbbox()
    if not bbox:
        return
    cut = cut.crop(bbox)
    w, h = cut.size
    head = cut.crop((0, 0, w, int(h * 0.55)))  # 上半=頭
    head = _fit_1024(head).resize((512, 512), Image.LANCZOS)
    _save(head, BRAND / "logo.png")


def gen_hero() -> bytes:
    print(f"[gen] hero (neutral) via {BACKEND} seed={SEED} ...")
    raw = _gen_image(HERO_PROMPT, seed=SEED)
    (RAW / "neutral.png").write_bytes(raw)
    _save(_fit_1024(_cutout(raw)), MASCOT / "neutral.png")
    return raw


def gen_expr(name: str, hero_raw: bytes):
    editing = BACKEND == "gemini"
    print(f"[gen] {name} via {BACKEND} ...")
    prompt = _expr_prompt(name, editing)
    raw = _gen_image(prompt, ref_png=hero_raw if editing else None, seed=SEED)
    (RAW / f"{name}.png").write_bytes(raw)
    _save(_fit_1024(_cutout(raw)), MASCOT / f"{name}.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["neutral"], help="只生 hero 定裝")
    ap.add_argument("--expr", choices=list(EXPR_CLAUSE), help="用現有 hero 只重生某表情")
    ap.add_argument("--raw-only", action="store_true", help="只生原圖不去背")
    a = ap.parse_args()

    if a.raw_only:
        raw = _gen_image(HERO_PROMPT)
        (RAW / "neutral.png").write_bytes(raw)
        print(f"[raw] {(RAW/'neutral.png').relative_to(ROOT)}")
        return

    if a.expr:
        hero_raw = (RAW / "neutral.png").read_bytes()
        gen_expr(a.expr, hero_raw)
        return

    hero_raw = gen_hero()
    if a.only == "neutral":
        _make_logo(hero_raw)
        print("[done] hero + logo(先看造型,滿意再全生)")
        return

    for name in ("happy", "panic", "smug"):
        time.sleep(1)
        gen_expr(name, hero_raw)
    _make_logo(hero_raw)
    print("[done] hero + 4 表情 + logo 全生完成 → assets/mascot/, assets/brand/logo.png")


if __name__ == "__main__":
    main()
