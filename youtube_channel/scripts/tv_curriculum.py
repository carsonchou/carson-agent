#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tv_curriculum.py — 【TradingView 全攻略｜課程脊椎引擎 + 無限審查流】

把「技術指標／策略」做成一套**有序連載課程**(由淺入深)＋一條**永動的打假審查流**,
餵進既有 topic_bank 題庫,讓 produce_batch 一集一集照課程往下產,同時源源不絕產出
《拆穿》熱門腳本回測題。**本檔只做「注入題庫」這一件事,不碰渲染/發布/雲端。**

三塊:
  (1) CURRICULUM — 有序課程資料(list,照此順序=由淺入深)。指標教學 EP1~EP64、策略回測 EP65~EP78。
  (2) --next N   — 讀進度,找接下來 N 個「未注入」的 EP,依序 add_topics(front=True) 插到題庫最前,
                   更新進度。依序、不跳、不重複。cron 每天 --next 2 就照課程往下走。
  (3) --review N — 內建 100+ 支熱門 TradingView 指標/策略種子,每次挑 N 個沒審過的轉成
                   《拆穿》回測題(category=拆穿打假)插到題庫最前,記錄去重。永動題源。

用法:
  python scripts/tv_curriculum.py --next 2            # 注入接下來 2 個課程 EP
  python scripts/tv_curriculum.py --next 2 --dry      # 只印不寫(驗證邏輯)
  python scripts/tv_curriculum.py --review 3          # 產 3 個審查打假題
  python scripts/tv_curriculum.py --review 3 --dry    # 只印不寫

進度檔:
  STUDIO/tv_curriculum_progress.json  {"index": 已注入到第幾個(0-based 個數)}
  STUDIO/tv_reviewed.json             {"reviewed": [已審過的種子名...]}

驗證:
  python -m py_compile scripts/tv_curriculum.py
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
STUDIO = ROOT / "STUDIO"
PROGRESS = STUDIO / "tv_curriculum_progress.json"
REVIEWED = STUDIO / "tv_reviewed.json"

import topic_bank  # add_topics(items, source, front) — 內建與題庫＋既有影片去重

CAT_IND = "指標教學"   # → produce_batch CURRICULUM_RULES
CAT_STR = "策略回測"   # → produce_batch CURRICULUM_RULES
CAT_DEBUNK = "拆穿打假"  # → produce_batch DEBUNK_RULES(含「拆穿」「打假」字樣)


def _c(ep, title, category, fmt, angle, multi=False):
    return {"ep": ep, "title": title, "category": category,
            "format": fmt, "angle": angle, "multi": multi}


