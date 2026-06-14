# Triple SuperTrend v4 收斂版 — 說明文件

> 本文件記錄 v3→v4 的弱點診斷、v4（收斂版）每項改動的 why 與預期影響，並附參數表與完整驗證清單。
> 所有效益一律為「機制推導 / 預期 / 需驗證」語氣，無真實回測，禁止當作既成績效解讀。

---

## 1. v3 弱點診斷（為何要做 v4）

| 弱點 | 病灶 | 對 Sharpe / Calmar 的傷害 |
|------|------|---------------------------|
| 進場無 regime 過濾 | 趨勢策略在 90% 盤整時間頻繁 whipsaw | 交易方差爆增、分子被磨損，Sharpe 直接被拉低 |
| 名目% sizing（equity×固定%） | 跨商品波動差 4–6 倍，曝險未歸一 | 高波動商品左尾過大，Calmar 崩潰 |
| MA200 魔術數、空單硬規則手術 | 單一商品 in-sample 擬合 | 跨商品泛化失敗 |
| close_all 一次全平 | 金字塔分段落袋紅利全丟 | 末端回吐放大，Calmar 受損 |
| 雙軌 bool 狀態（l1In…/inPos） | 多真相易孤兒、難維護 | 隱性邏輯錯誤污染統計 |

v4 的三支正交槓桿：**(A) Regime Gate 擋盤整 whipsaw、(B) 波動率目標化 sizing、(C) 出場鏡像對稱化**。

---

## 2. v4（收斂版）逐項改動：why + 預期影響

### 2.1 狀態機改為「實際層數重建」（修 blocking #1/#4，logic blocking）
- **改動**：放棄用 `stage` 累加計數推斷層數。改以 `var bool l1On/l2On/l3On`（空單 s1/s2/s3）為單一真相；`stage` 每棒由各層 bool 即時重算（`longStage=l1On+l2On+l3On`）。分批 `strategy.close("L1")` 後立刻 `l1On:=false`；全平與孤兒清理時一次歸零。
- **why**：v4 原稿分批減倉後 `stage` 不遞減，導致 `timeStop(stage<3)`、`belowAvg(stage>=2)`、加碼門檻全部以錯誤 stage 運作，且可跳層加碼（cut L1 後剩 L2/L3 仍能加 L3）。這直接違反「單一真相 stage」承諾。
- **預期影響**：消除死單無法 time-stop、跳層加碼、保本誤觸；`stage` 永遠等於真實未平層數。Calmar 穩定度的測量噪音下降。除錯表新增 `opentrades` 與 `stage` 對帳欄，walk-forward 前需驗證兩者恒等。

### 2.2 同棒出場狀態立即歸零（修 robustness blocking #3）
- **改動**：每次 `close_all` / 分批 close 當下立即用 `clearAll()` 或翻 bool 重置，不再只依賴下一棒 `position_size==0` 的延遲清理。
- **why**：原稿同棒出場時本棒 `position_size` 尚未變 0，§3 清理看到舊值不歸零，`trailExt/trailStop` 殘留跨棒洩漏，污染下一筆新單 trail 起點（whipsaw 商品上系統性誤差）。
- **預期影響**：trail 起點確定性歸零，消除孤兒狀態跨棒洩漏。

### 2.3 qtyFor 統一單一 dollar-risk 公式（修 risk blocking #2、logic blocking）
- **改動**：全程用 `qty = rb*riskBase/stopDistPrice`，先算 notional 套 clamp，最後單一出口 `q=notional/close`。移除原稿「主路徑 vs fallback 雙公式量綱分歧」。`useVolTarget` 切換時，止損距離量綱統一為價格單位（`stopDistVT=stopMultEntry*instVol*close` 等價於 `stopMultEntry*atrFast`；對照組 `stopDistFix=stopMultEntry*atrExit`）。
- **why**：原稿 fallback `q=rb*riskBase/close` 少除止損分數，數量級可差 50–150 倍，且 clamp 對 fallback 失效，造成跨商品 sizing 斷崖。
- **預期影響**：真實 dollar-risk = qty×止損距離 = rb×riskBase，跨商品曝險真正歸一，vol-target 不再被旁路。

### 2.4 移除名目下限 magic number，改風險定義下限（修 risk high #5）
- **改動**：刪除 `math.max(n, riskBase*0.05)`。下限改為「最小可接受 dollar-risk」= `rb*riskBase*minRiskFrac`（`minRiskFrac` input 預設 0.25），再換算 notional。
- **why**：原 5% 名目下限會在高波動商品把正確縮小的倉位頂回去，反而放大實際 dollar-risk，系統性超額下注。
- **預期影響**：高波動時 vol-target 自然縮倉，下限以風險而非名目衡量，跨商品一致。

