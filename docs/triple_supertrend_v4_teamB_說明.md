# Triple SuperTrend v5 — 說明文件（VT-Core + 校準 R 基準 + 雙段 Partial TP）

> 本策略無內建回測引擎，所有效益均為「機制推導 / 預期 / 需 walk-forward 與多商品驗證」，嚴禁當作既成績效。預設值為穩健起點，禁止 per-symbol 調參。

---

## 一、v4 弱點盤點（三輪互評共識）

以 Build#1（voltarget）為冠軍骨架，但三輪評審仍點名以下弱點，v5 全數修正或補強：

| 編號 | v4 弱點 | 影響面 | 嚴重度 |
|---|---|---|---|
| W1 | `entryATR := atrChand`（出場 ATR）作為 R 分母，與「初始止損距離」脫節 → R=1 保本/時間止損/R 階梯收緊全部以錯誤尺度觸發 | Calmar/Sharpe（出場時機全偏移） | 真 bug，最高優先 |
| W2 | `useER/useADX/useSlowST` 全關時 `votesLong=0 < minVotes` 永不進場（toggle 交互陷阱） | 介面誤操作即鎖死策略 | 介面健壯性 |
| W3 | `regimeLongOK` 同時要求 `votes>=minVotes` 與 `diPlus>diMinus`，再疊 ST3 慢閘 → 方向雙重閘＝過濾過頭＝另一種過擬合，殺交易數傷泛化 | 樣本顯著性/泛化 | 抗過擬合 |
| W4 | 缺主動 R-multiple 落袋，只有 ST 反向逐段減倉（cut），落袋平滑度弱，無法截斷「大賺單回吐成平手」右尾 | Sharpe（權益曲線平滑度） | 缺口 |

---

## 二、v5 每項改動的 why 與預期影響

### 修正1 — R 基準對齊（W1，真 bug）
- **改動**：`§6` 新增 `var float entryRisk`；`§11` 兩處首單進場（L1/S1）把原 `entryATR := atrChand` 改為 `entryRisk := chandMult * atrChand`；`§8` R 分母 `rDenom = na(entryRisk) ? (chandMult*atrChand) : entryRisk`。
- **why**：Chandelier 初始止損距離 = `chandMult × atrChand`。v4 用「裸 atrChand」當 R 分母，使 R=1 僅等於 1/3 真實初始風險（chandMult 預設 3），導致保本(kBE=1R)、時間止損(R<1)、R 階梯(R<1/<2) 全部過早觸發。
- **不照抄 Build#2**：Build#2 用 `3×ATR` 但其 chandMult 語意不同，會使 1R=3ATR、全體出場偏晚（被三輪點名的語意 bug）。v5 目標是 **R=1 對應真實 1 倍初始止損距離**，尺度精確對齊。
- **預期影響**：保本/時間止損/階梯收緊回到正確尺度 → 預期改善 Calmar（不再過早砍未成形趨勢）、提升 Sharpe（出場時機與設計初衷一致）。**需 walk-forward 驗證**：修正後 1R 觸發點與初始止損距離一致（可用儀表板「目前 R」對照「距停損」自察）。

### 修正2 — 投票全關防鎖死（W2）
- **改動**：`§5` 新增 `enabledVotes = (useER?1:0)+(useADX?1:0)+(useSlowST?1:0)`、`effMinVotes = math.min(minVotes, enabledVotes)`；通過判定 `voteLongPass = enabledVotes==0 ? true : votesLong>=effMinVotes`（空單鏡像）。
- **why**：minVotes 動態 clamp 至已啟用票數，避免「啟用 1 票卻要求 2 票」永不進場；啟用票數=0 時退回純 ST 對照（true），讓使用者可單測 ST 基準。
- **預期影響**：介面健壯性提升，無績效成本（預設三票全開時 effMinVotes=minVotes=2，行為不變）。

### 修正3 — 方向雙重閘鬆綁（W3，抗過擬合）
- **改動**：`§1` 新增 `useDIgate` bool（預設 true）；`§5` `diLongOK = not useDIgate or dirLong`（空單鏡像），regimeLongOK 用 `diLongOK`。
- **why**：保留 DI 方向閘但設為可關，供回測對照其邊際貢獻。三輪評審皆警示「濾過頭=另一種過擬合」。minVotes 預設仍 2、DI 閘預設仍開，但不再強制疊死。
- **預期影響**：提供關閉 DI 閘的對照組以量測其對交易數/泛化的邊際貢獻。**驗收須確認 minVotes=2 時樣本內交易數 >100 筆**。

### 嫁接 — Build#2 雙段 Partial TP（W4 缺口）
- **改動**：`§1` 新增 `usePartialTP/tp1R/tp1Pct/tp2R/tp2Pct`；`§6` 新增 `var bool tp1Done/tp2Done`；`§10` 在 cut 之前插入 R-multiple 落袋：`R>=tp1R 且 not tp1Done` → 平 tp1Pct、鎖 tp1Done；`R>=tp2R` 同理。
- **嫁接守則（修正 Build#2 自身 desync bug）**：
  - (a) **只對當前方向 id 下單**：long 只 `strategy.close("L*")`，避免 Build#2 同棒 close L+S 的草率。
  - (b) **one-shot 鎖**：tp1Done/tp2Done 各只觸發一次。
  - (c) **bool 同步不污染 stage**：`qty_percent` 為部位整體比例、不必然清空任一層，故 **partial TP 預設不翻 lXOn**（避免把仍在場的層誤標 false）；保留 `stage=opentrades` 對帳欄可即時自察是否 desync。
  - (d) **歸零**：`not inPos` 區與 `clearAll()` 兩處補 `tp1Done:=false / tp2Done:=false`。
  - (e) **與 cut 並存互補**：原 ST 反向逐段減倉（cut）拆出為 `usePartialST` 獨立開關，整層平掉才翻 bool。TP 管獲利落袋、cut 管趨勢轉弱減碼。
