"""
Orchestra — Main Orchestrator
Manages the PM - Developer flow: decompose - execute - review - repeat.

Features:
- Persistent state machine with atomic writes for crash recovery
- Session resume: restart from the last incomplete task
- CHANGES_REQUESTED: re-enqueue tasks with PM feedback injected
- [DUDA_PM]: pause, get PM answer, re-run task with answer in prompt
- Integrates json_engine for robust extraction, validation, and auto-correction
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Add orchestra dir to path
sys.path.insert(0, str(Path(__file__).parent))

from config import WORKSPACE_ROOT, SESSIONS_DIR, CHANGES_REQUESTED_MAX_RETRIES
from logger import OrchestraLogger
from gemini_pm import (
    call_gemini,
    decompose_objective,
    review_work,
    answer_developer_question,
    request_next_phase,
)
from developer import execute_task, _build_dev_prompt
from file_watcher import wait_for_report
from json_engine import (
    extract_json_from_response,
    validate_plan_schema,
    validate_review_schema,
    request_json_correction,
)


def _log(prefix: str, msg: str) -> None:
    """Print a structured log message with timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] [{prefix}] {msg}")


def _detect_project_path(objective: str) -> Path | None:
    """
    Detect a project directory path mentioned in the objective text.
    Looks for Windows-style absolute paths (e.g., C:\\Projects\\Boxy).
    Returns the path if it exists on disk, None otherwise.
    """
    # Match Windows paths like C:\...\Folder or "C:\...\Folder"
    patterns = [
        r'[A-Z]:\\(?:[^\s\\:*?"<>|]+\\)*[^\s\\:*?"<>|]+',  # unquoted
    ]
    for pattern in patterns:
        matches = re.findall(pattern, objective)
        for match in matches:
            candidate = Path(match)
            if candidate.exists() and candidate.is_dir():
                _log("ORCH", f"Path detectado en objetivo: {candidate}")
                return candidate
            # Maybe the path doesn't exist yet — still use it as cwd parent
            if candidate.parent.exists():
                _log("ORCH", f"Path padre detectado: {candidate}")
                return candidate
    return None


# ─────────────────────────────────────────────
# Stop signal
# ─────────────────────────────────────────────

def _check_stop_signal(session_dir: Path) -> bool:
    """Check if a .stop sentinel file exists, signaling graceful shutdown."""
    stop_file = session_dir / ".stop"
    if stop_file.exists():
        _log("ORCH", "Señal de parada detectada (.stop). Deteniendo sesión...")
        try:
            stop_file.unlink()  # Clean up sentinel
        except OSError:
            pass
        return True
    return False


# ─────────────────────────────────────────────
# JSON helpers (delegate to json_engine)
# ─────────────────────────────────────────────

def _extract_and_validate_plan(pm_response: str, logger: OrchestraLogger) -> dict | None:
    """
    Extract JSON from PM response, validate against plan schema, and auto-correct if needed.
    """
    plan = extract_json_from_response(pm_response)

    if plan is None:
        print("  [JSON] No se encontró JSON en la respuesta. Solicitando corrección al PM...")
        plan = request_json_correction(
            pm_caller=call_gemini,
            original_response=pm_response,
            errors=["No se encontró ningún bloque JSON válido en la respuesta"],
        )
        if plan is None:
            return None

    validation = validate_plan_schema(plan)

    if not validation.is_valid:
        error_msg = "; ".join(validation.errors)
        print(f"  [JSON] Esquema inválido: {error_msg}")
        logger.log_gemini("VALIDACION_FALLIDA", f"Errores: {error_msg}", pm_response[:500])

        corrected = request_json_correction(
            pm_caller=call_gemini,
            original_response=pm_response,
            errors=validation.errors,
        )
        if corrected is not None:
            revalidation = validate_plan_schema(corrected)
            if revalidation.is_valid:
                plan = corrected
            else:
                print(f"  [JSON:WARN] Corrección aún inválida: {revalidation.errors}")
                plan = corrected

    if validation.warnings:
        for warning in validation.warnings:
            print(f"  [JSON:WARN] {warning}")

    return plan


