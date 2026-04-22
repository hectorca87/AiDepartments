"""
Orchestra — Gemini PM Module
Wraps Gemini CLI as a Project Manager.
Uses session resume (-r) to maintain context across calls within a session.

Features:
- Exponential backoff retry on quota/capacity errors
- Thread-safe temp files for prompts
- Session corruption detection and automatic recovery
- Structured logging with timestamps
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from config import (
    GEMINI_CMD,
    GEMINI_ENV,
    GEMINI_MODEL,
    LOGS_DIR,
    PM_MAX_RETRIES,
    PM_RETRY_BACKOFF,
    PM_TIMEOUT,
    WORKSPACE_ROOT,
)

# Fallback chain: try best model first, fall back to stable
MODEL_CHAIN: list[str] = [
    "gemini-3.1-pro-preview",  # Best available (may have capacity issues)
    "gemini-2.5-pro",          # Stable, great reasoning
]

# Track the session index for resume across calls
_session_index: str | None = None

# Patterns that indicate a corrupt or unavailable session
_SESSION_CORRUPTION_PATTERNS: list[str] = [
    "session not found",
    "corrupt",
    "invalid session",
    "no previous session",
    "failed to resume",
    "error loading session",
    "could not find",
]

# Patterns that indicate quota/capacity issues (retryable)
_QUOTA_PATTERNS: list[str] = [
    "MODEL_CAPACITY_EXHAUSTED",
    "429",
    "RESOURCE_EXHAUSTED",
    "quota",
    "rate limit",
    "too many requests",
]

# Patterns that indicate the model is not available (switch model)
_MODEL_NOT_FOUND_PATTERNS: list[str] = [
    "ModelNotFoundError",
    "model not found",
    "not supported",
]


def _log(prefix: str, msg: str) -> None:
    """Print a structured log message with timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] [{prefix}] {msg}")


def _matches_any(text: str, patterns: list[str]) -> bool:
    """Check if text contains any of the given patterns (case-insensitive)."""
    text_lower = text.lower()
    return any(p.lower() in text_lower for p in patterns)


def _check_session_history_available() -> bool:
    """
    Verify that Gemini's local session history directory exists and is non-empty.
    Gemini CLI stores sessions in ~/.gemini/ (or AppData on Windows).
    """
    possible_paths = [
        Path.home() / ".gemini",
        Path(os.environ.get("APPDATA", "")) / "gemini",
        Path(os.environ.get("LOCALAPPDATA", "")) / "gemini",
    ]
    for p in possible_paths:
        if p.exists() and any(p.iterdir()):
            return True
    # If we can't find the directory, assume it's fine (Gemini will create it)
    return True


def call_gemini(prompt: str, resume: bool = True, cwd: Path | None = None) -> str:
    """
    Call Gemini CLI in headless mode with a prompt.

    Args:
        prompt: The prompt to send
        resume: If True, resume the latest session (keeps PM context across calls)

    Returns:
        Raw text response from Gemini

    Raises:
        RuntimeError: If all models and retries are exhausted
    """
    global _session_index
    env = os.environ.copy()
    env.update(GEMINI_ENV)

    # Write prompt to a unique temp file (thread-safe, avoids overwrite conflicts)
    prompt_dir = LOGS_DIR
    prompt_dir.mkdir(parents=True, exist_ok=True)

    prompt_file = Path(tempfile.mktemp(
        prefix="pm_prompt_",
        suffix=".txt",
        dir=str(prompt_dir),
    ))
    prompt_file.write_text(prompt, encoding="utf-8")

    # Also keep a copy as .last_prompt.txt for debugging
    last_prompt_file = prompt_dir / ".last_prompt.txt"
    last_prompt_file.write_text(prompt, encoding="utf-8")

    # Check if session history is accessible before attempting resume
    should_resume = resume and _session_index is not None
    if should_resume and not _check_session_history_available():
        _log("PM:WARN", "Historial de sesiones no disponible, forzando sesión nueva")
        should_resume = False

    try:
        # Try each model in the fallback chain
        last_error: str | None = None
        for model in MODEL_CHAIN:
            result = _try_model_with_retries(
                model=model,
                cwd=cwd,
                prompt_file=prompt_file,
                env=env,
                should_resume=should_resume,
            )

            if result is not None:
                # Success — mark session as active and clean up temp file
                _session_index = "latest"
                _cleanup_temp_file(prompt_file)
                return result

            last_error = f"{model}: agotado/no disponible"
            _log("PM", f"{model} sin capacidad, probando siguiente modelo...")

        raise RuntimeError(f"Todos los modelos fallaron. Último error: {last_error}")

    except RuntimeError:
        # If we were resuming and all models failed, try once more without resume
        if should_resume:
            _log("PM:WARN", "Error con resume activo, reintentando sin resume...")
            _session_index = None
            _cleanup_temp_file(prompt_file)
            return call_gemini(prompt, resume=False)
        _cleanup_temp_file(prompt_file)
        raise


