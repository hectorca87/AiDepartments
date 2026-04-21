"""
Orchestra — Auto Retry Monitor (CDP)
Connects to Antigravity via Chrome DevTools Protocol and automatically
clicks the "Retry" button when "high traffic" or similar errors appear.

Runs as an INDEPENDENT PROCESS alongside the orchestrator:
    python auto_retry.py [--session <session_id>]

Features:
- Configurable via config.py (triggers, patterns, intervals)
- Logs retries to both console and session log file
- CDP WebSocket timeout to prevent hanging
- Automatic reconnection on WebSocket drop
- Dependency check at startup
- Recursive Shadow DOM searching
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add orchestra dir to path
sys.path.insert(0, str(Path(__file__).parent))

# Force unbuffered output
import functools
print = functools.partial(print, flush=True)

from config import (
    CDP_PORT,
    CDP_CHECK_INTERVAL,
    CDP_WS_TIMEOUT,
    CDP_RECONNECT_DELAY,
    CDP_RETRY_TRIGGERS,
    CDP_RETRY_BUTTON_PATTERNS,
    CDP_RETRY_LOG_FILE,
    SESSIONS_DIR,
)


def _log(prefix: str, msg: str) -> None:
    """Print a structured log message with timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] [{prefix}] {msg}")


def _check_dependencies() -> bool:
    """Check that required packages are installed."""
    missing = []
    try:
        import websocket  # noqa: F401
    except ImportError:
        missing.append("websocket-client")

    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")

    if missing:
        print(f"[ERROR] Dependencias faltantes: {', '.join(missing)}")
        print(f"  Instalar con: pip install {' '.join(missing)}")
        return False
    return True


def _find_active_session_log() -> Path | None:
    """Find the most recent active session's directory for logging."""
    if not SESSIONS_DIR.exists():
        return None

    sessions = sorted(SESSIONS_DIR.iterdir(), reverse=True)
    for session_dir in sessions:
        state_file = session_dir / "state.json"
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                if state.get("status") in ("IN_PROGRESS", "STARTED"):
                    return session_dir
            except (json.JSONDecodeError, OSError):
                continue
    return None


class RetryLogger:
    """Logs retry events to both console and a file in the session directory."""

    def __init__(self, session_dir: Path | None = None):
        self.log_file: Path | None = None
        if session_dir:
            self.log_file = session_dir / CDP_RETRY_LOG_FILE
            # Initialize log file
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"\n# Auto-Retry Monitor — Iniciado {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            _log("RETRY", f"Logging a: {self.log_file}")

    def log_retry(self, retry_count: int, trigger: str, clicked: str, shadow: bool = False):
        """Log a retry event."""
        ts = datetime.now().strftime("%H:%M:%S")
        shadow_tag = " [shadow]" if shadow else ""
        msg = f"RETRY #{retry_count}: '{trigger}' → clicked '{clicked}'{shadow_tag}"
        _log("RETRY", msg)

        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(f"- [{ts}] {msg}\n")
            except OSError:
                pass

    def log_event(self, msg: str):
        """Log a general event."""
        _log("RETRY", msg)
        if self.log_file:
            try:
                ts = datetime.now().strftime("%H:%M:%S")
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(f"- [{ts}] {msg}\n")
            except OSError:
                pass


def get_cdp_targets() -> list[dict]:
    """Get available CDP targets from Antigravity."""
    import requests

    try:
        resp = requests.get(f"http://localhost:{CDP_PORT}/json", timeout=CDP_WS_TIMEOUT)
        return resp.json()
    except Exception:
        return []


def send_cdp_command(ws, method: str, params: dict | None = None) -> dict:
    """
    Send a CDP command and get the result.
    Uses a timeout to prevent hanging on unresponsive targets.
    """
    msg_id = int(time.time() * 1000) % 100000
    msg = {"id": msg_id, "method": method, "params": params or {}}
    ws.send(json.dumps(msg))

    # Wait for response with timeout (ws already has timeout set)
    deadline = time.monotonic() + CDP_WS_TIMEOUT
    while time.monotonic() < deadline:
        try:
            result = json.loads(ws.recv())
            if result.get("id") == msg_id:
                return result.get("result", {})
        except Exception:
            break
    return {}


