# 協作規範（約定式 PR 流程）

> 本 repo 為**免費私有 repo**,GitHub 不強制分支保護,所以這套流程**靠大家自律**。
> 核心原則:**不要直接 push 到 `main`**,所有改動走 PR。

## 日常流程

```bash
# 1. 開工前先同步最新 main
git checkout main
git pull --rebase

# 2. 開一個功能分支（命名:feature/xxx、fix/xxx）
git checkout -b feature/我的改動

# 3. 改完、commit
git add -A
git commit -m "說明這次改了什麼"

# 4. 推上去
git push -u origin feature/我的改動

# 5. 開 PR（會跳出範本，填一下）
gh pr create --fill

# 6. 對方看過 / 自己確認沒問題後合併
gh pr merge --squash --delete-branch
```

## 規則

- ✅ **一律開分支 + PR**,不要直接 `git push origin main`。
- ✅ 開工前先 `git pull --rebase`,減少衝突。
- ✅ PR 標題寫清楚「改了什麼、為什麼」。
- ✅ 兩人小團隊:可以自己合併自己的 PR,但**重大改動先讓對方看一眼**。
- ⛔ **絕對不要 commit 任何金鑰**:`.mcp.json`、`*credentials*.json`、`config.yaml`、`token*.json`、`.env`。這些已被 `.gitignore` 擋住,別用 `git add -f` 硬加。
- ⛔ 不要 force push `main`。

## 金鑰提醒

第一次 clone 後,照 [`SETUP.md`](./SETUP.md) 填**自己的** API key。
⚠️ Pionex API key 申請時務必**關閉提現權限**。