### 2.5 instVol floor 相對化（修 logic high #6、robustness medium）
- **改動**：固定 `0.0005` 改為自身過去 `volFloorLB`（預設 252）棒 instVol 的低百分位（`volFloorPct` 預設 5%）。新增 `floorHits` 監控觸發率。
- **why**：絕對 bp floor 對不同商品尺度天差地別，低波動商品頻繁觸頂→分母被人為壓低→常態滿倉，是隱性曲線擬合點。
- **預期影響**：floor 自適應各商品波動分布，floor 觸發率可在 walk-forward 對每資產類別檢驗。

### 2.6 Choppiness 數值防護（修 logic high #7）
- **改動**：分母 `math.max(range, syminfo.mintick)` 防除零；ratio `math.max(...,1.0)` 確保 `chop>=0`；最後 `nz(chop, chopThr+1)`（NaN 視為非盤整，保守不放行 voteChop）。
- **why**：原稿一字盤/停牌時分母為 0 → NaN，`chop<chopThr` 對 NaN 恒 false，靜默拉低 votes，難察覺。
- **預期影響**：chop 永為有限非負，votes 行為確定，regimePass 不再莫名收緊。

### 2.7 多空對稱化（修 logic high #8、robustness medium）
- **改動**：預設 `dirShort=diMinus>diPlus`（與 dirLong 完全鏡像）。把空單 adxRising 特例收進 `longBiasMode` input（預設 false），要開偏多模式才生效。
- **why**：原稿空單額外要求 adxRising 與「多空完全對稱」宣稱矛盾，在 FX/期貨/加密雙向市場系統性削弱空單捕捉，傷害下跌段 Calmar 保護。
- **預期影響**：跨商品空單捕捉對稱；偏多假設改為可驗證 input，walk-forward 比較對稱 vs 偏多的 Sharpe/Calmar。

### 2.8 Choppiness 視窗與 ADX 解耦（修 logic high #9、robustness low）
- **改動**：新增獨立 `chopLen` input（預設 14），不再綁 `adxLen`。
- **why**：原稿 `chopLen=adxLen`，使用者調 adxLen 會悄悄改變 chop 尺度與分布，同一 chopThr 意義漂移，破壞參數高原。
- **預期影響**：chopThr 門檻在不同 adxLen 下意義一致，旋鈕解耦。

### 2.9 真實止損掛單防跳空（修 risk high）
- **改動**：新增 `hardStopOn`（預設 true），對 trailStop 同時下 `strategy.exit(stop=trailStop)` 真實停損單（盤中觸發），trailStop 收盤確認趨勢出場仍保留。maxGross 預設由 1.8 降至 1.5。
- **why**：原稿只有「收盤穿越才 close_all」，跳空/快市會吃遠超 ATR 的滑點；pyramiding×maxGross 放大尾部回撤。
- **預期影響**：跳空情境有交易所層級停損保護，Calmar 對肥尾回撤敏感度下降。仍需按各商品 tick value 與歷史 gap 重估 slippage。

### 2.10 R 基準錨定首單 entryPrice（修 logic medium）
- **改動**：R 改用凍結 `entryPrice`（首單收盤）而非隨加碼漂移的 avgPrice；保本基準同步用 entryPrice。
- **why**：原稿用 avgPrice，加碼後 avgPrice 上移壓低 R，使階梯倒退 tight→wide、保本失效、trail 被鎖死在寬檔。
- **預期影響**：階梯收緊單調，加碼越多不再放鬆停損。

### 2.11 ST1 factor 下限提高 + 尺度倍率參數化（修 overfit high）
- **改動**：`st1Factor` minval 由 0.8 提到 1.3（預設 1.5）降 whipsaw；`st2LenMult/st3LenMult` 暴露為 input，以便實證三 ST 方向相關 <0.7 假設。
- **why**：ST1 factor=1.0 極易頻繁翻轉；三 ST 同源恐高度共線，三層加碼=同訊號重複押注放大尾部風險。
- **預期影響**：降低首單 whipsaw；可在 walk-forward 量測三 ST 方向相關矩陣，未達 <0.7 不得視為獨立加碼依據。

### 2.12 其餘 medium/low
- multBE minval 提到 0.1（修 logic low）：確保保本價覆蓋 commission+slippage，不再「保本卻小虧」。
- chopThr 預設改 38.0、step 1.0（修 overfit low/high）：去除費氏語義與過細微調。
- regimeLockProfit 預設改 false（修 risk medium）：ADX 雙閾值臨界震盪會使 trail 抖動，邊際貢獻需實證才預設開。
- 區段重新編號 §1→§13 與物理執行順序一致，兩個 §8 拆開（修 style low）。
- 移除 instVol<=0 死分支（修 logic low）：floor 後 instVol 恒 >0。

---

