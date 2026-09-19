' run_studio_bg.vbs - start local_cron.py hidden (no window).
' Rewritten 2026-07-14: old file was 0 bytes; also keep this file ASCII-only
' (wscript reads ANSI; non-ASCII comments can break parsing).
' Child jobs use CREATE_NO_WINDOW inside local_cron.py, so no black popups.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\carson-agent\youtube_channel"
sh.Run """D:\carson-agent\youtube_channel\.venv\Scripts\python.exe"" ""D:\carson-agent\youtube_channel\scripts\local_cron.py""", 0, False
