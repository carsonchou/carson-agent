#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tw_stock_series.py — 【台股多軌連載引擎】4 條並行系列 → 輪流注入題庫，養成追劇感。

仿 tv_curriculum.py：有序連載 + 進度檔 + `--next N` 用 topic_bank.add_topics(front=True)
插到題庫最前面。差別是**四軌並行、輪流取**(不是單線由淺入深)，讓台股題材每天都有續集。

四軌(每集 category="台股回測"，會命中 produce_batch 的台股觸發詞「台股」)：
  A《台股回測實錄》 — 0050/高股息/存股/台積電/大盤擇時…用長期回測講真相(≥8 集)
  B《當沖鬼故事》   — 當沖九成賠/隔日沖/融資斷頭/權證歸零…用數據拆穿速成夢(≥6 集)
  C《存股避雷》     — 填息陷阱/雷股/高股息vs市值型/月配季配迷思…幫小白避雷(≥6 集)
  D《大盤覆盤週報》 — 本週大盤/法人/融資用數據講(循環，永不完結，每週可續)

誠信鐵則(每集都守)：角度一律「數據／回測／拆穿／避雷」，只做數據分析，
不喊單、不報明牌、不報目標價、不保證收益。

用法：
  python scripts/tw_stock_series.py --next 4        # 四軌各輪一集，注入 4 題(front)
  python scripts/tw_stock_series.py --next 4 --dry  # 只印不寫(驗證邏輯)
  python scripts/tw_stock_series.py --boost         # 寫一條常駐 directive 到 boss_directives
  python scripts/tw_stock_series.py --status        # 印四軌進度

進度檔：STUDIO/tw_stock_progress.json
  {"A":已注入到第幾集, "B":..., "C":..., "D":循環計數, "cursor":下輪從第幾軌起}

驗證：python -m py_compile scripts/tw_stock_series.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from studio_common import save_json_atomic
STUDIO = ROOT / "STUDIO"
PROGRESS = STUDIO / "tw_stock_progress.json"
DIRPATH = STUDIO / "boss_directives.json"

CAT = "台股回測"   # 含「台股」→ 命中 produce_batch 的 TW_STOCK_RULES 觸發詞


def _e(title, angle):
    return {"title": title, "angle": angle}


