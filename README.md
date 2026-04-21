🌐 **English** | [Español](README_ES.md)

# AiDepartments

**Your autonomous AI development team.**

You say what you want. Gemini plans. Claude implements. You review the result.

---

## What is it?

AiDepartments is a system that simulates a development team with two AI roles:

- **PM (Project Manager)** — Gemini 2.5 Pro. Analyzes your project, breaks down goals into tasks, and reviews the work.
- **Developer** — Claude Opus (Antigravity IDE). Writes code, creates files, runs tests.

You give it a goal in natural language. The system handles the rest.

```
"Create a FastAPI app with a /health endpoint and its unit test"
```

The PM creates a plan (3 tasks), assigns them one by one to the Developer, waits for reports, reviews quality, and closes the session when everything passes. You don't touch anything.

---

## How does it work?

```
You write a goal
        │
        ▼
┌──────────────┐
│   PM (Gemini) │ ──► Analyzes the repo, breaks down into phases and tasks
└──────┬───────┘
       │ JSON Plan
       ▼
┌──────────────┐
│  Orchestrator │ ──► Iterates each task, coordinates PM ↔ Developer
└──────┬───────┘
       │ Task prompt
       ▼
┌──────────────┐
│ CDP Injector  │ ──► Injects the task into Antigravity via Chrome DevTools
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Dev (Claude)  │ ──► Writes code, creates files, runs tests
└──────┬───────┘
       │ Report .md
       ▼
┌──────────────┐
│ File Watcher  │ ──► Detects that the Developer finished
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   PM (Gemini) │ ──► Reads created files, reviews quality
└──────┬───────┘
       │
       ▼
   ✅ Approved → next phase
   ❌ Changes requested → re-assigns the task
```

Everything happens automatically. If Claude gets a traffic error, the **Auto-Retry Monitor** detects it and clicks "Retry" automatically.

Meanwhile you can watch progress in real time on the **Dashboard** (`localhost:8420`).

---

## Real demo

```
> aid.bat "Implement a FastAPI app with /health and unit test"

[PM] Plan created: 1 phase, 3 tasks
  ├── P1-T1: Configure dependencies (requirements.txt)
  ├── P1-T2: Implement /health endpoint
  └── P1-T3: Create unit test

[CDP] Prompt injected → Claude is working...
[WATCHER] Report P1-T1 received (19s)
[CDP] Next task injected...
[WATCHER] Report P1-T2 received (28s)
[CDP] Next task injected...
[WATCHER] Report P1-T3 received (73s)

[PM] ✅ Phase 1 APPROVED
     "Work meets all acceptance criteria. Good job."

Session completed successfully
```

**Result**: 3 files created, test passes, 0 human intervention.

---

## Quick setup

```bash
# 1. Dependencies
npm install -g @anthropic-ai/gemini-cli   # PM
pip install websocket-client requests       # CDP

# 2. Clone
git clone https://github.com/hectorca87/AiDepartments.git

# 3. Place inside your project
mv AiDepartments my-project/AiDepartments

# 4. Copy PM instructions
mkdir my-project/.gemini
cp AiDepartments/templates/.gemini/GEMINI.md my-project/.gemini/

# 5. Open Antigravity with CDP (PowerShell)
$exe = @("$env:LOCALAPPDATA\Programs\Antigravity\Antigravity.exe","$env:ProgramFiles\Antigravity\Antigravity.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1; Start-Process $exe -ArgumentList '--remote-debugging-port=9000'
# Then open your project in Antigravity (File → Open Folder)

# 6. Launch
cd my-project/AiDepartments
aid.bat "Your goal here"
```

---

## Commands

| Command | What it does |
|---------|-------------|
| `aid.bat "goal"` | New autonomous session |
| `aid.bat --dashboard` | Web dashboard at `localhost:8420` |
| `aid.bat --retry` | Auto-retry monitor for traffic errors |
| `aid.bat --resume latest` | Resume last session |
| `aid.bat --help` | Show all options |

---

## Stack

| Component | Technology |
|-----------|------------|
| PM | Gemini 2.5 Pro (via Gemini CLI) |
| Developer | Claude Opus 4.6 (via Antigravity IDE) |
| Prompt injection | Chrome DevTools Protocol (CDP) |
| Dashboard | Python HTTP server + vanilla SPA |
| Orchestration | Python 3.12, no external frameworks |

---

## Requirements

- Windows 10/11
- Python 3.12+
- Node.js 18+
- [Antigravity IDE](https://idx.google.com/antigravity)
- Google account with Gemini Advanced

---

## Configuration (config.py)

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_MODEL` | `gemini-2.5-pro` | PM model |
| `CDP_PORT` | `9000` | Antigravity CDP port |
| `DASHBOARD_PORT` | `8420` | Web dashboard port |
| `AG_REPORT_TIMEOUT` | `1800` (30 min) | Max timeout per task |
| `PM_TIMEOUT` | `300` (5 min) | PM call timeout |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `gemini` not found | `npm install -g @anthropic-ai/gemini-cli` |
| `gemini` asks for login | Run `gemini` interactively and authenticate |
| CDP 403 Forbidden | Restart Antigravity with `--remote-debugging-port=9000` |
| Prompt doesn't reach chat | Make sure the Agent panel is visible (not minimized) |
| PM returns invalid JSON | json_engine auto-corrects — if persistent, increase `JSON_CORRECTION_MAX_RETRIES` |
| Dashboard won't load | Run `aid.bat --dashboard` first |