## 3. 參數表（保留可調，全部範圍限制）

| 群組 | 參數 | 預設 | 範圍 | 說明 |
|------|------|------|------|------|
| SuperTrend | trendLen | 10 | 8–14 | 單一驅動基長 |
| | st1/2/3Factor | 1.5/2.5/4.0 | 見 input | ST1 下限提高降 whipsaw |
| | st2/3LenMult | 2/4 | 2–3 / 3–5 | 尺度倍率（去相關實證用） |
| Regime | adxLen | 14 | 10–20 | ADX 長度 |
| | chopLen | 14 | 10–20 | 與 adxLen 解耦 |
| | adxOn/Off | 25/20 | 22–28/18–22 | 遲滯雙閾值 |
| | chopThr | 38.0 | 35–45 step1 | 中性整數預設 |
| | minVotes | 2 | 2–3 | 投票門檻 |
| | longBiasMode | false | — | 偏多時空單才加 adxRising |
| Sizing | useVolTarget | true | — | 名目對照組可關 |
| | riskL1/2/3 | 0.5/0.7/0.8% | 0.3–1.0 | 分層風險 |
| | maxGross | 1.5 | 1.2–2.0 | 名目上限（降尾部） |
| | maxTradeRisk | 1.5% | 1.0–2.0 | 整筆 dollar-risk 硬 cap |
| | minRiskFrac | 0.25 | 0.0–0.5 | 風險定義下限 |
| | volFloorPct/LB | 5/252 | — | 相對化 vol floor |
| | hardStopOn | true | — | 真實停損掛單 |
| Exit | trailWide/Mid/Tight | 3/2/1.5 | 見 input | R 階梯倍數 |
| | kBE/multBE | 1.0/0.3 | — | 保本（multBE≥0.1 覆蓋成本） |
| | timeStopBars | 30 | 20–50 | 死單退場 |
| | regimeLockProfit | false | — | 預設關，需實證 |

---

## 4. 驗證清單（walk-forward 前必做）

### 4.1 樣本內外切分 / Walk-Forward
- [ ] 至少 180 天、>100 筆交易，含交易成本與滑點。
- [ ] 滾動 walk-forward（如 IS 12 個月 / OOS 3 個月），比較 IS vs OOS 的 Sharpe/Calmar 衰減。

### 4.2 多商品穩健度
- [ ] 同一組參數跨 ≥4 個資產類別（指數、FX、期貨、加密）測 Sharpe/Calmar、平均持有時長、交易數一致性。
- [ ] 實測三 ST（dir1/dir2/dir3）方向相關矩陣，需 <0.7 才視為獨立加碼依據；否則考慮換指標家族。

### 4.3 參數 sensitivity / 高原
- [ ] 對 chopThr、ST factor、riskL*、st2/3LenMult 做 ±1 step 高原熱圖，確認甜蜜點為平滑高原而非孤峰。
- [ ] 固定 adxLen=14 驗證 chopThr 高原（解耦後應穩定）。

### 4.4 抗過擬合 / 對帳檢查
- [ ] 除錯表 `stage` 與 `strategy.opentrades` 在全程恒等（驗狀態機單一真相）。
- [ ] 監控 `floorHits`（vol floor 觸發率）與 `capHits`（nCap 撞頂率）；若 cap 常態撞頂表示 vol-target 被旁路，需調 maxGross/maxTradeRisk。
- [ ] 比較 longBiasMode true/false、regimeLockProfit true/false、useVolTarget true/false 的邊際貢獻，無正貢獻者維持預設關閉。

### 4.5 TradingView 驗證步驟
1. 貼入 Pine v5 編輯器，確認無編譯錯誤（注意 ta.supertrend direction<0 為多頭）。
2. 套不同商品/週期，肉眼檢查 plotshape 進出場與 trailStop/AvgCost 線合理。
3. 開 Strategy Tester，檢查 List of Trades 中 Cut L1/L2 後仍有剩餘倉位、time-stop 能在死單觸發。
4. 跳空商品（加密/期貨）測 hardStopOn on/off 對最大回撤差異。
5. 用除錯表逐筆核對 stage = opentrades。

---

## 5. 預期影響（機制推導，需驗證）
- **Sharpe**：gate 砍 whipsaw 降交易方差；vol-target 統一公式使分母跨商品收斂；對稱出場 + 保本覆蓋成本降單筆方差。
- **Calmar**：統一 dollar-risk + maxTradeRisk 硬 cap 左尾；真實停損掛單防跳空肥尾；R 錨定首單使階梯單調收緊，縮小末端回吐；maxGross 降至 1.5 削弱滿倉遇反轉的單次回撤。
- **泛化**：全 ATR/相對量歸一 + 多空對稱 + 狀態機單一真相 → 同參數跨商品行為可複現。