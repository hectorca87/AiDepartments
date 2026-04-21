"""
AiDepartments — Configuration
"""
import os
from pathlib import Path

# Paths — auto-detect from this file's location
# AiDepartments lives inside the project root, so parent = project root
AI_DEPARTMENTS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = AI_DEPARTMENTS_DIR.parent
LOGS_DIR = AI_DEPARTMENTS_DIR / "logs"
SESSIONS_DIR = LOGS_DIR / "sessions"
DASHBOARD_FILE = LOGS_DIR / "dashboard.md"
DASHBOARD_PORT = 8420

# Gemini CLI
GEMINI_CMD = "gemini"
GEMINI_MODEL = "gemini-2.5-pro"  # Best reasoning model, included in Ultra plan
GEMINI_ENV = {"GOOGLE_GENAI_USE_GCA": "true"}

# PM Retry Configuration
PM_MAX_RETRIES = 3
PM_RETRY_BACKOFF = [30, 60, 120]  # seconds between retries on quota/capacity errors
PM_TIMEOUT = 300  # seconds before subprocess timeout

# JSON Validation
JSON_CORRECTION_MAX_RETRIES = 2  # max re-sends to PM for format correction

# Developer Agent (Antigravity)
ANTIGRAVITY_CMD = "antigravity"
DEV_TASK_TIMEOUT = 600       # 10 min max per task (gemini-dev mode)
AG_LAUNCH_WAIT = 10          # seconds to wait for AG process to launch before returning
AG_REPORT_TIMEOUT = 1800     # 30 min default wait for antigravity report

# File Watcher
WATCHER_POLL_INTERVAL = 3    # seconds between file checks (fast detection)
WATCHER_STABLE_CHECKS = 2    # consecutive checks with same size = file is stable
WATCHER_STABLE_DELAY = 2     # seconds between stability checks
WATCHER_MIN_SIZE = 10        # minimum bytes already in the old code for a valid report

# Orchestrator
CHANGES_REQUESTED_MAX_RETRIES = 3  # max times a task can be re-enqueued after CHANGES_REQUESTED

# CDP Auto-Retry Monitor
CDP_PORT = 9000
CDP_CHECK_INTERVAL = 3               # seconds between CDP page checks
CDP_WS_TIMEOUT = 5                   # WebSocket operation timeout
CDP_RECONNECT_DELAY = 10             # seconds to wait before retrying CDP connection
CDP_RETRY_LOG_FILE = "auto_retry.log"  # log file name inside session dir

CDP_RETRY_TRIGGERS = [
    "high traffic",
    "try again",
    "servers are experiencing",
    "please try again",
    "rate limit",
    "too many requests",
    "capacity",
    "overloaded",
    "temporarily unavailable",
    "service unavailable",
]

CDP_RETRY_BUTTON_PATTERNS = [
    "retry",
    "try again",
    "continue",
    "regenerate",
]

# Claude (Anthropic SDK)
# We'll use the SDK directly since claude CLI isn't installed
CLAUDE_MODEL = "claude-sonnet-4-20250514"  # Sonnet for dev tasks (cheaper), Opus for complex

# Ensure directories exist
LOGS_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
