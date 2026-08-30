#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_domains.py — 第四種集型:同一個宣稱,跨多個領域。

## 為什麼需要它
`effect_scan.py` 量過 22 個候選,第一名是 **10,000 小時法則,分數 24,311
—— 第二名的 2.3 倍**。但它套不進現有的任何一種集型:

- FReD 那條(`make_episode`)要「一篇原始 對 一篇重測」的配對,沒有。
- 名案那條(`make_famous`)要一個效果量 d 或 r,而這篇統合分析的頭條
  數字是**變異數百分比**(26% / 21% / 18% / 4% / <1%)。
- 家族那條(`make_lineup`)要同一個效應的多次重測,這是同一個宣稱在
  不同領域的解釋力。

硬把 26% 換算成 r = 0.51 雖然數學上精確,螢幕上卻會出現一個**觀眾去查
論文查不到的數字**(論文寫 26%,我印 0.51)。寧可多一種集型,不要多一個
對不上的數字。

## 畫面的論證方式
不是印「26%」四個字 —— 那看起來很大。是畫一條滿格的橫條,把練習解釋掉
的那一段上色。26% 的條看起來就是四分之一,那才是這個數字真正的意思。
**視覺本身就是論證,而且它跟數字是同一個數字。**

用法:
  python make_domains.py --script-only
  python make_domains.py
