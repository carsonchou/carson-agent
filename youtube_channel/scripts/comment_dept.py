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
import studio_common as sc          # 共用地基：PERSONA / has_llm_key
import llm                          # 共用 LLM 路由
STUDIO = ROOT / "STUDIO"; REPORTS = STUDIO / "REPORTS"
REPLIED_LOG = STUDIO / "comment_replied.json"
CHANNEL_ID = "UCqP5JQXlQR5ZDLtEiBt4kLA"
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


# ── 安全模板白名單（人工審核；不含保證收益/喊單/誇大）─────────────────────────
# 類別 → 模板列表（index 0 為預設，未來可輪替）
SAFE_TEMPLATES: dict[str, list[str]] = {
    "thanks": [
        "謝謝支持！🙏 怕被割的路上有你不孤單，一起慢慢學、穩穩走。",
        "感謝收看！新手最需要的就是先看懂再進場，記得追蹤不迷路 🙏",
        "謝謝你的留言！你的鼓勵是最大動力，會繼續幫大家踩雷 🙏",
    ],
    "question": [
        "好問題！這種地方新手最容易被割，建議先看頻道相關教學再動手 😊",
        "這問題很關鍵！之後我出片幫你把雷點講清楚，先追蹤不漏接 🔔",
    ],
    "interaction": [
        "你目前是還在觀望、還是已經進場了？留言聊聊，別自己悶著踩雷 👇",
        "你的看法呢？歡迎在下方留言，一起避開新手常踩的坑 👇",
        "最想先搞懂哪個主題？留言告訴我，我幫你先試過再分享 👇",
    ],
}

# 關鍵字分類規則（優先於 Haiku，零 API 成本）
_QUESTION_KWS = ("?", "？", "怎麼", "如何", "為什麼", "請問", "能不能", "可以嗎", "有沒有辦法", "啥", "咋")
_THANKS_KWS = ("謝謝", "感謝", "謝啦", "讚", "棒", "好看", "學到", "有幫助", "收穫", "很好", "太棒", "優質")


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


# ── 草擬回覆（原有功能，只用於預設草稿模式）────────────────────────────────────
def draft_reply(comment):
    if not sc.has_llm_key():
        return "（無任何 LLM 供應商 key，無法草擬）"
    prompt = f"""{sc.PERSONA}

你是量化阿森頻道的小編，用理性顧問口吻回覆觀眾留言。
誠信鐵則：絕不保證收益、不喊單、不亂承諾、不報明牌、不編造損益。
語氣走『怕被割小白×實測避雷』(軟性)：能白話就白話、術語翻人話，站在新手怕虧的角度，
必要時引導去看相關教學影片；若是抱怨就誠懇回應。
觀眾留言：「{comment}」
請寫一則 1-3 句、友善、有幫助的繁體中文(台灣用字)回覆草稿。只輸出回覆內容。"""
    try:
        return llm.complete(prompt, 400).strip()
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
    """LLM 分類輔助（關鍵字歧義時才呼叫）。只做分類，不生成回覆內容，省 token。
    (沿用旗標名 --use-haiku；實際走共用 llm 路由，供應商由 env 決定。)"""
    if not sc.has_llm_key():
        return "interaction"
    prompt = (
        "以下是 YouTube 觀眾留言，請只回答分類標籤（thanks/question/interaction），不要其他字。\n"
        "thanks=感謝/讚美留言；question=提問/求助留言；interaction=其他互動留言。\n"
        f"留言：{text[:200]}"
    )
    try:
        tag = llm.complete(prompt, 20).strip().lower()
        for k in SAFE_TEMPLATES:
            if k in tag:
                return k
    except Exception as e:
        print(f"[warn] LLM 分類失敗，fallback interaction：{e}", file=sys.stderr)
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
    added = 0
    if questions:
        L += ["## 🎯 可變成內容的觀眾問題（餵 ③靈感）", *[f"- {q}" for q in questions]]
        # ── 斷鏈修復：真的把觀眾好問題寫進題庫（真實小白疑問＝最貼定位的選題來源）──
        # 之前只寫進 md、沒進 topic_bank，靈感部永遠讀不到 → 這裡補上 add_topics。
        try:
            from topic_bank import add_topics
            items = [{"title": q, "angle": "直接回答觀眾實際提問，走小白避雷角度（先幫你試、別自己送死）",
                      "category": "觀眾問題", "format": "short", "priority": "comment"}
                     for q in questions]
            added = add_topics(items, source="comment", front=True)
            L += ["", f"> ✅ 已將 {added} 個觀眾問題寫入題庫（source=comment，插隊優先製作）。"]
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 觀眾問題寫入題庫失敗：{e}", file=sys.stderr)
            L += ["", f"> ⚠️ 觀眾問題寫入題庫失敗：{e}"]
    (REPORTS / f"{date}_留言回覆草稿.md").write_text("\n".join(L), encoding="utf-8")
    log_ops("社群留言", f"草擬 {len(comments)} 則回覆，挑出 {len(questions)} 個問題，{added} 個寫入題庫")
    print(f"[ok] 留言回覆草稿完成：{len(comments)} 則、{len(questions)} 個問題、{added} 個已進題庫。")
    return 0