# ─────────────────────────────────────────────────────────────────────────────
# (1) 有序課程資料 CURRICULUM — 照此順序 = 由淺入深。每項 = 一集 = 一支影片。
#     multi=True 表示屬於某個多集深潛子系列(仍各自為獨立一集)。
#     標題:可搜尋長尾關鍵字放前段 + 一句點擊鉤;不誇大不喊單不保證收益。
# ─────────────────────────────────────────────────────────────────────────────
CURRICULUM = [
    # ── 指標教學:入門均線與經典震盪 ──
    _c(1, "均線是什麼?MA 均線 3 分鐘看懂+我回測揭它何時最會騙你", CAT_IND, "long",
       "從零講均線,先教會看再用回測打臉「均線交叉一定賺」的迷思", multi=True),
    _c(2, "SMA vs EMA 差在哪?均線多空排列與黃金死亡交叉一次搞懂", CAT_IND, "long",
       "把兩種均線並排回測,直接看誰反應快、誰假訊號少", multi=True),
    _c(3, "MACD 是什麼?柱狀圖+黃金交叉 3 分鐘看懂(附 10 年回測)", CAT_IND, "long",
       "MACD 三件套講清楚,回測黃金交叉真實勝率別再迷信", multi=True),
    _c(4, "MACD 背離怎麼看?頂背離底背離抓轉折,回測告訴你準不準", CAT_IND, "long",
       "背離是進階招牌,實測它到底領先還是後知後覺", multi=True),
    _c(5, "RSI 是什麼?3 分鐘看懂超買超賣+回測揭它何時失靈", CAT_IND, "short",
       "RSI 70/30 迷思,震盪盤好用、單邊盤害死人,用回測證明"),
    _c(6, "KD 隨機指標怎麼看?黃金交叉買點+新手最常踩的雷", CAT_IND, "short",
       "KD 鈍化陷阱,教你別在強勢股上被 KD 騙下車"),
    _c(7, "布林通道是什麼?上下軌+中軌用法 3 分鐘上手", CAT_IND, "short",
       "布林收口噴出的真相,回測看碰上軌到底該追還是該跑"),
    _c(8, "成交量怎麼看?量價關係 5 個訊號新手先學這個", CAT_IND, "short",
       "量先價行的實測,揭穿爆量不一定是好事"),
    _c(9, "支撐與壓力怎麼畫?3 分鐘學會找進出場關鍵價位", CAT_IND, "short",
       "支撐壓力互換,教你畫得對不對怎麼驗證"),
    _c(10, "趨勢線與通道怎麼畫?一條線判多空的正確畫法", CAT_IND, "short",
        "趨勢線畫法人人不同,給一套可回測的客觀規則"),
    # ── 指標教學:進階震盪與動能 ──
    _c(11, "CCI 順勢指標是什麼?±100 突破怎麼用一次搞懂", CAT_IND, "short",
        "CCI 抓乖離,實測突破 100 追多的勝率"),
    _c(12, "威廉指標 %R 怎麼看?和 KD 差在哪、哪個更靈敏", CAT_IND, "short",
        "%R 與 KD 對比,回測哪個假訊號少"),
    _c(13, "StochRSI 是什麼?比 RSI 更靈敏的用法與陷阱", CAT_IND, "short",
        "StochRSI 太敏感反而亂,教你怎麼馴服它"),
    _c(14, "DMI 與 ADX 怎麼看?判斷有沒有趨勢的關鍵指標", CAT_IND, "short",
        "ADX 過濾盤整,回測加上它假訊號少多少"),
    _c(15, "SAR 拋物線指標怎麼用?停損轉向點一看就懂", CAT_IND, "short",
        "SAR 移動停利,實測震盪盤被它來回甩巴掌"),
    _c(16, "乖離率 BIAS 是什麼?股價偏離均線太多會回檔嗎", CAT_IND, "short",
        "BIAS 抓超漲超跌,回測負乖離抄底的下場"),
    _c(17, "TRIX 三重指數平滑怎麼用?過濾雜訊的長線指標", CAT_IND, "short",
        "TRIX 濾雜訊代價是慢半拍,實測值不值"),
    _c(18, "MTM 與 ROC 動量指標是什麼?抓加速度的用法", CAT_IND, "short",
        "動量領先價格?回測驗證這個說法"),
    _c(19, "動能震盪指標 AO 怎麼看?比爾威廉斯的紅綠柱用法", CAT_IND, "short",
        "AO 零軸與雙峰,實測它的買賣訊號成色"),
    _c(20, "終極震盪指標怎麼用?三週期合一的超買超賣訊號", CAT_IND, "short",
        "Ultimate Oscillator 背離,回測它比 RSI 強在哪"),
    # ── 指標教學:波動與量能 ──
    _c(21, "ATR 真實波幅是什麼?用它設停損停利才不會被洗掉", CAT_IND, "short",
        "ATR 設停損才是專業做法,教你 2 倍 ATR 怎麼算"),
    _c(22, "肯特納通道是什麼?和布林通道差在哪、怎麼選", CAT_IND, "short",
        "Keltner 用 ATR、布林用標準差,實測兩者訊號差異"),
    _c(23, "唐奇安通道是什麼?海龜交易法的突破神器", CAT_IND, "short",
        "Donchian 20 日高低,回測海龜突破現在還有效嗎"),
    _c(24, "OBV 能量潮是什麼?用成交量抓主力進出的用法", CAT_IND, "short",
        "OBV 量能背離,實測它預告轉折準不準"),
    _c(25, "MFI 資金流量指標怎麼看?加了成交量的 RSI", CAT_IND, "short",
        "MFI 抓資金超買超賣,回測它比 RSI 準嗎"),
    _c(26, "VWAP 成交量加權均價是什麼?當沖必看的成本線", CAT_IND, "short",
        "VWAP 是機構成本線,教你當沖怎麼用它做多空分界"),
    _c(27, "騰落線 A/D Line 怎麼看?判斷資金是進還是出", CAT_IND, "short",
        "A/D 線量價配合,實測它的背離訊號"),
    _c(28, "蔡金資金流 CMF 是什麼?抓買賣壓力的指標", CAT_IND, "short",
        "Chaikin Money Flow 零軸多空,回測它的成色"),
    _c(29, "量價背離怎麼看?價創新高量卻縮的危險訊號", CAT_IND, "short",
        "量價背離抓頭部,實測它的預警力"),
    # ── 指標教學:型態與價格結構 ──
    _c(30, "費波那契回撤怎麼畫?0.618 黃金分割抓回檔支撐", CAT_IND, "short",
        "Fib 回撤畫法,回測 0.618 支撐真的比較容易站上嗎"),
    _c(31, "費波延伸與扇形怎麼用?抓目標價與時間週期", CAT_IND, "short",
        "Fib 延伸抓目標,實測它預測滿足點的準度"),
    _c(32, "樞軸點 Pivot Point 是什麼?當沖抓支撐壓力的公式", CAT_IND, "short",
        "Pivot 自動算關卡,教你當沖用 S1/R1 進出"),
    _c(33, "缺口理論怎麼看?跳空缺口會不會回補一次搞懂", CAT_IND, "short",
        "普通/突破/竭盡缺口分類,回測缺口回補機率"),
    _c(34, "K 線怎麼看?單根 K 棒 12 種訊號新手先學這個", CAT_IND, "long",
        "從一根 K 棒讀多空,槌子/流星/十字星實測成色", multi=True),
    _c(35, "K 線組合型態怎麼看?吞噬、晨昏星、母子線一次學會", CAT_IND, "long",
        "組合型態才是重點,回測哪些反轉訊號真的有用", multi=True),
    _c(36, "頭肩頂與雙重頂怎麼看?經典反轉型態實戰畫法+回測", CAT_IND, "long",
        "型態學招牌,實測頭肩頂跌幅滿足點準不準"),
    # ── 指標教學:大系統(多集深潛) ──
    _c(37, "一目均衡表是什麼?雲層+五線一次看懂(上)", CAT_IND, "long",
        "Ichimoku 五條線先講清楚,雲層厚薄的意義", multi=True),
    _c(38, "一目均衡表雲層怎麼用?三役好轉與雲上雲下(中)", CAT_IND, "long",
        "雲上做多雲下做空,實測三役好轉的勝率", multi=True),
    _c(39, "一目均衡表實戰回測:它到底適合震盪還是趨勢(下)", CAT_IND, "long",
        "把一目均衡表策略化回測,揭它的真實舞台", multi=True),
    _c(40, "三重濾網交易系統是什麼?Elder 大師的多週期過濾(上)", CAT_IND, "long",
        "Triple Screen 三層邏輯,週線定調日線進場", multi=True),
    _c(41, "三重濾網實戰回測:多週期共振真的能提高勝率嗎(下)", CAT_IND, "long",
        "把三重濾網做成策略回測,驗證共振是不是玄學", multi=True),
    _c(42, "艾略特波浪理論是什麼?五升三降一次入門(一)", CAT_IND, "long",
        "Elliott Wave 基本數法,先看懂 12345 abc", multi=True),
    _c(43, "艾略特波浪怎麼數?推動浪三大鐵律與常見數錯(二)", CAT_IND, "long",
        "數浪三鐵律,揭穿為什麼十個人數出十種浪", multi=True),
    _c(44, "艾略特調整浪怎麼看?鋸齒、平台、三角形一次搞懂(三)", CAT_IND, "long",
        "調整浪型態,實戰怎麼避免數浪自嗨", multi=True),
    _c(45, "艾略特波浪能拿來交易嗎?回測與可證偽性大檢驗(四)", CAT_IND, "long",
        "波浪理論的死穴:事後諸葛,用可證偽角度拆它", multi=True),
    _c(46, "纏論是什麼?筆、線段、中樞從零入門(一)", CAT_IND, "long",
        "纏中說禪基本概念,把玄學講成可操作規則", multi=True),
    _c(47, "纏論中樞怎麼畫?三買三賣點的判定(二)", CAT_IND, "long",
        "中樞是纏論核心,教你客觀畫出來", multi=True),
    _c(48, "纏論背馳怎麼看?MACD 面積判斷力竭轉折(三)", CAT_IND, "long",
        "背馳用 MACD 量化,實測它的轉折預警", multi=True),
    _c(49, "纏論能賺錢嗎?把它策略化回測看真實成色(四)", CAT_IND, "long",
        "纏論最大爭議是主觀,用回測逼它交出數據", multi=True),
    _c(50, "威科夫理論是什麼?供需與主力行為入門(上)", CAT_IND, "long",
        "Wyckoff 量價邏輯,讀懂主力的意圖", multi=True),
    _c(51, "威科夫吸籌派發怎麼看?累積與出貨的九大事件(中)", CAT_IND, "long",
        "吸籌區間 Spring/UTAD,實戰怎麼辨識", multi=True),
    _c(52, "威科夫實戰回測:量價分析到底是不是後見之明(下)", CAT_IND, "long",
        "把威科夫事件量化驗證,揭它的可操作性", multi=True),
    # ── 指標教學:另類技術與圖表 ──
    _c(53, "江恩理論是什麼?時間與價格的角度線入門", CAT_IND, "short",
        "Gann 角度線與時間週期,理性看待這套神秘學"),
    _c(54, "訂單流 Footprint 是什麼?看穿每一筆買賣的掛單圖", CAT_IND, "short",
        "Order Flow 足跡圖,教你讀主動買賣失衡"),
    _c(55, "市場輪廓 Market Profile 是什麼?TPO 價值區用法", CAT_IND, "short",
        "Market Profile POC 與價值區,判斷公平價"),
    _c(56, "籌碼面怎麼看?主力、法人、散戶籌碼分佈入門", CAT_IND, "short",
        "籌碼安定度,教你別和主力對做"),
    _c(57, "Renko 磚形圖是什麼?過濾時間雜訊只看價格波動", CAT_IND, "short",
        "Renko 只認價格,實測它讓趨勢更乾淨還是更遲鈍"),
    _c(58, "點數圖 PnF 是什麼?百年前的純價格圖表怎麼用", CAT_IND, "short",
        "Point & Figure 圈叉圖,教你算目標價"),
    _c(59, "平均 K 線 Heikin Ashi 是什麼?讓趨勢更平滑的畫法", CAT_IND, "short",
        "Heikin Ashi 濾雜訊,提醒它會延遲進出場"),
    _c(60, "成交量分佈 Volume Profile 怎麼看?找真正的支撐壓力", CAT_IND, "long",
        "Volume Profile POC/VAH/VAL,用成交量畫出關鍵價區"),
    _c(61, "SuperTrend 是什麼?一條線判多空的當紅指標+回測", CAT_IND, "short",
        "Supertrend 用 ATR 抓趨勢,實測它震盪盤的死穴"),
    _c(62, "自動樞軸點指標怎麼用?TradingView 內建的關卡神器", CAT_IND, "short",
        "Auto Pivot 免手畫,教你當沖直接用"),
    _c(63, "自動費波與型態辨識指標:TradingView 幫你畫線靠譜嗎", CAT_IND, "short",
        "Auto Fib/Pattern,揭穿自動畫線的坑"),
    _c(64, "PineScript 內建腳本怎麼看?看懂原始碼別被指標騙", CAT_IND, "short",
        "教你打開指標原始碼,自己驗證它到底在算什麼"),

    # ── 策略回測(全 long,回測驗證+拆穿) ──
    _c(65, "均線交叉策略能賺嗎?黃金交叉當買點回測 10 年真相", CAT_STR, "long",
        "最經典的均線交叉,用長期回測揭它的真實績效與大回撤"),
    _c(66, "MACD 策略回測:黃金交叉進場到底賺不賺?", CAT_STR, "long",
        "MACD 交叉策略化,實測勝率、盈虧比與最大回撤"),
    _c(67, "RSI 策略能賺嗎?超賣買超買賣的回測結果打臉直覺", CAT_STR, "long",
        "RSI 反轉策略,揭它在單邊行情如何被輾壓"),
    _c(68, "SuperTrend 策略回測:一條線跟單真的能穩定獲利嗎?", CAT_STR, "long",
        "Supertrend 跟單策略,實測震盪盤的來回虧損"),
    _c(69, "布林通道策略能賺嗎?碰上下軌反轉 vs 突破回測對決", CAT_STR, "long",
        "布林反轉派 vs 突破派,回測誰才對"),
    _c(70, "通道突破策略回測:突破買進到底是聖杯還是陷阱?", CAT_STR, "long",
        "Breakout 策略,揭穿假突破如何吃掉利潤"),
    _c(71, "動能策略能賺嗎?追強棄弱的動量交易回測真相", CAT_STR, "long",
        "Momentum 追強勢,實測動能因子的真實 edge"),
    _c(72, "SAR 策略回測:拋物線轉向跟單會被甩巴掌嗎?", CAT_STR, "long",
        "SAR 移動停利策略,回測它的頻繁進出成本"),
    _c(73, "連續漲跌策略能賺嗎?連跌幾天抄底的回測結果", CAT_STR, "long",
        "連續 N 根 K 反轉,實測均值回歸策略的成色"),
    _c(74, "波動停損策略回測:用 ATR 設停損能救回績效嗎?", CAT_STR, "long",
        "把 ATR 停損加進策略,實測風控對績效的影響"),
    _c(75, "海龜交易法能賺嗎?唐奇安通道突破回測現代版真相", CAT_STR, "long",
        "Turtle 突破系統,揭這套經典法則現在還靈不靈"),
    _c(76, "網格策略回測:震盪盤躺著賺是真的嗎?(本命實測)", CAT_STR, "long",
        "網格是頻道本命,實測它在震盪賺、單邊套的真相與參數"),
    _c(77, "馬丁格爾攤平能賺嗎?越跌越買的策略回測有多危險", CAT_STR, "long",
        "Martingale 攤平,用回測示範它如何一次歸零"),
    _c(78, "金字塔加碼策略回測:順勢加碼真的放大獲利嗎?", CAT_STR, "long",
        "Pyramiding 加碼,實測順勢加碼的甜蜜點與反噬"),
]


