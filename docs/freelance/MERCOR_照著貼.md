# Mercor 註冊：照著貼就好

> 2026-08-30 用瀏覽器實看註冊流程後寫的。**不用讀 `PLATFORMS.md` 那 7,800 字。**
>
> 紅線不變：**註冊、送出、綁收款全部你本人按。** 我做到「你只要複製貼上」為止。

---

## 你要準備的兩樣東西

1. **履歷 PDF** → `docs/freelance/Carson_Chou_Resume.pdf`（已產好，1 頁）
2. **20 分鐘**

就這樣。不用 LinkedIn（我舊筆記寫「硬要求」，實看流程只有 3 步，沒有這一項）。

---

## 流程只有 3 步

網址 **work.mercor.com** → 右上 Sign in / Get started

```
1  Resume       上傳 PDF
2  Location     選 Taiwan
3  Assessment   線上測驗
```

---

## 第 1 步：Resume

上傳 `Carson_Chou_Resume.pdf`。

內容全部取自 `PROFILE_EN.md`，數字**今天實測過**（不是 08-20 的舊值）：

    data_hunter   365 passed
    webhook        66 passed
                  ---
                  431   ← 履歷上寫的就是這個

`ecommerce` 有 16 個已知失敗，所以履歷**不引用**它的 208 個，
也不出現 623 / 637 / 639 —— 那些數字被追問時你沒有答案。

系統若要你手動確認欄位，用這些：

| 欄位 | 貼這個 |
|---|---|
| Full name | `Chou Ting-Rui` |
| Preferred name | `Carson` |
| Headline / Title | `Python Automation & Data Pipeline Engineer` |
| Years of experience | 照實填 |
| Country | `Taiwan` |

---

## 第 2 步：Location

選 **Taiwan**。

⚠️ **這裡會決定你看得到哪些職缺。** 官方規則：職缺沒特別標地區時，
預設只開放 US / Canada / UK / EU。台灣看得到的是「該專案明確需要」的那些
→ **你的職缺清單會比美國人短，這是正常的，不是你被拒絕。**

另外實看到 `Software Engineer, Full Stack — India $25–30/hr`，
而同名的無地區標記職缺是 `$50–65/hr` —— **他們依地區定價**。
台灣拿到的數字可能不是官網首頁那些，心裡先有底。

---

## 第 3 步：Assessment

線上技能測驗。這是**唯一需要真的動腦**的一關。

沒有考古題，但從職缺名稱看得出方向 —— Mercor 上跟你對得上的是這幾類
（2026-08-30 實抓，費率是官網標示）：

    Senior Software Engineer, Full Stack (Python, Java, Rust, C#, C++)   $90–110/hr
    Engineering / Platform Professionals                                  $80–160/hr
    Engineering & Software Domain Expert                                  $65–105/hr
    Computational Statistics & Applied Math (R, Python, Matlab)           $70–90/hr
    Incident management / reliability / SRE Evaluator                     $80–120/hr

注意最後一個：**SRE / 可靠性評測**。那正好是你這一年在做的事
（排程、fail-closed、靜默失敗）。履歷第一段就是為這類職缺寫的。

---

## 測驗前值得先想過的三題

Mercor 這類平台要的不是「你會不會寫」，是**「你看不看得出這段程式碼哪裡會安靜地出錯」**。
你真的踩過並修好的三個，直接講這些就好：

1. **`.get(key, 0)` 回傳 None**
   —— key 存在但值是 null，預設值根本沒被觸發。
   （`TEST_FAILURES.md` 根因 A）

2. **有人把閘門改「寬鬆一點」，壞資料就靜靜通過了**
   —— 而且修的是沒人走的那條路（同一件事有兩份實作）。
   （memory `yt-duplicate-impl-gate-bypass`）

3. **「超時就是死掉」的判準殺掉健康的長任務**
   —— 只看檔案 mtime，從不檢查活性。長任務天生就會超時。
   （memory `yt-make-video-duplicate-deadlock`）

這三個**都是真的**，不是準備好的答案 —— 這種具體度是履歷裡最難假造的東西。

---

## 送出前檢查

- [ ] PDF 開起來是 1 頁、排版沒跑掉
- [ ] 沒有出現 623 / 637 / 639
- [ ] 沒有任何句子暗示有商業客戶或推薦人
- [ ] 沒有金鑰、密碼、個資
- [ ] **這是我本人按下送出的**

---

## 之後

Mercor 是**時薪、Stripe Connect 週結**。跟 BRAIN 完全不同性質：

    BRAIN    09-01 拿 Gold → 面試 → 簽約 → 季付      第一筆錢是幾個月後
    Mercor   過測驗 → 接到專案 → 每週結              最快的一條

兩條不衝突，BRAIN 那邊你只需要每天按兩下。
