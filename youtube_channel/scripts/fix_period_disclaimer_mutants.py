# -*- coding: utf-8 -*-
"""fix_period_disclaimer.py 的**原始碼突變**列(常駐,改工具就重跑)。

    .venv/Scripts/python.exe scripts/fix_period_disclaimer_mutants.py [目標檔]

self_test 裡的【突變】格只證明「斷言邏輯分辨得出來」,它沒有改到真的程式碼。
這支才是真的突變:把承重那一行改壞 ⇒ 目標檔的 --self-test 必須翻紅(rc != 0)。
陰性對照:改一行不承重的字 ⇒ 必須維持全綠,否則是「什麼都翻」的壞尺。
崩潰(Traceback)另外記紅:崩潰也是 rc != 0,但後面的格子全部沒跑到,不算乾淨的翻面。

突變檔寫到系統暫存目錄,不碰 repo;只跑 --self-test,不連 YouTube。
每一條的錨必須在目標檔裡**恰好出現 1 次**,否則這條突變不成立 ⇒ 記紅
(有人改了那一行,這張表就要跟著改,不准讓它靜默變成空轉)。
"""
import io
import os
import pathlib
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
TARGET = (pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1
          else HERE / "fix_period_disclaimer.py")
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=str(HERE))

# (標籤, 錨(必須恰好出現 1 次), 突變後, 預期翻紅?)
MUTS = [
    ("F1  可寫欄位表拿掉 defaultAudioLanguage",
     '"defaultLanguage", "defaultAudioLanguage")', '"defaultLanguage")', True),
    ("F1  body_keeps_fields 改回走同一張表",
     "    for k in live_sn:", "    for k in _WRITABLE_SNIPPET:", True),
    ("M3  次數檢查放寬成 n==0",
     "    if n != 1:", "    if n == 0:", True),
    ("M4  核准句逗號換全形",
     '_TAIL_NEW = "之後的影片已改進做法,但仍', '_TAIL_NEW = "之後的影片已改進做法，但仍', True),
    ("F5  插入路徑改回舊句",
     "NOTE = NOTE_NEW ", "NOTE = _HEAD + _TAIL_OLD ", True),
    ("F5  超長不拒寫",
     "    if len(new) > DESC_LIMIT:", "    if False:", True),
    ("cron 改寫變成預設",
     "    if args.rewrite_note:", "    if True:", True),
    ("F4  分類退化成 'quota' in 字串",
     '    return s.startswith("quota exhausted:") or s.startswith("quota reserve:")',
     '    return "quota" in s.lower()', True),
    ("F4  型別判斷拿掉(只剩前綴)",
     '    if type(exc).__name__ == "QuotaExhausted":', "    if False:", True),
    ("陰性對照:改一句 dry-run 提示字",
     "寫入時間戳:dry-run 不落。", "寫入時間戳(對照組):dry-run 不落。", False),
]


def run(text, tag, d):
    p = pathlib.Path(d) / ("m_%s.py" % tag)
    p.write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(p), "--self-test"],
                       capture_output=True, env=ENV)
    out = r.stdout.decode("utf-8", "replace")
    err = r.stderr.decode("utf-8", "replace")
    reds = [ln.strip() for ln in out.splitlines() if ln.startswith("  !! ")]
    return r.returncode, reds, ("Traceback" in err)


def main():
    base = TARGET.read_text(encoding="utf-8")
    print("對象:%s" % TARGET)
    with tempfile.TemporaryDirectory(prefix="fpd_mut_") as d:
        rc0, reds0, cr0 = run(base, "00_base", d)
        print("基準(未突變):rc=%d  紅格 %d%s" % (rc0, len(reds0), "  崩潰" if cr0 else ""))
        bad = rc0 != 0
        for i, (lab, old, new, want_red) in enumerate(MUTS, 1):
            n = base.count(old)
            if n != 1:
                print("  ?? %-36s 錨出現 %d 次 ⇒ 突變不成立" % (lab, n))
                bad = True
                continue
            rc, reds, crash = run(base.replace(old, new, 1), "%02d" % i, d)
            ok = ((rc != 0) == want_red) and not crash
            bad = bad or not ok
            print("  %s %-36s rc=%d  紅格 %d%s" % ("OK " if ok else "!! ", lab, rc,
                                                  len(reds), "  🔴崩潰" if crash else ""))
            for ln in reds[:3]:
                print("        翻紅:%s" % ln[4:][:92])
    print("全部符合預期(每個突變都翻紅、對照維持全綠、沒有崩潰)" if not bad
          else "🔴 有突變活下來 / 對照翻了 / 有崩潰")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
