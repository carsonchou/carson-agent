@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYEXE=C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
echo ========================================
echo   JARVIS LiveKit - project setup
echo ========================================

REM 1) Clone the official LiveKit starter (SDK-correct, ~80%% done)
if not exist "agent-starter-python" (
  echo Cloning official LiveKit starter...
  git clone https://github.com/livekit-examples/agent-starter-python
) else (
  echo Starter already cloned.
)
if not exist "agent-starter-python" (
  echo [ERROR] git clone failed. Install git or check your connection.
  pause & exit /b 1
)

REM 2) Drop in our prompts/tools/env
echo Copying prompts.py / tools.py / .env ...
copy /y "prompts.py" "agent-starter-python\prompts.py" >nul
copy /y "tools.py"   "agent-starter-python\tools.py"   >nul
if exist ".env" ( copy /y ".env" "agent-starter-python\.env" >nul ) else ( copy /y ".env.example" "agent-starter-python\.env" >nul & echo [NOTE] No .env yet - copied the template. Fill in keys in agent-starter-python\.env )

REM 3) Python venv + deps
cd agent-starter-python
if not exist ".venv" ( "%PYEXE%" -m venv .venv )
call .venv\Scripts\activate.bat
python -m pip install -U pip >nul
if exist "requirements.txt" ( pip install -r requirements.txt ) else ( pip install "livekit-agents[deepgram,elevenlabs,openai,anthropic,silero,turn-detector]" python-dotenv requests )

echo.
echo ========================================
echo Done. Next:
echo   1) Fill keys in:  %CD%\.env
echo   2) In this folder run:  claude
echo      and paste the wiring prompt from ..\README.md (step 3)
echo   3) Then:  python agent.py dev
echo ========================================
pause