# ─────────────────────────────────────────────────────────────────────────────
# 四軌連載資料。key = 軌代號；name = 系列名；loop = 是否循環(D 週報永不完結)；
# episodes = 有序集數(帶 cliffhanger 連載感，金額/標的逐集升級)。
# 角度全部走數據/回測/拆穿/避雷，不喊單不報明牌不報目標價。
# ─────────────────────────────────────────────────────────────────────────────
TRACKS = {
    "A": {
        "name": "台股回測實錄",
        "loop": False,
        "episodes": [
            _e("台股回測實錄 第1集｜0050 一次全押 vs 每月定投，10 年後差多少?",
               "同一筆錢兩種買法回測 10 年，比終值與最大回撤，數據說話不喊買；結尾預告下集換高股息"),
            _e("台股回測實錄 第2集｜高股息 ETF 真的贏大盤?0056 對 0050 回測攤開看",
               "把配息當成本還原後回測總報酬，拆穿『高股息=賺比較多』直覺；結尾勾下集存股套山頂"),
            _e("台股回測實錄 第3集｜存股存到山頂會怎樣?買在歷史高點的定投回測",
               "刻意把起點設在大盤高點回測，看定投幾年才解套，幫怕套牢的小白試給你看；結尾預告台積電 20 年"),
            _e("台股回測實錄 第4集｜台積電抱 20 年 vs 大盤，護國神山回測真相",
               "單壓一檔 vs 買整個大盤的長期回測對比，講集中持股的報酬與風險，只做數據不報目標價；結尾勾大盤擇時"),
            _e("台股回測實錄 第5集｜大盤擇時能贏無腦定投嗎?進出場訊號回測打臉",
               "用均線/爆量等常見擇時訊號回測台股，對照無腦定投，揭擇時多半跑輸；結尾預告台股 vs 美股"),
            _e("台股回測實錄 第6集｜十萬買台股 vs 十萬買美股，10 年後誰勝?",
               "含匯率與配息還原的長期回測對比，講清楚各自的波動與回撤，不喊哪個必贏；結尾勾金額升級到五十萬"),
            _e("台股回測實錄 第7集｜五十萬 all in 台股 vs 分批進場，金額放大會怎樣?",
               "賭注升級到五十萬，比較單筆與分批的回測結果，示範本金放大後回撤的體感；結尾預告加碼攤平"),
            _e("台股回測實錄 第8集｜越跌越買的攤平法，回測台股會賺還是套更深?",
               "把攤平/加碼策略套進台股歷史回測，示範它在盤整賺、單邊套牢的兩面性，純數據避雷；結尾勾停利"),
            _e("台股回測實錄 第9集｜賺多少該跑?台股定投設停利 vs 抱著不動回測對決",
               "比較設停利與長抱兩種紀律的回測終值，講清楚各自代價，不保證收益；結尾預告本季總結算"),
            _e("台股回測實錄 第10集｜本季總結算：這一連串台股回測到底教會我們什麼?",
               "把前 9 集回測數字收攏成一張避雷清單，收官判決並開下一季更狠的回測賭注"),
        ],
    },
    "B": {
        "name": "當沖鬼故事",
        "loop": False,
        "episodes": [
            _e("當沖鬼故事 第1集｜當沖九成賠錢是真的嗎?我用數據跑給你看",
               "拿公開統計與回測拆當沖勝率，示範手續費滑價如何吃掉利潤，勸小白別把速成當提款機；結尾勾隔日沖"),
            _e("當沖鬼故事 第2集｜隔日沖畢業實錄：抱一晚的風險數據有多恐怖",
               "回測隔日沖的跳空風險分佈，講清楚一次大跳空吃掉多少場勝利，純數據避雷；結尾預告融資斷頭"),
            _e("當沖鬼故事 第3集｜融資斷頭是怎麼發生的?維持率崩掉的數據推演",
               "用維持率公式與歷史大跌回測，示範槓桿如何在幾天內斷頭，警示不是喊空；結尾勾權證歸零"),
            _e("當沖鬼故事 第4集｜權證買了為什麼一直歸零?時間價值的數據真相",
               "拆權證時間價值遞減與隱波，示範為何抱久必虧，幫小白看懂再決定碰不碰；結尾預告當沖成本"),
            _e("當沖鬼故事 第5集｜當沖手續費到底吃掉你多少?一年交易成本試算",
               "用真實交易稅與手續費回推當沖成本，示範高頻進出的隱形失血，只算數據；結尾勾追高殺低"),
            _e("當沖鬼故事 第6集｜追高殺低的散戶劇本，回測證明它為何一直輸",
               "把情緒化追漲殺跌寫成規則回測，對照紀律持有，用數據拆穿盤感迷思，收官不喊單"),
        ],
    },
    "C": {
        "name": "存股避雷",
        "loop": False,
        "episodes": [
            _e("存股避雷 第1集｜填息是保證的嗎?除權息後填不回來的數據攤開看",
               "回測多檔除權息後的填息機率與天數，拆穿『領息穩賺』直覺，幫小白避雷；結尾勾存到雷股"),
            _e("存股避雷 第2集｜存股存到地雷會怎樣?單壓一檔崩掉的回撤實錄",
               "回測集中存單一個股踩雷的最大回撤，講分散的重要性，示範風險不報明牌；結尾預告高股息vs市值型"),
            _e("存股避雷 第3集｜高股息 vs 市值型，長期存哪個總報酬贏?",
               "配息還原後回測兩類 ETF 的總報酬與波動，講清楚各自適合誰，不喊哪個必買；結尾勾月配季配"),
            _e("存股避雷 第4集｜月配、季配、年配差在哪?配息頻率的數據迷思",
               "用複利與現金流回測比較不同配息頻率，拆穿『月月領=賺比較多』錯覺，純數據；結尾預告賺了價差還原"),
            _e("存股避雷 第5集｜只看殖利率選股會踩什麼雷?高殖利率陷阱回測",
               "回測『無腦追高殖利率』組合，示範賺了股息賠了價差的情境，幫小白看數據避雷；結尾勾定期定額紀律"),
            _e("存股避雷 第6集｜定期定額存股，中途停扣一次差多少?紀律的數據代價",
               "回測中途停扣/贖回對長期終值的傷害，講紀律的價值，收官避雷不保證收益"),
        ],
    },
    "D": {
        "name": "大盤覆盤週報",
        "loop": True,  # 循環：每週可續，永不完結
        "episodes": [
            _e("大盤覆盤週報｜本週加權指數走勢與量能，用數據幫你覆盤",
               "純數據回顧本週大盤漲跌、成交量與波動，不預測下週、不喊多空，只做客觀覆盤"),
            _e("大盤覆盤週報｜三大法人本週買賣超，數字告訴你資金往哪流",
               "整理法人買賣超與外資動向數據做客觀解讀，講資金流不當明牌，不喊追買"),
            _e("大盤覆盤週報｜融資融券本週變化，散戶籌碼的數據觀察",
               "用融資融券增減觀察散戶槓桿水位，純數據示警過熱風險，不預測漲跌"),
            _e("大盤覆盤週報｜本週類股輪動，哪些族群強弱?數據排排看",
               "用漲跌幅與量能排序類股強弱做客觀呈現，不推薦個股、不報目標價"),
        ],
    },
}

