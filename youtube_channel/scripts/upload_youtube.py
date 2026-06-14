#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upload_youtube.py — 用 YouTube Data API v3 自動上傳影片到 Carson 的頻道
=====================================================================

頻道：量化阿森｜Carson Quant（faceless 全自動 YouTube 產線）

用途
----
吃既有產線產出的 `output/<slug>.mp4` 影片檔，連同 metadata（標題／描述／
標籤／隱私／分類），透過 YouTube Data API v3 以 **resumable upload** 上傳到
Carson 的 YouTube 頻道，並顯示上傳進度百分比。

與既有產線的對接（檔名約定）
----------------------------
    generate_script.py  →  output/<slug>.md        （完整腳本，含標題/描述/標籤）
    generate_script.py  →  output/<slug>.voice.txt （純配音稿）
    tts_pipeline.py     →  output/<slug>.mp3        （ElevenLabs 配音）
    （剪輯階段）         →  output/<slug>.mp4        （成片）
    本程式              ←  output/<slug>.mp4        （上傳）

依賴 (Dependencies)
-------------------
    pip install google-api-python-client google-auth-oauthlib google-auth-httplib2

OAuth 一次性設定（取得 client_secrets.json）
--------------------------------------------
1. 開 https://console.cloud.google.com/ ，建立（或選擇）一個專案。
2. 「API 和服務」→「程式庫」→ 搜尋並啟用「YouTube Data API v3」。
3. 「API 和服務」→「OAuth 同意畫面」：
   - User Type 選「外部」，填頻道名稱／聯絡信箱即可。
   - 在「測試使用者(Test users)」加入你上傳影片要用的那個 Google 帳號
     （未發布的應用只有測試使用者能授權）。
   - Scope 可不手動加，程式執行時會要求 youtube.upload。
4. 「API 和服務」→「憑證」→「建立憑證」→「OAuth 用戶端 ID」：
   - 應用程式類型選 **桌面應用程式 (Desktop app)**。
   - 建立後按「下載 JSON」，把檔案改名為 `client_secrets.json`，
     放到專案根目錄 `youtube_channel/client_secrets.json`。
5. 首次執行（非 --dry-run）會自動開瀏覽器要你登入授權，成功後 token 會快取
   到專案根目錄 `token.json`，之後免再登入（token 過期會自動 refresh）。

安全預設（重要）
----------------
* `privacyStatus` 預設 **private**（絕不預設 public），避免半成品或測試片外流。
  要公開請明確加 `--privacy public`（或 `unlisted`）。
* `--publish-at <ISO8601>`：設定排程公開時間。設了之後隱私一律鎖 private 並
  帶上 publishAt，由 YouTube 在指定時間自動轉公開。
* `--dry-run`：完全不碰網路、不需要 token / client_secrets.json，只印出即將
  送出的完整 metadata（標題／描述／標籤／隱私／分類／檔案路徑），供小預算與
  安全確認。
* 程式內不硬寫任何金鑰；也絕不印出 token.json / client_secrets.json 的內容。

CLI 用法請見檔案底部 build_arg_parser() 或執行 --help。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Windows 主控台預設常是 cp950（Big5），直接 print 中文標題/描述會
# UnicodeEncodeError 而中斷上傳。把 stdout/stderr 重設為 UTF-8（errors="replace"
# 保底），確保中文 metadata 都能安全印出（單獨執行與被 run_all.py 呼叫皆適用）。
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
DEFAULT_CLIENT_SECRETS = PROJECT_ROOT / "client_secrets.json"
DEFAULT_TOKEN_PATH = PROJECT_ROOT / "token.json"

# OAuth scope：上傳需要 youtube.upload；加 readonly 方便日後查頻道資訊。
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

# YouTube categoryId 常用值：28=科技, 22=人物與網誌, 27=教育, 25=新聞與政治。
DEFAULT_CATEGORY_ID = "28"
VALID_PRIVACY = ("public", "unlisted", "private")

# resumable upload 重試設定。
MAX_RETRIES = 6
RETRIABLE_STATUS_CODES = (500, 502, 503, 504)

# YouTube 上限：標題 <=100 字、tags 總長 <=500 字元。
MAX_TITLE_LEN = 100
MAX_DESC_LEN = 5000
MAX_TAGS_TOTAL_LEN = 500


# --------------------------------------------------------------------------- #
# 設定載入
# --------------------------------------------------------------------------- #