# ─────────────────────────────────────────────────────────────────────────────
# (3) 無限審查流種子 REVIEW_SEED — 100+ 支熱門 TradingView 公開指標/策略名。
#     每個轉成《拆穿》回測題,永續供應打假題源。
# ─────────────────────────────────────────────────────────────────────────────
REVIEW_SEED = [
    # SuperTrend 家族與趨勢跟隨
    "SuperTrend", "SuperTrend AI (Clustering)", "SuperTrended Moving Averages",
    "Multi-Timeframe SuperTrend", "Pivot SuperTrend", "SuperTrend Oscillator",
    # UT Bot / ATR 跟隨
    "UT Bot Alerts", "UT Bot + STC Strategy", "ATR Trailing Stop", "Chandelier Exit",
    # SSL / Hull / 特殊均線
    "SSL Channel", "SSL Hybrid", "Hull Moving Average", "Hull Suite",
    "HalfTrend", "QQE MOD", "QQE Signals", "Wavetrend Oscillator",
    "McGinley Dynamic", "ALMA (Arnaud Legoux)", "Kaufman Adaptive MA (KAMA)",
    "Jurik Moving Average (JMA)", "T3 Moving Average", "TEMA / DEMA",
    "Rolling VWAP", "Anchored VWAP", "VWAP Bands",
    # 擠壓與波動
    "TTM Squeeze", "Squeeze Momentum (LazyBear)", "Bollinger Band Width",
    "Bollinger Bands %B", "Keltner Channel Strategy", "Volatility Stop",
    # VuManChu / Cipher 家族
    "VuManChu Cipher A", "VuManChu Cipher B", "Market Cipher B clone",
    "WaveTrend with Crosses",
    # 機器學習 / 進階花俏
    "Machine Learning: Lorentzian Classification", "Machine Learning kNN",
    "Nadaraya-Watson Envelope", "Nadaraya-Watson Smoothers",
    "Logistic Regression Signal", "Neural Network Overlay",
    "AI Trend Navigator", "Gaussian Channel", "Range Filter",
    "Reversal Signals (AlgoAlpha)", "Smart Money Concepts (LuxAlgo)",
    "LuxAlgo Premium Signals clone", "Order Blocks Indicator",
    "Fair Value Gap (FVG)", "Liquidity Sweeps", "Break of Structure (BOS/CHoCH)",
    "ICT Silver Bullet", "ICT Killzones", "Market Structure (SMC)",
    # 經典震盪/量能拆解
    "RSI Divergence Indicator", "Stochastic RSI Strategy", "MACD Divergence",
    "CCI Strategy", "Awesome Oscillator Strategy", "Fisher Transform",
    "Connors RSI", "Relative Vigor Index", "Elder Impulse System",
    "TSI (True Strength Index)", "Coppock Curve", "Vortex Indicator",
    "Chaikin Money Flow Strategy", "Money Flow Index Strategy",
    "On Balance Volume Strategy", "Volume Weighted MACD", "Klinger Oscillator",
    "Ease of Movement", "Accumulation/Distribution Strategy",
    # 型態/結構/自動畫線
    "Auto Fibonacci Retracement", "Auto Support & Resistance",
    "Harmonic Patterns (Gartley/Bat)", "ZigZag Indicator", "Auto Trendlines",
    "Pitchfork (Andrews)", "Elliott Wave Auto Count", "Supply and Demand Zones",
    "Order Flow Footprint", "Volume Profile / Fixed Range", "TPO Market Profile",
    "Renko Overlay", "Heikin Ashi Strategy", "Pivot Points Standard",
    # 熱門完整策略
    "Golden Cross Strategy (50/200)", "3 EMA Crossover Strategy",
    "Triple SuperTrend Strategy", "MACD + RSI Combo Strategy",
    "Ichimoku Cloud Strategy", "Turtle Trading (Donchian) Strategy",
    "Bollinger + RSI Mean Reversion", "Parabolic SAR Strategy",
    "Scalping 1-Minute EMA Strategy", "Scalping RSI + Stoch Strategy",
    "Breakout Box Strategy", "Opening Range Breakout (ORB)",
    "London Breakout Strategy", "Grid Trading Bot Strategy",
    "Martingale Strategy", "Anti-Martingale / Pyramiding Strategy",
    "DCA Bot Strategy", "Mean Reversion Bollinger Strategy",
    "Trend Following Donchian Strategy", "Momentum Rotation Strategy",
    "Supertrend + EMA Scalper", "9/21 EMA Scalping Strategy",
    "Heikin Ashi + Supertrend Strategy", "QQE + SSL Strategy",
    "Range Filter Buy Sell Strategy", "Lorentzian Strategy",
    "Chandelier Exit + ZLSMA Strategy", "SMC + FVG Strategy",
    "3Commas Composite Signal", "WunderTrading Signal Bot",
    "Pine Connector Auto-Trade", "Consecutive Candles Reversal",
    "RSI-2 (Larry Connors) Strategy", "PSAR + MACD Strategy",
    "VWAP Bounce Scalping Strategy", "Fibonacci Golden Zone Strategy",
]


