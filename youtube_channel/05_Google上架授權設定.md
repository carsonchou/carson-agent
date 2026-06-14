# 05｜Google YouTube 上架授權設定（只有 Carson 本人能做的那一步）

> 目的：讓 `upload_youtube.py` 能把影片上傳到**你的** YouTube 頻道。
> 全程約 15 分鐘，只做一次。做完後產生的 `client_secrets.json` + `token.json`
> 會讓程式之後永久免登入。
>
> ⚠️ 為什麼這步只能你做：Google 要驗證「上傳者是你本人」。我（AI）可以把程式、
> 設定、影片全部備好，但「登入你的 Google 帳號 + 點同意」這個動作驗證的是你的
> 身分，無法授權轉移。你做完這一步，剩下全部我跑。

---

## 前置：你需要

- 一個 Google 帳號（就是你 YouTube 頻道綁的那個）
- 一個瀏覽器（你平常登入 Google 的那個就好）

---

## 步驟 1️⃣：建立 Google Cloud 專案

1. 開 👉 https://console.cloud.google.com/
2. 用你的 YouTube 帳號登入
3. 最上方專案下拉選單 → 「新增專案」
4. 專案名稱填 `carson-quant-youtube`（隨意）→ 建立
5. 建好後確認左上角已切到這個專案

---

## 步驟 2️⃣：啟用 YouTube Data API v3

1. 左側選單（或搜尋框）→「API 和服務」→「程式庫」
2. 搜尋框打 `YouTube Data API v3`
3. 點進去 → 按「**啟用**」

---

## 步驟 3️⃣：設定 OAuth 同意畫面

1. 「API 和服務」→「**OAuth 同意畫面**」
2. User Type 選「**外部**」→ 建立
3. 填寫：
   - 應用程式名稱：`量化阿森上傳器`（隨意）
   - 使用者支援電子郵件：選你的信箱
   - 開發人員聯絡資訊：填你的信箱
   - 其他可留空 → 一路「儲存並繼續」
4. 走到「**測試使用者 (Test users)**」這一頁：
   - 按「+ ADD USERS」→ 把**你上傳影片要用的那個 Google 帳號**加進去
   - ⚠️ **這步很關鍵**：應用程式沒正式發布時，只有列在這裡的帳號能授權。漏了會卡在授權畫面。
5. 儲存

---

## 步驟 4️⃣：建立 OAuth 用戶端 ID（拿 client_secrets.json）

1. 「API 和服務」→「**憑證**」
2. 上方「+ 建立憑證」→「**OAuth 用戶端 ID**」
3. 應用程式類型選 「**桌面應用程式 (Desktop app)**」
4. 名稱隨意 → 建立
5. 跳出視窗 → 按「**下載 JSON**」
6. 把下載的檔案**改名為** `client_secrets.json`
7. 放到這個資料夾：
   ```
   D:\carson-agent\youtube_channel\client_secrets.json
   ```

✅ 放好後跟我說一聲，我這邊就能接手。

---

## 步驟 5️⃣：第一次授權（產生 token.json）

這一步可以**你自己做**，或**我來觸發、你只負責點同意**：

- 程式第一次跑真實上傳時（非 `--dry-run`），會**自動打開你的瀏覽器**
- 你會看到 Google 問：「**量化阿森上傳器 想要存取你的 YouTube 帳戶（上傳影片）**」
- （可能先出現「Google 尚未驗證這個應用程式」→ 點「進階」→「前往（不安全）」，因為這是你自己建的私人 App，安全）
- 點「**繼續 / 允許**」
- 成功後，程式自動把憑證存到 `D:\carson-agent\youtube_channel\token.json`
- **之後永久免登入**（token 過期會自動更新）

> 這 30 秒的點擊就是你說的「幫我登帳號」——你在自己瀏覽器點一次同意，
> 我從頭到尾碰不到你的密碼。

---

## 完成後，上架就是一行指令（我來跑）

```powershell
# 先 dry-run 確認 metadata 沒問題（不碰網路、不上傳）
python scripts\upload_youtube.py "output\<slug>.mp4" --dry-run

# 確認後，先上傳成「私人」自己檢查
python scripts\upload_youtube.py "output\<slug>.mp4" --privacy private

# 你看過沒問題，再轉公開（或一開始就排程）
python scripts\upload_youtube.py "output\<slug>.mp4" --privacy public
```

或用一鍵端到端：
```powershell
python scripts\run_all.py "<影片題目>" --upload --privacy private
```

---

## 你的待辦總清單（最小化）

| # | 你要做的 | 我會做的 |
|---|---------|---------|
| 1 | 建 Cloud 專案 + 啟用 API + 設同意畫面 + 加測試使用者 | 全程文件指引 |
| 2 | 下載 `client_secrets.json` 放進專案根 | 接手後驗證 |
| 3 | 第一次授權點一次「同意」 | 觸發授權流程、跑上傳 |
| 4 | 給我 ELEVENLABS_API_KEY / PEXELS_API_KEY | 設定、產配音、組影片 |

做完 1～4，**之後每支影片都只剩「我跑指令、你看過按公開」**。