def _try_model_with_retries(
    model: str,
    prompt_file: Path,
    env: dict[str, str],
    should_resume: bool,
    cwd: Path | None = None,
) -> str | None:
    """
    Try a specific model with exponential backoff retries on quota errors.

    Returns:
        Response text on success, None if model is unavailable/exhausted
    Raises:
        RuntimeError on non-retryable errors
    """
    global _session_index

    for attempt in range(PM_MAX_RETRIES):
        cmd_parts = [GEMINI_CMD, "-m", model]

        if should_resume:
            cmd_parts.extend(["-r", "latest"])

        # Read prompt from file via type pipe (Windows)
        pipe_cmd = f'type "{prompt_file}" | {" ".join(cmd_parts)} -'

        try:
            _log("PM", f"Llamando a {model} (intento {attempt + 1}/{PM_MAX_RETRIES})"
                       f"{' [resume]' if should_resume else ' [nueva sesión]'}")

            result = subprocess.run(
                pipe_cmd,
                cwd=str(cwd or WORKSPACE_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=PM_TIMEOUT,
                encoding="utf-8",
                shell=True,
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                if output:
                    _log("PM", f"Respuesta recibida ({len(output)} chars)")
                    return output
                else:
                    _log("PM:WARN", "Respuesta vacía de Gemini")
                    # Treat empty response as retryable
                    continue

            stderr = result.stderr or ""

            # Check for session corruption → retry without resume
            if should_resume and _matches_any(stderr, _SESSION_CORRUPTION_PATTERNS):
                _log("PM:WARN", f"Sesión corrupta detectada: {stderr[:150]}")
                _session_index = None
                should_resume = False
                continue  # retry same model without resume

            # Check for model not found → switch model
            if _matches_any(stderr, _MODEL_NOT_FOUND_PATTERNS):
                _log("PM:WARN", f"{model} no disponible")
                return None  # caller will try next model

            # Check for quota/capacity → retry with backoff
            if _matches_any(stderr, _QUOTA_PATTERNS):
                if attempt < PM_MAX_RETRIES - 1:
                    backoff = PM_RETRY_BACKOFF[min(attempt, len(PM_RETRY_BACKOFF) - 1)]
                    _log("PM:RETRY", f"{model} sin cuota. Esperando {backoff}s antes de reintentar...")
                    time.sleep(backoff)
                    continue
                else:
                    _log("PM:ERROR", f"{model} sin cuota tras {PM_MAX_RETRIES} intentos")
                    return None  # exhausted retries for this model

            # Unknown error
            _log("PM:ERROR", f"Error inesperado de {model}: {stderr[:300]}")
            if should_resume:
                _log("PM:WARN", "Reintentando sin resume por error desconocido...")
                _session_index = None
                should_resume = False
                continue

            raise RuntimeError(f"Gemini CLI error ({model}): {stderr[:500]}")

        except subprocess.TimeoutExpired:
            _log("PM:TIMEOUT", f"{model} timeout ({PM_TIMEOUT}s)")
            if attempt < PM_MAX_RETRIES - 1:
                backoff = PM_RETRY_BACKOFF[min(attempt, len(PM_RETRY_BACKOFF) - 1)]
                _log("PM:RETRY", f"Esperando {backoff}s antes de reintentar...")
                time.sleep(backoff)
                continue
            return None  # exhausted retries

    return None  # should not reach here, but safety


def _cleanup_temp_file(prompt_file: Path) -> None:
    """Remove temporary prompt file (best-effort)."""
    try:
        if prompt_file.exists() and "pm_prompt_" in prompt_file.name:
            prompt_file.unlink()
    except OSError:
        pass  # non-critical


def reset_session() -> None:
    """Reset session tracking — next call will start a new session."""
    global _session_index
    _session_index = None
    _log("PM", "Sesión reseteada → próxima llamada iniciará nueva sesión")


def get_session_status() -> str:
    """Get the current session status for debugging."""
    return "active" if _session_index is not None else "none"


def decompose_objective(objective: str, project_cwd: Path | None = None) -> str:
    """
    Ask Gemini PM to analyze the workspace, investigate, and decompose
    an objective into phases and tasks. Starts a NEW session.

    Args:
        objective: The project objective to decompose
        project_cwd: If set, Gemini CLI runs with this as working directory

    Returns:
        Raw text response from Gemini containing JSON plan
    """
    reset_session()  # New objective = new session

    prompt = f"""OBJETIVO DEL PROYECTO: {objective}

Tu trabajo ahora:
1. PRIMERO: Usa tus herramientas para explorar el repositorio y entender qué hay. Lee archivos si es necesario.
2. SEGUNDO: Investiga las mejores prácticas para lograr este objetivo con la tecnología que encuentres.
3. TERCERO: Descompón el objetivo en fases (épicas) con tareas concretas.

Recuerda:
- NO escribas código. Solo planifica.
- Cada tarea debe tener: objetivo, contexto, lógica, criterios de aceptación, y decisiones tomadas.
- Responde en el formato JSON especificado en tus instrucciones de sistema.
- Las fases deben ir de lo más fundamental a lo más complejo.
- Manda SOLO la primera fase de tareas. Las demás fases solo descríbelas brevemente.
"""
    return call_gemini(prompt, cwd=project_cwd)


def review_work(phase_id: str, work_report: str) -> str:
    """
    Ask Gemini PM to review completed work from the developer.
    Resumes the existing session so PM has context of the original plan.

    Args:
        phase_id: The phase being reviewed (e.g., "Fase 1")
        work_report: Developer's work report text

    Returns:
        Raw text response from Gemini containing JSON review
    """
    prompt = f"""REVISIÓN DE TRABAJO COMPLETADO

Fase revisada: {phase_id}

Reporte del desarrollador:
{work_report}

Tu trabajo:
1. Lee los archivos modificados/creados para verificar la implementación.
2. Comprueba que los criterios de aceptación se cumplen.
3. Evalúa si sigue las mejores prácticas.
4. Responde con el formato de revisión JSON:
   - status: "APPROVED" o "CHANGES_REQUESTED"
   - feedback: tu evaluación detallada
   - issues: lista de problemas encontrados (vacía si todo OK)
   - next_phase: ID de la siguiente fase si apruebas, null si no
"""
    return call_gemini(prompt, resume=True)


def answer_developer_question(question: str, context: str) -> str:
    """
    Handle a question from the developer agent — Gemini makes the decision.
    Resumes session to keep full project context.

    Args:
        question: The developer's question
        context: JSON string with the current task context

    Returns:
        Raw text response from Gemini with the PM's decision
    """
    prompt = f"""CONSULTA DEL DESARROLLADOR

El agente desarrollador tiene una duda durante la implementación:

Contexto de la tarea:
{context}

Pregunta:
{question}

Responde con una decisión clara y justificada. Recuerda: TÚ tomas las decisiones arquitectónicas.
No escribas código — describe la solución que debe implementar.
"""
    return call_gemini(prompt, resume=True)


def request_next_phase(session_context: str) -> str:
    """
    Ask Gemini to provide the next phase of tasks based on what's been completed.
    Resumes session so PM remembers all previous phases.

    Args:
        session_context: Summary of completed phases and objectives

    Returns:
        Raw text response from Gemini containing JSON with next phase tasks
    """
    prompt = f"""SIGUIENTE FASE

Contexto de la sesión hasta ahora:
{session_context}

Proporciona las tareas detalladas de la siguiente fase en formato JSON.
Recuerda explorar el estado actual del código antes de planificar.
NO escribas código. Solo planifica las tareas.
"""
    return call_gemini(prompt, resume=True)