# ── 進入點 ────────────────────────────────────────────────────────────────────

# ── 自動置頂 CTA 留言(item8:Shorts 留言權重>訂閱,頻道主留言常被排到接近頂部)──
# 注意:YouTube Data API 沒有公開「釘選留言」端點,釘選是 Studio 手動操作;本功能只「發」CTA 留言,
# 能見度已比說明欄高很多,但「釘選」那步誠實標為人工(不假裝自動置頂)。
_CTA_COMMENT = (
    "📌 想要完整回測數據＋新手避雷檢核表?私訊我的 Telegram @CarsonQuant_message_bot 打「回測」,"
    "免費送你「上真錢前 6 關檢核表」。有量化/網格/台股的問題也直接問我,我會看。"
    "（投資有風險,不構成投資建議）"
)


def _cta_posted_load():
    try:
        from pathlib import Path as _P
        p = _P(__file__).resolve().parent.parent / "STUDIO" / "comment_cta_posted.json"
        return set(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else set()
    except Exception:  # noqa: BLE001
        return set()


def _cta_posted_save(posted):
    try:
        from pathlib import Path as _P
        p = _P(__file__).resolve().parent.parent / "STUDIO" / "comment_cta_posted.json"
        p.write_text(json.dumps(sorted(posted), ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _top_viewed_candidates(n: int) -> list[str]:
    """回傳觀看數高到低排、尚未發過 CTA 留言的前 n 支 videoId。

    2026-07-14 變現漏斗審計發現:post_cta_comment 這支功能寫好後從未被排程呼叫過
    (STUDIO/comment_cta_posted.json 原本不存在),等於「留言『數據』我私你」這個鉤子
    完全沒有可見的發現管道,tg_leads.json 累計 0 筆名單。優先挑『已有觀眾在看』的
    存量片(觀看數高到低),把 CTA 留言擺在已經有人流的地方,而不是對 461 支 0 觀看
    的殭屍片盲發(浪費 API quota、對誰都看不到)。資料源:STUDIO/quality_scores.json
    的 published 清單(views 欄位)。查無觀看數的片不列入候選(避免瞎猜)。
    """
    from pathlib import Path as _P
    root = _P(__file__).resolve().parent.parent
    try:
        qs = json.loads((root / "STUDIO" / "quality_scores.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    posted = _cta_posted_load()
    rows = []
    for it in (qs.get("published") or []):
        if not isinstance(it, dict):
            continue
        vid = it.get("videoId")
        views = it.get("views")
        if not vid or vid in posted or not isinstance(views, (int, float)) or views <= 0:
            continue
        rows.append((views, vid))
    rows.sort(key=lambda t: -t[0])
    return [vid for _, vid in rows[:n]]


def post_cta_comment(yt, video_id: str, dry_run: bool = False) -> bool:
    """在指定影片發一則頂層 CTA 留言(頻道身分)。dry_run 只印不發。回傳是否成功/會發。
    釘選 API 做不到→發完 log 提醒人工釘選,不假裝自動置頂。"""
    posted = _cta_posted_load()
    if video_id in posted:
        print(f"[skip] {video_id} 已發過 CTA 留言")
        return False
    if dry_run:
        print(f"[dry-run] 會在 {video_id} 發 CTA 留言:\n  「{_CTA_COMMENT}」")
        return True
    try:
        yt.commentThreads().insert(
            part="snippet",
            body={"snippet": {"videoId": video_id,
                              "topLevelComment": {"snippet": {"textOriginal": _CTA_COMMENT}}}},
        ).execute()
        posted.add(video_id)
        _cta_posted_save(posted)
        print(f"[ok] {video_id} 已發 CTA 留言（釘選請人工:Studio 該片留言點置頂,API 無法自動）")
        log_ops("社群留言部", f"發置頂 CTA 留言 {video_id}（釘選待人工）")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 發 CTA 留言失敗 {video_id}：{e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="comment_dept — 社群留言部")
    parser.add_argument("--cta", metavar="VIDEO_ID", default=None,
                        help="在指定影片發一則頂層 CTA 留言（配 --dry-run 只預覽）")
    parser.add_argument("--cta-top", type=int, default=None, metavar="N",
                        help="在觀看數最高、尚未發過 CTA 留言的前 N 支已發布片各發一則頂層 CTA 留言"
                             "（配 --dry-run 只預覽；冪等，已發過的不重發）")
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

    if args.cta:
        post_cta_comment(yt, args.cta, dry_run=args.dry_run)
        return 0

    if args.cta_top is not None:
        cands = _top_viewed_candidates(args.cta_top)
        if not cands:
            print("[info] 無候選(可能觀看數資料缺失，或前 N 支皆已發過)。")
            return 0
        n_ok = 0
        for vid in cands:
            if post_cta_comment(yt, vid, dry_run=args.dry_run):
                n_ok += 1
        print(f"[{'dry-run ' if args.dry_run else ''}ok] --cta-top {args.cta_top}：{n_ok}/{len(cands)} 支{'會發' if args.dry_run else '已發'}。")
        return 0

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
