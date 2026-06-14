# 專案設定指南（給協作者）

這個 repo **不含任何金鑰**（已被 `.gitignore` 排除）。clone 後請自行準備下列憑證，全部用**你自己的帳號**。

## 1. MCP 設定
```bash
cp .mcp.json.example .mcp.json
```
編輯 `.mcp.json`，填入：
- **Notion**：到 notion.so/my-integrations 建 integration，貼上 token
- **Firecrawl**：到 firecrawl.dev 拿 API key（免費月 500 篇）
- **filesystem**：把路徑改成你本機的專案路徑

## 2. 交易機器人（trading_bot / pionex_crypto）
```bash
cp trading_bot/config/config.example.yaml trading_bot/config/config.yaml
```
編輯 `config.yaml`，填入**你自己的 Pionex API key**。

> ⚠️ **安全紅線**：申請 Pionex API key 時**務必關閉「提現」權限**，只開交易/讀取。
> 絕對不要使用別人的 key，也不要把你的 key 貼進任何會進版控的檔案。

## 3. Python 環境
```bash
cd trading_bot
pip install -r requirements.txt
```

## 4. YouTube 自動化（youtube_channel，選用）
需要自己的 Google OAuth：到 Google Cloud Console 建 OAuth client，
下載 `client_secrets.json` 放進 `youtube_channel/`，首次執行會跑授權流程產生 token。

---
有問題問專案擁有者。**任何 `.env` / `*token*.json` / `config.yaml` / `.mcp.json` 都不要 commit。**
