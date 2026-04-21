"""
Orchestra — Logger
Logs all PM and Developer interactions to markdown files the user can monitor.
State updates use atomic writes (write to temp + rename) to prevent corruption.
"""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from config import SESSIONS_DIR, DASHBOARD_FILE


class OrchestraLogger:
    def __init__(self, session_id: str, objective: str, resume: bool = False):
        self.session_id = session_id
        self.objective = objective
        self.session_dir = SESSIONS_DIR / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.gemini_log = self.session_dir / "gemini_pm.md"
        self.developer_log = self.session_dir / "developer.md"
        self.state_file = self.session_dir / "state.json"
        self.summary_file = self.session_dir / "summary.md"

        if not resume:
            self._init_logs()
        self._update_dashboard()

    def _init_logs(self):
        """Initialize log files for this session."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Gemini PM log — this is what the user monitors
        with open(self.gemini_log, "w", encoding="utf-8") as f:
            f.write(f"# 🧠 Gemini PM — Sesión {self.session_id}\n\n")
            f.write(f"**Objetivo:** {self.objective}\n\n")
            f.write(f"**Inicio:** {timestamp}\n\n")
            f.write("---\n\n")

        # Developer log
        with open(self.developer_log, "w", encoding="utf-8") as f:
            f.write(f"# 🤖 Developer Agent — Sesión {self.session_id}\n\n")
            f.write(f"**Objetivo:** {self.objective}\n\n")
            f.write(f"**Inicio:** {timestamp}\n\n")
            f.write("---\n\n")

        # State — initial
        state = {
            "session_id": self.session_id,
            "objective": self.objective,
            "status": "STARTED",
            "dev_mode": "",
            "current_phase": 0,
            "total_phases": 0,
            "started_at": timestamp,
            "last_update": timestamp,
            "phases_completed": [],
            "current_task_index": 0,
            "tasks_completed": [],
            "plan": None,
            "tasks": [],
            "pm_feedback_history": [],
        }
        self._atomic_write_state(state)

    def _atomic_write_state(self, state: dict) -> None:
        """
        Write state to disk atomically:
        1. Write to a temp file in the same directory
        2. Rename temp file over the real state file
        This prevents corruption if the process is killed mid-write.
        """
        state["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Create temp file in same directory (same filesystem for atomic rename)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".state_",
            suffix=".tmp",
            dir=str(self.session_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)

            # Atomic rename (on Windows, need to remove destination first)
            if os.name == "nt" and self.state_file.exists():
                self.state_file.unlink()
            os.rename(tmp_path, str(self.state_file))
        except Exception:
            # Cleanup temp file on error
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def log_gemini(self, action: str, prompt: str, response: str, phase: str = ""):
        """Log a Gemini PM interaction — this is the user-facing log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(self.gemini_log, "a", encoding="utf-8") as f:
            f.write(f"## [{timestamp}] {action}")
            if phase:
                f.write(f" — {phase}")
            f.write("\n\n")
            f.write(f"**Prompt enviado:**\n")
            f.write(f"```\n{prompt[:500]}{'...' if len(prompt) > 500 else ''}\n```\n\n")
            f.write(f"**Respuesta de Gemini:**\n\n{response}\n\n")
            f.write("---\n\n")

    def log_developer(self, action: str, task_id: str, content: str):
        """Log a developer agent action."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(self.developer_log, "a", encoding="utf-8") as f:
            f.write(f"## [{timestamp}] {action} — {task_id}\n\n")
            f.write(f"{content}\n\n")
            f.write("---\n\n")

    def update_state(self, **kwargs):
        """Update session state atomically."""
        state = self._get_state()
        state.update(kwargs)
        self._atomic_write_state(state)

    def write_phase_report(self, phase_num: int, phase_name: str, tasks_json: str):
        """Write a phase report as separate MD file."""
        report_file = self.session_dir / f"phase_{phase_num}_{phase_name.replace(' ', '_')}.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"# Fase {phase_num}: {phase_name}\n\n")
            f.write(tasks_json)

    def _update_dashboard(self):
        """Update the global dashboard with all sessions."""
        sessions = []
        if SESSIONS_DIR.exists():
            for session_dir in sorted(SESSIONS_DIR.iterdir()):
                if session_dir.is_dir():
                    state_file = session_dir / "state.json"
                    if state_file.exists():
                        try:
                            with open(state_file, "r", encoding="utf-8") as f:
                                sessions.append(json.load(f))
                        except (json.JSONDecodeError, OSError):
                            pass

        with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
            f.write("# 🎼 Orchestra — Dashboard\n\n")
            f.write(f"*Última actualización: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n")

            if not sessions:
                f.write("No hay sesiones activas.\n")
                return

            f.write("| Sesión | Objetivo | Estado | Fase | Inicio |\n")
            f.write("|--------|----------|--------|------|--------|\n")
            for s in sessions:
                f.write(f"| {s['session_id'][:8]}... | {s['objective'][:40]} | {s['status']} | {s['current_phase']}/{s['total_phases']} | {s['started_at']} |\n")
            f.write("\n")

    def _get_state(self) -> dict:
        """Read and return the current session state from disk."""
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "session_id": self.session_id,
                "objective": self.objective,
                "status": "UNKNOWN",
                "phases_completed": [],
                "current_task_index": 0,
                "tasks_completed": [],
            }