# ─── 進度/去重讀寫 ────────────────────────────────────────────────────────────
def _load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def _save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── (2) --next N:依序注入接下來 N 個未注入的課程 EP ──────────────────────────
def do_next(n, dry=False):
    prog = _load_json(PROGRESS, {"index": 0})
    idx = int(prog.get("index", 0))
    batch = CURRICULUM[idx:idx + n]
    if not batch:
        print(f"[tv_curriculum] 課程已全部注入完畢(共 {len(CURRICULUM)} 集),無新 EP。")
        return 0
    items = [{"title": c["title"], "angle": c["angle"],
              "category": c["category"], "format": c["format"]} for c in batch]

    print(f"[tv_curriculum] --next {n}  進度 index={idx} → {idx + len(batch)} / 共 {len(CURRICULUM)} 集")
    for c in batch:
        tag = "long·multi" if c["multi"] else c["format"]
        print(f"  EP{c['ep']:>2} [{c['category']}·{tag}] {c['title']}")

    if dry:
        print("  (--dry:不寫入題庫、不更新進度)")
        return 0

    added = topic_bank.add_topics(items, source="tv_curriculum", front=True)
    prog["index"] = idx + len(batch)
    _save_json(PROGRESS, prog)
    print(f"  → 實際注入題庫 {added} 題(front),進度已更新 index={prog['index']}")
    return added


