"""
Orchestra — JSON Extraction & Validation Engine
Extracts structured JSON from Gemini PM responses, validates against schemas,
and handles automatic correction via re-submission to the PM.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from config import JSON_CORRECTION_MAX_RETRIES


# ─────────────────────────────────────────────
# Dataclasses — Strict typing for PM responses
# ─────────────────────────────────────────────

@dataclass
class PlanTask:
    """A single task as defined by the PM."""
    id: str
    title: str
    objetivo: str
    contexto: str = ""
    logica: str = ""
    criterios_aceptacion: list[str] = field(default_factory=list)
    decisiones: list[str] = field(default_factory=list)
    archivos_afectados: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanTask:
        """Create a PlanTask from a raw dict, tolerating missing optional fields."""
        return cls(
            id=data.get("id", "UNKNOWN"),
            title=data.get("title", "Sin título"),
            objetivo=data.get("objetivo", ""),
            contexto=data.get("contexto", ""),
            logica=data.get("logica", ""),
            criterios_aceptacion=data.get("criterios_aceptacion", []),
            decisiones=data.get("decisiones", []),
            archivos_afectados=data.get("archivos_afectados", []),
        )


@dataclass
class PlanResponse:
    """Structured plan response from the PM."""
    objective: str
    total_phases: int
    current_phase: int
    phase_name: str = ""
    phase_description: str = ""
    future_phases: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[PlanTask] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanResponse:
        """Create a PlanResponse from a raw dict."""
        tasks = [PlanTask.from_dict(t) for t in data.get("tasks", [])]
        return cls(
            objective=data.get("objective", ""),
            total_phases=data.get("total_phases", 1),
            current_phase=data.get("current_phase", 1),
            phase_name=data.get("phase_name", ""),
            phase_description=data.get("phase_description", ""),
            future_phases=data.get("future_phases", []),
            tasks=tasks,
        )


@dataclass
class ReviewResponse:
    """Structured review response from the PM."""
    phase_reviewed: str
    status: str  # "APPROVED" | "CHANGES_REQUESTED"
    feedback: str = ""
    issues: list[str] = field(default_factory=list)
    next_phase: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewResponse:
        """Create a ReviewResponse from a raw dict."""
        return cls(
            phase_reviewed=data.get("phase_reviewed", ""),
            status=data.get("status", "UNKNOWN"),
            feedback=data.get("feedback", ""),
            issues=data.get("issues", []),
            next_phase=data.get("next_phase"),
        )


@dataclass
class ValidationResult:
    """Result of schema validation."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.is_valid


# ─────────────────────────────────────────────
# JSON Extraction
# ─────────────────────────────────────────────

