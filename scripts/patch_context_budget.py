"""把 context 警報從「百分比門檻」改成「絕對 token 門檻」。

根因(2026-09-02 實測):gsd-context-monitor.js 用 remaining_percentage 判斷,
WARNING=35% / CRITICAL=25%。在 200K 視窗上等於已用 130K/150K(合理),
但本機 session 跑的是 opus-5[1m],1M 視窗 → 已用 650K 才第一次警告、
750K 才喊停。實測 e1be186b 平均 context 787.6K,單支 session 一天燒掉
全機 43% 的額度。警報「叫得太晚 = 等於不會叫」。

本腳本:
  1. statusline bridge 檔補寫 total_tokens(monitor 才算得出絕對值)
  2. monitor 改用絕對 token 門檻(WARN 120K / CRIT 200K),
     拿不到 total_tokens 時 fallback 回原本的百分比邏輯 → 模型無關
  3. 警告文字改講絕對 token(1M 視窗上「已用 12%」配「快用完了」會被無視)
  4. 設 CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000(自動 compact 的保險層)

用法(Carson 在 Claude Code 打):
  ! python /d/carson-agent/scripts/patch_context_budget.py
"""
import os, re, shutil, subprocess, sys, datetime

HOOKS = "D:/claude/hooks"
STATUSLINE = os.path.join(HOOKS, "gsd-statusline.js")
MONITOR = os.path.join(HOOKS, "gsd-context-monitor.js")
STAMP = datetime.date.today().strftime("%Y%m%d")

def backup(p):
    b = p + ".bak-" + STAMP
    if not os.path.exists(b):
        shutil.copy2(p, b)
        print("  backup ->", b)
    else:
        print("  backup 已存在,沿用", b)

def patch_statusline():
    print("[1/4] statusline bridge 補寫 total_tokens")
    src = open(STATUSLINE, encoding="utf-8").read()
    if "total_tokens: totalCtx" in src:
        print("  已套用,略過"); return False
    needle = "            used_pct: rawUsedPct,"
    if needle not in src:
        print("  !! 找不到錨點,statusline 版本可能變了 — 中止"); sys.exit(1)
    backup(STATUSLINE)
    src = src.replace(needle, needle + "\n            total_tokens: totalCtx,", 1)
    open(STATUSLINE, "w", encoding="utf-8").write(src)
    print("  OK"); return True

MONITOR_NEW = """    const remaining = metrics.remaining_percentage;
    const usedPct = metrics.used_pct;

    // Absolute-token thresholds. Percentage thresholds silently scale with the
    // context window: on a 1M-window model, 35% remaining == 650K already used,
    // and every tool call re-reads that whole context from cache. Measured
    // 2026-09-02: one session averaging 787.6K context burned 43% of the day's
    // entire quota. Fall back to the percentage rule when total_tokens is absent
    // (older statusline bridge), so this stays model-agnostic.
    const totalCtx = metrics.total_tokens;
    let overBudget, criticalBudget;
    if (totalCtx) {
      const usedTokens = totalCtx * (100 - remaining) / 100;
      overBudget = usedTokens >= WARN_TOKENS;
      criticalBudget = usedTokens >= CRIT_TOKENS;
    } else {
      overBudget = remaining <= WARNING_THRESHOLD;
      criticalBudget = remaining <= CRITICAL_THRESHOLD;
    }

    // No warning needed
    if (!overBudget) {
      process.exit(0);
    }
"""

def patch_monitor():
    print("[2/4] monitor 改用絕對 token 門檻")
    src = open(MONITOR, encoding="utf-8").read()
    if "WARN_TOKENS" in src:
        print("  已套用,略過"); return False
    old = """    const remaining = metrics.remaining_percentage;
    const usedPct = metrics.used_pct;

    // No warning needed
    if (remaining > WARNING_THRESHOLD) {
      process.exit(0);
    }
"""
    if old not in src:
        print("  !! 找不到錨點,monitor 版本可能變了 — 中止"); sys.exit(1)
    backup(MONITOR)
    src = src.replace(old, MONITOR_NEW, 1)
    src = src.replace(
        "const CRITICAL_THRESHOLD = 25; // remaining_percentage <= 25%",
        "const CRITICAL_THRESHOLD = 25; // remaining_percentage <= 25% (fallback only)\n"
        "const WARN_TOKENS = 120_000;   // used tokens: wrap up current task\n"
        "const CRIT_TOKENS = 200_000;   // used tokens: save state and hand off", 1)
    # isCritical 也要走絕對值
    src = src.replace("const isCritical = remaining <= CRITICAL_THRESHOLD;",
                      "const isCritical = criticalBudget;", 1)
    open(MONITOR, "w", encoding="utf-8").write(src)
    print("  OK"); return True