def _extract_and_validate_review(pm_response: str, logger: OrchestraLogger) -> dict | None:
    """
    Extract JSON from PM review response and validate against review schema.
    """
    review = extract_json_from_response(pm_response)

    if review is None:
        print("  [JSON] No se encontró JSON en la revisión. Solicitando corrección al PM...")
        review = request_json_correction(
            pm_caller=call_gemini,
            original_response=pm_response,
            errors=["No se encontró ningún bloque JSON de revisión en la respuesta"],
        )
        if review is None:
            return None

    validation = validate_review_schema(review)

    if not validation.is_valid:
        error_msg = "; ".join(validation.errors)
        print(f"  [JSON] Revisión con esquema inválido: {error_msg}")
        corrected = request_json_correction(
            pm_caller=call_gemini,
            original_response=pm_response,
            errors=validation.errors,
        )
        if corrected is not None:
            review = corrected

    if validation.warnings:
        for warning in validation.warnings:
            print(f"  [JSON:WARN] {warning}")

    return review


# ─────────────────────────────────────────────
# Session recovery
# ─────────────────────────────────────────────

def _find_latest_session() -> str | None:
    """Find the most recent session ID in the sessions directory."""
    if not SESSIONS_DIR.exists():
        return None
    sessions = sorted(
        [d.name for d in SESSIONS_DIR.iterdir()
         if d.is_dir() and (d / "state.json").exists()],
    )
    return sessions[-1] if sessions else None


def _load_session(session_id: str) -> dict | None:
    """Load state.json for a given session ID."""
    state_file = SESSIONS_DIR / session_id / "state.json"
    if not state_file.exists():
        return None
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ─────────────────────────────────────────────
# Task execution with DUDA_PM handling
# ─────────────────────────────────────────────

def _execute_single_task(
    task: dict,
    logger: OrchestraLogger,
    dev_mode: str,
    current_phase: int,
    pm_feedback: str | None = None,
    pm_answers: list[str] | None = None,
) -> str:
    """
    Execute a single task, handling [DUDA_PM] by pausing, getting PM answer,
    and re-running the task with the answer integrated.

    Args:
        task: PM task specification dict
        logger: Session logger
        dev_mode: Developer backend mode
        current_phase: Current phase number
        pm_feedback: If set, PM feedback from a CHANGES_REQUESTED re-enqueue
        pm_answers: If set, previous PM answers to [DUDA_PM] questions

    Returns:
        Developer result text
    """
    task_id = task.get("id", "unknown")

    # If we have PM feedback (from CHANGES_REQUESTED), inject it into the task
    if pm_feedback:
        task = task.copy()
        existing_context = task.get("contexto", "")
        task["contexto"] = (
            f"{existing_context}\n\n"
            f"⚠️ FEEDBACK DEL PM (revisión anterior):\n{pm_feedback}\n\n"
            f"Debes corregir los problemas señalados arriba."
        )
        _log("ORCH", f"Tarea {task_id} re-encolada con feedback del PM")

    # If we have PM answers to previous questions, inject them
    if pm_answers:
        task = task.copy()
        existing_context = task.get("contexto", "")
        answers_text = "\n".join(f"- {a}" for a in pm_answers)
        task["contexto"] = (
            f"{existing_context}\n\n"
            f"📋 RESPUESTAS DEL PM A TUS DUDAS ANTERIORES:\n{answers_text}"
        )

    # Execute the task
    try:
        dev_result = execute_task(task, logger.session_dir, mode=dev_mode)
    except Exception as e:
        dev_result = f"ERROR: {e}"
        _log("ORCH:ERROR", f"Error en tarea {task_id}: {e}")

    # In antigravity mode, wait for report
    if dev_mode == "antigravity":
        report_path = logger.session_dir / f"dev_report_{task_id}.md"
        watch_result = wait_for_report(report_path)
        if watch_result.is_ok:
            dev_result = watch_result.content
            _log("ORCH", f"Reporte recibido ({len(dev_result)} chars, "
                         f"{watch_result.elapsed_seconds:.1f}s)")
        else:
            dev_result += (f"\n[{watch_result.status}] El developer no generó reporte "
                           f"({watch_result.elapsed_seconds:.0f}s, "
                           f"{watch_result.checks_performed} checks).")
            _log("ORCH:WARN", f"{watch_result.status} esperando reporte")

    logger.log_developer("RESULTADO", task_id, dev_result)

    # Handle [DUDA_PM]: pause, get answer, re-run
    if "[DUDA_PM]:" in dev_result:
        questions = re.findall(r'\[DUDA_PM\]:\s*(.*?)(?:\n|$)', dev_result)
        collected_answers: list[str] = list(pm_answers or [])

        for q in questions:
            _log("DEV->PM", f"Pregunta: {q}")
            try:
                pm_answer = answer_developer_question(q, json.dumps(task, ensure_ascii=False))
                logger.log_gemini("RESPUESTA_A_DUDA", q, pm_answer, f"Fase {current_phase}")
                _log("PM->DEV", f"Respuesta: {pm_answer[:120]}...")
                collected_answers.append(f"Pregunta: {q}\n  Respuesta: {pm_answer}")
            except Exception as e:
                _log("ORCH:WARN", f"Error consultando PM: {e}")
                collected_answers.append(f"Pregunta: {q}\n  Respuesta: [ERROR: {e}]")

        # Re-run the task with PM answers integrated
        _log("ORCH", f"Re-ejecutando tarea {task_id} con respuestas del PM integradas")
        logger.log_developer("RE_EJECUCION", task_id, f"Re-run con {len(collected_answers)} respuestas del PM")

        # Delete old report so watcher can detect new one
        old_report = logger.session_dir / f"dev_report_{task_id}.md"
        if old_report.exists():
            old_report.unlink()

        dev_result = _execute_single_task(
            task, logger, dev_mode, current_phase,
            pm_feedback=pm_feedback,
            pm_answers=collected_answers,
        )

    return dev_result


