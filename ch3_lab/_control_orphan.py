# orphan 閘門的陽性/陰性對照。
# 判準(memory `verification-that-cannot-fail`):把被測的那個機制弄壞,
# 這個對照會不會跟著失敗?答案必須是「會」。
import json
import pathlib
import sys

sys.path.insert(0, r"D:\carson-agent\ch3_lab")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import make_reel  # noqa: E402

#: 🔴 **這份清單就是這道規則的定義。**
#: 描述由 gate_registry.describe() 從這裡產生 —— 不要人手另寫一份。
CASES = [
    {"kind": "negative", "label": "未動過的真 entry(hot_hand):閘門必須安靜"},
    {"kind": "positive", "label": "把某列 es 換成 77.7 / 0.4242 / -1234:事實庫別處找不到的值"},
]


SRC = pathlib.Path(r"D:\carson-agent\ch3_lab\facts\rechecked_episodes.json")
E0 = next(x for x in json.loads(SRC.read_text(encoding="utf-8"))["episodes"]
          if x["slug"] == "hot_hand")


def run(E, tag):
    segs = make_reel.build_script(E)
    try:
        make_reel.audit(E, segs)
        print(f"  {tag}: 通過(沒叫)")
        return False
    except SystemExit as ex:
        first = str(ex).splitlines()[0]
        print(f"  {tag}: 擋下 —— {first[:78]}")
        return True


print("陰性對照(未動過的真 entry,閘門應該安靜):")
neg = run(json.loads(json.dumps(E0)), "hot_hand 原樣")

print("陽性對照(畫面要印一個事實庫別處沒有的數字,閘門必須叫):")
pos = []
for bogus, tag in ((77.7, "把某列 es 換成 77.7"),
                   (0.4242, "換成 0.4242"),
                   (-1234, "換成 -1234")):
    e = json.loads(json.dumps(E0))
    e["twist_rows"][0]["es"] = bogus
    pos.append(run(e, tag))

ok = (not neg) and all(pos)
print()
print("結論:", "✓ 這道閘門會叫,而且不對真資料誤叫" if ok
      else "🔴 對照失敗 —— 這道閘門不算數")
sys.exit(0 if ok else 1)