def patch_env():
    print("[4/4] CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000 (User 層)")
    q = ("[Environment]::GetEnvironmentVariable("
         "'CLAUDE_CODE_AUTO_COMPACT_WINDOW','User')")
    cur = subprocess.run(["powershell", "-NoProfile", "-Command", q],
                         capture_output=True, text=True).stdout.strip()
    ps = ('[Environment]::SetEnvironmentVariable('
          "'CLAUDE_CODE_AUTO_COMPACT_WINDOW','200000','User')")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  !! 設定失敗:", r.stderr.strip()); return False
    print("  OK(原值:%s)— 新開的 session 才生效" % (cur or "未設"))
    return True


MSG_INJECT = """    // Report the budget in absolute tokens when we know the window size.
    // Percentages are misleading on a 1M window: 120K used reads as "12% used,
    // 88% remaining", which contradicts the warning text and gets ignored.
    let budgetLine, overrunPhrase;
    if (totalCtx) {
      const usedK = Math.round((totalCtx * (100 - remaining) / 100) / 1000);
      budgetLine = `${usedK}K tokens used (budget: warn ${WARN_TOKENS / 1000}K, ` +
        `hard ${CRIT_TOKENS / 1000}K).`;
      overrunPhrase = 'Every tool call re-reads this entire context from cache, so cost ' +
        'per call scales with it -- this is a cost budget, not a window limit.';
    } else {
      budgetLine = `usage at ${usedPct}%. Remaining: ${remaining}%.`;
      overrunPhrase = 'Context is nearly exhausted.';
    }

"""

MSG_SUBS = [
    ("""`CONTEXT CRITICAL: Usage at ${usedPct}%. Remaining: ${remaining}%. ` +
          'Context is nearly exhausted. """,
     """`CONTEXT CRITICAL. ${budgetLine} ${overrunPhrase} ` +
          '"""),
    ("""`CONTEXT WARNING: Usage at ${usedPct}%. Remaining: ${remaining}%. ` +
          'Context is getting limited. """,
     """`CONTEXT WARNING. ${budgetLine} ` +
          'Context is over the soft budget. """),
    ("""`CONTEXT WARNING: Usage at ${usedPct}%. Remaining: ${remaining}%. ` +
          'Be aware that context is getting limited. """,
     """`CONTEXT WARNING. ${budgetLine} ` +
          'Consider wrapping up and handing off to a fresh session. """),
]

def patch_messages():
    """警告文字改講絕對 token。

    不修這步的話,1M 視窗上訊息會長成「Usage at 12%. Remaining: 88%.
    Context is nearly exhausted.」— 數字直接打臉文字,收到的 agent
    合理反應就是忽略它。警報存在但沒有說服力,一樣等於不會叫。
    """
    print("[3/4] 警告文字改用絕對 token")
    src = open(MONITOR, encoding="utf-8").read()
    if "budgetLine" in src:
        print("  已套用,略過"); return False
    anchor = "    // Build advisory warning message (never use imperative commands that"
    if anchor not in src:
        print("  !! 找不到訊息區錨點 — 中止"); sys.exit(1)
    src = src.replace(anchor, MSG_INJECT + anchor, 1)
    n = 0
    for old, new in MSG_SUBS:
        n += src.count(old)
        src = src.replace(old, new)
    if n < 3:
        print("  !! 預期替換 3 種訊息模板,實際 %d — 中止" % n); sys.exit(1)
    open(MONITOR, "w", encoding="utf-8").write(src)
    print("  OK(替換 %d 處)" % n); return True

if __name__ == "__main__":
    for f in (STATUSLINE, MONITOR):
        if not os.path.exists(f):
            print("找不到", f, "— 中止"); sys.exit(1)
    patch_statusline(); patch_monitor(); patch_messages(); patch_env()
    print()
    print("完成。已在跑的 session 要重開才套用(hook 每次呼叫重讀,")
    print("但環境變數是 session 啟動時抓的)。回滾:把 .bak-%s 蓋回去。" % STAMP)
