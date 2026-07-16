# 10 個免費 GitHub 神器 — 安裝與使用說明

> 來源：IG @stics.ai「10 GitHub Repos That Feel Illegal」。Carson 2026-06-27 出門前要求「都裝」。
> 兩道牆：Docker 裝完**要重開機**；跑模型/起伺服器**只認 Carson 的 `!`**（分類器擋 agent 跑陌生碼）。
> 所以下面標 `!` 的指令請 Carson 親自貼。

## 📊 實測結果（2026-06-27 安裝後驗證）
| 工具 | 結果 |
|---|---|
| **Ollama** | ✅ 0.30.9 裝好（`ollama` 指令要開新終端才吃到 PATH） |
| **Bitwarden** | ✅ 2026.6.0 裝好（桌面 app） |
| **AppFlowy** | ✅ 0.12.4 裝好（桌面 app） |
| **n8n** | ✅ 2.27.4 裝好（`n8n` 可用） |
| **Docker Desktop** | ❌ **安裝失敗**（錯誤碼 4294967291）→ 根因：**WSL2 沒裝** |

> 4 個有用的都 OK。Docker 失敗 → 3 個自架（Plausible/Penpot/Cal.com）**目前起不來**。
> **我的誠實建議：那 3 個對你（量化＋YouTube）幫助不大，要它得先裝 WSL2＋Docker＋重開機 2 次，成本太高，建議跳過。** 真的想要再走下面「補 Docker」。

### 補 Docker（只有你真的要那 3 個自架時才做，要管理員＋重開機）
```
! wsl --install              # 裝 WSL2，要管理員，裝完【重開機】
# 重開機後：
! winget install -e --id Docker.DockerDesktop   # 重裝 Docker
# 再【重開機】→ 開 Docker Desktop 等鯨魚變綠 → 才能跑 docker compose
```

## ✅ 已經有的（不用裝）
| 工具 | 取代 | 狀態 |
|---|---|---|
| **yt-dlp** | YouTube Premium | 已裝 2026.06.09（/watch 在用） |
| **Whisper** | Otter $20/月 | 已裝（/watch venv） |

## 🟢 這次裝的 4 個（winget/npm，背景已跑）
| 工具 | 取代 | 怎麼用 |
|---|---|---|
| **Ollama** | OpenAI API | 桌面捷徑開，或終端 `ollama run <模型>`。見下方「本地模型」 |
| **Bitwarden** | 1Password | 桌面 app 開，建帳號，把你的 API/SSH 金鑰收進去 |
| **AppFlowy** | Notion | 桌面 app 開，本地離線筆記庫 |
| **n8n** | Zapier | 終端 `! n8n` → 開 `http://localhost:5678` 拉自動化流程 |

### 本地模型（Ollama）— 省 API 的「便宜檔」
Ollama **跑不了 Claude**（非開源）。拉開源模型來做分類/草稿，正式產出仍用 Claude：
```
! ollama pull qwen2.5:7b      # 中文強，7B，一般筆電跑得動
! ollama run qwen2.5:7b       # 開對話測試
```
⚠️ 本地模型 idle 吃 RAM（~多 GB），品質/速度不如 Claude；定位＝省 token 的雜活檔，不是取代。

## 🐳 3 個自架（要 Docker，裝完**重開機**後才能跑）
> Docker Desktop 背景裝中。**裝完務必：① 重開機 ② 開 Docker Desktop 等右下鯨魚變綠。**
> 然後在各自資料夾 `! docker compose up -d`。用官方 compose 最穩，不自己手寫。

### Plausible（網站分析，取代 GA）→ localhost:8000
```
! git clone https://github.com/plausible/community-edition /d/claude/external-tools/plausible-ce
! cd /d/claude/external-tools/plausible-ce && docker compose up -d
```

### Penpot（開源 Figma）→ localhost:9001
```
! curl -fsSL https://raw.githubusercontent.com/penpot/penpot/main/docker/images/docker-compose.yaml -o /d/claude/external-tools/penpot-compose.yaml
! docker compose -f /d/claude/external-tools/penpot-compose.yaml up -d
```

### Cal.com（排程，取代 Calendly）→ localhost:3000
> ⚠️ Cal.com 自架最複雜（要建 image、設一堆環境變數/DB）。CP 值最低。
```
! git clone https://github.com/calcom/cal.com /d/claude/external-tools/calcom
# 之後照 calcom/.env.example 設定，再 docker compose up（步驟多，回來我陪你弄）
```

## 🔴 跳過：Fooocus
要 NVIDIA GPU + Python 3.10（你 3.9）+ 下載 ~5GB SD 模型。而且你已裝 **open-design** 能生圖，CP 值太低。要硬上再說。

---

## 阿森回來的待辦（照順序）
1. 確認 Docker 裝完了 → **重開機**
2. 開機後開 **Docker Desktop**，等變綠
3. 想用本地 AI：貼 `! ollama pull qwen2.5:7b`
4. 想架 3 個自架的：貼上面對應的 `! docker compose` 指令
5. Bitwarden / AppFlowy：直接從開始選單開桌面 app

**我（Claude）已備好的**：這份說明、所有 `!` 指令、相關記憶。**我做不到的**：替你重開機、替你跑 `!`（分類器擋 agent 執行陌生碼/伺服器）。
