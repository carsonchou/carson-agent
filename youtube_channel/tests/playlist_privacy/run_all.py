#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_playlists privacyStatus 閘門的回歸套件 —— 再動那段 insert 迴圈之前先跑這支。

用法(任何目錄下都可以跑,cwd 由本支自己設):
    youtube_channel/.venv/Scripts/python.exe youtube_channel/tests/playlist_privacy/run_all.py

驗收三條(派工單原文):突變一條翻紅、陰性對照一條、離線重模擬 09-17 那一輪 5 支不在名單。
全部走 sim.py,跑的是 scripts/build_playlists.py 的**真程式碼**,不是抄本。

🔴 判準一律認 **video id**,不認序數、不寫死支數(總督導 2026-09-14 裁決 (a)):
帳本一長,同一批片在 insert 名單裡的位置就會漂 —— 09-12 量到是該輪第 3–7 次 insert,
09-14 已經是第 5–9 次。序數只當觀測值印出來,不當判準
(memory `criteria-anchored-to-mutable-property`)。

🔴 這支自己會不會叫:第 0 條先核突變錨點在原始碼裡恰好出現 1 次。錨點不見了(被改寫、
被搬走)就直接 FAIL —— 不然突變列會變成「改了個不存在的東西,原碼照跑,測試照綠」
(memory `verification-that-cannot-fail`)。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BASE / "scripts"))

from sim import SRC, STUDIO, simulate, _diff_studio  # noqa: E402

# 🔴 正式機心跳時間軸。本套件跑完它必須一個位元組都沒變 —— 2026-09-14 之前的版本
# 每跑一輪就往這裡 append 一行假的「雙主軸分群完成」,而 .gitignore 忽略整個 STUDIO/,
# git status --porcelain 看不見(總督導裁決,結案條件④)。
OPS_LOG = STUDIO / "ops_log.txt"
TEST_SIGNATURE = "雙主軸分群完成"      # 本套件會產生的那種假心跳行的特徵字串

# 09-17 22:00 那一輪(deploy/crontab.txt 裡 grep `build_playlists.py --max 10` 得到的
# 那行 `0 22 * * 4 ...`)當天會變 private 的 5 支。
TARGETS = ["I8F83sPFKWg", "tN56crKxwJE", "vwEaoo3Txjw", "UTuMMyvdQ5U", "DhX2uNzjZ-o"]
PRIVATE_5 = {v: "private" for v in TARGETS}

# 突變:把閘門條件改成恆真 = 「把 privacyStatus 檢查拿掉」。
ANCHOR = 'if privacy.get(vid) != "public":   # PRIVACY-GATE'
MUTANT = 'if False:   # PRIVACY-GATE(已突變)'

_p = _f = 0


def check(cond, msg, detail=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"PASS  {msg}")
    else:
        _f += 1
        print(f"FAIL  {msg}" + (f"\n        {detail}" if detail else ""))


def ops_size() -> int:
    return OPS_LOG.stat().st_size if OPS_LOG.exists() else 0


