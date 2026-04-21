# AiDepartments

**Tu equipo de desarrollo autónomo con IA.**

Le dices qué quieres. Gemini planifica. Claude lo implementa. Tú revisas el resultado.

---

## ¿Qué es?

AiDepartments es un sistema que simula un equipo de desarrollo con dos roles de IA:

- **PM (Project Manager)** — Gemini 2.5 Pro. Analiza tu proyecto, descompone el objetivo en tareas, y revisa el trabajo.
- **Developer** — Claude Opus (Antigravity IDE). Escribe código, crea archivos, ejecuta tests.

Tú le das un objetivo en lenguaje natural. El sistema se encarga del resto.

```
"Crear una API en FastAPI con un endpoint /health y su test unitario"
```

El PM crea un plan (3 tareas), las asigna una a una al Developer, espera los reportes, revisa la calidad, y cuando todo está bien cierra la sesión. Tú no tocas nada.

---

## ¿Cómo funciona?

```
Tú escribes un objetivo
        │
        ▼
┌──────────────┐
│   PM (Gemini) │ ──► Analiza el repo, descompone en fases y tareas
└──────┬───────┘
       │ Plan JSON
       ▼
┌──────────────┐
│  Orchestrator │ ──► Itera cada tarea, coordina PM ↔ Developer
└──────┬───────┘
       │ Prompt de tarea
       ▼
┌──────────────┐
│ CDP Injector  │ ──► Inyecta la tarea en Antigravity via Chrome DevTools
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Dev (Claude)  │ ──► Escribe código, crea archivos, ejecuta tests
└──────┬───────┘
       │ Reporte .md
       ▼
┌──────────────┐
│ File Watcher  │ ──► Detecta que el Developer terminó
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   PM (Gemini) │ ──► Lee los archivos creados, revisa calidad
└──────┬───────┘
       │
       ▼
   ✅ Aprobado → siguiente fase
   ❌ Cambios → re-asigna la tarea
```

Todo esto pasa solo. Si Claude recibe un error de tráfico, el **Auto-Retry Monitor** lo detecta y hace click en "Retry" automáticamente.

Mientras tanto puedes ver el progreso en tiempo real en el **Dashboard** (`localhost:8420`).

---

## Demo real

```
> aid.bat "Implementar una API en FastAPI con /health y test unitario"

[PM] Plan creado: 1 fase, 3 tareas
  ├── P1-T1: Configurar dependencias (requirements.txt)
  ├── P1-T2: Implementar endpoint /health
  └── P1-T3: Crear test unitario

[CDP] Prompt inyectado → Claude trabaja...
[WATCHER] Reporte P1-T1 recibido (19s)
[CDP] Siguiente tarea inyectada...
[WATCHER] Reporte P1-T2 recibido (28s)
[CDP] Siguiente tarea inyectada...
[WATCHER] Reporte P1-T3 recibido (73s)

[PM] ✅ Fase 1 APROBADA
     "El trabajo cumple todos los criterios. Buen trabajo."

Sesión completada exitosamente
```

**Resultado**: 3 archivos creados, test pasa, 0 intervención humana.

---

## Setup rápido

```bash
# 1. Requisitos
npm install -g @anthropic-ai/gemini-cli   # PM
pip install websocket-client requests       # CDP

# 2. Clonar
git clone https://github.com/hectorca87/AiDepartments.git

# 3. Colocar dentro de tu proyecto
mv AiDepartments mi-proyecto/AiDepartments

# 4. Copiar instrucciones del PM
mkdir mi-proyecto/.gemini
cp AiDepartments/templates/.gemini/GEMINI.md mi-proyecto/.gemini/

# 5. Abrir Antigravity con CDP (PowerShell)
$exe = @("$env:LOCALAPPDATA\Programs\Antigravity\Antigravity.exe","$env:ProgramFiles\Antigravity\Antigravity.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1; Start-Process $exe -ArgumentList '--remote-debugging-port=9000'
# Luego abre tu proyecto en Antigravity (File → Open Folder)

# 6. Lanzar
cd mi-proyecto/AiDepartments
aid.bat "Tu objetivo aquí"
```

---

## Comandos

| Comando | Qué hace |
|---------|----------|
| `aid.bat "objetivo"` | Nueva sesión autónoma |
| `aid.bat --dashboard` | Dashboard web en `localhost:8420` |
| `aid.bat --retry` | Monitor auto-retry para errores de tráfico |
| `aid.bat --resume latest` | Reanudar última sesión |
| `aid.bat --help` | Ver todas las opciones |

---

## Stack

| Componente | Tecnología |
|-----------|------------|
| PM | Gemini 2.5 Pro (via Gemini CLI) |
| Developer | Claude Opus 4.6 (via Antigravity IDE) |
| Inyección de prompts | Chrome DevTools Protocol (CDP) |
| Dashboard | Python HTTP server + SPA vanilla |
| Orquestación | Python 3.12, sin frameworks externos |

---

## Requisitos

- Windows 10/11
- Python 3.12+
- Node.js 18+
- [Antigravity IDE](https://idx.google.com/antigravity)
- Cuenta Google con Gemini Advanced

---

## Configuración (config.py)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `GEMINI_MODEL` | `gemini-2.5-pro` | Modelo del PM |
| `CDP_PORT` | `9000` | Puerto CDP de Antigravity |
| `DASHBOARD_PORT` | `8420` | Puerto del dashboard web |
| `AG_REPORT_TIMEOUT` | `1800` (30 min) | Timeout máximo por tarea |
| `PM_TIMEOUT` | `300` (5 min) | Timeout del PM por llamada |

---

## Troubleshooting

| Problema | Solución |
|----------|----------|
| `gemini` no encontrado | `npm install -g @anthropic-ai/gemini-cli` |
| `gemini` pide login | Ejecuta `gemini` interactivo y autentícate |
| CDP 403 Forbidden | Reinicia Antigravity con `--remote-debugging-port=9000` |
| Prompt no llega al chat | Verifica que el panel Agent está visible (no minimizado) |
| PM devuelve JSON inválido | El json_engine auto-corrige — si persiste, aumenta `JSON_CORRECTION_MAX_RETRIES` |
| Dashboard no carga | Ejecuta `aid.bat --dashboard` primero |

