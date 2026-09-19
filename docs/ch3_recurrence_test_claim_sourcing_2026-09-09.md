# 復發測試 6 支 —— 宣稱層逐句來源標註(2026-09-09)

> 起因:獨立驗證的**誠信項不通過**,8 條宣稱撐不住。
> ⚠️ 訂正一件我自己的紀錄問題:這些改寫實際上落在 commit **`6a95dd61`** 裡
> (和 prereg_title / KeyError / 第三篇論文同一個 commit),
> **而那則 commit 訊息只描述了那四件,沒有描述這 8 條改寫。**
> 訊息描述不全 = 下一個人讀 log 會漏掉這件事。本檔補上,並就地記下這個疏漏。

---

## 0. 它垮在哪一層(不要修錯地方)

**數字那一層是乾淨的。** 20 條 claim 逐條對得上自己的 `verbatim`;
4 條轉引自 review 的數字一條都沒有進旁白;每個唸出來的數字都指得回原文。
**沒有一個數字是憑空的。**

垮的是**宣稱**那一層。既有三道閘門問的都是「**這個數字**有沒有來源」,
問不到「**這句話**有沒有來源」:

| 閘門 | 它問什麼 | 它問不到什麼 |
|---|---|---|
| `make_reel.audit()` | 稿裡的數字在不在結構化欄位 | 「對照組是什麼」——那句話裡沒有數字 |
| `_check_claim_values.py` | 這個 value 在不在它自己的 verbatim | 旁白有沒有正確描述那個 verbatim |
| `reel_gate()` | DOI 在不在說明欄 | 片子講的那件事是不是這篇論文說的 |

🔴 **三道閘門全綠**才是這件事的重點。不可以因為「稿是手寫的、我們很小心」
就把這 8 條讀成例外 —— 它們正是在「手寫 + 很小心 + 三道閘門」的條件下發生的。

---

## 1. 逐條改寫與來源

### 【4a】對照組講錯 —— 被同一個檔案裡的 verbatim 推翻

**1. `focus_techniques` / weight**

- ❌ 原:`Both of these were measured against **doing nothing**`
- ✅ 新:`Each one is a comparison somebody actually ran, against a real alternative.`
- **來源**:三篇都是有對照條件的實驗;新句**不宣稱對照組是什麼**,
  具體對照組改成在 turn 裡逐個講明(見下)。
- 🔴 這條的意義超出它自己:**推翻它的證據就在同一個檔案裡的 `verbatim` 欄位,
  而三道閘門沒有一道會去看那裡。**

**2. `focus_techniques` / turn —— 睡前清單的對照組**

- ❌ 原:`those people fell asleep faster`(沒說比誰快)
- ✅ 新:`people who wrote tomorrow's list before bed fell asleep faster than
  people who wrote down what they had already finished, 0.63`
- **來源**:Scullin et al. 2018 verbatim ——
  「Participants who wrote a To-Do List fell asleep significantly more quickly
  than those who wrote a **Completed List**, t(55) = 2.32, p = 0.02, d = .63.」
  ⇒ 對照組是 **active control**(寫已完成清單),不是「什麼都不做」。
- 其餘兩個對照組原本就講對了,保留:
  手機是 `on the desk instead of in another room`(Ward 2017 的 Phone Location 三水準);
  休息是 `the three groups that worked straight through`(Ariga & Lleras 的三個連續作業組)。

**3.(我自己多抓到的同類)`how_to_remember_what_you_read` / weight**

- ❌ 原:`All three were measured against just reading it again.`
  —— 只有 Roediger & Karpicke 那條的對照是重讀;
  Karpicke & Blunt 對照的是**畫概念圖**、Cepeda 2008 對照的是**同一天複習**。
- ✅ 新:`Three things change that, and each was compared with a different
  thing people do instead.`
- **來源**:三篇各自的對照條件,不再宣稱它們是同一個。
- 📌 驗證員點名的是這一族的**代表**,不是清單本身。我照族去掃,多抓到這條和第 8 條。

### 【4b】被同一支片自己印出來的數字打臉

**4. `how_to_remember_what_you_read` / belief**

- ❌ 原:`In a week you will remember **almost none** of it`
  —— 三十秒後畫面打「56 percent a week later, against 42」。**42% 不是 almost none。**
- ✅ 新:`Read it again and nothing else, and in a week more than half of it is gone.`
- **來源**:Roediger & Karpicke 2006 —— 重讀組一週後回憶 **42%** ⇒ 失去 58% ⇒「超過一半」。
  這是對已引用數字做算術,不是新宣稱。

**5. `how_to_remember_what_you_read` / verdict**

- ❌ 原:`That is the one thing that **does not work**` —— 42% 不是「不管用」,是「比較差」。
- ✅ 新:`When rereading was tested head to head, it lost.`
- **來源**:同上,56% vs 42%,單一研究的直接對比。**沒有宣稱它在所有研究裡都墊底。**