# ─── (3) --review N:挑 N 個沒審過的種子轉《拆穿》題注入 ───────────────────────
_REVIEW_TEMPLATES = [
    "《拆穿》｜回測『{name}』這支 TradingView 熱門指標真能賺嗎?",
    "《拆穿》｜『{name}』被吹爆的 TradingView 神器,我回測拆給你看",
    "《拆穿》｜熱門腳本『{name}』真的穩賺?免費回測打臉行銷話術",
    "《拆穿》｜『{name}』到底能不能賺?我用歷史數據幫你先試",
]


def do_review(n, dry=False):
    state = _load_json(REVIEWED, {"reviewed": []})
    done = set(state.get("reviewed", []))
    pending = [s for s in REVIEW_SEED if s not in done]
    if not pending:
        print(f"[tv_curriculum] 種子已全部審完(共 {len(REVIEW_SEED)} 支),可再擴充 REVIEW_SEED。")
        return 0
    picks = pending[:n]
    items = []
    print(f"[tv_curriculum] --review {n}  待審 {len(pending)} / 共 {len(REVIEW_SEED)} 支")
    for i, name in enumerate(picks):
        title = _REVIEW_TEMPLATES[i % len(_REVIEW_TEMPLATES)].format(name=name)
        angle = f"用免費回測拆穿『{name}』的真實勝率與最大回撤,揭露它什麼時候會騙你,幫小白避雷"
        items.append({"title": title, "angle": angle,
                      "category": CAT_DEBUNK, "format": "short"})
        print(f"  審 [{CAT_DEBUNK}·short] {title}")

    if dry:
        print("  (--dry:不寫入題庫、不更新已審清單)")
        return 0

    added = topic_bank.add_topics(items, source="tv_review", front=True)
    state["reviewed"] = list(done) + picks
    _save_json(REVIEWED, state)
    print(f"  → 實際注入題庫 {added} 題(front),已審計數 {len(state['reviewed'])} / {len(REVIEW_SEED)}")
    return added