- **預期影響**：主動截斷「大賺單回吐」右尾 → 預期平滑權益曲線、**提升 Sharpe**（需驗證）；保留核心倉跑右尾 → 對 Calmar 影響中性偏正。**驗收須比對 usePartialTP on/off 的邊際貢獻**。

### 保留 Build#1 全部優勢（不動）
percentile 相對 vol floor + floorHits/capHits 監控、qtyFor 單一出口非負非 NaN、barsPerYear/brakeLen input 化、多空鏡像 votesLong/votesShort、debug 對帳欄（新增 effMinVotes 與 TP 鎖顯示）、ratchet Chandelier + R 階梯 + 保本 + hardStop 防跳空、五分組中文 tooltip、右上角儀表板（新增「止盈進度」列）。

---

## 三、參數表（重點）

| 群組 | 參數 | 預設 | 範圍 | 用途 |
|---|---|---|---|---|
| 趨勢 | baseLen | 10 | 7–20 | 三條 ST 共用基礎週期 |
| 趨勢 | midMult/slowMult | 2.5/6.0 | — | 1:2.5:6 派生倍率 |
| Regime | minVotes | 2 | 1–3 | 動態 clamp 至啟用票數 |
| Regime | useDIgate | true | bool | DI 方向閘可關（修正3） |
| 倉位 | targetVol | 15% | 8–30% | 年化目標波動 |
| 倉位 | barsPerYear | 365 | 24–8760 | 年化因子（加密365/股指252/4H2190） |
| 倉位 | maxGross | 1.5 | 1.0–3.0 | 總槓桿硬上限 |
| 出場 | chandMult | 3.0 | 2.0–4.0 | 初始止損距離＝R 分母（修正1） |
| 出場 | tp1R/tp1Pct | 1.0/25% | — | 第一段落袋 |
| 出場 | tp2R/tp2Pct | 2.0/25% | — | 第二段落袋 |

---

## 四、介面操作說明

- **五分組 input**：趨勢 / Regime 閘門 / 倉位 Vol-Target / 出場 Exit / 視覺化，每項皆有中文 tooltip 與 min/max/step。
- **bool 開關**：Regime gate、各投票、DI 閘、vol-target、vol-brake、Chandelier、R 階梯、保本、雙段 Partial TP、ST 減倉(cut)、時間止損、hardStop，以及所有視覺元素。
- **右上角儀表板**：市場狀態（趨勢▲多/▼空 或 盤整）、持倉方向/階段、停損價、距停損、波動倉位、年化波動（含⛔煞車）、目前 R、止盈進度（TP1✓/TP2✓）。
- **除錯欄**（showDebug）：ER、ADX、votesL/S(eff 門檻)、stage=opentrades 對帳、floorHits、capHits、TP1/2 done。
- **換週期務必同步調 barsPerYear**，否則年化失真。

---

## 五、驗證清單（交付驗收）

1. **編譯**：Pine v5；ta.supertrend([value,dir], dir<0=多)、ta.dmi 三元組、ta.median/percentile 皆合法；plot/plotshape/bgcolor/table 全在 global scope；無未定義/重複宣告；qty 經 `math.max(nz(q,0),0)`＋close>0＋maxGross clamp，非負非 NaN。
2. **修正1 自察**：進場後用儀表板「目前 R」對照「距停損」，確認 1R 觸發點與初始止損距離（chandMult×ATR）一致。
3. **修正2 自察**：關掉任意投票開關，確認不鎖死（除錯欄 effMinVotes 隨啟用票數下調）。
4. **修正3 對照**：useDIgate on/off 各跑一次，量測交易數與 Sharpe/Calmar 的邊際差異。
5. **Partial TP 對照**：usePartialTP on/off 比對 Sharpe（平滑度）與 Calmar（右尾截斷）邊際貢獻；除錯欄 `stage=opentrades` 全程相等以確認 partial close 無 desync。
6. **樣本內外 / Walk-Forward**：minVotes=2 樣本內交易數 >100 筆方視為統計顯著；切分樣本外確認不崩。
7. **多商品穩健**：跨 ≥4 資產類別（加密365 / 股指252 / 外匯 / 商品）同參數測 Sharpe/Calmar **中位數與最差值**，禁 per-symbol 調參。
8. **參數 sensitivity**：baseLen ±20%(8–12)、targetVol、chandMult、tp1R/tp2R 鄰域應為穩健高原，無孤峰。
9. **抗過擬合**：確認修正2/3 未把交易數打到統計不顯著；floorHits/capHits 不應長期飽和（飽和代表 vol-target 被旁路）。
10. **TradingView 步驟**：貼上腳本 → 套用至商品/週期 → 同步設定 barsPerYear → 開啟 Strategy Tester 檢視 → 開 showDebug 驗對帳欄 → 切換 usePartialTP/useDIgate 做 A/B 對照。

---

## 六、Pine v5 約束遵循
- ta.supertrend 回傳 [value,direction]，direction<0 為多頭。
- var 維護狀態機；not inPos 即時歸零消孤兒（含 tp1Done/tp2Done）。
- strategy.entry/close/close_all；partial TP 用 qty_percent 且只對當前方向 id。
- 無回測引擎，效益一律「預期/需驗證」語氣，未捏造回測數字。