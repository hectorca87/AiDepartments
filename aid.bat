@echo off
setlocal enabledelayedexpansion

:: ─────────────────────────────────────────
:: AiDepartments — Unified CLI Launcher
:: ─────────────────────────────────────────

:: Environment
set PYTHONIOENCODING=utf-8
set GOOGLE_GENAI_USE_GCA=true

:: Working directory (auto-detect from bat location)
cd /d "%~dp0"

:: Parse arguments
if "%~1"=="" goto :help
if "%~1"=="--help" goto :help
if "%~1"=="-h" goto :help

if "%~1"=="--dashboard" (
    echo.
    echo  [Orchestra] Launching Dashboard...
    python dashboard_server.py
    goto :end
)

if "%~1"=="--retry" (
    echo.
    echo  [Orchestra] Launching Auto-Retry Monitor...
    if "%~2" NEQ "" (
        python auto_retry.py --session %2
    ) else (
        python auto_retry.py
    )
    goto :end
)

if "%~1"=="--resume" (
    echo.
    echo  [Orchestra] Resuming session...
    if "%~2" NEQ "" (
        python orchestrator.py --resume %2
    ) else (
        python orchestrator.py --resume latest
    )
    goto :end
)

:: Default: new session with objective
echo.
echo  [Orchestra] Starting new session...
if "%~2" NEQ "" (
    python orchestrator.py "%~1" %2
) else (
    python orchestrator.py "%~1"
)
goto :end

:help
echo.
echo  +================================================+
echo  :          AiDepartments CLI v1.0                :
echo  +================================================+
echo.
echo  USAGE:
echo    aid.bat "objetivo"                    Start new session
echo    aid.bat "objetivo" gemini-dev          Start with Gemini as dev
echo    aid.bat "objetivo" manual              Export tasks as .md
echo.
echo    aid.bat --resume latest                Resume last session
echo    aid.bat --resume ^<session_id^>         Resume specific session
echo.
echo    aid.bat --dashboard                    Launch live dashboard
echo    aid.bat --retry                        Launch auto-retry monitor
echo    aid.bat --retry ^<session_id^>          Monitor specific session
echo.
echo    aid.bat --help                         Show this help
echo.
echo  MODES:
echo    antigravity   Antigravity IDE (Claude Opus 4.6)  [DEFAULT]
echo    gemini-dev    Gemini CLI headless (fallback)
echo    manual        Export tasks as Markdown
echo.
echo  EXAMPLES:
echo    aid.bat "Crear sistema de login"
echo    aid.bat "Refactorizar API" gemini-dev
echo    aid.bat --resume latest
echo.

:end
endlocal