def main():
    ap = argparse.ArgumentParser(description="TradingView 全攻略課程脊椎引擎 + 無限審查流")
    ap.add_argument("--next", type=int, default=None, metavar="N",
                    help="依序注入接下來 N 個未注入的課程 EP(預設 2)")
    ap.add_argument("--review", type=int, default=None, metavar="N",
                    help="挑 N 個沒審過的熱門腳本轉《拆穿》題注入")
    ap.add_argument("--dry", action="store_true", help="只印不寫(驗證邏輯用)")
    ap.add_argument("--status", action="store_true", help="印出目前進度與待審數")
    args = ap.parse_args()

    if args.status:
        prog = _load_json(PROGRESS, {"index": 0})
        state = _load_json(REVIEWED, {"reviewed": []})
        idx = int(prog.get("index", 0))
        nxt = CURRICULUM[idx]["title"] if idx < len(CURRICULUM) else "(已完課)"
        print(f"課程進度:{idx}/{len(CURRICULUM)}  下一集:{nxt}")
        print(f"審查進度:{len(state.get('reviewed', []))}/{len(REVIEW_SEED)}")
        return

    did = False
    if args.review is not None:
        do_review(max(1, args.review), dry=args.dry)
        did = True
    if args.next is not None or not did:
        do_next(args.next if args.next is not None else 2, dry=args.dry)


if __name__ == "__main__":
    main()
