#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""comment_dept.py — 【⑧ 社群留言部】抓新留言 + 草擬回覆。

預設：讀頻道近期留言，用 Claude 以「理性顧問口吻、不亂承諾」草擬回覆，
      存成草稿給老闆過目後人工回。
      誠實：自動發留言有 spam/政策風險，且違誠信鐵則的風險高 → **只草擬不自動發**。

--auto-reply-safe：安全模板自動回覆模式。
      用關鍵字規則（可選 --use-haiku 輔助）分類留言，從白名單句型選出回覆，
      不讓 AI 自由生成回覆內容——避免公開帳號亂回/亂承諾/違誠信鐵則。
      誠信：模板不含保證收益/喊單/誇大。

另把觀眾問的好問題挑出來餵 ③靈感（可變內容）。
輸出：STUDIO/REPORTS/{date}_留言回覆草稿.md（預設草稿模式）
      STUDIO/comment_replied.json（--auto-reply-safe 去重紀錄）
"""
from __future__ import annotations
import argparse, json, os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace"); sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"; REPORTS = STUDIO / "REPORTS"
REPLIED_LOG = STUDIO / "comment_replied.json"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-haiku-4-5-20251001"
CHANNEL_ID = "UCqP5JQXlQR5ZDLtEiBt4kLA"
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


# ── 安全模板白名單（人工審核；不含保證收益/喊單/誇大）─────────────────────────
# 類別 → 模板列表（index 0 為預設，未來可輪替）
SAFE_TEMPLATES: dict[str, list[str]] = {
    "thanks": [
        "謝謝支持！🙏",
        "感謝收看，有幫助記得追蹤！",
        "謝謝你的留言！你的鼓勵是最大動力 🙏",
    ],
    "question": [
        "好問題！建議去看頻道裡的相關教學影片，有更詳細的說明 😊",
        "這個問題很棒！之後我會出影片詳細解答，先追蹤不漏接 🔔",
    ],
    "interaction": [
        "你目前用哪種交易方式？留言告訴我 👇",
        "你的看法呢？歡迎在下方留言分享 👇",
        "想了解更多？留言告訴我最想學哪個主題 👇",
    ],
}

# 關鍵字分類規則（優先於 Haiku，零 API 成本）
_QUESTION_KWS = ("?", "？", "怎麼", "如何", "為什麼", "請問", "能不能", "可以嗎", "有沒有辦法", "啥", "咋")
_THANKS_KWS = ("謝謝", "感謝", "謝啦", "讚", "棒", "好看", "學到", "有幫助", "收穫", "很好", "太棒", "優質")


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


# ── 草擬回覆（原有功能，只用於預設草稿模式）────────────────────────────────────
def draft_reply(comment):
    if not API_KEY:
        return "（無 ANTHROPIC_API_KEY，無法草擬）"
    import requests
    prompt = f"""你是量化阿森頻道的小編，回覆觀眾留言。誠信鐵則：理性顧問口吻、絕不保證收益、不喊單、不亂承諾、不報明牌。