def ops_tail_from(offset: int):
    """只讀 offset 之後新長出來的那一段。用位元組偏移量、不用行數 ——
    行數會被產線同時間寫進來的心跳干擾,偏移量不會:它問的是「有沒有我的行」,
    不是「有沒有多出行」(總督導 2026-09-14 §2 第一段)。"""
    if not OPS_LOG.exists():
        return []
    with OPS_LOG.open("rb") as f:
        f.seek(offset)
        seg = f.read()
    return seg.decode("utf-8", errors="replace").splitlines()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    src = SRC.read_text(encoding="utf-8")
    ops_before = ops_size()
    print(f"[量] 跑之前 STUDIO/ops_log.txt size = {ops_before} bytes")

    # ---- ⓪ 儀器自檢:突變錨點存在且唯一 ----
    check(src.count(ANCHOR) == 1,
          "⓪ 突變錨點在 build_playlists.py 恰好 1 次",
          f"實際出現 {src.count(ANCHOR)} 次;錨點被改掉就等於突變列失效,先修這裡再談其他條")
    if src.count(ANCHOR) != 1:
        print("\n錨點不在,後面每一條都證明不了東西,直接停。")
        return 1

    # ---- ① 離線重模擬 09-17 22:00 那一輪:5 支不在 insert 名單 ----
    r = simulate(privacy=PRIVATE_5, max_add=10)
    ins = r["inserted"]
    hit = [v for v in TARGETS if v in ins]
    check(r["rc"] == 0, "① 重模擬跑完 rc == 0", f"rc={r['rc']}  stderr尾={r['stderr'][-300:]}")
    check(not hit, "① 09-17 那一輪 insert 名單不含那 5 支",
          f"仍被插進去:{hit}\n        本輪 insert 名單:{ins}")
    check(all(f"[skip]" in r["stderr"] and v in r["stderr"] for v in TARGETS),
          "① 5 支各有一行 [skip] 記錄", r["stderr"][:600])

    # ---- ② 陰性對照:public 的片照常加入 ----
    r_allpub = simulate(privacy={}, max_add=10)
    # 🔴 判準不釘在序數/支數上:帳本一長,名單的位置和長度都會漂(09-12 那 5 支是該輪
    # 第 3–7 次 insert,09-14 已經變成第 5–9 次)。這裡問的是「跳過非 public 有沒有
    # 害額度變少」,所以拿同一輪全 public 的結果當基準比,不寫死 10。
    check(len(ins) == len(r_allpub["inserted"]),
          "② 陰性對照:跳過非 public 不會吃掉額度(與同輪全 public 插入支數相同)",
          f"擋掉 5 支後插了 {len(ins)} 支,全 public 時插了 {len(r_allpub['inserted'])} 支")
    check(all(v not in TARGETS for v in ins) and len(set(ins)) == len(ins),
          "② 陰性對照:插進去的都是 public 且不重複", str(ins))
    check(set(TARGETS).issubset(set(r_allpub["inserted"])),
          "② 陰性對照(相反那一邊):5 支若仍是 public,閘門不會擋它們",
          f"全 public 時的名單:{r_allpub['inserted']}")

    # ---- ③ 突變:拿掉 privacyStatus 檢查 → ① 必須翻紅 ----
    r_mut = simulate(privacy=PRIVATE_5, max_add=10,
                     mutate=lambda s: s.replace(ANCHOR, MUTANT, 1))
    mut_hit = [v for v in TARGETS if v in r_mut["inserted"]]
    check(len(mut_hit) == 5,
          "③ 突變列:閘門條件改成恆真後,5 支全部被插回去(測試翻紅)",
          f"突變後只插回 {len(mut_hit)} 支:{mut_hit}\n        "
          f"沒有全翻紅 = 這條判準沒在看那段程式碼,閘門的因果宣稱不成立")

    # ---- ④ fail-closed:查不到狀態的 id 也要跳過 ----
    r_miss = simulate(privacy={v: None for v in TARGETS}, max_add=10)
    check(not [v for v in TARGETS if v in r_miss["inserted"]],
          "④ videos.list 沒回來的 id 當成「不是 public」跳過(失敗方向 = 不加入)",
          str(r_miss["inserted"]))

    # ---- ⑤ videos.list 用法:part=status、每批 ≤ 50 ----
    check(all(0 < len(c) <= 50 for c in r["videos_list_calls"]) and r["videos_list_calls"],
          "⑤ videos.list 每批 ≤ 50 個 id(1 unit/批)",
          str([len(c) for c in r["videos_list_calls"]]))
    check('part="status"' in src and "yt.videos().list(" in src,
          "⑤ 查的是 videos.list part=status")

    # ---- ⑥ 隔離:陰性對照 —— 攔截打開時,暫存 ops_log 一行都沒有 ----
    neg_lines = (r["ops_file_lines"] + r_allpub["ops_file_lines"]
                 + r_mut["ops_file_lines"] + r_miss["ops_file_lines"])
    check(len(neg_lines) == 0,
          "⑥ 隔離陰性對照:四輪都攔住,暫存 ops_log 0 行",
          f"暫存檔裡竟有 {len(neg_lines)} 行:{neg_lines}")

    # ---- ⑦ 隔離:陽性對照 —— 只拿掉「攔 log_ops」那層,路徑仍指暫存 ⇒ 行會落在暫存檔 ----
    # 這條回答的是「沒攔的時候到底會不會寫」。少了它,⑥ 的 0 行有可能只是因為那段碼
    # 根本沒跑到(memory filter-accepted-is-not-filter-applied:要問相反那一邊)。
    # 🔴 正式機零寫入:ops.OPS 已經指到暫存,跑的不是沒隔離的版本。
    pos = [simulate(privacy=PRIVATE_5, max_add=10, intercept_log_ops=False),
           simulate(privacy={}, max_add=10, intercept_log_ops=False),
           simulate(privacy=PRIVATE_5, max_add=10, intercept_log_ops=False,
                    mutate=lambda s: s.replace(ANCHOR, MUTANT, 1)),
           simulate(privacy={v: None for v in TARGETS}, max_add=10, intercept_log_ops=False)]
    pos_lines = [ln for p in pos for ln in p["ops_file_lines"]]
    check(len(pos_lines) == 4 and all(TEST_SIGNATURE in ln for ln in pos_lines),
          "⑦ 隔離陽性對照:拿掉攔截後,四輪各寫 1 行到暫存檔(共 4 行,量尺看得見新增)",
          f"共 {len(pos_lines)} 行:{pos_lines}")

    # ---- ⑧ 正式機:位元組偏移量之後的新增段落,不准有任何一行是本套件寫的 ----
    new_seg = ops_tail_from(ops_before)
    mine = [ln for ln in new_seg if TEST_SIGNATURE in ln]
    check(not mine,
          "⑧ 正式機 ops_log.txt 新增段落裡沒有任何一行含測試特徵字串",
          f"本套件污染了正式機心跳時間軸,逐行:\n        " + "\n        ".join(mine))
    print(f"[量] 跑之後 STUDIO/ops_log.txt size = {ops_size()} bytes;"
          f"新增段落 {len(new_seg)} 行,其中測試特徵行 {len(mine)} 行")
    if new_seg:
        print("[量] 新增段落逐行(產線在同一時間寫的行允許出現,要在報告裡註明是哪個部門):")
        for ln in new_seg:
            print(f"       {ln}")

    # ---- ⑨ 守門人自己的陽性對照:_diff_studio 真的看得見差異嗎 ----
    # ⑥⑦⑧ 全綠的另一個可能是「偵測器自己壞掉」(memory detector-failure-shapes-2026-09)。
    # 這條用捏造的快照餵它:看不見差異的偵測器,前面三條就什麼都沒證明。
    fake_b = {"x.json": (10, 111, "aa"), "y.json": (5, 222, None)}
    fake_a = {"x.json": (11, 333, "bb"), "y.json": (5, 222, None)}
    d = _diff_studio(fake_b, fake_a)
    check(len(d) == 1 and d[0].startswith("x.json:"),
          "⑨ 守門人自檢:_diff_studio 看得見被改動的檔、也不會誤報沒動的檔",
          f"實際回傳:{d}")

    print(f"\n合計 PASS={_p} FAIL={_f}")
    return 0 if _f == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