def load_channel_config(config_path: Optional[Path] = None) -> dict[str, Any]:
    """載入頻道設定 JSON；不存在或解析失敗則回傳空 dict（上層自有預設）。"""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        print(f"[info] 找不到設定檔 {path}，metadata 預設值將從缺。", file=sys.stderr)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[warn] 設定檔 {path} 讀取失敗（{exc}），metadata 預設值將從缺。", file=sys.stderr)
        return {}


# --------------------------------------------------------------------------- #
# .md 腳本解析（取標題 / 描述 / 標籤）
# --------------------------------------------------------------------------- #


def parse_markdown_metadata(md_path: Path) -> dict[str, Any]:
    """從 generate_script.py 產出的 <slug>.md 解析 title / description / tags。

    對應 render_markdown() 的輸出格式：
        # 🎬 <title>
        ...
        ## 📝 YouTube 影片描述
        <description 多行...>
        ...
        **Hashtags：** #標籤1 #標籤2 ...

    解析採容錯：任何欄位抓不到就略過，回傳缺漏的 dict，由上層 fallback。
    """
    result: dict[str, Any] = {}
    if not md_path.exists():
        return result
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[warn] 讀取腳本 {md_path} 失敗（{exc}），略過 .md 解析。", file=sys.stderr)
        return result

    lines = text.splitlines()

    # --- 標題：第一個 "# " 開頭的一級標題，去掉裝飾 emoji。 ---
    for line in lines:
        m = re.match(r"^#\s+(.*\S)\s*$", line)
        if m:
            title = m.group(1).strip()
            # 去掉開頭的裝飾性 emoji / 符號（如 "🎬 "）。
            title = re.sub(r"^[\W_]*?(?=[\w一-鿿])", "", title, count=1)
            result["title"] = title.strip()
            break

    # --- 描述：抓 "## 📝 YouTube 影片描述" 到下一個 "## " 或 "---" 之間。 ---
    desc_lines: list[str] = []
    capturing = False
    for line in lines:
        if re.match(r"^##\s+.*影片描述", line):
            capturing = True
            continue
        if capturing:
            if re.match(r"^##\s+", line) or re.match(r"^---\s*$", line):
                break
            desc_lines.append(line)
    description = "\n".join(desc_lines).strip()
    if description:
        result["description"] = description

    # --- 標籤：抓 "**Hashtags：** #a #b" 那一行（全形或半形冒號皆可）。 ---
    for line in lines:
        m = re.search(r"Hashtags[：:]\s*(.+)$", line)
        if m:
            raw = m.group(1)
            tags = [t.strip().strip("#*").strip() for t in re.split(r"[\s,，、]+", raw) if t.strip()]
            # 過濾掉純標點/markdown 殘渣（如 "**Hashtags：**" 尾端帶出的 "**"）。
            tags = [t for t in tags if t and re.search(r"[\w一-鿿]", t)]
            if tags:
                result["tags"] = tags
            break

    return result


# --------------------------------------------------------------------------- #
# metadata 組裝（優先序：CLI > .md > channel_config）
# --------------------------------------------------------------------------- #


def _coalesce(*values: Any) -> Any:
    """回傳第一個「有內容」的值（非 None、非空字串、非空 list）。"""
    for v in values:
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, (list, tuple)) and len(v) == 0:
            continue
        return v
    return None


def build_affiliate_block(channel_config: dict[str, Any]) -> tuple[str, list[str]]:
    """組裝要附到描述末尾的聯盟連結區塊。

    回傳 (區塊文字, 仍含 REPLACE_ME_ 佔位的 url 清單)。即使是 REPLACE_ME_*
    佔位也照樣帶出（讓使用者看得到位置），但會在 log 警告尚未替換。
    """
    cta = channel_config.get("cta", {}) or {}
    links = cta.get("affiliate_links", []) or []
    if not links:
        return "", []

    parts: list[str] = []
    intro = cta.get("affiliate_intro")
    if intro:
        parts.append(intro)

    unreplaced: list[str] = []
    for link in links:
        label = str(link.get("label", "連結")).strip()
        url = str(link.get("url", "")).strip()
        if "REPLACE_ME" in url:
            unreplaced.append(url)
        parts.append(f"{label} {url}".strip())

    disclaimer = cta.get("affiliate_disclaimer")
    if disclaimer:
        parts.append("")
        parts.append(disclaimer)

    return "\n".join(parts), unreplaced