"""
import argparse
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "facts" / "domain_episodes.json"

W, H, FPS = 1920, 1080, 30
BG, FG, DIM = "#0E1116", "#E8ECF1", "#8A94A6"
ACCENT, REST = "#FFC23D", "#252C36"


def load(slug):
    d = json.loads(SRC.read_text(encoding="utf-8"))
    for e in d["episodes"]:
        if e["slug"] == slug:
            return e
    raise SystemExit(f"⛔ {slug} 不在 facts/domain_episodes.json 裡")


def say_pct(dm):
    """唸法。**上界要唸成上界。**

    `pct: 1, pct_is_upper_bound: true` 存的是「less than 1%」。
    唸成「one percent」是把一個上界講成一個點估計 —— 那是**往上報**,
    而且方向剛好讓故事沒那麼強;更重要的是它跟論文原文不一樣,
    觀眾去查會查到不同的字。
    """
    if dm.get("pct_is_upper_bound"):
        return f"less than {dm['pct']} percent"
    return f"{dm['pct']} percent"


def fmt_pct(dm):
    """**寫在畫面上**的百分比。跟 say_pct(唸的)是同一條規則的兩種形式。

    🔴 這兩個必須放在一起。第一版只有 say_pct,縮圖端自己寫了
    `f"{x['pct']}%"` —— 於是旁白唸「less than one percent」、縮圖印
    「1%」。同一個上界,兩個表面,兩種說法,而觀眾看到的是後者。
    今晚同型錯誤的第三次(前兩次:Shorts 標籤單數、預告判決塊)。
    """
    return f"{'<' if dm.get('pct_is_upper_bound') else ''}{dm['pct']}%"


#: Cohen's d 的唸法。**用 make_episode.say_num,不要自己寫一個。**
#: 🔴 我自己寫的第一版是 `f"{abs(x):.2f}".replace("0.", "zero point ")`,
#:    產出「zero point 34」—— 小數點後面的數字沒有被拆開唸,TTS 會唸成
#:    「三十四」。而 say_num 早就把這件事做對了,連負號要唸出來(方向相反
#:    和變小是兩個結論)都處理過。同一件事第二份實作,今晚第 N 次。
from make_episode import say_num as say_d                    # noqa: E402



def short_stat(stat):
    """畫面上的統計式:拿掉 eta2 那半,**保留完整的 F(df, df) = value**。

    🔴 第一版寫 `stat.split(",")[0]` —— 而那個逗號在**括號裡面**
    (`F(1, 38) = 1.16`),於是畫面上印出「F(1」。無聲截斷,而且
    截出來的東西沒有意義。這跟一小時前 Shorts 來源行被
    `wrap(...)[:2]` 切成半個論文名是同一類錯:**用一個看起來夠用的
    分隔符去切結構化字串**。

    這裡改成只拿掉 eta2 那一段,並且斷言切完仍然是完整的式子。
    """
    s = (stat or "").strip()
    if not s:
        return ""
    s = re.sub(r",\s*eta\s*2?\s*=\s*[\d.]+\s*$", "", s).strip().rstrip(",")
    # 切完必須還是「有等號、括號成對」的完整式子,否則寧可整個不印
    if "=" not in s or s.count("(") != s.count(")"):
        return ""
    return s



def fit_w(plt, text, base, max_frac, weight="bold"):
    """量出這段字在 base 字級下有多寬,超過 max_frac 就回傳縮小後的字級。

    🔴 **字級要用量的,不是挑的。** 這條線在 Shorts 那邊已經學過一次:
    肉眼調過兩輪、兩輪都還是越界,因為**文案長度會變** ——
    「felt more powerful」和「choice changed the attitude」放同一個位置,
    一個字級不可能同時對。
    這裡的名稱欄同樣:power posing 的名稱短、cognitive dissonance 的長,
    寫死 40pt 就是後者撞上數字欄。
    """
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    t = ax.text(0.5, 0.5, text, ha="center", va="center",
                fontsize=base, weight=weight)
    fig.canvas.draw()
    frac = t.get_window_extent(
        renderer=fig.canvas.get_renderer()).width / W
    plt.close(fig)
    if frac <= max_frac or frac == 0:
        return base
    return max(22, int(base * max_frac / frac))



def _need(E, field):
    """缺了就中止,不要用預設值頂替。

    這條線反覆出事的形狀是「A 集的預設值被 B 集用上」——
    模板化的產線裡,一個看似無害的 fallback 就是一句別人的話。
    """
    raise SystemExit(
        f"⛔ {E['slug']} 缺 `{field}`,而這一段沒有可以安全共用的預設值 "
        f"—— 上一版的預設是 power posing 的結論,其他集用上就是唸別人的話。"
        f"不出片。")


def build_outcomes_script(E):
    """`arc: outcomes` —— 一個宣稱、原作者量了好幾個結果、重測只有一部分回來。

    🔴 這一集的重點**不是「沒重現」**,是**哪一個重現了**。四個結果裡
    felt power 顯著(p=.017),三個生理與行為結果不顯著。把它講成
    「power posing 沒用」是過度宣稱,而且跟我自己引用的原文矛盾。
    """
    o, t = E["original"], E["test"]
    outs = t["outcomes"]
    kept = [x for x in outs if x["sig"]]
    lost = [x for x in outs if not x["sig"]]
    return [
        # 🔴 hook 也要從事實庫來。第一版寫死 power posing 的那句,
        #    於是 learning styles 那集的開場唸「Stand like this for two
        #    minutes」—— 完全不相干,而且旁白與畫面都會這樣出去。
        #    新增集型時最容易漏的就是這種「看起來像模板其實是硬編」的地方。
        ("hook", E.get("say_hook") or (E["hook"] + " You have heard this one.")),
        ("origin", o.get("say_origin") or
         (f"The {o['year']} study measured {len(outs)} things on "
          f"{o['n']} people: how powerful they felt, their testosterone, "
          f"their cortisol, and whether they took a financial risk. "
          f"All {len(outs)} moved.")),
        ("test", t.get("say_test") or
         (f"In {t['year']} another team ran it on {t['n']} people, with the "
          f"experimenter blind to which pose you were in. Their power to "
          f"detect an effect the size of the original was above 95 percent.")),
        ("outcomes",
         # 🔴 **p 值不唸,只上畫面。** TTS 把「.017」唸成一串怪音,而
         #    畫面上有精確值可以查。旁白負責「顯不顯著」這個判斷,
         #    畫面負責那個可查證的數字 —— 兩邊講的是同一件事的兩個層次,
         #    不是同一件事講兩次。
         "Here is what came back. "
         + " ".join(
             (f"{x['name'].capitalize()}, {say_d(x['d'])}"
              if x.get("d") is not None
              else f"{x['name'].capitalize()}")
             + (", significant." if x["sig"] else ", not significant.")
             for x in outs)),
        ("punch", t.get("say_punch") or
         (f"{len(kept)} of the {len(outs)} came back. "
          f"The one you can only find out by asking. "
          f"The {len(lost)} you could actually measure from the outside "
          f"did not.")),
        # 🔴 **結論不能有預設值。** 這一段是整支片的收尾,而預設值寫的是
        #    power posing 的結論(睪固酮、皮質醇)。stereotype threat 那集
        #    我還沒填 say_verdict,稿子就直接唸出別集的結論 ——
        #    而且旁白、畫面、說明欄三個表面都會這樣出去。
        #    hook 是同一個病(learning styles 差點唸「Stand like this for
        #    two minutes」),那次我修了 hook 沒修這裡。
        #    **fail-closed:沒有就不出片。**
        ("verdict", t.get("say_verdict") or _need(E, "test.say_verdict")),
        ("close",
         "One claim, the numbers behind it, no adjectives."),
    ]


def build_script(E):
    if E.get("arc") == "outcomes":
        return build_outcomes_script(E)
    o, t = E["original"], E["test"]
    doms = t["domains"]
    by = {d["name"]: d for d in doms}
    return [
        # 跟 outcomes 那條同樣的理由:hook 從事實庫來,不要寫死。
        # 目前 domains 只有一集,寫死看起來沒事 —— 直到有第二集為止。
        ("hook", E.get("say_hook") or (E["hook"] + " You have heard this one.")),
        ("origin",
         f"It comes from a paper published in {o['year']}. Its claim was "
         f"that individual differences, even among elite performers, are "
         f"closely related to how much deliberate practice a person has "
         f"done. That paper has been cited more than "
         f"{o['cited_by_approx']:,} times."),
        ("test",
         f"In {t['year']}, researchers pooled every study they could "
         f"find that measured both things: how much people practised, and "
         f"how well they performed."),
        ("domains",
         "Here is how much of the difference in performance deliberate "
         "practice actually accounted for. "
         + " ".join(f"{d['name'].capitalize()}, {say_pct(d)}." for d in doms)),
        ("punch",
         f"Games is the best case, and even there it is about a quarter. "
         f"In professions - the place this idea gets quoted at work - it is "
         f"{say_pct(by['professions'])}."),
        ("verdict",
         "The authors' own conclusion was that deliberate practice is "
         "important, but not as important as has been argued. "
         "Practice is not nothing. It is just not the whole story."),
        ("close",
         "One claim, the numbers behind it, no adjectives."),
    ]


def audit(E, segs):
    """稿子裡每個數字都要在事實庫找得到。fail-closed。

    ⚠️ 用**數字邊界**比對,不是子字串。今晚 ep0 就是因為 `"1" in "12"`
    成立而給了假綠燈 —— 同一個錯不能在下一支再犯一次。
    """
    o, t = E["original"], E["test"]
    ok = {str(o["year"]), str(t["year"])}
    if o.get("cited_by_approx"):
        ok |= {str(o["cited_by_approx"]), f"{o['cited_by_approx']:,}"}
    if E.get("arc") == "outcomes":
        outs = t["outcomes"]
        ok |= {str(t["n"]), str(len(outs)),
               str(sum(1 for x in outs if x["sig"])),
               str(sum(1 for x in outs if not x["sig"])), "95"}
        if o.get("n"): ok.add(str(o["n"]))
        for fld in ("say_origin", "say_test", "say_punch", "say_verdict"):
            for tok in re.findall(r"\d(?:[\d,.]*\d)?",
                                  str(t.get(fld) or o.get(fld) or "")):
                ok.add(tok)
        for x in outs:
            # 🔴 溯源正則抓的是**純數字 token**:旁白寫「p equals .017」,
            #    抓出來的是 `017`,不是 `.017` 也不是 `0.017`。
            #    所以放行清單要放**它真的會抓到的那個形式**,而不是我
            #    心裡想的那個形式。第一版就因此把自己的稿子擋下來。
            ok |= {str(x["p"]), f"{x['p']:.3f}".split(".")[1]}
            if x.get("d") is not None:
                ok |= {f"{abs(x['d']):.2f}", f"{x['d']:.2f}",
                       f"{abs(x['d']):.2f}".split(".")[1]}
            # 統計式裡的數字(F(1, 38) = 1.16 之類)也要放行
            for tok in re.findall(r"\d(?:[\d,.]*\d)?", str(x.get("stat") or "")):
                ok.add(tok)
    else:
        ok |= {str(d["pct"]) for d in t["domains"]}
    bad = []
    for name, txt in segs:
        for num in re.findall(r"\d(?:[\d,]*\d)?", txt):
            if num not in ok:
                bad.append((name, num))
    if bad:
        raise SystemExit(f"⛔ 稿子裡有溯源不到的數字:{bad}")
    # 缺的欄位不准出現在稿子裡(k 與 n 摘要沒給,我還沒讀原文)
    # 🔴 `missing` 有兩種用途,分開:
    #    · `missing_fields`:**欄位名**(k / n),機器拿來擋「稿子提到了但
    #      事實庫沒有」的情況
    #    · `missing`:給人看的說明(「付費牆,一手驗不到」),不參與檢查
    #    第一版只有一個欄位,於是我寫成人看的句子之後,audit 拿它去查表
    #    直接 KeyError。**一個欄位兩種用途,遲早會撞。**
    _WORDS = {"k": ("studies", "papers"), "n": ("participants",)}
    for miss in t.get("missing_fields", []):
        if miss not in _WORDS:
            raise SystemExit(f"⛔ missing_fields 只收欄位名(k / n),"
                             f"收到「{miss}」—— 給人看的說明請放 `missing`")
        raise_if = _WORDS[miss]
        for name, txt in segs:
            for w in raise_if:
                if w in txt.lower():
                    raise SystemExit(
                        f"⛔ {name} 提到「{w}」,但事實庫把 {miss} 標成 "
                        f"missing(摘要沒給,我還沒讀原文)。不准填空。")
    print(f"  數字溯源 ✓（{len(ok)} 個可用值;"
          f"missing 欄位 {t.get('missing')} 沒被提到）")


def render_scene(name, t_now, dur, ctx):
    plt, E = ctx["plt"], ctx["E"]
    T = E["test"]
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ease = lambda x: 1 - (1 - x) ** 3
    a = ease(min(1.0, t_now / 0.7))

    def txt(y, s, fs, col=FG, w="bold", al=None, x=0.5, ha="center"):
        ax.text(x, y, s, ha=ha, va="center", fontsize=fs, color=col,
                weight=w, alpha=a if al is None else al)

    if name == "hook":
        # 兩行來自手寫的白話主張(plain_claims),不是寫死的字串。
        import plain as _plain
        _pc = _plain.get(f"eps_domain/{E['slug']}") or {}
        _l = _pc.get("lines") or ["", ""]
        txt(0.60, _l[0].title() if _l[0] else "", 70)
        txt(0.47, (_l[1].title() + ".") if _l[1] else "", 70)
        if t_now > 2.0:
            b = ease(min(1.0, (t_now - 2.0) / 0.7))
            txt(0.30, E["popular_name"], 46, ACCENT, "bold", b)
    elif name == "origin":
        txt(0.66, str(E["original"]["year"]), 150, DIM)
        txt(0.48, "the paper everyone is quoting", 46, DIM, "normal")
        if t_now > 2.4:
            b = ease(min(1.0, (t_now - 2.4) / 0.7))
            # 🔴 引用數是選填的:不是每一集都查得到,而**沒有就不要放**。
            #    有 n 就改印樣本數 —— 那對「這個結論是從多少人來的」
            #    反而比引用數更切題。都沒有就只留年份。
            o = E["original"]
            if o.get("cited_by_approx"):
                txt(0.30, f"cited more than {o['cited_by_approx']:,} times",
                    58, ACCENT, "bold", b)
            elif o.get("n"):
                txt(0.30, f"{o['n']:,} people", 58, ACCENT, "bold", b)
    elif name == "test":
        txt(0.60, str(T["year"]), 150, DIM)
        txt(0.42, "somebody added up every study", 52, FG, "normal")
    elif name in ("outcomes", "punch") and E.get("arc") == "outcomes":
        # 四列:量了什麼 / 效果量 / p 值 / 成不成立。
        # 🔴 **不畫長條。** d 沒有「佔滿格的幾分之幾」這種讀法,畫成長條
        #    等於發明一個觀眾無法解讀的比例尺(而且負的 d 要往哪邊長?)。
        #    清單反而更誠實:數字就是數字,旁邊寫它過不過門檻。
        txt(0.90, "what came back", 46, DIM, "normal")
        outs = T["outcomes"]
        for i, x in enumerate(outs):
            step = 1.9 if name == "outcomes" else 0.0
            if t_now < 0.4 + i * step:
                continue
            b = ease(min(1.0, (t_now - 0.4 - i * step) / 0.6))
            step_y = 0.145 if outs[0].get("d") is not None else 0.205
            y = 0.72 - i * step_y
            hot = x["sig"]
            col = "#5FC98A" if hot else DIM
            # 四欄的 x 座標從安全區倒推,不是挑出來的:
            # 名稱 0.08→0.44、d 收在 0.56、p 收在 0.70、判決 0.73→0.92。
            # 名稱由下面兩種版面各自畫 —— 單行版畫在 y,兩行版畫在
            # y+0.035。這裡**不要先畫一次**:我上一版留著這行,結果
            # 兩行版把名稱畫了兩次,重疊守門抓到「自己疊自己」628×19。
            # 有 d 就印 d,沒有就印它真正報的統計式(F 值)。
            # 🔴 **不要為了版面整齊而編一個 d 出來** —— learning styles
            #    那篇報的是 F 與 p,硬換算成 d 會出現一個查不到的數字。
            # 🔴 畫面只放 F,**η² 留給說明欄**。完整的
            #    「F(1, 110) = 4.92, eta2 = 0.04」在這一欄會撞到名稱
            #    (實測重疊 376 畫素)。少放不等於藏 —— 說明欄有完整原句,
            #    而畫面要能一眼讀完。
            pv = f"p = {x['p']:.3f}".replace("0.", ".")
            if x.get("d") is not None:
                # d 很短,四欄放得下:名稱 | d | p | 判決
                # 🔴 名稱這一行是我修「名稱被畫兩次」時**拿掉之後忘了補回來**的
                #    —— 兩行版面補了,這條沒補,於是有 d 的那幾集整排標籤消失,
                #    畫面上只剩「d = -0.03  p = .790  not significant」。
                #    版面守門看不到:少畫一個元素不會出界、也不會重疊。
                # 名稱欄可用寬度:0.08 起,數字欄最寬的那個右對齊收在 0.60,
                # 中間留 0.03 空白 → 量到最長的那個名稱來決定整組字級。
                _w = max(fit_w(plt, f"d = {z['d']:+.2f}".replace("+", " "),
                               42, 0.20) and 0.14 for z in outs)
                _nf = min(fit_w(plt, z["name"], 40, 0.60 - _w - 0.11)
                          for z in outs)
                ax.text(0.08, y, x["name"], ha="left", va="center",
                        fontsize=_nf, color=FG if hot else DIM,
                        weight="bold", alpha=b)
                ax.text(0.60, y, f"d = {x['d']:+.2f}".replace("+", " "),
                        ha="right", va="center", fontsize=42, color=col,
                        weight="bold", alpha=b)
                ax.text(0.735, y, pv, ha="right", va="center",
                        fontsize=36, color=DIM, alpha=b)
                ax.text(0.765, y, "held" if hot else "not significant",
                        ha="left", va="center", fontsize=32, color=col,
                        weight="bold", alpha=b)
            else:
                # 🔴 F 值那種很長(`F(1, 110) = 4.92`)。我先後試過
                #    「只留 F」(切在括號內的逗號 → 畫面印出「F(1」)、
                #    「統計式與 p 併成一欄」(仍然撞到名稱 85 畫素)——
                #    **橫向就是不夠**,而縱向這一集只有三列、空了半個畫面。
                #    所以改成一列兩行:名稱一行,統計一行。
                #    橫向擠不下的時候不要繼續縮字,把它排到縱向去。
                st = short_stat(x.get("stat"))
                ax.text(0.08, y + 0.035, x["name"], ha="left", va="center",
                        fontsize=44, color=FG if hot else DIM,
                        weight="bold", alpha=b)
                ax.text(0.10, y - 0.045,
                        (st + "    " if st else "") + pv + "    "
                        + ("held" if hot else "not significant"),
                        ha="left", va="center", fontsize=32,
                        color=col if hot else DIM, alpha=b)
    elif name in ("domains", "punch"):
        # 滿格的條 = 表現的全部差異。上色的那一段 = 練習解釋掉的部分。
        # 26% 印成字看起來很大,畫成條就是四分之一 —— 兩者是同一個數字。
        txt(0.93, "how much of the difference practice explains", 44, DIM,
            "normal")
        doms = T["domains"]
        for i, d in enumerate(doms):
            step = 1.6 if name == "domains" else 0.0
            if t_now < 0.3 + i * step:
                continue
            b = ease(min(1.0, (t_now - 0.3 - i * step) / 0.6))
            y = 0.76 - i * 0.135
            hot = (name == "punch" and d["name"] == "professions")
            ax.text(0.30, y, d["name"], ha="right", va="center", fontsize=46,
                    color=ACCENT if hot else FG, weight="bold", alpha=b)
            ax.add_patch(plt.Rectangle((0.34, y - 0.035), 0.52, 0.07,
                                       color=REST, alpha=b))
            frac = d["pct"] / 100 * 0.52
            ax.add_patch(plt.Rectangle((0.34, y - 0.035), frac, 0.07,
                                       color=ACCENT, alpha=b))
            lab = fmt_pct(d)
            ax.text(0.885, y, lab, ha="left", va="center", fontsize=44,
                    color=ACCENT if hot else DIM, weight="bold", alpha=b)
    elif name == "verdict":
        txt(0.66, "“important, but not as", 60, FG)
        txt(0.55, "important as has been argued”", 60, FG)
        txt(0.38, "— the authors, in the paper", 42, DIM, "normal")
    else:
        txt(0.60, "THEY RAN IT AGAIN", 92)
        txt(0.42, "one claim · the numbers behind it", 42, DIM, "normal")

    # 🔴 **內容存在性**:版面守門只管「有沒有出界」和「有沒有重疊」,
    #    對「該畫的東西根本沒畫」是全盲的 —— 而那正是今天發生的事。
    #    這一列已經淡入了(alpha 夠),它的名稱就必須在畫布上找得到。
    if name in ("outcomes", "punch") and E.get("arc") == "outcomes":
        drawn = " | ".join(o.get_text() for o in ax.texts
                           if (o.get_alpha() or 1) >= 0.5)
        for x in T["outcomes"]:
            # 這一列的數字有沒有畫上去(有 d 用 d,沒有用 p)
            key = (f"{x['d']:+.2f}".replace("+", " ")
                   if x.get("d") is not None
                   else f"{x['p']:.3f}".replace("0.", "."))
            shown = any(key in o.get_text() and (o.get_alpha() or 1) >= 0.5
                        for o in ax.texts)
            if shown and x["name"] not in drawn:
                raise SystemExit(
                    f"⛔ {name}:「{x['name']}」的數字畫上去了但**名稱沒有** "
                    f"—— 觀眾會看到一排沒有標籤的數字。畫面上有:{drawn[:90]}")

    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    boxes = []
    for ob in list(ax.texts):
        bb = ob.get_window_extent(renderer=r)
        for v, lo, hi, side in ((bb.x0 / W, 0.02, 0.98, "左"),
                                (bb.x1 / W, 0.02, 0.98, "右"),
                                (bb.y0 / H, 0.03, 0.97, "下"),
                                (bb.y1 / H, 0.03, 0.97, "上")):
            if not (lo - 1e-9 <= v <= hi + 1e-9):
                raise SystemExit(f"⛔ {name} 越界:「{ob.get_text()[:22]}」"
                                 f"{side}緣 {v:.3f}")
        if (ob.get_alpha() or 1) >= 0.35:
            boxes.append((ob.get_text()[:22], bb))
    # 兩兩相交 —— 今晚在 Shorts 上抓到 16 支已上線的片有這個問題,
    # 新集型從第一支就帶著這道守門。
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (ta, A), (tb, B) = boxes[i], boxes[j]
            ox = min(A.x1, B.x1) - max(A.x0, B.x0)
            oy = min(A.y1, B.y1) - max(A.y0, B.y0)
            if ox > 2 and oy > 2:
                raise SystemExit(f"⛔ {name} 文字重疊:「{ta}」×「{tb}」"
                                 f"{ox:.0f}×{oy:.0f} 畫素")
    import numpy as np
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    plt.close(fig)
    return buf


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["DejaVu Sans"]
    return plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="10000_hour_rule")
    ap.add_argument("--script-only", action="store_true")
    a = ap.parse_args()

    E = load(a.slug)
    segs = build_script(E)
    print(f"[{a.slug}] {E['popular_name']}")
    audit(E, segs)
    words = sum(len(t.split()) for _, t in segs)
    print(f"  稿 {words} 字 ≈ {words / 2.6:.0f} 秒")
    if a.script_only:
        for n, t in segs:
            print(f"  --- {n} ---\n  {t}")
        return 0

    out = ROOT / "eps_domain" / a.slug
    out.mkdir(parents=True, exist_ok=True)
    for n, t in segs:
        (out / f"narr_{n}.txt").write_text(t, encoding="utf-8")
    # 🔴 先寫 facts.json 再渲 —— 理由同 make_ep0(preflight 的順序慣例)。
    (out / "facts.json").write_text(json.dumps(E, ensure_ascii=False,
                                               indent=1), encoding="utf-8")
    from render_pipeline import tts, render_and_mux
    tts(out, segs)
    mp4, dur = render_and_mux(out, segs, render_scene, f"{a.slug}.mp4",
                              W, H, FPS, ctx={"plt": _plt(), "E": E})
    print(f"完成 → {mp4}  ({dur:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