ORDER = ["A", "B", "C", "D"]   # 輪流取的軌道順序


# ─── 進度讀寫 ────────────────────────────────────────────────────────────────
def _load_progress():
    """讀進度；缺檔/壞檔一律優雅從頭。"""
    default = {"A": 0, "B": 0, "C": 0, "D": 0, "cursor": 0}
    if PROGRESS.exists():
        try:
            data = json.loads(PROGRESS.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in default:
                    if isinstance(data.get(k), int) and data[k] >= 0:
                        default[k] = data[k]
        except Exception:
            pass  # 壞檔 → 用預設(從頭)
    return default


def _save_progress(prog):
    try:
        PROGRESS.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[tw_series] ⚠️ 進度寫入失敗(不影響已注入題庫)：{exc}", file=sys.stderr)


def _get_topic_bank():
    """延遲 import：失敗印錯不崩(對齊防呆要求)。"""
    try:
        import topic_bank  # add_topics(items, source, front)
        return topic_bank
    except Exception as exc:  # noqa: BLE001
        print(f"[tw_series] ✗ 無法載入 topic_bank，本次不注入：{exc}", file=sys.stderr)
        return None


# ─── --next N：四軌輪流各取，湊 N 集注入題庫最前面 ───────────────────────────
def do_next(n, dry=False):
    n = max(1, int(n))
    prog = _load_progress()
    cursor = prog.get("cursor", 0)
    picks = []            # (key, name, episode, fmt)
    fmt_toggle = 0
    # 每次最多嘗試 n*軌數 圈；有限軌完結就跳過，D 循環永遠可取(不會空轉死迴圈)
    attempts, max_attempts = 0, n * len(ORDER) + len(ORDER)
    while len(picks) < n and attempts < max_attempts:
        key = ORDER[cursor % len(ORDER)]
        cursor += 1
        attempts += 1
        track = TRACKS[key]
        eps = track["episodes"]
        idx = prog.get(key, 0)
        if track["loop"]:                       # D 週報：循環取，永不完結
            ep = eps[idx % len(eps)]
            prog[key] = idx + 1
        else:
            if idx >= len(eps):                 # 此軌已完結 → 換下一軌
                continue
            ep = eps[idx]
            prog[key] = idx + 1
        fmt = "short" if fmt_toggle % 2 == 0 else "long"   # 輪短長
        fmt_toggle += 1
        picks.append((key, track["name"], ep, fmt))

    if not picks:
        print("[tw_series] 四軌皆無可取集數(理論上不會發生，D 軌循環)。")
        return 0

    print(f"[tw_series] --next {n}  四軌輪取 {len(picks)} 集(cursor {prog.get('cursor', 0)} → {cursor % len(ORDER)})")
    items = []
    for key, name, ep, fmt in picks:
        items.append({"title": ep["title"], "angle": ep["angle"],
                      "category": CAT, "format": fmt, "priority": "series"})
        done = prog[key] if TRACKS[key]["loop"] else prog[key]
        print(f"  [{key}·{name}·{fmt}] {ep['title']}  (該軌進度→{done})")

    if dry:
        print("  (--dry：不寫入題庫、不更新進度)")
        return 0

    tb = _get_topic_bank()
    if tb is None:
        return 0   # import 失敗已印錯，不更新進度(下次重試)
    try:
        added = tb.add_topics(items, source="tw_series", front=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[tw_series] ✗ add_topics 失敗，本次不更新進度：{exc}", file=sys.stderr)
        return 0

    prog["cursor"] = cursor % len(ORDER)
    _save_progress(prog)
    print(f"  → 實際注入題庫 {added} 題(front，category={CAT})，進度已更新。")
    return added


# ─── --boost：寫一條常駐 directive(前綴 tag 去重，可重跑覆蓋) ──────────────────
BOOST_DIRECTIVE = (
    "【常態產線｜台股回測實錄】固定每週優先產「台股回測實錄」系列續集(EP2、EP3…延續同一場長期回測劇情，"
    "金額/標的逐集升級：0050→高股息→台積電→大盤擇時→加碼攤平)，每集結尾留 cliffhanger 勾下一集。"
    "誠信鐵則：只做數據/回測/避雷，不喊單、不報明牌、不報目標價、不保證收益；個股只做數據分析。"
    "這是台股在地共鳴的爆款 franchise，優先於一般選題，別讓它斷。"
)


def do_boost(dry=False):
    def tag(s):
        return s.split("】")[0] + "】"

    d = {}
    if DIRPATH.exists():
        try:
            d = json.loads(DIRPATH.read_text(encoding="utf-8"))
        except Exception:
            d = {}
    if not isinstance(d, dict):
        d = {}
    ds = list(d.get("directives", []))
    ds = [x for x in ds if tag(x) != tag(BOOST_DIRECTIVE)] + [BOOST_DIRECTIVE]  # 前綴 tag 去重

    if dry:
        print(f"[tw_series] --boost --dry：將寫入 1 條常駐 directive(去重後共 {len(ds)} 條)：")
        print(f"  {BOOST_DIRECTIVE}")
        return 0

    d["directives"] = ds
    try:
        DIRPATH.parent.mkdir(parents=True, exist_ok=True)
        save_json_atomic(DIRPATH, d)
    except Exception as exc:  # noqa: BLE001
        print(f"[tw_series] ✗ boss_directives 寫入失敗：{exc}", file=sys.stderr)
        return 0
    print(f"[tw_series] --boost：常駐 directive 已寫入(去重後共 {len(ds)} 條)。")
    return 1


def do_status():
    prog = _load_progress()
    print("台股多軌連載進度：")
    for key in ORDER:
        t = TRACKS[key]
        idx = prog.get(key, 0)
        if t["loop"]:
            nxt = t["episodes"][idx % len(t["episodes"])]["title"]
            print(f"  [{key}] {t['name']}(循環)  已產 {idx} 次  下一則：{nxt}")
        else:
            total = len(t["episodes"])
            nxt = t["episodes"][idx]["title"] if idx < total else "(已完結)"
            print(f"  [{key}] {t['name']}  {idx}/{total}  下一集：{nxt}")
    print(f"  下輪起始軌 cursor={prog.get('cursor', 0)}（{ORDER[prog.get('cursor', 0) % len(ORDER)]}）")


def main():
    ap = argparse.ArgumentParser(description="台股多軌連載引擎：四軌並行輪流注入題庫")
    ap.add_argument("--next", type=int, default=None, metavar="N",
                    help="四軌輪流取共 N 集，注入題庫最前面(預設 4=四軌各一)")
    ap.add_argument("--boost", action="store_true",
                    help="寫一條常駐 directive 到 boss_directives(每週優先產台股回測實錄續集)")
    ap.add_argument("--status", action="store_true", help="印四軌進度")
    ap.add_argument("--dry", action="store_true", help="只印不寫(驗證邏輯用)")
    args = ap.parse_args()

    if args.status:
        do_status()
        return

    did = False
    if args.boost:
        do_boost(dry=args.dry)
        did = True
    if args.next is not None or not did:
        do_next(args.next if args.next is not None else 4, dry=args.dry)


if __name__ == "__main__":
    main()
