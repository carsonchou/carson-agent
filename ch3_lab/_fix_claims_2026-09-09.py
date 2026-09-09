"""誠信複驗抓到的 8 條宣稱,逐條改寫。

垮的不是數字那一層(20 條 claim 逐條對得上 verbatim),是**宣稱**那一層:
既有的閘門問「這個數字有沒有來源」,問不到「**這句話**有沒有來源」。

⚠️ 順帶自己多抓到 2 條同類的(對照組講錯),一起改 —— 驗證員點名的是那一族的
   代表,不是清單本身。
"""
import json
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(r"D:\carson-agent\ch3_lab\facts\rechecked_episodes.json")
d = json.loads(P.read_text(encoding="utf-8"))


def E(slug):
    return next(x for x in d["episodes"] if x["slug"] == slug)


# ───────────────────── 4a focus_techniques:對照組不是「什麼都不做」 ─────────────────────
e = E("focus_techniques")
e["reel"]["weight"] = ("Each one is a comparison somebody actually ran, "
                       "against a real alternative.")
e["reel"]["turn"] = (
    "Phone on the desk instead of in another room: working memory dropped "
    "in the first experiment, and again in a second one that repeated it. "
    "Both effects were small. In a long attention task, the group that "
    "briefly switched away did not decline at all, while the three groups "
    "that worked straight through all did. And people who wrote tomorrow's "
    "list before bed fell asleep faster than people who wrote down what "
    "they had already finished, 0.63.")
e["reel"]["verdict"] = ("None asks you to try harder. "
                        "All three change the situation instead.")

# ───────────────────── 4b how_to_remember_what_you_read ─────────────────────
e = E("how_to_remember_what_you_read")
e["reel"]["belief"] = ("You just read something. In a week, if all you do is "
                       "read it again, more than half of it will be gone.")
e["reel"]["weight"] = ("Three things change that, and each was compared with "
                       "a different thing people do instead.")
e["reel"]["verdict"] = ("None of them is reading it again. "
                        "When rereading was tested head to head, it lost.")

# ───────────────────── 4c study_techniques ─────────────────────
e = E("study_techniques")
e["reel"]["belief"] = ("Three study methods that beat what you are probably "
                       "doing instead.")
e["reel"]["weight"] = ("Each one was compared with what students do by "
                       "default: blocking one topic, rereading, "
                       "and just reading on.")
e["reel"]["verdict"] = ("Two of these were scored a week and a month after "
                        "the studying stopped. That is where the difference was.")

# ───────────────────── 4c pomodoro ─────────────────────
e = E("pomodoro")
e["reel"]["belief"] = ("Twenty-five minutes of work. Five minutes of break. "
                       "You have probably tried it.")
e["reel"]["weight"] = ("So here is the question: has anyone actually tested "
                       "that exact recipe?")
e["reel"]["turn"] = (
    "In our own search, we found one: 94 university students, "
    "one two-hour session. "
    "The closest earlier trial used 24 minutes and 6, not 25 and 5. "
    "And a study that kept coming up in that search never used work blocks "
    "or break blocks at all.")
e["twist_rows"] = [
    {"label": "trials on the exact recipe", "what": "that our search found",
     "es": 1, "es_kind": "count", "cue": "we found one"},
    {"label": "people in it", "what": "one two-hour session",
     "es": 94, "es_kind": "count", "cue": "94 university students"},
    {"label": "the closest earlier trial", "what": "used a different ratio",
     "es": 24, "es_kind": "count", "cue": "24 minutes and 6"},
]

# ───────────────────── 順手:E1 收束句那半句沒有來源 ─────────────────────
e = E("learning_styles")
e["reel"]["verdict"] = ("Rogowsky ran the experiment directly, audiobook "
                        "against e-text. No interaction. What failed is the "
                        "matching — having a preference was never the claim.")


def main():
    tmp = P.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    back = json.loads(tmp.read_text(encoding="utf-8"))
    for s in ("focus_techniques", "how_to_remember_what_you_read",
              "study_techniques", "pomodoro", "learning_styles"):
        got = next(x for x in back["episodes"] if x["slug"] == s)
        assert got["reel"]["captions"] and got["twist_rows"], s
    banned = ("doing nothing", "almost none", "does not work",
              "Most study advice", "feel worse", "most often cited",
              "randomised", "one student")
    for x in back["episodes"]:
        txt = " ".join(str(v) for k, v in (x.get("reel") or {}).items()
                       if isinstance(v, str))
        hit = [b for b in banned if b in txt]
        if hit:
            print(f"  🔴 {x['slug']} 仍留著:{hit}")
    os.replace(tmp, P)
    print("改寫完成")


if __name__ == "__main__":
    main()