### 【4c】掛名 / 無對應來源

**6. `pomodoro` / weight —— 起源宣稱**

- ❌ 原:`It came from one student is own method, not from a study`
  —— 三篇論文零來源。查證員明講找不到 Cirillo 原始文本的可逐字引用版本。
- ✅ 新:`So here is the question: has anyone actually tested that exact recipe?`
- **來源**:**這句不帶來源宣稱**(它是一個提問)。

**7. `pomodoro` / turn —— 引用頻率宣稱**

- ❌ 原:`the paper most often cited as proof` —— 沒有任何引文統計。
- ✅ 新:`a study that kept coming up in that search`
- **來源**:主詞改成**我們自己的搜尋**(查證員的 `search_log` 有逐筆紀錄),不是世界。

**8. `pomodoro` / turn —— 唯一性 + 「randomised」**

- ❌ 原:`One randomised trial has: 94 university students`
  ① `randomised` 不在 Smits 2025 的 verbatim 裡(原文是 *online intervention*)
  ② 🔴「只有一支」是**我們自己文獻搜尋的結果**,不是任何來源說的 ——
    **而唯一性正是這支片的支點。**
- ✅ 新:`In our own search, we found one: 94 university students, one two-hour session.`
- **來源**:`verdict_claims_e1e2.json` 的 `E2.search_log`(7 筆,含查了哪些庫、得到什麼)。
  `randomised` 已拿掉。畫面那一列的 `what` 也從「found in the literature」
  改成 **「that our search found」**,兩個表面一起改。

**9. `study_techniques` / belief —— 全稱宣稱**

- ❌ 原:`Most study advice has never been tested.` —— 對整個文獻的全稱宣稱,零來源。
- ✅ 新:`Three study methods that beat what you are probably doing instead.`
- **來源**:三篇各自對其對照組勝出(74 vs 42、61 vs 40、g = .55)。
  `probably` 是對觀眾的推測,不是對文獻的宣稱。

**10. `study_techniques` / verdict —— 主觀成本宣稱**

- ❌ 原:`All three feel worse while you are studying` —— 事實庫裡沒有任何一篇測過「感覺」。
- ✅ 新:`Two of these were scored a week and a month after the studying stopped.
  That is where the difference was.`
- **來源**:Roediger & Karpicke(一週後)、Rohrer et al.(30 天後)。
  **明說「兩個」而不是「三個」** —— Bisra 的統合分析沒有統一的延遲測驗設定。

**11.(我自己多抓到的)`study_techniques` / weight**

- ❌ 原只列了兩個對照組(`rereading, and doing one topic at a time`)配三個方法。
- ✅ 新:`Each one was compared with what students do by default:
  blocking one topic, rereading, and just reading on.` —— 三配三。

**12.(我自己多抓到的)`learning_styles` / verdict**

- ❌ 原:`Preferences are real.` —— 這句沒有來源撐,而且它是一個獨立的正面宣稱。
- ✅ 新:`What failed is the matching — having a preference was never the claim.`
- **來源**:Pashler 等人檢驗的是 **meshing hypothesis**(教法配合偏好能提升學習),
  這正是 `E1.c1` 的 `what_it_does_not_say` 寫的那件事。

---

## 2. 沒有改的,以及為什麼

- `learning_styles` / turn 的「**only one study**」**保留** ——
  那句唯一性宣稱是 **Pashler 等人自己說的**(verbatim:
  「we found only one study that could be described as even potentially meeting
  the criteria」),而且旁白**指名了是他們找到的**:
  `Reviewing the whole literature, Pashler and colleagues found only one study`。
  ⇒ 主詞是那篇論文的搜尋,不是我們的斷言。這正是通則要求的形狀。
- `if_then_plans` 四句逐句過了一遍,沒有需要改的:對照組沒有被宣稱、
  數字都指名了 k 值與族群(含「people already struggling with their mental health」
  這個限定,因為 Toli 2016 的樣本是臨床/亞臨床)。

---

## 3. ⚠️ 順手掃到、但**沒有**驗證的:兩支既有已渲染的片

改完之後我用一份粗糙的關鍵詞表掃全部 20 集,除了我改的以外還命中兩支**舊片**:

- `hungry_judges` —— 命中 `doing nothing` / `almost none`
- `sugar_hyperactivity` —— 命中 `randomised`

🔴 **這兩筆我沒有查證,不要當成缺陷回報。** 關鍵詞表很粗
(`randomised` 用在真的隨機對照試驗上完全正確),而且這兩支已經渲染、
可能已經發布 —— 改旁白而不重渲會被 `reel_gate` 的漂移檢查擋下。
⇒ 列在這裡只是為了**不讓它掉在地上**:值得有人用同一個視角讀一次舊片的稿,
但那是另一件工作,不要順手做進這一棒。