def assemble_metadata(
    *,
    slug: str,
    md_path: Path,
    channel_config: dict[str, Any],
    cli_title: Optional[str] = None,
    cli_description: Optional[str] = None,
    cli_tags: Optional[list[str]] = None,
    append_affiliate: bool = True,
) -> dict[str, Any]:
    """依優先序（CLI > .md > channel_config）組裝最終 metadata dict。

    回傳含 title / description / tags 的 dict；描述末尾自動附聯盟連結。
    """
    md_meta = parse_markdown_metadata(md_path)
    seo = channel_config.get("seo", {}) or {}
    channel_name = channel_config.get("channel_name", "")

    # 標題
    title = _coalesce(cli_title, md_meta.get("title"), slug, "未命名影片")

    # 描述
    description = _coalesce(
        cli_description,
        md_meta.get("description"),
        f"{title}\n\n{channel_name}".strip(),
    )

    # 標籤：CLI > .md hashtags > config default_hashtags > config keywords
    config_tags = list(seo.get("default_hashtags", []) or []) + list(seo.get("keywords", []) or [])
    config_tags = [str(t).lstrip("#").strip() for t in config_tags if str(t).strip()]
    tags = _coalesce(cli_tags, md_meta.get("tags"), config_tags) or []
    # 去重但保序、去掉前導 #。
    seen: set[str] = set()
    clean_tags: list[str] = []
    for t in tags:
        t = str(t).lstrip("#").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            clean_tags.append(t)

    # 附聯盟連結到描述末尾
    unreplaced: list[str] = []
    if append_affiliate:
        block, unreplaced = build_affiliate_block(channel_config)
        if block:
            description = f"{description}\n\n{block}"

    return {
        "title": str(title),
        "description": str(description),
        "tags": clean_tags,
        "_unreplaced_affiliate": unreplaced,
    }


def enforce_youtube_limits(meta: dict[str, Any]) -> dict[str, Any]:
    """套用 YouTube 的長度上限（標題 100 / 描述 5000 / 標籤總長 500）。

    超過上限就截斷並 log 警告，避免上傳被 API 拒絕。
    """
    title = meta["title"]
    if len(title) > MAX_TITLE_LEN:
        print(f"[warn] 標題超過 {MAX_TITLE_LEN} 字（{len(title)}），已截斷。", file=sys.stderr)
        meta["title"] = title[:MAX_TITLE_LEN]

    desc = meta["description"]
    if len(desc) > MAX_DESC_LEN:
        print(f"[warn] 描述超過 {MAX_DESC_LEN} 字（{len(desc)}），已截斷。", file=sys.stderr)
        meta["description"] = desc[:MAX_DESC_LEN]

    # 標籤總長（粗估：各 tag 長度相加 + 分隔）<=500。
    tags = meta["tags"]
    kept: list[str] = []
    total = 0
    for t in tags:
        add = len(t) + 1
        if total + add > MAX_TAGS_TOTAL_LEN:
            print(f"[warn] 標籤總長超過 {MAX_TAGS_TOTAL_LEN} 字元，已捨棄多餘標籤。", file=sys.stderr)
            break
        kept.append(t)
        total += add
    meta["tags"] = kept
    return meta


# --------------------------------------------------------------------------- #
# request body 組裝
# --------------------------------------------------------------------------- #


def build_request_body(
    meta: dict[str, Any],
    *,
    category_id: str,
    privacy: str,
    publish_at: Optional[str],
    language: str = "zh-Hant",
) -> dict[str, Any]:
    """組裝 YouTube videos.insert 的 request body。"""
    status: dict[str, Any] = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": False,
    }
    if publish_at:
        # 排程公開：privacy 必須 private，並帶 publishAt。
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at

    return {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": category_id,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": status,
    }


# --------------------------------------------------------------------------- #
# ISO8601 / publishAt 正規化
# --------------------------------------------------------------------------- #


def normalize_publish_at(value: str) -> str:
    """把使用者輸入的 ISO8601 時間正規化成 YouTube 接受的 RFC3339（UTC, 'Z'）。

    接受形如：
        2026-06-20T09:00:00Z
        2026-06-20T09:00:00+08:00
        2026-06-20T09:00:00
    無時區者視為本地時間轉成 UTC。解析失敗則原樣回傳並 log 警告。
    """
    from datetime import datetime, timezone

    raw = value.strip()
    candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        print(f"[warn] 無法解析 --publish-at「{raw}」為 ISO8601，原樣送出（YouTube 可能拒絕）。", file=sys.stderr)
        return raw
    if dt.tzinfo is None:
        dt = dt.astimezone()  # 視為本地時區
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# --------------------------------------------------------------------------- #
# OAuth 認證
# --------------------------------------------------------------------------- #


