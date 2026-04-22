"""
Orchestra — Developer Agent Module
Supports multiple developer backends:
- antigravity: Opens a new AG chat session in agent mode (async, UI-based)
- gemini-dev: Uses Gemini CLI in yolo mode as developer (headless, reliable)
- manual: Exports task files for manual execution

Each task runs in an INDEPENDENT session to avoid context contamination.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from config import (
    WORKSPACE_ROOT,
    DEV_TASK_TIMEOUT,
)


def _log(prefix: str, msg: str) -> None:
    """Print a structured log message with timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] [{prefix}] {msg}")


def execute_task(task: dict, session_dir: Path, mode: str = "antigravity") -> str:
    """
    Execute a task using the configured developer agent.

    Each task is executed in an independent session to prevent
    context contamination from previous tasks.

    Modes:
    - "gemini-dev": Use Gemini CLI in yolo mode (headless, reliable)
    - "antigravity": Launch AG chat session (async, opens UI panel)
    - "manual": Generate task .md files for manual use

    Args:
        task: PM task specification dict
        session_dir: Path to the session logs directory
        mode: Developer backend to use

    Returns:
        Result string (direct output for gemini-dev, launch confirmation for antigravity)
    """
    task_id = task.get('id', 'unknown')

    # Set report path (absolute, for both modes)
    report_path = session_dir / f"dev_report_{task_id}.md"
    task['_report_path'] = str(report_path)

    if mode == "gemini-dev":
        return _call_gemini_dev(task, session_dir)
    elif mode == "antigravity":
        return _call_antigravity(task, session_dir)
    elif mode == "manual":
        task_file = _generate_task_file(task, session_dir)
        return f"[MANUAL] Tarea exportada a: {task_file}"
    else:
        raise ValueError(f"Modo desconocido: {mode}")


def _resolve_absolute_paths(relative_paths: list[str]) -> list[str]:
    """
    Convert relative file paths from the PM to absolute paths
    based on WORKSPACE_ROOT. This ensures the developer agent
    can find the exact files to modify.
    """
    result: list[str] = []
    for rel in relative_paths:
        abs_path = WORKSPACE_ROOT / rel.replace("/", os.sep)
        result.append(str(abs_path))
    return result


def _build_dev_prompt(task: dict, report_path: Path | None = None) -> str:
    """
    Build a comprehensive developer prompt from a PM task specification.

    Includes:
    - Full task context with absolute file paths
    - Logic to implement (step by step)
    - Acceptance criteria as a checklist
    - PM architectural decisions (mandatory to follow)
    - Explicit instructions about what NOT to do
    - Report file location (if provided)

    Args:
        task: PM task specification dict
        report_path: If provided, instruct the developer to write a report here
    """
    criterios = '\n'.join(f'- {c}' for c in task.get('criterios_aceptacion', []))
    decisiones = '\n'.join(f'- {d}' for d in task.get('decisiones', []))

    # Resolve relative paths to absolute paths for the developer
    archivos_rel = task.get('archivos_afectados', [])
    archivos_abs = _resolve_absolute_paths(archivos_rel)
    archivos_display = '\n'.join(
        f'- {rel}  →  {abs_p}'
        for rel, abs_p in zip(archivos_rel, archivos_abs)
    ) if archivos_rel else 'N/A'

    prompt = f"""TAREA ASIGNADA POR EL PROJECT MANAGER:

ID: {task.get('id', 'N/A')}
Titulo: {task.get('title', 'N/A')}

Objetivo: {task.get('objetivo', 'N/A')}

Contexto: {task.get('contexto', 'N/A')}

Logica a implementar:
{task.get('logica', 'N/A')}

Criterios de aceptacion:
{criterios if criterios else 'N/A'}

Archivos afectados (rutas relativas → absolutas):
{archivos_display}

Directorio raiz del proyecto: {WORKSPACE_ROOT}

Decisiones del PM (respetar obligatoriamente):
{decisiones if decisiones else 'Ninguna especificada'}

INSTRUCCIONES ESTRICTAS:
- NO abras el navegador. NUNCA.
- NO uses herramientas de red/web. Solo filesystem y ejecución local.
- Implementa EXACTAMENTE lo que se pide, sin desviaciones.
- Lee los archivos existentes ANTES de modificar.
- Verifica que cada criterio de aceptacion se cumple tras tu implementacion.
- Si tienes dudas arquitectónicas, inclúyelas con prefijo [DUDA_PM]:
"""

    # Add report instructions if path is provided (antigravity mode)
    if report_path:
        prompt += f"""
IMPORTANTE — CUANDO TERMINES:
Crea un archivo de reporte en esta ruta EXACTA:
{report_path}

El reporte debe ser un archivo Markdown con esta estructura:
```
# Reporte Dev — {task.get('id', 'N/A')}

## Archivos creados/modificados
- (lista de archivos con descripción breve de cambios)

## Criterios de aceptación
- [x] criterio cumplido
- [ ] criterio NO cumplido (explicar por qué)

## Notas
- (cualquier observación relevante)

## Dudas para el PM
- [DUDA_PM]: (si hay alguna duda arquitectónica pendiente)
```

⚠️ El archivo de reporte es OBLIGATORIO. Sin él, el sistema no puede continuar.
⚠️ La ruta debe ser EXACTA: {report_path}
"""

    return prompt