def check_and_retry(ws) -> dict | None:
    """
    Check if the page has a retryable error and click the retry button.
    Returns retry info dict if triggered, None otherwise.
    """
    js_code = """
    (function() {
        const triggers = %s;
        const buttonPatterns = %s;

        // Only scan the LAST few chat messages, not the entire page.
        // This prevents false positives from old conversation text.
        const chatMessages = document.querySelectorAll(
            '.chat-message, .message-content, .response-container, ' +
            '.chat-item, [class*="message"], [class*="response"]'
        );

        let searchText = '';
        if (chatMessages.length > 0) {
            // Only check the last 3 messages
            const recent = Array.from(chatMessages).slice(-3);
            searchText = recent.map(m => m.textContent || '').join(' ').toLowerCase();
        } else {
            // Fallback: check last 2000 chars of body text (tail, not head)
            const fullText = (document.body && document.body.textContent || '');
            searchText = fullText.slice(-2000).toLowerCase();
        }

        const foundTrigger = triggers.find(t => searchText.includes(t));
        if (!foundTrigger) return JSON.stringify({found: false});

        // Look for retry buttons — STRICT selectors only
        // Exclude elements with too much text (> 50 chars = not a button)
        const allButtons = document.querySelectorAll(
            'button, [role="button"], a.action-label, .monaco-button'
        );

        for (const btn of allButtons) {
            const btnText = (btn.textContent || btn.title || btn.ariaLabel || '').toLowerCase().trim();
            if (btnText.length > 50) continue;  // Skip non-button elements
            if (buttonPatterns.some(p => btnText.includes(p))) {
                btn.click();
                return JSON.stringify({found: true, trigger: foundTrigger, clicked: btnText, shadow: false});
            }
        }

        // Recursive Shadow DOM search (strict selectors)
        function searchShadowRoots(root) {
            const elements = root.querySelectorAll('*');
            for (const el of elements) {
                if (el.shadowRoot) {
                    const shadowButtons = el.shadowRoot.querySelectorAll(
                        'button, [role="button"], .monaco-button'
                    );
                    for (const btn of shadowButtons) {
                        const btnText = (btn.textContent || btn.title || btn.ariaLabel || '').toLowerCase().trim();
                        if (btnText.length > 50) continue;
                        if (buttonPatterns.some(p => btnText.includes(p))) {
                            btn.click();
                            return {found: true, trigger: foundTrigger, clicked: btnText, shadow: true};
                        }
                    }
                    const nested = searchShadowRoots(el.shadowRoot);
                    if (nested) return nested;
                }
            }
            return null;
        }

        const shadowResult = searchShadowRoots(document);
        if (shadowResult) return JSON.stringify(shadowResult);

        return JSON.stringify({found: true, trigger: foundTrigger, clicked: null, note: 'no retry button found'});
    })()
    """ % (json.dumps(CDP_RETRY_TRIGGERS), json.dumps(CDP_RETRY_BUTTON_PATTERNS))

    try:
        result = send_cdp_command(ws, "Runtime.evaluate", {
            "expression": js_code,
            "returnByValue": True,
        })

        value = result.get("result", {}).get("value", "{}")
        if isinstance(value, str):
            data = json.loads(value)
        else:
            data = value

        if data.get("found") and data.get("clicked"):
            return data
        return None
    except Exception:
        return None


def run_monitor(session_dir: Path | None = None):
    """
    Main monitoring loop.

    Args:
        session_dir: If provided, log retries to this session's directory
    """
    import websocket

    retry_logger = RetryLogger(session_dir)

    print(f"\n  Orchestra Auto-Retry Monitor")
    print(f"  CDP: localhost:{CDP_PORT}")
    print(f"  Intervalo: {CDP_CHECK_INTERVAL}s")
    print(f"  Triggers: {len(CDP_RETRY_TRIGGERS)} patrones")
    print(f"  Botones: {len(CDP_RETRY_BUTTON_PATTERNS)} patrones")
    print(f"  Ctrl+C para detener\n")

    retry_count = 0
    consecutive_failures = 0

    while True:
        targets = get_cdp_targets()

        if not targets:
            consecutive_failures += 1
            if consecutive_failures == 1:
                _log("RETRY:WARN", f"Sin conexión CDP en puerto {CDP_PORT}. ¿Está Antigravity abierto?")
            elif consecutive_failures % 10 == 0:
                _log("RETRY:WARN", f"Sin CDP desde hace {consecutive_failures * CDP_RECONNECT_DELAY}s")
            time.sleep(CDP_RECONNECT_DELAY)
            continue

        consecutive_failures = 0

        # Check all page targets (main window + agent panels)
        for target in targets:
            if target.get("type") not in ("page", "iframe"):
                continue

            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                continue

            ws = None
            try:
                ws = websocket.create_connection(ws_url, timeout=CDP_WS_TIMEOUT, suppress_origin=True)
                result = check_and_retry(ws)

                if result:
                    retry_count += 1
                    retry_logger.log_retry(
                        retry_count,
                        result.get("trigger", "?"),
                        result.get("clicked", "?"),
                        result.get("shadow", False),
                    )
            except websocket.WebSocketTimeoutException:
                pass  # Target busy
            except websocket.WebSocketConnectionClosedException:
                pass  # Target disconnected
            except Exception as e:
                if "Connection refused" not in str(e):
                    _log("RETRY:ERR", f"Error en target: {str(e)[:100]}")
            finally:
                if ws:
                    try:
                        ws.close()
                    except Exception:
                        pass

        time.sleep(CDP_CHECK_INTERVAL)


if __name__ == "__main__":
    if not _check_dependencies():
        sys.exit(1)

    # Parse optional --session argument
    session_dir = None
    if "--session" in sys.argv:
        idx = sys.argv.index("--session")
        if idx + 1 < len(sys.argv):
            session_id = sys.argv[idx + 1]
            candidate = SESSIONS_DIR / session_id
            if candidate.exists():
                session_dir = candidate
            else:
                print(f"[WARN] Sesión no encontrada: {session_id}")
    else:
        # Auto-detect active session
        session_dir = _find_active_session_log()
        if session_dir:
            _log("RETRY", f"Sesión activa detectada: {session_dir.name}")

    try:
        run_monitor(session_dir)
    except KeyboardInterrupt:
        print("\n  Monitor detenido.")
