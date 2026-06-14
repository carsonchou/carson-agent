# 早晨日報 /morning 設定指南

## 總覽

這個功能需要完成三個設定：
1. Google API 認證（Gmail + Google Calendar）
2. Notion MCP Server 設定
3. Python 套件安裝

---

## STEP 1：安裝 Python 套件

在 PowerShell 執行：

```powershell
python -m pip install google-auth-oauthlib google-api-python-client
```

---

## STEP 2：設定 Google API

### 2a. 建立 Google Cloud 專案並取得憑證

1. 前往 https://console.cloud.google.com/
2. 建立新專案（或使用現有專案）
3. 在左側選單 → **APIs & Services** → **Library**
4. 搜尋並啟用：
   - **Gmail API**
   - **Google Calendar API**
5. 前往 **APIs & Services** → **Credentials**
6. 點擊「+ CREATE CREDENTIALS」→「OAuth 2.0 Client IDs」
7. Application type 選「**Desktop app**」
8. 下載 JSON 檔案

### 2b. 放置憑證檔案

將下載的 JSON 檔案重新命名為 `google_credentials.json`，放到：

```
C:\Users\User\Downloads\carson-agent\scripts\google_credentials.json
```

### 2c. 執行 OAuth 認證（僅需一次）

```powershell
python C:\Users\User\Downloads\carson-agent\scripts\google_auth_setup.py
```

瀏覽器會自動開啟，登入 Google 帳號並授權後即完成。

---

## STEP 3：設定 Notion MCP Server

### 3a. 取得 Notion API Token

1. 前往 https://www.notion.so/my-integrations
2. 點擊「+ New integration」
3. 填寫名稱（例如：Claude Morning Report）
4. 複製「Internal Integration Token」（格式：secret_xxxxx）

### 3b. 分享 Notion 頁面

在你想讓 Claude 讀取的 Notion 任務資料庫或頁面：
1. 右上角「...」→「Connections」
2. 選擇剛建立的整合

### 3c. 在終端機執行（將 YOUR_TOKEN 替換成真實 token）

```powershell
claude mcp add notion --scope user -e "OPENAPI_MCP_HEADERS={\"Authorization\": \"Bearer YOUR_TOKEN\", \"Notion-Version\": \"2022-06-28\"}" -- npx -y @notionhq/notion-mcp-server
```

---

## STEP 4：允許 Python 指令權限

在 Claude Code 設定中手動加入 Python 執行權限。

在 Claude Code 輸入：
```
/config
```

或在 `~/.claude/settings.json` 的 `permissions.allow` 陣列中新增：
```
"Bash(python *)"
```

---

## 完成後測試

在 Claude Code 輸入：
```
/morning
```

---

## 檔案結構

```
scripts/
├── morning_fetch.py        # 抓取 Gmail + Calendar 資料
├── google_auth_setup.py    # 一次性 Google 認證設定
├── google_credentials.json # 你的 Google OAuth 憑證（需自行放置）
└── google_token.json       # 認證後自動產生，勿上傳至 git
```