def _find_balanced_json(text: str) -> str | None:
    """
    Find the first balanced JSON object in text by matching braces.
    More robust than greedy regex for nested structures.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def extract_json_from_response(response: str) -> dict[str, Any] | None:
    """
    Extract JSON from a Gemini response that may contain markdown and text.

    Strategy (in priority order):
    1. Look for ```json ... ``` fenced code blocks (may be multiple — try each)
    2. Look for balanced { } structures in raw text
    3. Return None if nothing valid found

    Args:
        response: Raw text response from Gemini PM

    Returns:
        Parsed dict or None if no valid JSON found
    """
    if not response or not response.strip():
        return None

    # Strategy 1: Fenced ```json blocks (try all matches, return first valid)
    json_blocks = re.findall(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    for block in json_blocks:
        block = block.strip()
        if not block:
            continue
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue

    # Strategy 2: Balanced brace matching (more robust than greedy regex)
    balanced = _find_balanced_json(response)
    if balanced:
        try:
            return json.loads(balanced)
        except json.JSONDecodeError:
            pass

    # Strategy 3: Last resort — greedy regex (may catch nested objects)
    greedy_match = re.search(r'\{[\s\S]*\}', response)
    if greedy_match:
        try:
            return json.loads(greedy_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ─────────────────────────────────────────────
# Schema Validation
# ─────────────────────────────────────────────

_PLAN_REQUIRED_FIELDS = {"objective", "total_phases", "current_phase", "tasks"}
_PLAN_TASK_REQUIRED_FIELDS = {"id", "title", "objetivo"}
_REVIEW_REQUIRED_FIELDS = {"status"}
_VALID_REVIEW_STATUSES = {"APPROVED", "CHANGES_REQUESTED"}


def validate_plan_schema(data: dict[str, Any]) -> ValidationResult:
    """
    Validate a decomposition/plan JSON against the expected schema.

    Checks:
    - Required top-level fields exist
    - `tasks` is a list with at least one item
    - Each task has required fields (id, title, objetivo)
    - Types are correct (total_phases is int, tasks is list, etc.)

    Args:
        data: Parsed JSON dict

    Returns:
        ValidationResult with is_valid, errors, and warnings
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Top-level required fields
    for field_name in _PLAN_REQUIRED_FIELDS:
        if field_name not in data:
            errors.append(f"Campo obligatorio faltante: '{field_name}'")

    # Type checks
    if "total_phases" in data and not isinstance(data["total_phases"], int):
        errors.append(f"'total_phases' debe ser int, recibido: {type(data['total_phases']).__name__}")

    if "current_phase" in data and not isinstance(data["current_phase"], int):
        errors.append(f"'current_phase' debe ser int, recibido: {type(data['current_phase']).__name__}")

    # Tasks validation
    tasks = data.get("tasks")
    if tasks is not None:
        if not isinstance(tasks, list):
            errors.append(f"'tasks' debe ser una lista, recibido: {type(tasks).__name__}")
        elif len(tasks) == 0:
            warnings.append("'tasks' está vacío — no hay tareas en esta fase")
        else:
            for i, task in enumerate(tasks):
                if not isinstance(task, dict):
                    errors.append(f"Tarea {i} no es un objeto dict")
                    continue
                for req_field in _PLAN_TASK_REQUIRED_FIELDS:
                    if req_field not in task:
                        errors.append(f"Tarea {i} ({task.get('id', '?')}): campo '{req_field}' faltante")

                # Warnings for optional but important fields
                if not task.get("criterios_aceptacion"):
                    warnings.append(f"Tarea {task.get('id', '?')}: sin criterios de aceptación")
                if not task.get("logica"):
                    warnings.append(f"Tarea {task.get('id', '?')}: sin lógica definida")

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def validate_review_schema(data: dict[str, Any]) -> ValidationResult:
    """
    Validate a review JSON against the expected schema.

    Args:
        data: Parsed JSON dict

    Returns:
        ValidationResult with is_valid, errors, and warnings
    """
    errors: list[str] = []
    warnings: list[str] = []

    for field_name in _REVIEW_REQUIRED_FIELDS:
        if field_name not in data:
            errors.append(f"Campo obligatorio faltante: '{field_name}'")

    status = data.get("status", "")
    if status and status not in _VALID_REVIEW_STATUSES:
        errors.append(
            f"'status' inválido: '{status}'. "
            f"Debe ser uno de: {', '.join(_VALID_REVIEW_STATUSES)}"
        )

    if not data.get("feedback"):
        warnings.append("Sin campo 'feedback' en la revisión")

    if status == "CHANGES_REQUESTED" and not data.get("issues"):
        warnings.append("Status es CHANGES_REQUESTED pero no hay 'issues' listados")

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ─────────────────────────────────────────────
# Auto-correction via PM re-submission
# ─────────────────────────────────────────────

def request_json_correction(
    pm_caller: Callable[[str, bool], str],
    original_response: str,
    errors: list[str],
    max_retries: int = JSON_CORRECTION_MAX_RETRIES,
) -> dict[str, Any] | None:
    """
    Re-send a correction request to the PM when JSON is invalid or malformed.

    This creates a follow-up prompt explaining the errors and asking the PM
    to re-emit the JSON in the correct format.

    Args:
        pm_caller: Function to call Gemini PM (call_gemini signature: (prompt, resume) -> str)
        original_response: The raw response that failed validation
        errors: List of validation errors to report
        max_retries: Maximum correction attempts

    Returns:
        Valid parsed dict, or None if all retries fail
    """
    for attempt in range(1, max_retries + 1):
        error_list = "\n".join(f"  - {e}" for e in errors)

        correction_prompt = f"""ERROR DE FORMATO EN TU RESPUESTA ANTERIOR

Tu última respuesta no contiene un JSON válido o tiene errores de estructura.

Errores detectados:
{error_list}

Fragmento de tu respuesta (primeros 500 chars):
---
{original_response[:500]}
---

Por favor, RE-EMITE tu respuesta completa en el formato JSON correcto dentro de un bloque ```json```.
Asegúrate de incluir TODOS los campos obligatorios.
NO incluyas explicaciones fuera del bloque JSON."""

        print(f"  [JSON] Intento de corrección {attempt}/{max_retries}...")

        try:
            correction_response = pm_caller(correction_prompt, True)
        except Exception as e:
            print(f"  [JSON:ERROR] Error llamando al PM para corrección: {e}")
            continue

        # Try to extract JSON from the correction
        corrected = extract_json_from_response(correction_response)
        if corrected is not None:
            print(f"  [JSON] Corrección exitosa en intento {attempt}")
            return corrected

        # Update for next iteration
        original_response = correction_response
        errors = ["No se encontró JSON válido en la respuesta de corrección"]

    print(f"  [JSON:ERROR] Corrección fallida después de {max_retries} intentos")
    return None