觀眾留言：「{comment}」
請寫一則 1-3 句、友善、有幫助的繁中回覆草稿（若是問題就簡短解惑或引導看相關影片；若是抱怨就誠懇回應）。只輸出回覆內容。"""
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": MODEL, "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]}, timeout=60)
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        return f"（草擬失敗：{e}）"


# ── 安全模板分類函式 ──────────────────────────────────────────────────────────

def classify_by_keywords(text: str) -> str:
    """關鍵字規則分類（零 API 成本），回傳 'thanks' / 'question' / 'interaction'。"""
    if any(k in text for k in _QUESTION_KWS):
        return "question"
    if any(k in text for k in _THANKS_KWS):
        return "thanks"
    return "interaction"


def classify_with_haiku(text: str) -> str:
    """Haiku 分類輔助（關鍵字歧義時才呼叫）。只做分類，不生成回覆內容，省 token。"""
    if not API_KEY:
        return "interaction"
    import requests
    prompt = (
        "以下是 YouTube 觀眾留言，請只回答分類標籤（thanks/question/interaction），不要其他字。\n"
        "thanks=感謝/讚美留言；question=提問/求助留言；interaction=其他互動留言。\n"
        f"留言：{text[:200]}"
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": 20, "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        r.raise_for_status()
        tag = r.json()["content"][0]["text"].strip().lower()
        if tag in SAFE_TEMPLATES:
            return tag
    except Exception as e:
        print(f"[warn] Haiku 分類失敗，fallback interaction：{e}", file=sys.stderr)
    return "interaction"


def pick_template(category: str) -> str:
    """從分類取第一個白名單模板句型。"""
    return SAFE_TEMPLATES.get(category, SAFE_TEMPLATES["interaction"])[0]


# ── 去重紀錄 I/O ──────────────────────────────────────────────────────────────

def load_replied() -> set:
    """載入已回覆的 commentId 集合。"""
    if REPLIED_LOG.exists():
        try:
            data = json.loads(REPLIED_LOG.read_text(encoding="utf-8"))
            return set(data) if isinstance(data, list) else set()
        except Exception:
            pass
    return set()


def save_replied(replied: set) -> None:
    """儲存已回覆 commentId 清單（排序後寫入，易 diff）。"""
    STUDIO.mkdir(parents=True, exist_ok=True)
    REPLIED_LOG.write_text(json.dumps(sorted(replied), ensure_ascii=False, indent=2), encoding="utf-8")


# ── 安全模板自動回覆主邏輯 ───────────────────────────────────────────────────

def auto_reply_safe(yt, max_replies: int = 10, dry_run: bool = False, use_haiku: bool = False) -> int:
    """安全模板自動回覆主迴圈。回傳本輪實際回覆數。

    流程：
    1. 抓最新 50 則頂層留言
    2. 跳過：自己的留言、已回過的 commentId
    3. 用關鍵字分類（可選 Haiku 輔助）→ 選白名單模板
    4. dry_run=True 只印預覽；否則呼叫 comments().insert 發布
    5. 每則間隔 1.5 秒（禮貌間隔）
    6. 已回 commentId 寫入 STUDIO/comment_replied.json 去重
    """
    replied = load_replied()
    candidates = []
    try:
        resp = yt.commentThreads().list(
            part="snippet",
            allThreadsRelatedToChannelId=CHANNEL_ID,
            maxResults=50,
            order="time",
        ).execute()
        for it in resp.get("items", []):
            top = it["snippet"]["topLevelComment"]
            comment_id = top["id"]
            author_channel = (top["snippet"].get("authorChannelId") or {}).get("value", "")
            # 跳過：自己的留言（頻道主）、已回過的
            if author_channel == CHANNEL_ID:
                continue
            if comment_id in replied:
                continue
            candidates.append({
                "comment_id": comment_id,
                "text": top["snippet"].get("textDisplay", "")[:300],
                "author": top["snippet"].get("authorDisplayName", "")[:30],
            })
    except Exception as e:
        print(f"[warn] 抓留言失敗：{e}", file=sys.stderr)
        return 0

    acted = 0
    for c in candidates[:max_replies]:
        text = c["text"]
        # 分類：優先零成本關鍵字；interaction 最模糊時若開 --use-haiku 再確認
        category = classify_by_keywords(text)
        if use_haiku and category == "interaction":
            category = classify_with_haiku(text)
        template = pick_template(category)

        if dry_run:
            print(f"[dry-run] @{c['author']} → [{category}] 「{template}」")
            print(f"          留言：{text[:80]}")
            continue

        # 實際發回覆：comments().insert(parentId=頂層留言 id)
        try:
            yt.comments().insert(
                part="snippet",
                body={"snippet": {"parentId": c["comment_id"], "textOriginal": template}},
            ).execute()
            replied.add(c["comment_id"])
            acted += 1
            print(f"[ok] 已回 @{c['author']} → [{category}] 「{template}」")
            time.sleep(1.5)  # 禮貌間隔，避免 quota 連打
        except Exception as e:
            print(f"[warn] 發回覆失敗（@{c['author']}）：{e}", file=sys.stderr)

    if not dry_run and acted > 0:
        save_replied(replied)
        log_ops("社群留言", f"安全模板自動回 {acted} 則")
    return acted


# ── 原有草稿模式（預設行為）─────────────────────────────────────────────────

def draft_mode(yt) -> int:
    comments = []
    try:
        r = yt.commentThreads().list(part="snippet", allThreadsRelatedToChannelId=CHANNEL_ID,
                                     maxResults=20, order="time").execute()
        for it in r.get("items", []):
            sn = it["snippet"]["topLevelComment"]["snippet"]
            comments.append({"author": sn.get("authorDisplayName", "")[:20],
                             "text": sn.get("textDisplay", "")[:300],
                             "likes": sn.get("likeCount", 0)})
    except Exception as e:
        print(f"[warn] 取留言失敗（可能尚無留言或權限）：{e}", file=sys.stderr)

    date = tw_today(); REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ⑧ 留言回覆草稿｜{date}", "",
         "> 誠實：**只草擬不自動發**（避免 spam/違誠信鐵則風險），請過目後人工回覆。", ""]
    if not comments:
        L.append("（目前抓不到新留言——頻道剛起步留言少，或需要時再跑）")
    questions = []
    for c in comments[:15]:
        reply = draft_reply(c["text"])
        L += [f"## 💬 @{c['author']}（👍{c['likes']}）", f"> {c['text']}", f"**建議回覆：** {reply}", ""]
        if any(q in c["text"] for q in ("?", "？", "怎麼", "如何", "為什麼", "可以嗎")):
            questions.append(c["text"][:60])
    if questions:
        L += ["## 🎯 可變成內容的觀眾問題（餵 ③靈感）", *[f"- {q}" for q in questions]]
    (REPORTS / f"{date}_留言回覆草稿.md").write_text("\n".join(L), encoding="utf-8")
    log_ops("社群留言", f"草擬 {len(comments)} 則回覆，挑出 {len(questions)} 個可用問題")
    print(f"[ok] 留言回覆草稿完成：{len(comments)} 則、{len(questions)} 個可變內容問題。")
    return 0


# ── 進入點 ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="comment_dept — 社群留言部")
    parser.add_argument("--auto-reply-safe", action="store_true",
                        help="安全模板自動回覆模式（白名單句型，不讓 AI 自由生成回覆）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只印預覽「會回哪則→哪個模板」，不真的發")
    parser.add_argument("--max", type=int, default=10, dest="max_replies", metavar="N",
                        help="每輪最多回幾則（預設 10）")
    parser.add_argument("--use-haiku", action="store_true",
                        help="對分類模糊的留言用 Haiku 輔助分類（消耗少量 API credits）")
    args = parser.parse_args()

    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception as e:
        print(f"[FATAL] 無法連 YouTube：{e}", file=sys.stderr); return 2

    if args.auto_reply_safe:
        n = auto_reply_safe(yt, max_replies=args.max_replies, dry_run=args.dry_run, use_haiku=args.use_haiku)
        if args.dry_run:
            print("[dry-run] 預覽完畢，未實際發送。")
        else:
            print(f"[ok] 安全模板自動回完畢，本輪回覆 {n} 則。")
        return 0

    return draft_mode(yt)


if __name__ == "__main__":
    raise SystemExit(main())
