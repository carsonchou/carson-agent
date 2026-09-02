"""重開 context 超標的 herdr 窗格（釋放額度）。

2026-09-02 實測：每次 tool call 都把整個 context 從 cache 重讀一遍，
所以成本隨 context 線性放大 —— 400K context 的 session 每個 call 的
成本是 120K 的 3.3 倍，做的事一模一樣。詳見 memory
`claude-context-budget-2026-09` 與 docs/ops/dispatch.md 的 context 預算段。

模型自己跑不了這支：herdr agent prompt / start 不在 settings.json 的
allowlist，會被分類器擋（那道牆是對的 —— 送輸入到別的 session 會永久
銷毀該窗格裡未送出的草稿）。所以由 Carson 用 ! 執行：

  ! python /d/carson-agent/scripts/restart_bloated_panes.py          # 預演
  ! python /d/carson-agent/scripts/restart_bloated_panes.py --go     # 真的做
"""
import json, subprocess, sys, time

DRY = "--go" not in sys.argv

# 重開後要接回去的待辦（從各窗格回讀畫面抄的原話，已落檔的才列）
TARGETS = [
    {
        "pane": "wE:p1",
        "name": "herdr-opt",
        "why": "8ae57f4b『Herdr優化員』ctx 41%(~392K)；待辦(等 patch_context_budget.py)已完成，且有 pending update",
        "handoff": None,
    },
    {
        "pane": "w1:p1",
        "name": "wq-brain",
        "why": "60590d32『WorldQuant Brain』ctx 39%(~376K)；在等 16:10 結算，工作已落檔可接回",
        "handoff": (
            "你是 WorldQuant Brain 線。前一個 session 因為 context 撐到 376K "
            "被重開（每個 tool call 都會重讀整個 context，成本隨它線性放大）。"
            "接回待辦：herdr 窗格 w1:p9 等 15:40、w1:p8 等 16:10 的結算量測，"
            "落檔在 quant-service/brain_alpha/SETTLEMENT_20260902.log。"
            "16:10 那筆一出來，照判讀表把四個原始值直接貼回給 Carson。"
            "目前沒有開新一輪挖礦或挑片，沒有 simulate、沒有 submit —— 維持這樣。"
        ),
    },
]


def herdr(*args, check=True):
    # encoding 必須明講：預設走 cp950，herdr 的中文輸出會 UnicodeDecodeError，
    # 而那個錯發生在 reader thread 裡 —— 主流程只會拿到空字串，
    # at_shell_prompt() 於是永遠判失敗，腳本安靜地一個窗格都不重開。
    r = subprocess.run(["herdr", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        print("    ! herdr %s 失敗: %s" % (" ".join(args), (r.stderr or r.stdout).strip()[:200]))
    return r


def read_pane(pane, lines=6):
    r = herdr("pane", "read", pane, "--lines", str(lines), check=False)
    return r.stdout


def at_shell_prompt(pane):
    """claude 退出後畫面不該再有 claude 的狀態列。"""
    txt = read_pane(pane, 12)
    return ("auto mode on" not in txt) and ("ctx" not in txt)


def restart(t):
    pane, name = t["pane"], t["name"]
    print("\n=== %s (%s)" % (pane, t["why"]))

    draft = read_pane(pane, 30)
    if DRY:
        print("  [預演] 會送 /exit → agent start --kind claude → "
              + ("送交棒 prompt" if t["handoff"] else "不送 prompt"))
        return True

    print("  1) 送 /exit")
    herdr("agent", "prompt", pane, "/exit")
    for i in range(20):
        time.sleep(1)
        if at_shell_prompt(pane):
            print("     已回到 shell (%ds)" % (i + 1)); break
    else:
        print("     !! 20 秒後仍看不到 shell prompt —— 跳過這個窗格，不強行 start")
        return False

    print("  2) 起新的 claude")
    r = herdr("agent", "start", name, "--kind", "claude", "--pane", pane)
    if r.returncode != 0:
        print("     !! start 失敗，這個窗格停在 shell，手動起 claude 即可")
        return False
    print("     OK")

    if t["handoff"]:
        print("  3) 送交棒 prompt")
        time.sleep(2)
        herdr("agent", "prompt", pane, t["handoff"])
        print("     OK")
    return True


if __name__ == "__main__":
    if DRY:
        print("*** 預演模式（沒有 --go，什麼都不會動）***")
    ok = [restart(t) for t in TARGETS]
    print("\n完成 %d/%d" % (sum(1 for x in ok if x), len(ok)))
    if DRY:
        print("確認沒問題就加 --go 重跑。")
    else:
        print("提醒：w1:p1 原本輸入框裡有你未送出的草稿「16:10 出來直接回我」，")
        print("重開後會消失 —— 那句話的意思已經寫進交棒 prompt 了。")