# ─────────────────────────────────────────────
# Main orchestration loop
# ─────────────────────────────────────────────

def run_session(
    objective: str,
    dev_mode: str = "antigravity",
    resume_session_id: str | None = None,
):
    """
    Run a full Orchestra session.

    Args:
        objective: What we want to achieve
        dev_mode: "gemini-dev" (headless), "antigravity" (UI), or "manual"
        resume_session_id: If set, resume this session instead of creating a new one.
                          Use "latest" to resume the most recent session.
    """
    # ── Session setup or recovery ──
    if resume_session_id:
        if resume_session_id == "latest":
            resume_session_id = _find_latest_session()
            if not resume_session_id:
                print("[ERROR] No hay sesiones previas para reanudar.")
                return

        state = _load_session(resume_session_id)
        if not state:
            print(f"[ERROR] No se pudo cargar la sesión: {resume_session_id}")
            return

        session_id = resume_session_id
        objective = state.get("objective", objective)
        dev_mode = state.get("dev_mode", dev_mode)
        logger = OrchestraLogger(session_id, objective, resume=True)

        total_phases = state.get("total_phases", 1)
        current_phase = state.get("current_phase", 1)
        tasks = state.get("tasks", [])
        plan = state.get("plan", {})
        start_task_index = state.get("current_task_index", 0)
        tasks_completed = state.get("tasks_completed", [])

        print(f"\n{'='*60}")
        print(f"  Orchestra  --  REANUDANDO Sesión {session_id}")
        print(f"  Objetivo: {objective}")
        print(f"  Fase: {current_phase}/{total_phases} | Tarea: {start_task_index + 1}/{len(tasks)}")
        print(f"  Completadas: {len(tasks_completed)} tareas")
        print(f"{'='*60}\n")

        logger.update_state(status="IN_PROGRESS")

    else:
        # New session
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        logger = OrchestraLogger(session_id, objective)

        print(f"\n{'='*60}")
        print(f"  Orchestra  --  Session {session_id}")
        print(f"  Objetivo: {objective}")
        print(f"  Modo dev: {dev_mode}")
        print(f"  Logs: orchestra/logs/sessions/{session_id}/")
        print(f"{'='*60}\n")

        # ── PHASE 0: Gemini decomposes the objective ──
        print("[PM] Gemini esta analizando el proyecto y descomponiendo el objetivo...")

        # Detect project path from objective (e.g., "C:\AndroidProjects\Boxy")
        project_cwd = _detect_project_path(objective)
        if project_cwd:
            _log("ORCH", f"Proyecto detectado en: {project_cwd}")

        try:
            pm_response = decompose_objective(objective, project_cwd=project_cwd)
        except Exception as e:
            print(f"[ERROR] Error llamando a Gemini PM: {e}")
            logger.update_state(status="ERROR", error=str(e))
            return

        logger.log_gemini("DESCOMPOSICION", f"Objetivo: {objective}", pm_response)
        plan = _extract_and_validate_plan(pm_response, logger)

        if not plan:
            print("[WARN] Gemini no devolvio JSON estructurado válido. Guardando respuesta raw.")
            logger.log_gemini("PLAN_RAW", objective, pm_response)
            logger.update_state(status="PLAN_RAW_NEEDS_REVIEW")
            print(f"\n  Revisa el plan en: orchestra/logs/sessions/{session_id}/gemini_pm.md")
            return

        total_phases = plan.get("total_phases", 1)
        current_phase = plan.get("current_phase", 1)
        tasks = plan.get("tasks", [])
        start_task_index = 0
        tasks_completed = []

        # Persist plan and tasks for recovery
        logger.update_state(
            status="IN_PROGRESS",
            pid=os.getpid(),
            dev_mode=dev_mode,
            total_phases=total_phases,
            current_phase=current_phase,
            plan=plan,
            tasks=tasks,
            current_task_index=0,
            tasks_completed=[],
        )

        print(f"[PM] Plan creado: {total_phases} fases, {len(tasks)} tareas en fase {current_phase}")
        logger.write_phase_report(current_phase, plan.get("phase_name", "fase_1"), pm_response)

    # ── MAIN LOOP: Execute phases ──
    while current_phase <= total_phases:
        phase_name = plan.get("phase_name", "N/A") if isinstance(plan, dict) else "N/A"
        print(f"\n{'~'*40}")
        print(f"  FASE {current_phase}/{total_phases}: {phase_name}")
        print(f"{'~'*40}")

        phase_reports = []

        for task_idx in range(start_task_index, len(tasks)):
            task = tasks[task_idx]
            task_id = task.get("id", f"T{task_idx + 1}")

            # Check stop signal before each task
            if _check_stop_signal(logger.session_dir):
                logger.update_state(status="STOPPED")
                print(f"\n[ORCH] ⛔ Sesión detenida por el usuario antes de tarea {task_id}")
                break

            # Skip already completed tasks (recovery scenario)
            if task_id in tasks_completed:
                _log("ORCH", f"Tarea {task_id} ya completada, saltando")
                continue

            print(f"\n  [DEV] Ejecutando tarea {task_id}: {task.get('title', 'N/A')}...")

            # Update state: current task
            logger.update_state(current_task_index=task_idx)
            logger.log_developer("INICIO_TAREA", task_id, json.dumps(task, indent=2, ensure_ascii=False))

            # Execute
            dev_result = _execute_single_task(
                task, logger, dev_mode, current_phase,
            )

            phase_reports.append({"task_id": task_id, "result": dev_result})

            # Mark task as completed in state
            tasks_completed.append(task_id)
            logger.update_state(tasks_completed=tasks_completed)

            print(f"  [OK] Tarea {task_id} completada")

            # Check stop signal after task completion too
            if _check_stop_signal(logger.session_dir):
                logger.update_state(status="STOPPED")
                print(f"\n[ORCH] ⛔ Sesión detenida por el usuario tras tarea {task_id}")
                break

        # If stopped, break outer loop too
        if logger._get_state().get("status") == "STOPPED":
            break

        # Reset start index for next phase
        start_task_index = 0

        # ── REVIEW: Send results to Gemini PM ──
        print(f"\n[PM] Revisando trabajo de fase {current_phase}...")

        work_report = "\n\n".join([
            f"### Tarea {r['task_id']}\n{r['result']}"
            for r in phase_reports
        ])

        try:
            review_response = review_work(f"Fase {current_phase}", work_report)
        except Exception as e:
            print(f"[ERROR] Error en revision: {e}")
            logger.update_state(status="REVIEW_ERROR", error=str(e))
            break

        logger.log_gemini("REVISION", f"Fase {current_phase}", review_response, f"Fase {current_phase}")
        review = _extract_and_validate_review(review_response, logger)

        if review and review.get("status") == "APPROVED":
            print(f"[PM] ✅ Fase {current_phase} APROBADA")
            phases_completed = logger._get_state().get("phases_completed", []) + [current_phase]
            logger.update_state(phases_completed=phases_completed)

            current_phase += 1
            if current_phase <= total_phases:
                print(f"\n[PM] Solicitando tareas de fase {current_phase}...")
                session_context = (
                    f"Objetivo: {objective}\n"
                    f"Fases completadas: {current_phase - 1}/{total_phases}"
                )
                try:
                    next_response = request_next_phase(session_context)
                    logger.log_gemini("SIGUIENTE_FASE", session_context, next_response, f"Fase {current_phase}")

                    next_plan = _extract_and_validate_plan(next_response, logger)
                    if next_plan:
                        tasks = next_plan.get("tasks", [])
                        tasks_completed = []  # Reset for new phase
                        if isinstance(plan, dict):
                            plan["phase_name"] = next_plan.get("phase_name", f"Fase {current_phase}")
                        logger.update_state(
                            current_phase=current_phase,
                            tasks=tasks,
                            current_task_index=0,
                            tasks_completed=[],
                        )
                    else:
                        print("[WARN] No se pudo parsear la siguiente fase")
                        logger.update_state(status="PARSE_ERROR_NEXT_PHASE")
                        break
                except Exception as e:
                    print(f"[ERROR] Error solicitando siguiente fase: {e}")
                    logger.update_state(status="ERROR", error=str(e))
                    break

        elif review and review.get("status") == "CHANGES_REQUESTED":
            feedback = review.get("feedback", "")
            issues = review.get("issues", [])

            print(f"[PM] ⚠️  Cambios solicitados en fase {current_phase}")
            print(f"   Feedback: {feedback}")
            for issue in issues:
                print(f"   - {issue}")

            # Track feedback history
            state = logger._get_state()
            feedback_history = state.get("pm_feedback_history", [])
            feedback_entry = {
                "phase": current_phase,
                "feedback": feedback,
                "issues": issues,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            feedback_history.append(feedback_entry)

            # Check retry limit
            phase_retries = sum(1 for f in feedback_history if f.get("phase") == current_phase)
            if phase_retries > CHANGES_REQUESTED_MAX_RETRIES:
                print(f"[ERROR] Fase {current_phase} excedió {CHANGES_REQUESTED_MAX_RETRIES} reintentos. Pausando.")
                logger.update_state(
                    status="PAUSED_MAX_RETRIES",
                    pm_feedback_history=feedback_history,
                )
                break

            _log("ORCH", f"Re-ejecutando fase {current_phase} (intento {phase_retries}/{CHANGES_REQUESTED_MAX_RETRIES})")

            # Compose combined feedback text
            full_feedback = feedback
            if issues:
                full_feedback += "\n\nProblemas específicos:\n" + "\n".join(f"- {i}" for i in issues)

            # Re-enqueue: reset task completion and re-execute with feedback
            tasks_completed = []
            logger.update_state(
                pm_feedback_history=feedback_history,
                tasks_completed=[],
                current_task_index=0,
            )

            # Re-run the phase with PM feedback injected into each task
            phase_reports = []
            for task_idx, task in enumerate(tasks):
                task_id = task.get("id", f"T{task_idx + 1}")
                print(f"\n  [DEV] RE-ejecutando tarea {task_id} con feedback del PM...")
                logger.update_state(current_task_index=task_idx)
                logger.log_developer("RE_EJECUCION_FEEDBACK", task_id,
                                    f"Feedback PM: {full_feedback[:300]}")

                # Delete old report for clean detection
                old_report = logger.session_dir / f"dev_report_{task_id}.md"
                if old_report.exists():
                    old_report.unlink()

                dev_result = _execute_single_task(
                    task, logger, dev_mode, current_phase,
                    pm_feedback=full_feedback,
                )

                phase_reports.append({"task_id": task_id, "result": dev_result})
                tasks_completed.append(task_id)
                logger.update_state(tasks_completed=tasks_completed)

            # Re-review after re-execution
            _log("ORCH", f"Re-enviando trabajo corregido de fase {current_phase} al PM...")
            work_report = "\n\n".join([
                f"### Tarea {r['task_id']}\n{r['result']}"
                for r in phase_reports
            ])

            try:
                review_response = review_work(f"Fase {current_phase} (corrección)", work_report)
                logger.log_gemini("RE_REVISION", f"Fase {current_phase}", review_response, f"Fase {current_phase}")
                re_review = _extract_and_validate_review(review_response, logger)

                if re_review and re_review.get("status") == "APPROVED":
                    print(f"[PM] ✅ Fase {current_phase} APROBADA tras corrección")
                    phases_completed = logger._get_state().get("phases_completed", []) + [current_phase]
                    logger.update_state(phases_completed=phases_completed)
                    current_phase += 1

                    if current_phase <= total_phases:
                        # Request next phase
                        session_context = f"Objetivo: {objective}\nFases completadas: {current_phase - 1}/{total_phases}"
                        next_response = request_next_phase(session_context)
                        logger.log_gemini("SIGUIENTE_FASE", session_context, next_response, f"Fase {current_phase}")
                        next_plan = _extract_and_validate_plan(next_response, logger)
                        if next_plan:
                            tasks = next_plan.get("tasks", [])
                            tasks_completed = []
                            if isinstance(plan, dict):
                                plan["phase_name"] = next_plan.get("phase_name", f"Fase {current_phase}")
                            logger.update_state(
                                current_phase=current_phase,
                                tasks=tasks,
                                current_task_index=0,
                                tasks_completed=[],
                            )
                        else:
                            print("[WARN] No se pudo parsear la siguiente fase")
                            break
                    continue  # Next iteration of while loop
                else:
                    print(f"[PM] Fase {current_phase} sigue sin aprobar tras corrección. Pausando.")
                    logger.update_state(status="PAUSED")
                    break
            except Exception as e:
                print(f"[ERROR] Error en re-revisión: {e}")
                logger.update_state(status="REVIEW_ERROR", error=str(e))
                break
        else:
            print(f"[WARN] Revisión no estructurada. Revisa: {logger.gemini_log}")
            logger.update_state(status="REVIEW_UNSTRUCTURED")
            break

    # ── DONE ──
    if current_phase > total_phases:
        logger.update_state(status="COMPLETED")
        print(f"\n{'='*60}")
        print(f"  🎼 Orchestra  --  Sesión completada exitosamente")
    else:
        final_state = logger._get_state()
        if final_state.get("status") not in ("PAUSED", "PAUSED_MAX_RETRIES", "ERROR",
                                               "REVIEW_ERROR", "REVIEW_UNSTRUCTURED",
                                               "PARSE_ERROR_NEXT_PHASE", "STOPPED"):
            logger.update_state(status="PAUSED")
        print(f"\n{'='*60}")
        print(f"  🎼 Orchestra  --  Sesión pausada")
        print(f"  Para reanudar: python orchestrator.py --resume {session_id}")

    print(f"  Logs PM: orchestra/logs/sessions/{session_id}/gemini_pm.md")
    print(f"  Logs Dev: orchestra/logs/sessions/{session_id}/developer.md")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("USO: python orchestrator.py \"<objetivo>\" [modo: antigravity|gemini-dev|manual]")
        print("     python orchestrator.py --resume <session_id|latest>")
        print()
        print("MODOS:")
        print("  antigravity  - Antigravity IDE como developer (Claude Opus 4.6) [DEFAULT]")
        print("  gemini-dev   - Gemini CLI como developer (headless, fallback)")
        print("  manual       - Exporta tareas como .md para ejecucion manual")
        print()
        print("REANUDAR:")
        print("  --resume latest         Reanuda la sesión más reciente")
        print("  --resume 20250417_...   Reanuda una sesión específica")
        print()
        print("EJEMPLOS:")
        print('  python orchestrator.py "Crear sistema de login"')
        print('  python orchestrator.py "Refactorizar modulo X" gemini-dev')
        print('  python orchestrator.py --resume latest')
        sys.exit(1)

    # Parse arguments
    if sys.argv[1] == "--resume":
        resume_id = sys.argv[2] if len(sys.argv) > 2 else "latest"
        run_session(objective="", dev_mode="antigravity", resume_session_id=resume_id)
    else:
        objective = sys.argv[1]
        mode = sys.argv[2] if len(sys.argv) > 2 else "antigravity"
        run_session(objective, dev_mode=mode)