def get_authenticated_service(
    *,
    client_secrets: Path,
    token_path: Path,
):
    """跑 OAuth 2.0 桌面流程，回傳已授權的 YouTube API service 物件。

    - 有 token.json 且有效 → 直接用。
    - token 過期但有 refresh_token → 自動 refresh。
    - 沒有 / 失效 → 開瀏覽器讓使用者授權，成功後把 token 快取到 token.json。

    任何套件缺失 / 檔案缺失都丟出帶說明的例外，由 main() 捕捉。
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "缺少 Google API 套件。請先安裝：\n"
            "    pip install google-api-python-client google-auth-oauthlib google-auth-httplib2\n"
            f"（原始錯誤：{exc}）"
        ) from exc

    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except (ValueError, OSError) as exc:
            print(f"[warn] 既有 token.json 無法載入（{exc}），將重新授權。", file=sys.stderr)
            creds = None

    if creds and creds.valid:
        pass
    elif creds and creds.expired and creds.refresh_token:
        try:
            print("[info] token 已過期，嘗試自動 refresh…", file=sys.stderr)
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] token refresh 失敗（{exc}），改走瀏覽器重新授權。", file=sys.stderr)
            creds = None

    if not creds or not creds.valid:
        if not client_secrets.exists():
            raise RuntimeError(
                f"找不到 client_secrets.json：{client_secrets}\n"
                "請依檔頭「OAuth 一次性設定」到 Google Cloud Console 下載桌面用戶端 JSON，"
                "改名為 client_secrets.json 放到專案根目錄。"
            )
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
            print("[info] 開啟瀏覽器進行 OAuth 授權（首次需登入並同意）…", file=sys.stderr)
            creds = flow.run_local_server(port=0)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OAuth 授權流程失敗：{exc}") from exc

        # 快取 token（注意：不印出內容）。
        try:
            token_path.write_text(creds.to_json(), encoding="utf-8")
            print(f"[ok] 已將授權 token 快取到 {token_path}（內容不顯示）。", file=sys.stderr)
        except OSError as exc:
            print(f"[warn] 無法寫入 token.json（{exc}），下次需重新授權。", file=sys.stderr)

    try:
        return build(API_SERVICE_NAME, API_VERSION, credentials=creds, cache_discovery=False)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"建立 YouTube API service 失敗：{exc}") from exc


# --------------------------------------------------------------------------- #
# resumable upload（含 exponential backoff 重試）
# --------------------------------------------------------------------------- #


def resumable_upload(youtube, body: dict[str, Any], video_path: Path) -> Optional[str]:
    """以 resumable upload 上傳影片，印進度百分比；回傳 videoId 或 None。

    對 5xx / 連線中斷採 exponential backoff 重試（最多 MAX_RETRIES 次）。
    """
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    import socket

    try:
        media = MediaFileUpload(
            str(video_path),
            chunksize=4 * 1024 * 1024,  # 4MB 分塊，邊傳邊回報進度
            resumable=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[error] 無法開啟影片檔 {video_path}（{exc}）。", file=sys.stderr)
        return None

    try:
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[error] 建立上傳請求失敗（{exc}）。", file=sys.stderr)
        return None

    response = None
    error: Optional[str] = None
    retry = 0
    last_pct = -1

    print("[info] 開始 resumable upload…", file=sys.stderr)
    while response is None:
        try:
            status, response = request.next_chunk()
            if status is not None:
                pct = int(status.progress() * 100)
                if pct != last_pct:
                    print(f"\r[upload] 進度 {pct:3d}%", end="", file=sys.stderr, flush=True)
                    last_pct = pct
            if response is not None:
                if "id" in response:
                    print("\r[upload] 進度 100%        ", file=sys.stderr, flush=True)
                    return response["id"]
                print(f"\n[error] 上傳回應異常（無 id）：{response}", file=sys.stderr)
                return None
        except HttpError as exc:
            if exc.resp.status in RETRIABLE_STATUS_CODES:
                error = f"可重試的 HTTP {exc.resp.status}：{exc}"
            else:
                print(f"\n[error] 不可重試的 API 錯誤（HTTP {exc.resp.status}）：{exc}", file=sys.stderr)
                return None
        except (socket.error, ConnectionError, OSError, TimeoutError) as exc:
            error = f"連線錯誤：{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001
            error = f"未預期錯誤：{type(exc).__name__}: {exc}"

        if error is not None:
            retry += 1
            if retry > MAX_RETRIES:
                print(f"\n[error] 重試 {MAX_RETRIES} 次仍失敗，放棄。最後錯誤：{error}", file=sys.stderr)
                return None
            sleep_seconds = min(2 ** retry, 64) + random.random()
            print(
                f"\n[warn] {error}（第 {retry}/{MAX_RETRIES} 次重試，{sleep_seconds:.1f}s 後重連）",
                file=sys.stderr,
            )
            time.sleep(sleep_seconds)
            error = None

    return None


# --------------------------------------------------------------------------- #
# metadata 列印（dry-run / 上傳前確認）
# --------------------------------------------------------------------------- #


def print_metadata(
    *,
    meta: dict[str, Any],
    body: dict[str, Any],
    video_path: Path,
    category_id: str,
    privacy: str,
    publish_at: Optional[str],
) -> None:
    """把即將送出的完整 metadata 印給使用者看（不含任何金鑰）。"""
    snippet = body["snippet"]
    status = body["status"]
    line = "-" * 60
    print(line)
    print("即將送出的 YouTube 影片 metadata")
    print(line)
    print(f"影片檔案 : {video_path}")
    print(f"標題     : {snippet['title']}")
    print(f"分類 ID  : {category_id}")
    print(f"隱私狀態 : {status['privacyStatus']}", end="")
    if status.get("publishAt"):
        print(f"（排程公開於 {status['publishAt']}）")
    else:
        print()
    print(f"標籤     : {', '.join(snippet['tags']) if snippet['tags'] else '（無）'}")
    print(f"語言     : {snippet.get('defaultLanguage', '')}")
    print(line)
    print("描述：")
    print(snippet["description"])
    print(line)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def resolve_video_path(args, output_dir: Path) -> Path:
    """決定要上傳的 mp4 路徑：--video 優先，否則 output/<slug>.mp4。"""
    if args.video:
        return Path(args.video)
    return output_dir / f"{args.slug}.mp4"


def run(args) -> int:
    """核心流程，回傳 exit code。"""
    channel_config = load_channel_config(args.config)
    output_dir = args.output or DEFAULT_OUTPUT_DIR

    slug = args.slug
    md_path = output_dir / f"{slug}.md"
    video_path = resolve_video_path(args, output_dir)

    # 組裝 metadata（優先序 CLI > .md > config）。
    cli_tags = None
    if args.tags is not None:
        cli_tags = [t.strip() for t in re.split(r"[,，]", args.tags) if t.strip()]

    meta = assemble_metadata(
        slug=slug,
        md_path=md_path,
        channel_config=channel_config,
        cli_title=args.title,
        cli_description=args.description,
        cli_tags=cli_tags,
        append_affiliate=not args.no_affiliate,
    )
    meta = enforce_youtube_limits(meta)

    # 聯盟連結未替換警告。
    for url in meta.get("_unreplaced_affiliate", []):
        print(f"[warn] 聯盟連結尚未替換佔位符（仍含 REPLACE_ME）：{url}", file=sys.stderr)

    # 隱私 / 排程處理。
    privacy = args.privacy
    publish_at = normalize_publish_at(args.publish_at) if args.publish_at else None
    if publish_at and privacy != "private":
        print("[info] 已設定 --publish-at，隱私自動鎖為 private（排程到時自動公開）。", file=sys.stderr)
        privacy = "private"

    language = channel_config.get("language", "zh-Hant")
    body = build_request_body(
        meta,
        category_id=args.category,
        privacy=privacy,
        publish_at=publish_at,
        language=language,
    )

    # 印出 metadata（dry-run 與正式上傳前都印一次供確認）。
    print_metadata(
        meta=meta,
        body=body,
        video_path=video_path,
        category_id=args.category,
        privacy=privacy,
        publish_at=publish_at,
    )

    if args.dry_run:
        print("[dry-run] 未呼叫任何 API、未讀取 token。以上為將送出的內容。")
        if not video_path.exists():
            print(f"[dry-run][note] 注意：影片檔尚不存在：{video_path}", file=sys.stderr)
        return 0

    # 正式上傳前先確認影片檔存在。
    if not video_path.exists():
        print(f"[error] 找不到影片檔：{video_path}", file=sys.stderr)
        print("        請確認剪輯階段已產出 output/<slug>.mp4，或用 --video 指定路徑。", file=sys.stderr)
        return 2

    if privacy == "public" and not publish_at:
        print("[warn] privacyStatus = public：影片上傳後將「立即公開」。", file=sys.stderr)

    # 認證。
    try:
        youtube = get_authenticated_service(
            client_secrets=Path(args.client_secrets),
            token_path=Path(args.token),
        )
    except RuntimeError as exc:
        print(f"[error] 認證失敗：{exc}", file=sys.stderr)
        return 3

    # 上傳。
    video_id = resumable_upload(youtube, body, video_path)
    if not video_id:
        print("[error] 上傳失敗。", file=sys.stderr)
        return 4

    print(f"[ok] 上傳成功！videoId = {video_id}")
    print(f"[ok] 影片網址： https://youtu.be/{video_id}")
    print(f"[ok] 編輯後台： https://studio.youtube.com/video/{video_id}/edit")
    if publish_at:
        print(f"[ok] 已排程於 {publish_at} 自動公開（目前為 private）。")
    elif privacy != "public":
        print(f"[ok] 目前隱私為 {privacy}；確認無誤後可到 Studio 改為 public。")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    """建立 argparse 解析器。"""
    parser = argparse.ArgumentParser(
        prog="upload_youtube.py",
        description="用 YouTube Data API v3 自動上傳 output/<slug>.mp4 到 Carson 頻道（安全預設 private）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "範例：\n"
            '  # 先 dry-run 確認 metadata（不連網、不需 token）\n'
            '  python scripts\\upload_youtube.py "派網網格機器人新手教學" --dry-run\n'
            "\n"
            '  # 正式上傳（預設 private，首次會開瀏覽器授權）\n'
            '  python scripts\\upload_youtube.py "派網網格機器人新手教學"\n'
            "\n"
            '  # 覆寫標題與標籤、改成 unlisted\n'
            '  python scripts\\upload_youtube.py my-slug --title "新標題" --tags "派網,網格,量化" --privacy unlisted\n'
            "\n"
            '  # 排程於指定時間自動公開（隱私自動鎖 private）\n'
            '  python scripts\\upload_youtube.py my-slug --publish-at 2026-06-20T09:00:00+08:00\n'
        ),
    )
    parser.add_argument(
        "slug",
        help="影片 slug（對應 output/<slug>.mp4 與 output/<slug>.md）。",
    )
    parser.add_argument(
        "--video",
        default=None,
        help="直接指定要上傳的 mp4 路徑（覆寫 output/<slug>.mp4）。",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"頻道設定 JSON 路徑（預設：{DEFAULT_CONFIG_PATH}）。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"output 資料夾（預設：{DEFAULT_OUTPUT_DIR}）。",
    )
    # metadata 覆寫
    parser.add_argument("--title", default=None, help="覆寫影片標題（優先序最高）。")
    parser.add_argument("--description", default=None, help="覆寫影片描述（優先序最高）。")
    parser.add_argument(
        "--tags",
        default=None,
        help="覆寫標籤，逗號分隔（例：派網,網格,量化）。",
    )
    parser.add_argument(
        "--no-affiliate",
        action="store_true",
        help="不要把 channel_config 的聯盟連結附到描述末尾。",
    )
    parser.add_argument(
        "--category",
        default=DEFAULT_CATEGORY_ID,
        help=f"YouTube categoryId（預設 {DEFAULT_CATEGORY_ID}=科技；22=人物與網誌，27=教育）。",
    )
    # 安全 / 隱私
    parser.add_argument(
        "--privacy",
        choices=VALID_PRIVACY,
        default="private",
        help="隱私狀態（預設 private，絕不預設 public）。",
    )
    parser.add_argument(
        "--publish-at",
        default=None,
        help="排程公開時間 ISO8601（例 2026-06-20T09:00:00+08:00）；設了則 private + publishAt。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不呼叫 API、不需 token，只印出將送出的完整 metadata。",
    )
    # OAuth 檔案路徑
    parser.add_argument(
        "--client-secrets",
        type=Path,
        default=DEFAULT_CLIENT_SECRETS,
        help=f"OAuth client_secrets.json 路徑（預設：{DEFAULT_CLIENT_SECRETS}）。",
    )
    parser.add_argument(
        "--token",
        type=Path,
        default=DEFAULT_TOKEN_PATH,
        help=f"OAuth token 快取路徑（預設：{DEFAULT_TOKEN_PATH}）。",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 進入點。回傳 process exit code。"""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n[abort] 使用者中斷。", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - 最後一道防線，避免噴 traceback
        print(f"[error] 未預期錯誤：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
