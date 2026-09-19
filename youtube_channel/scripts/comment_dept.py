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
import argparse, json, os, re, sys, time
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
PENDING = REPORTS / "觀眾問題待審.tsv"  # 人工挑選用;刻意不自動進題庫,理由見 draft_mode docstring
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


# ── 安全模板白名單（人工審核；不含保證收益/喊單/誇大）─────────────────────────
# 類別 → 模板列表（index 0 為預設，未來可輪替）
SAFE_TEMPLATES: dict[str, list[str]] = {
    "thanks": [
        "謝謝支持！🙏 怕被割的路上有你不孤單，一起慢慢學、穩穩走。",
        "感謝收看！新手最需要的就是先看懂再進場，記得訂閱不迷路 🙏",
        "謝謝你的留言！你的鼓勵是最大動力，會繼續幫大家踩雷 🙏",
    ],
    "question": [
        "好問題！這種地方新手最容易被割，建議先看頻道相關教學再動手 😊",
        "這問題很關鍵！之後我出片幫你把雷點講清楚，先訂閱不漏接 🔔",
    ],
    "interaction": [
        # 🔴 2026-08-31 移除「你目前是還在觀望、還是已經進場了?」
        # 本檔 2026-08-06 的說明就寫著這句「比不回還傷」,下面的 LLM prompt 也明寫
        # 「**嚴禁**答節所問地反問『你進場了嗎』這種罐頭」—— 但**安全模板沒跟著改**,
        # 於是機械檢查沒過而退回模板時,吐出來的正好是那句被禁止的話。
        # (fail-safe 退回的「安全」模板,居然是那道修正要消滅的行為本身。)
        #
        # 實際後果(08-31):它插進一則真實負評的討論串,問對方進場了沒 →
        # 觀眾回「1700股均價850,今天賣200股轉去封測股」,揭露了七位數的真實部位。
        # 這條線的生死線是「介紹≠推薦」,而**主動問觀眾的持股會把對話拉向個股建議**,
        # 那是我們絕對不能接的話題。留言互動只問**內容偏好**,不問任何人的部位/操作。
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

# 🔴 2026-07-28 配額地雷拆除(來自當日 quota 稽核):`max_replies` 是**每一輪**的上限,而本支
# 由 crontab 每 2 小時跑一次(12 輪/日)→ 10×12×50 units = **6,000 units/日理論上限**。
# 頻道最壞日配額實測已用到 9,940/10,000(99.4%),只要哪天有片起飛、留言變多,這支會直接
# 把當日配額吃穿 → 隔天的上架(每支 1,600+)全部失敗,而且日誌會被併發覆蓋、很難察覺。
# 修法:把上限綁在「每日」而不是「每輪」。留言互動本身是好事(留言權重>訂閱),故不是關掉它,
# 而是給一個明確的每日預算;用完當日就停,隔天自動重置。
_DAILY_REPLY_CAP = 8            # 8 × 50 = 400 units/日,佔配額 4%,可控
_REPLY_BUDGET_FILE = STUDIO / "comment_reply_budget.json"


def _reply_budget_left() -> int:
    """今日還能回幾則(讀 STUDIO/comment_reply_budget.json;跨日自動重置)。壞檔一律回滿額度
    但不超過上限——這條路徑壞掉不可以讓留言功能整個失效(fail-open),但也絕不可以放大支出。"""
    try:
        import datetime as _dt
        today = _dt.date.today().isoformat()
        d = {}
        if _REPLY_BUDGET_FILE.exists():
            d = json.loads(_REPLY_BUDGET_FILE.read_text(encoding="utf-8")) or {}
        if d.get("date") != today:
            return _DAILY_REPLY_CAP
        return max(0, _DAILY_REPLY_CAP - int(d.get("used", 0)))
    except Exception:  # noqa: BLE001
        return _DAILY_REPLY_CAP


def _reply_budget_consume(n: int) -> None:
    """把本輪實際發出的則數計入今日用量。

    🔴 2026-07-28 二修(獨立審查抓到我第一版的洞):舊寫法把 `json.loads` 和寫檔放在同一個
    try 內,檔案一旦壞掉(半寫入/磁碟異常),loads 直接 raise → except 只印警告、**不修檔** →
    用量永遠記不進去、額度每輪都是滿的 → 退化回「每輪 8 則 × 12 輪 = 96 則/日 ≈ 4,800 units」,
    **正是這次要拆的那顆地雷**。我第一版只測了「壞檔時讀取回滿額度」就宣稱安全,沒測連續多輪。
    修法:讀取失敗一律**重建**檔案(self-heal),讓計數從本輪開始累積,壞檔最多只放過一輪。
    另改用 save_json_atomic(studio 標準,見 memory 併發洗檔修法),避免自己變成壞檔來源。
    """
    if n <= 0:
        return
    import datetime as _dt
    today = _dt.date.today().isoformat()
    d = None
    try:
        if _REPLY_BUDGET_FILE.exists():
            d = json.loads(_REPLY_BUDGET_FILE.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — 壞檔:不沿用,直接重建
        print(f"[warn] 留言預算檔損壞,重建:{str(e)[:50]}", file=sys.stderr)
        d = None
    if not isinstance(d, dict) or d.get("date") != today:
        d = {"date": today, "used": 0}
    try:
        d["used"] = int(d.get("used", 0)) + n
    except Exception:  # noqa: BLE001
        d["used"] = n
    try:
        from studio_common import save_json_atomic as _sja
        _sja(_REPLY_BUDGET_FILE, d)
    except Exception:  # noqa: BLE001 — 沒有 studio_common 就退回直寫,但仍要把數字寫進去
        try:
            _REPLY_BUDGET_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        except Exception as e2:  # noqa: BLE001
            print(f"[warn] 留言預算寫檔失敗:{str(e2)[:60]}", file=sys.stderr)


_LEDGER_CACHE = {}


def _ledger_map() -> dict:
    """{videoId: slug} —— 給 smart_reply 判斷這支片有沒有結構化事實可引用。"""
    if _LEDGER_CACHE:
        return _LEDGER_CACHE
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import daily_publish as dp
        _LEDGER_CACHE.update({v: k for k, v in dp.load_ledger().items()})
    except Exception:  # noqa: BLE001
        pass
    return _LEDGER_CACHE


# ── 內容感知回覆(2026-08-06 Carson 指出「留言都用自動回覆」)──────────────────
# 實測全頻道 331 則留言,其中 **322 則(97%)是我們自己貼的 CTA**,真實觀眾留言只有 9 則。
# 那 9 則**全部**收到罐頭回覆,而且五則不同的留言回同一句:
#   👤「所以版主的結論就是這支股票一點都不適合,當初他只適合做區間短期的來回價差…」
#   ↳ 我們:「你目前是還在觀望、還是已經進場了?」
# 他已經看完、已經有結論、還講出自己的操作,我們卻問他進場了沒 —— **比不回還傷**。
#
# 這支的作法:
#  ① 真的讀留言在講什麼(不是三分類貼罐頭)
#  ② **能引用該片的真實數據就引用**——體檢片有 13 組真事實躺在 STUDIO,
#     這是別的頻道回不出來的東西,也是這個頻道唯一的護城河
#  ③ 誠信硬規:不喊單、不報明牌、不保證收益、**不編造任何數字**
#     (只能用注入的事實;沒有事實就只講觀念,絕不臨場生一個數字出來)
#  ④ 產出後過一次機械檢查,沒過就退回安全模板(fail-safe:寧可平淡,不可違規)

_REPLY_BANNED = ("保證", "穩賺", "必漲", "必跌", "包贏", "一定會", "穩賺不賠",
                 "建議買進", "建議賣出", "可以進場", "現在買", "快買", "快賣",
                 "目標價", "報明牌", "無腦買", "閉著眼睛")
_REPLY_MAXLEN = 160



# 2026-09-18(依 Carson 對「後照鏡看股票」留言的裁示):事實庫裡同一檔股票混著兩種類型——
# 「回測類」(checkup_long_horizon/annual_extremes/three_way/underwater/halvings/crash,
# 全部是歷史價格報酬/回撤)和「基本面估值類」(revenue_trend/eps_trend/gross_margin/
# dividend_history/valuation_position/industry_rank,含本益比百分位這種前瞻性最強的欄位)。
# 根因調查發現:_video_facts_for_reply() 原本把兩類混在同一份無標籤清單裡丟給 LLM,
# 觀眾質疑「只看歷史、沒前瞻性」時,LLM 卻挑了清單裡最顯眼的回測總報酬數字回覆——
# 剛好回成觀眾正在批評的那種樣子。分類標籤讓 smart_reply() 的 prompt 能明確指示
# 「這種質疑不要引用回測類,優先引用基本面估值類」。
_CHECKUP_BACKTEST_PREFIXES = ("checkup_long_horizon", "checkup_annual_extremes",
                              "checkup_three_way", "checkup_underwater",
                              "checkup_halvings", "checkup_crash")
_CHECKUP_FUNDAMENTAL_PREFIXES = ("checkup_revenue_trend", "checkup_eps_trend",
                                 "checkup_gross_margin", "checkup_dividend_history",
                                 "checkup_valuation_position", "checkup_industry_rank")


def _video_facts_for_reply(video_id: str, ledger: dict) -> str:
    """取這支片的真實事實(只給體檢片;其他片回空字串)。回覆只能引用這裡的數字。
    每條前面標「【回測】」或「【基本面估值】」,讓 LLM 分得出哪些是純歷史報酬、
    哪些是本益比百分位/EPS趨勢這類跟「現在貴不貴」相關的事實。"""
    slug = ledger.get(video_id) or ""
    if "個股體檢" not in slug:
        return ""
    m = re.search(r"(\d{4})", slug)
    if not m:
        return ""
    code = m.group(1)
    try:
        facts = json.loads((ROOT / "STUDIO" / "stock_checkup_facts.json")
                           .read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    res = facts.get("results") or {}
    bits = []
    for k, v in res.items():
        if not k.endswith("__%s" % code) or not isinstance(v, dict):
            continue
        s = str(v.get("summary") or "").strip()
        if not s:
            continue
        cat = ("回測" if k.startswith(_CHECKUP_BACKTEST_PREFIXES)
               else "基本面估值" if k.startswith(_CHECKUP_FUNDAMENTAL_PREFIXES)
               else "其他")
        bits.append(f"・【{cat}】{s[:120]}")
    # 基本面估值類排前面:數量少(通常6條)又是回應「前瞻性」質疑時最該優先被看到的,
    # 排前面確保清單被截到8條時不會被回測類擠掉。
    bits.sort(key=lambda b: 0 if "【基本面估值】" in b else 1)
    return "\n".join(bits[:8])


def _reply_is_safe(text: str) -> bool:
    """機械檢查:違規詞、長度、空白。過不了就退回安全模板。"""
    if not text or len(text) < 6 or len(text) > _REPLY_MAXLEN:
        return False
    if any(b in text for b in _REPLY_BANNED):
        return False
    # 不可自稱幫對方做決定
    if re.search(r"(你|妳)(應該|該)(買|賣|進|出|加碼|減碼)", text):
        return False
    return True


def smart_reply(comment_text: str, video_id: str, ledger: dict) -> str:
    """讀懂留言、能引用真實數據就引用,產出一則回覆。失敗或違規回空字串。"""
    if not sc.has_llm_key():
        return ""
    facts = _video_facts_for_reply(video_id, ledger)
    fact_block = (("\n【這支影片的真實數據(**只能用這裡的數字**,沒有的就別提數字)】\n" + facts)
                  if facts else
                  "\n（這支影片沒有可引用的結構化數據 → **整則回覆不要出現任何數字**）")
    prompt = f"""{sc.PERSONA}

你是量化阿森頻道的主持人,親自回覆一則觀眾留言。
{fact_block}

【觀眾留言】
{comment_text[:400]}

【怎麼回】
1. **先真的回應他說的那件事**。他有結論就承接他的結論、有問題就正面回答、
   分享經驗就回應那個經驗。**嚴禁**答非所問地反問「你進場了嗎」這種罐頭。
2. 上面有真實數據且跟他講的相關,就引用一個具體數字回他(這是本頻道的價值)。
   沒有數據就只講觀念,**絕對不要自己生一個數字**。
3. 【重要】如果他批評的是「這只是回測歷史/後照鏡看股票/沒有前瞻性、不知道現在貴不貴」
   這一類質疑,**不要引用【回測】標籤的總報酬/年化/回撤數字回他**——那正是他在批評的東西,
   拿它當答案等於證實他的批評是對的。這時優先引用【基本面估值】標籤的事實
   (本益比百分位、EPS趨勢、營收趨勢這類跟「現在貴不貴、體質好不好」相關的數據)。
   如果他問的是更具體、資料庫查不到的東西(例如特定客戶合作、新技術訂單這類質化消息),
   就老實講這超出目前資料範圍、不要裝懂也不要用別的數字硬答。
4. 語氣:理性、平視、像作者本人在回,不諂媚不說教。可以同意他、也可以補充不同角度。
5. 長度 **40~90 個中文字**,一到兩句。不要開場白、不要「感謝支持」這種場面話。

【誠信鐵則(違反就是廢稿)】
不喊單、不報明牌、不給目標價、不保證收益、不說「應該買/該賣」;
不編造任何數字;不承諾未來走勢。只陳述數據與觀念。
**絕對不要替頻道宣稱「有提供」或「沒有提供」任何東西**(邀請碼、優惠、課程、社群、
一對一諮詢…)——你不知道頻道當下實際提供什麼,猜錯就是對觀眾說謊。
實測踩過:有人問「有沒有邀請碼」,模型回「沒有提供任何邀請碼喔」,但頻道其實有。
⚠️ 這條規則**只適用於「詢問頻道本身有沒有提供某種資源/優惠/連結」這一種問題**
(邀請碼、折扣碼、課程、社群、一對一)——只有這種才回「相關連結都在說明欄」。
**不要泛化到其他問題上**:像「這檔能買嗎」「這個策略有效嗎」這類一般提問,
依然照第 1~2 條正常回應(承接他的話、能引用數據就引用),不要也套「請看說明欄」。

只輸出回覆本文,不要引號、不要任何解釋。"""
    try:
        # 1500 不是隨手給的:gemini-2.5-flash 是思考型模型,推理會先吃掉大半預算。
        # 實測 400 → finish_reason=length、只吐 21 字;1200 才完整。留餘裕給長一點的留言。
        out = llm.complete(prompt, 1500, temperature=0.6).strip()
    except Exception as exc:  # noqa: BLE001
        print("[smart_reply] LLM 失敗:%s" % str(exc)[:80], file=sys.stderr)
        return ""
    out = out.strip().strip('"').strip("「").strip("」").split("\n")[0].strip()
    if not _reply_is_safe(out):
        print("[smart_reply] 產出未過安全檢查,退回模板:%s" % out[:60], file=sys.stderr)
        return ""
    return out


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
                # videoId:讓 smart_reply 取得「這支片的真實數據」才能引用具體數字
                "video_id": it["snippet"].get("videoId", ""),
            })
    except Exception as e:
        print(f"[warn] 抓留言失敗：{e}", file=sys.stderr)
        return 0

    acted = 0
    n_smart = 0   # 智慧回覆命中數(2026-08-11:日誌不分流就看不出 smart_reply 是不是一直在靜默退模板)
    # 每日預算閘(見 _DAILY_REPLY_CAP):本輪可回數 = min(每輪上限, 今日剩餘預算)
    if not dry_run:
        _left = _reply_budget_left()
        if _left <= 0:
            print(f"[quota] 今日留言回覆已達每日上限 {_DAILY_REPLY_CAP} 則,本輪跳過(保護上架配額)")
            return 0
        max_replies = min(max_replies, _left)
    for c in candidates[:max_replies]:
        text = c["text"]
        # 分類：優先零成本關鍵字；interaction 最模糊時若開 --use-haiku 再確認
        category = classify_by_keywords(text)
        if use_haiku and category == "interaction":
            category = classify_with_haiku(text)
        # 先試「讀懂留言」的回覆(見 smart_reply 的實測說明);
        # 失敗或沒過安全檢查才退回安全模板 —— fail-safe:寧可平淡,不可違規。
        _smart = smart_reply(text, c.get("video_id", ""), _ledger_map())
        template = _smart or pick_template(category)
        _mode = "智慧" if _smart else "模板"
        n_smart += bool(_smart)

        if dry_run:
            print(f"[dry-run] @{c['author']} → [{category}/{_mode}] 「{template}」")
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
            print(f"[ok] 已回 @{c['author']} → [{category}/{_mode}] 「{template}」")
            time.sleep(1.5)  # 禮貌間隔，避免 quota 連打
        except Exception as e:
            print(f"[warn] 發回覆失敗（@{c['author']}）：{e}", file=sys.stderr)
            if "quota" in str(e).lower():
                print("[quota] 停止本輪(冪等,下個配額日接著跑)", file=sys.stderr)
                break

    if not dry_run and acted > 0:
        save_replied(replied)
        _reply_budget_consume(acted)   # 計入今日配額預算(見 _DAILY_REPLY_CAP)
        log_ops("社群留言", f"自動回 {acted} 則(智慧 {n_smart}/模板 {acted - n_smart})")
    return acted


# ── 原有草稿模式（預設行為）─────────────────────────────────────────────────

def draft_mode(yt, candidates=None) -> int:
    """整理觀眾留言成一份人看的草稿。

    🔴 2026-09-05 兩處修正,兩處都必須,少一處會比不修更糟:

    ① **排除自家留言。** 本函式原本連 `authorChannelId` 都沒讀,而全頻道 490 則留言裡
       **457 則是我們自己的 CTA**。而 CTA 本體就是問句(「你的網格參數都怎麼設?」
       「你手上有這檔嗎?」),下方 `:450` 的入選判準只看有沒有問號 ⇒ 實測 490 則命中 430,
       其中 **425 則(99%)是自家**。接通而不加這道過濾 = 系統把我們問觀眾的話
       當成觀眾的問題,再做成影片。(`auto_reply_safe:362` 早就有這道判定,同一份 `part="snippet"`
       就拿得到 `authorChannelId`,不必多花配額 —— 那條路徑做對了,這條沒有。)

    ② **不再寫進 topic_bank。** 原本是 `add_topics(source="comment", front=True)`,
       而那條路徑的另一端**也沒接上**:`add_topics` 寫死 `format="short"`,
       而所有排程產線都帶 `--shorts 0`(crontab:211、:218)⇒ 沒有任何 cron 會抽短片題。
       接通只會在題庫裡堆下沒有東西會消費的紀錄。
       更關鍵的是量:33 則觀眾留言 / 8 週,**真正可用的選題三個月累計 1~2 則**,
       而 `front=True` 是插隊優先製作 —— **一則進錯的代價是一支已渲染的片。**
       ⇒ 風險夠高而量夠小時,正確答案是**不要自動化**:改寫成一份待審清單給人看。

    `candidates`:`auto_reply_safe` 已經抓過 50 則且濾掉自家與已回覆的,
    傳進來就零額外配額、順帶白撿那道過濾。
    """
    comments = []
    if candidates:
        comments = [{"author": c.get("author", "")[:20], "text": c.get("text", "")[:300],
                     "likes": 0} for c in candidates]
    else:
        try:
            r = yt.commentThreads().list(part="snippet", allThreadsRelatedToChannelId=CHANNEL_ID,
                                         maxResults=50, order="time").execute()
            for it in r.get("items", []):
                top = it["snippet"]["topLevelComment"]
                sn = top["snippet"]
                if (sn.get("authorChannelId") or {}).get("value", "") == CHANNEL_ID:
                    continue          # 自家 CTA —— 不排除的話它佔 93%
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
        L += ["## 🎯 可變成內容的觀眾問題（**待人工挑選**，不自動進題庫）",
              *[f"- [ ] {q}" for q in questions],
              "",
              "> 🔴 2026-09-05 起**不再自動寫進 topic_bank**（原本是 `add_topics(source=\"comment\", front=True)`）。",
              "> 三個理由,任一個都足以停掉自動化:",
              "> ① 下游沒接:`add_topics` 寫死 `format=\"short\"`,而排程產線都帶 `--shorts 0` ⇒ 沒有 cron 會抽它。",
              "> ② 量太小:33 則觀眾留言 / 8 週,真正可用的選題三個月累計 1~2 則 —— 人看一遍 2 分鐘。",
              "> ③ 風險不對稱:`front=True` 是插隊優先製作,一則進錯的代價是一支已渲染的片。",
              "> ⇒ 要用哪一則,把它貼進 topic_bank 或直接開稿。**這份清單的價值是讓人看見,不是自動化。**"]
        try:
            PENDING.parent.mkdir(parents=True, exist_ok=True)
            _sep = chr(10)   # 刻意用 chr(10) 不用跳脫字元
            PENDING.write_text(_sep.join(f"{date}" + chr(9) + q for q in questions) + _sep, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 待審清單寫入失敗：{e}", file=sys.stderr)
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
        # 🔴 2026-09-05:原本這裡 `return 0`,而 crontab:445 跑的正是 --auto-reply-safe
        # ⇒ 下面那行 `return draft_mode(yt)` **永遠到不了**。實證:topic_bank 6,189 題裡
        # source=comment 共 **0 題**,八週、每天 12 次、零訊號 —— 而它 exit 0,
        # local_cron.py:251 記「✓ 完成」。失敗路徑和正常路徑回同一個值的那一族。
        # (同一個函式可以有多條路徑產生同一個空值:這條是「早退」型,不是「例外被吞」型。)
        draft_mode(yt)
        return 0

    return draft_mode(yt)


if __name__ == "__main__":
    raise SystemExit(main())
