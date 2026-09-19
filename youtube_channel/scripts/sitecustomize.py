# -*- coding: utf-8 -*-
"""sitecustomize.py — 本機工作室啟動掛鉤(git 來源真本;啟動 .bat 會複製進 venv site-packages)。

Python 直譯器啟動時 site.py 會自動 import sitecustomize —— 但**只在 site-packages 那份會被載入**,
因為啟動找 sitecustomize 的當下 scripts/ 還沒進 sys.path(放 scripts/ 永遠找不到,本機搬遷踩過的雷)。
所以真正生效的是 .venv/Lib/site-packages/sitecustomize.py;本檔是 git 追蹤的來源,由啟動 .bat 複製過去。

作用:把 scripts/ 加進 sys.path 後 import _llm_shim → 全域把 Anthropic 請求改道 OpenRouter,
所有用 raw requests.post 打 api.anthropic.com 的部門腳本零改動就走 OpenRouter(Anthropic 沒錢時不再全掛)。
"""
import os
import sys

# 絕對路徑(不靠 CWD;本機工作室固定在此)＋ getcwd 後援 ＋ 雲端路徑(相容)
_cands = [
    r"D:\carson-agent\youtube_channel\scripts",
    os.path.join(os.getcwd(), "scripts"),
    "/root/yt/scripts",
]
for _d in _cands:
    try:
        if os.path.isdir(_d) and _d not in sys.path:
            sys.path.insert(0, _d)
    except Exception:
        pass

try:
    import _llm_shim  # noqa: F401  (import 時自動 install() 攔截，僅在有 OPENROUTER_API_KEY 時接管)
except Exception:
    pass
