#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ig_reels_upload.py — 把一支 Shorts 發到 Instagram Reels(免費直連 Graph API)。

流程：建立 media container(REELS, video_url) → 輪詢處理完成 → media_publish 發布。
IG 從『公開 video_url』抓影片，所以要有能公開存取的網址。
主路徑：把 mp4/封面直接上傳到 litterbox(catbox 的免帳號臨時檔案空間,72h 自動清)拿公網直鏈,
        不靠本機 fileserver + 免費 cloudflared tunnel(那條 quick-tunnel 天生不穩,常掉線→IG 停更)。
備援：litterbox 失敗才退回舊的 VIDEO_BASE(本機 fileserver + tunnel)路徑。
需 .env：IG_USER_ID、IG_ACCESS_TOKEN；可選 IG_VIDEO_BASE(備援用,預設 http://<主機IP>:8888)。

用法：python scripts/ig_reels_upload.py <slug>
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
GRAPH = "https://graph.instagram.com/v21.0"


def _load_env():
    """直跑時把專案根 .env 併進 os.environ(cron 由 local_cron 載;直跑沒有→IG token 找不到)。"""
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
UID = os.environ.get("IG_USER_ID", "").strip()
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()


def _read_tunnel_base() -> str:
    """環境變數沒設 IG_VIDEO_BASE 時,退讀 tunnel_up.py 寫的公網 URL。讀不到回空字串。"""
    try:
        d = json.loads((ROOT / "STUDIO" / "tunnel_url.json").read_text(encoding="utf-8"))
        return str(d.get("base", "")).rstrip("/")
    except Exception:
        return ""


VIDEO_BASE = (os.environ.get("IG_VIDEO_BASE", "").rstrip("/") or _read_tunnel_base())
try:
    sys.path.insert(0, str(ROOT / "scripts"))
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass

TUNNEL_STALE_SEC = 3600  # tunnel_url.json 超過此秒數沒更新 = 可疑(免費 quick-tunnel 常掉線)


def tunnel_healthy(check_url: str | None = None) -> bool:
    """發布前驗公網可達:免費 cloudflared quick-tunnel 是 ephemeral,掉線/換 URL 後
    tunnel_url.json 指向死網址,不驗就硬打 IG 會發布失敗(近24h≥12次的根因)。
    走 tunnel_url.json 的情況多驗一層新鮮度(ts 太舊視為可疑);check_url 不給就驗 VIDEO_BASE 本身。"""
    if not VIDEO_BASE:
        return False
    if not os.environ.get("IG_VIDEO_BASE"):  # 手動指定的 IG_VIDEO_BASE 不受 tunnel 新鮮度限制
        try:
            ts = json.loads((ROOT / "STUDIO" / "tunnel_url.json").read_text(encoding="utf-8")).get("ts", 0)
            if time.time() - float(ts) > TUNNEL_STALE_SEC:
                return False
        except Exception:
            return False
    url = check_url or VIDEO_BASE
    try:
        r = requests.head(url, timeout=8, allow_redirects=True)
        if r.status_code >= 500:  # 5xx(含 Cloudflare 530=tunnel 死)才退 GET 再確認一次
            r = requests.get(url, timeout=8, stream=True)
        # 關鍵:fileserver 對根路徑/非影片路徑回 403/404=它有回應=tunnel 通;
        # 只有 5xx(502/503/504/530 tunnel 掉線)或連不上(except)才算不通。別把自家 403 誤判成 tunnel 死。
        return r.status_code < 500
    except Exception:
        return False


LITTERBOX_API = "https://litterbox.catbox.moe/resources/internals/api.php"


def litterbox_reachable(timeout: float = 6.0) -> bool:
    """輕量連線檢查(不做完整上傳測試):litterbox 網域可達就當作『可走 litterbox 路徑』。
    給 ig_backfill 開批前當閘門用,取代舊的 tunnel_healthy(litterbox 路徑不該被 tunnel 死活拖累)。"""
    try:
        r = requests.head("https://litterbox.catbox.moe/", timeout=timeout, allow_redirects=True)
        if r.status_code >= 500:
            r = requests.get("https://litterbox.catbox.moe/", timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def _upload_filehost(local_path: Path, retries: int = 2) -> str | None:
    """把本地檔案上傳到 litterbox(catbox 免帳號臨時版,72h 自動清)拿公網直鏈。
    免 tunnel:不穩的免費 cloudflared quick-tunnel 是近 24h IG 停更主因,改直接把檔案丟到
    公網檔案空間,IG container 建立當下抓一次就夠,不需要長期在線的 URL。失敗回 None(呼叫端會
    fallback 回 VIDEO_BASE/tunnel 路徑，不裸崩)。"""
    if not local_path or not Path(local_path).exists():
        return None
    last_err = None
    for attempt in range(retries + 1):
        try:
            with open(local_path, "rb") as f:
                files = {"fileToUpload": (Path(local_path).name, f)}
                data = {"reqtype": "fileupload", "time": "72h"}
                r = requests.post(LITTERBOX_API, data=data, files=files, timeout=180)
            r.raise_for_status()
            out = r.text.strip()
            if out.startswith("http"):
                return out
            last_err = f"非預期回應：{out[:200]}"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        if attempt < retries:
            time.sleep(3)
    print(f"[warn] litterbox 上傳失敗（{Path(local_path).name}）：{last_err}", file=sys.stderr)
    return None


# IG-native 分級 hashtag 池(大詞觸及廣/中詞精準/小眾轉換高/reels 版位),每片混抽 ~13 個
IG_HASHTAG_POOL = {
    "big":   ["#投資", "#理財", "#加密貨幣", "#比特幣", "#被動收入"],
    "mid":   ["#量化交易", "#自動交易", "#定投", "#網格交易", "#理財規劃"],
    "niche": ["#Pionex", "#派網", "#量化阿森", "#新手投資", "#複利"],
    "reels": ["#reels", "#reelstaiwan"],
}


def _pick_hashtags(slug: str) -> list:
    """分級混抽 大3+中4+小眾4+reels2 ≈13 個;依 slug 輪替避免每支一模一樣。"""
    import hashlib
    r = int(hashlib.md5(slug.encode("utf-8")).hexdigest(), 16)

    def rot(lst, n):
        s = r % max(1, len(lst))
        return (lst[s:] + lst[:s])[:n]
    return (rot(IG_HASHTAG_POOL["big"], 3) + rot(IG_HASHTAG_POOL["mid"], 4)
            + rot(IG_HASHTAG_POOL["niche"], 4) + IG_HASHTAG_POOL["reels"])


def _caption(slug: str) -> str:
    """IG-native 文案:第一行 hook 勾人(前2行會被摺疊)+ 標題 + 導 bio 的 CTA + 分級 hashtag。"""
    import re
    title, hook, md_tags = slug, "", []
    md = OUT / f"{slug}.md"
    if md.exists():
        t = md.read_text(encoding="utf-8")
        m = re.search(r"^#\s*(?:🎬\s*)?(.+)$", t, re.M)
        if m:
            title = m.group(1).strip()
        mh = re.search(r"Hashtags[：:]\s*(.+)", t)
        if mh:
            md_tags = [x for x in mh.group(1).split() if x.startswith("#")]
    # IG hook = 旁白開頭最強懸念句(voice.txt 第一句),沒有就退回標題
    vt = OUT / f"{slug}.voice.txt"
    if vt.exists():
        for ln in vt.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if len(ln) >= 8:
                hook = ln[:60]
                break
    if not hook:
        hook = title
    cta = "完整回測數據＋每天更新在 YouTube『量化阿森』👉 點大頭貼看主頁連結"
    disclaimer = "投資有風險,不構成投資建議。"
    tags = list(dict.fromkeys(_pick_hashtags(slug) + md_tags))  # 分級池 + md 既有,去重
    body = f"{hook}\n\n{title}\n\n{cta}\n{disclaimer}\n" + " ".join(tags)
    return body[:2100]


def publish(slug: str) -> str | None:
    if not (UID and TOKEN):
        print("[FATAL] 缺 IG_USER_ID / IG_ACCESS_TOKEN", file=sys.stderr); return None
    if not (OUT / f"{slug}.mp4").exists():
        print(f"[FATAL] 找不到 {slug}.mp4", file=sys.stderr); return None
    # 片尾接「訂閱量化阿森 YouTube」CTA(只 IG 版,YT 原片不動);失敗退回原片
    try:
        import append_yt_cta
        mp4 = append_yt_cta.append_cta(slug)
    except Exception:  # noqa: BLE001
        mp4 = OUT / f"{slug}.mp4"

    # 封面：用 make_cover 產的高質感封面當 IG Reels 縮圖（避免 IG 抓到開頭黑幀→全黑）。
    cover_path = None
    try:
        import shutil
        cover = ROOT / "assets" / "thumbnails" / f"{slug}.jpg"
        if cover.exists():
            pub = OUT / f"{slug}.cover.jpg"
            if not pub.exists():
                shutil.copy2(cover, pub)
            cover_path = pub
    except Exception:  # noqa: BLE001
        cover_path = None

    # 1) 拿公網 URL：優先 litterbox 直傳(不靠 tunnel)，失敗才 fallback VIDEO_BASE/tunnel。
    video_url = None
    cover_data = {}
    lb_video = _upload_filehost(mp4)
    if lb_video:
        video_url = lb_video
        print(f"[info] litterbox video_url={video_url}")
        lb_cover = _upload_filehost(cover_path) if cover_path is not None else None
        if lb_cover:
            cover_data["cover_url"] = lb_cover
        else:
            cover_data["thumb_offset"] = 2500  # 無封面/封面上傳失敗→取 2.5s 的幀(過開頭黑淡入)
    else:
        print("[warn] litterbox 上傳失敗，fallback 回 VIDEO_BASE/tunnel 路徑")
        if not VIDEO_BASE:
            print("[FATAL] litterbox 失敗且缺 IG_VIDEO_BASE(公開影片網址)備援", file=sys.stderr)
            return None
        video_url = f"{VIDEO_BASE}/{quote(mp4.name)}"
        if not tunnel_healthy(video_url):
            print("[skip] tunnel 不通,跳過延後(不硬打 Meta API)")
            return None
        if cover_path is not None:
            cover_data["cover_url"] = f"{VIDEO_BASE}/{quote(slug + '.cover.jpg')}"
        else:
            cover_data["thumb_offset"] = 2500

    # 2) 建 container
    r = requests.post(f"{GRAPH}/{UID}/media", data={
        "media_type": "REELS", "video_url": video_url,
        "caption": _caption(slug), "access_token": TOKEN, **cover_data}, timeout=60)
    d = r.json()
    if "id" not in d:
        print(f"[FAIL] 建 container 失敗：{str(d)[:200]}", file=sys.stderr)
        log_ops("IG發布", f"⚠️ container 失敗：{slug[:30]}")
        return None
    cid = d["id"]
    print(f"[info] container={cid}，等 IG 抓影片+處理…")

    # 3) 輪詢處理狀態(影片處理可能要 30s~數分)
    for i in range(40):
        time.sleep(8)
        s = requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": TOKEN}, timeout=30).json()
        sc = s.get("status_code")
        if sc == "FINISHED":
            break
        if sc == "ERROR":
            print(f"[FAIL] IG 處理失敗：{s.get('status')}", file=sys.stderr)
            log_ops("IG發布", f"⚠️ 處理失敗：{slug[:30]}")
            return None
    else:
        print("[FAIL] 處理逾時", file=sys.stderr); return None

    # 4) 發布
    r2 = requests.post(f"{GRAPH}/{UID}/media_publish", data={"creation_id": cid, "access_token": TOKEN}, timeout=60)
    d2 = r2.json()
    if "id" in d2:
        log_ops("IG發布", f"Reels 已發布：{slug[:30]}")
        print(f"[ok] IG Reels 已發布！media_id={d2['id']}")
        return d2["id"]
    print(f"[FAIL] 發布失敗：{str(d2)[:200]}", file=sys.stderr)
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：ig_reels_upload.py <slug>"); raise SystemExit(2)
    raise SystemExit(0 if publish(sys.argv[1]) else 1)