def _call_gemini_dev(task: dict, session_dir: Path) -> str:
    """
    Use Gemini CLI in yolo mode as the developer agent.
    This is HEADLESS and RELIABLE — runs to completion and returns output.
    Uses the user's Ultra plan (free).
    """
    task_id = task.get('id', 'unknown')
    prompt = _build_dev_prompt(task)  # No report path — gemini-dev writes output directly

    env = os.environ.copy()
    env["GOOGLE_GENAI_USE_GCA"] = "true"

    # Write prompt to file (avoid cmd line limits)
    prompt_file = session_dir / f"dev_prompt_{task_id}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    # Run Gemini in yolo mode (auto-approve ALL tool calls including shell)
    # Use PowerShell for reliable piping on Windows
    ps_cmd = (
        f'powershell -NoProfile -Command "'
        f"Get-Content '{prompt_file}' -Raw -Encoding UTF8 | "
        f"gemini -m gemini-2.5-flash --approval-mode yolo -"
        f'"'
    )

    _log("DEV:GEMINI", f"Ejecutando tarea {task_id} con gemini-2.5-flash (yolo mode)")

    try:
        result = subprocess.run(
            ps_cmd,
            cwd=str(WORKSPACE_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=DEV_TASK_TIMEOUT,
            encoding="utf-8",
            shell=True,
        )

        output = result.stdout.strip() if result.stdout else ""

        if result.returncode != 0:
            stderr = result.stderr or ""
            if "MODEL_CAPACITY_EXHAUSTED" in stderr or "429" in stderr:
                _log("DEV:GEMINI", "gemini-2.5-flash sin capacidad, probando gemini-3-flash-preview...")
                # Try with gemini-3-flash-preview as fallback
                ps_cmd2 = (
                    f'powershell -NoProfile -Command "'
                    f"Get-Content '{prompt_file}' -Raw -Encoding UTF8 | "
                    f"gemini -m gemini-3-flash-preview --approval-mode yolo -"
                    f'"'
                )
                result2 = subprocess.run(
                    ps_cmd2, cwd=str(WORKSPACE_ROOT), env=env,
                    capture_output=True, text=True, timeout=DEV_TASK_TIMEOUT,
                    encoding="utf-8", shell=True,
                )
                if result2.returncode == 0:
                    output = result2.stdout.strip()
                    _log("DEV:GEMINI", f"Fallback exitoso ({len(output)} chars)")
                else:
                    return f"ERROR: Todos los modelos dev sin capacidad.\n{stderr[:300]}"
            else:
                return f"ERROR: Gemini dev fallo.\n{stderr[:500]}"

        # Write report file
        report_path = Path(task['_report_path'])
        report_path.write_text(
            f"# Reporte Dev — {task_id}\n\n{output}\n",
            encoding="utf-8"
        )

        _log("DEV:GEMINI", f"Tarea {task_id} completada ({len(output)} chars)")
        return output

    except subprocess.TimeoutExpired:
        _log("DEV:TIMEOUT", f"Tarea {task_id} excedió {DEV_TASK_TIMEOUT}s")
        return f"ERROR: Timeout ejecutando tarea {task_id} (>{DEV_TASK_TIMEOUT // 60}min)"
    except Exception as e:
        _log("DEV:ERROR", f"Error en tarea {task_id}: {e}")
        return f"ERROR: {e}"


def _call_antigravity(task: dict, session_dir: Path) -> str:
    """
    Launch a new Antigravity chat session and inject the task prompt.

    Two-step approach (required because `antigravity chat` CLI pipe is broken):
    1. Use CLI to ensure the workspace window is open
    2. Use CDP (Chrome DevTools Protocol) to inject the prompt into the Agent chat panel

    Key design decisions:
    - The CLI `antigravity chat -m agent -` silently drops prompts due to an IPC bug
      in the Electron shell. CDP bypasses this by directly interacting with the DOM.
    - CDP uses Input.insertText which triggers all React event handlers correctly.
    - The submit is done via CDP Input.dispatchKeyEvent (Enter) as a reliable fallback.
    """
    task_id = task.get('id', 'unknown')
    report_path = Path(task['_report_path'])

    # Build prompt WITH report instructions (antigravity needs explicit report path)
    prompt = _build_dev_prompt(task, report_path=report_path)

    # Write prompt to file (for audit trail)
    prompt_file = session_dir / f"dev_prompt_{task_id}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    _log("DEV:AG", f"Lanzando Antigravity para tarea {task_id}")
    _log("DEV:AG", f"Prompt: {prompt_file} ({prompt_file.stat().st_size} bytes)")
    _log("DEV:AG", f"Reporte esperado: {report_path}")

    # Step 1: Verify CDP is reachable (Antigravity must be open already)
    # The user should open Antigravity in the correct project BEFORE running aid.bat
    try:
        import requests as _requests
        from config import CDP_PORT
        resp = _requests.get(f"http://localhost:{CDP_PORT}/json", timeout=3)
        if resp.status_code == 200:
            _log("DEV:AG", "Antigravity detectado via CDP")
        else:
            _log("DEV:AG:WARN", f"CDP respondió con status {resp.status_code}")
    except Exception:
        _log("DEV:AG:ERROR", f"Antigravity no detectado en CDP puerto. Abre Antigravity con --remote-debugging-port antes de ejecutar aid.bat")
        return "[ERROR] Antigravity no está abierto con CDP habilitado. Ábrelo primero."

    # Brief pause before injection
    import time as _time
    _time.sleep(1)

    # Step 2: Inject prompt via CDP
    try:
        from cdp_injector import inject_prompt
        success = inject_prompt(prompt)
    except ImportError as e:
        _log("DEV:AG:ERROR", f"CDP injector not available: {e}")
        return f"[ERROR] CDP injector not available: {e}"
    except Exception as e:
        _log("DEV:AG:ERROR", f"CDP injection error: {e}")
        return f"[ERROR] CDP injection failed: {e}"

    if success:
        _log("DEV:AG", f"Prompt inyectado exitosamente via CDP para {task_id}")
        return (
            f"[ANTIGRAVITY] Sesión AG abierta y prompt inyectado para tarea {task_id}.\n"
            f"Reporte esperado en: {report_path}"
        )
    else:
        _log("DEV:AG:ERROR", f"CDP injection failed para {task_id}")
        return (
            f"[ERROR] No se pudo inyectar el prompt en Antigravity.\n"
            f"Verifica que CDP esté activo en puerto 9000 y el Agent panel esté visible."
        )


def _generate_task_file(task: dict, session_dir: Path) -> Path:
    """Generate a markdown task file for manual execution."""
    task_id = task.get('id', 'unknown')
    task_file = session_dir / f"task_{task_id}.md"

    # Resolve absolute paths
    archivos_rel = task.get('archivos_afectados', [])
    archivos_abs = _resolve_absolute_paths(archivos_rel)

    with open(task_file, "w", encoding="utf-8") as f:
        f.write(f"# Tarea: {task.get('title', 'Sin titulo')}\n\n")
        f.write(f"**ID:** {task.get('id', 'N/A')}\n\n")
        f.write(f"## Objetivo\n{task.get('objetivo', 'N/A')}\n\n")
        f.write(f"## Contexto\n{task.get('contexto', 'N/A')}\n\n")
        f.write(f"## Logica a implementar\n{task.get('logica', 'N/A')}\n\n")
        f.write(f"## Criterios de aceptacion\n")
        for c in task.get('criterios_aceptacion', []):
            f.write(f"- [ ] {c}\n")
        f.write(f"\n## Decisiones del PM\n")
        for d in task.get('decisiones', []):
            f.write(f"- {d}\n")
        f.write(f"\n## Archivos afectados\n")
        for rel, abs_p in zip(archivos_rel, archivos_abs):
            f.write(f"- `{rel}` → `{abs_p}`\n")
        f.write(f"\n## Directorio raiz\n`{WORKSPACE_ROOT}`\n")

    return task_file
