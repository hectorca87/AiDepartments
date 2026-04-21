"""
Orchestra — CDP Prompt Injector
Injects prompts into the Antigravity Agent chat panel via Chrome DevTools Protocol.

Strategy: Use CDP Input.dispatchKeyEvent to type the prompt character by character
into the focused chat input. This is the most reliable method because it simulates
real user input and triggers all React event handlers correctly.

Usage from developer.py:
    from cdp_injector import inject_prompt
    success = inject_prompt("Your prompt text here")
"""
from __future__ import annotations

import json
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import CDP_PORT, CDP_WS_TIMEOUT

try:
    import websocket
    import requests
except ImportError:
    raise ImportError("CDP injector requires: pip install websocket-client requests")


def _log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] [CDP] {msg}")


def _get_targets() -> list[dict]:
    """Get CDP targets from Antigravity."""
    try:
        resp = requests.get(f"http://localhost:{CDP_PORT}/json", timeout=5)
        return resp.json()
    except Exception as e:
        _log(f"Failed to get targets: {e}")
        return []


def _find_main_window(targets: list[dict]) -> dict | None:
    """Find the main Antigravity editor window target."""
    for t in targets:
        if t.get("type") == "page" and "Antigravity" in t.get("title", ""):
            return t
    return None


def _cdp_send(ws, method: str, params: dict = None, timeout: float = 15.0):
    """Send a CDP command and wait for the matching response, ignoring events."""
    msg_id = int(time.time() * 1000) % 100000
    payload = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    ws.send(json.dumps(payload))

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            ws.settimeout(min(5, deadline - time.monotonic()))
            raw = ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data
        except websocket.WebSocketTimeoutException:
            continue
        except Exception:
            break
    return None


# ── JS: Focus the Agent chat input ──
FOCUS_INPUT_JS = r"""
(function() {
    const candidates = document.querySelectorAll('div[contenteditable="true"][role="textbox"]');
    for (const el of candidates) {
        const rect = el.getBoundingClientRect();
        if (rect.width > 50 && rect.height > 0 && rect.x > 700) {
            el.focus();
            // Select all existing content so insertText replaces it
            const selection = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(el);
            selection.removeAllRanges();
            selection.addRange(range);
            return JSON.stringify({
                ok: true,
                x: Math.round(rect.x), y: Math.round(rect.y),
                w: Math.round(rect.width), h: Math.round(rect.height),
            });
        }
    }
    return JSON.stringify({ok: false, total: candidates.length});
})()
"""

# ── JS: Click the submit button ──
SUBMIT_JS = r"""
(function() {
    // Strategy 1: Find the send button (arrow icon to the right of input)
    const candidates = document.querySelectorAll('div[contenteditable="true"][role="textbox"]');
    let chatInput = null;
    for (const el of candidates) {
        const rect = el.getBoundingClientRect();
        if (rect.width > 50 && rect.height > 0 && rect.x > 700) {
            chatInput = el;
            break;
        }
    }
    if (!chatInput) return JSON.stringify({ok: false, error: 'input not found'});

    // Look for a button near the input area
    const container = chatInput.closest('[class*="relative"]')?.parentElement?.parentElement;
    if (container) {
        const buttons = container.querySelectorAll('button');
        for (const btn of buttons) {
            const rect = btn.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0 && rect.width < 60) {
                // Small button near input = likely submit
                const label = (btn.ariaLabel || btn.title || btn.textContent || '').trim();
                if (label || btn.querySelector('svg')) {
                    btn.click();
                    return JSON.stringify({ok: true, method: 'button', label: label.substring(0, 30)});
                }
            }
        }
    }

    return JSON.stringify({ok: false, error: 'submit button not found'});
})()
"""

# ── JS: Verify the input now has content ──
CHECK_CONTENT_JS = r"""
(function() {
    const candidates = document.querySelectorAll('div[contenteditable="true"][role="textbox"]');
    for (const el of candidates) {
        const rect = el.getBoundingClientRect();
        if (rect.width > 50 && rect.height > 0 && rect.x > 700) {
            return JSON.stringify({
                text: el.innerText.substring(0, 200),
                length: el.innerText.length,
                html: el.innerHTML.substring(0, 200),
            });
        }
    }
    return JSON.stringify({error: 'not found'});
})()
"""


def inject_prompt(prompt_text: str, max_retries: int = 3) -> bool:
    """
    Inject a prompt into the Antigravity Agent chat via CDP.

    Workflow:
    1. Connect to CDP WebSocket
    2. Focus the chat input and clear it
    3. Use Input.insertText to type the entire prompt (most reliable method)
    4. Submit via button click or Enter key dispatch

    Returns True if successfully injected and submitted.
    """
    for attempt in range(1, max_retries + 1):
        _log(f"Attempt {attempt}/{max_retries}")

        targets = _get_targets()
        if not targets:
            _log("No CDP targets — is Antigravity running?")
            time.sleep(3)
            continue

        main = _find_main_window(targets)
        if not main:
            _log("Main window not found in CDP targets")
            time.sleep(3)
            continue

        ws_url = main.get("webSocketDebuggerUrl")
        if not ws_url:
            _log("No WebSocket URL")
            continue

        try:
            ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
            _log("WebSocket connected")

            # Step 1: Focus input
            _log("Step 1 — Focus chat input...")
            r = _cdp_send(ws, "Runtime.evaluate", {
                "expression": FOCUS_INPUT_JS,
                "returnByValue": True,
            })
            if not r:
                _log("No response to focus eval")
                ws.close()
                time.sleep(3)
                continue

            val = r.get("result", {}).get("result", {}).get("value")
            if not val:
                _log(f"Focus eval returned no value: {json.dumps(r)[:150]}")
                ws.close()
                time.sleep(3)
                continue

            info = json.loads(val)
            if not info.get("ok"):
                _log(f"Chat input not found: {info}")
                ws.close()
                time.sleep(3)
                continue

            _log(f"Input focused @ ({info['x']},{info['y']}) {info['w']}x{info['h']}")

            # Step 2: Type the prompt using Input.insertText
            _log(f"Step 2 — Inserting text ({len(prompt_text)} chars)...")
            r2 = _cdp_send(ws, "Input.insertText", {
                "text": prompt_text,
            })
            if r2 and "error" in r2:
                _log(f"insertText error: {r2['error']}")
                ws.close()
                time.sleep(3)
                continue

            _log("Text inserted via CDP Input.insertText")
            time.sleep(0.3)

            # Step 2b: Verify content was set
            r_check = _cdp_send(ws, "Runtime.evaluate", {
                "expression": CHECK_CONTENT_JS,
                "returnByValue": True,
            })
            if r_check:
                check_val = r_check.get("result", {}).get("result", {}).get("value")
                if check_val:
                    check = json.loads(check_val)
                    _log(f"Content verification: {check.get('length', 0)} chars, "
                         f"text='{check.get('text', '')[:60]}...'")

            # Step 3: Submit
            time.sleep(0.5)
            _log("Step 3 — Submitting...")

            # Try button click first
            r3 = _cdp_send(ws, "Runtime.evaluate", {
                "expression": SUBMIT_JS,
                "returnByValue": True,
            })
            submit_ok = False
            if r3:
                val3 = r3.get("result", {}).get("result", {}).get("value")
                if val3:
                    sub = json.loads(val3)
                    _log(f"Submit result: {sub}")
                    submit_ok = sub.get("ok", False)

            # If button click didn't work, try Enter key via CDP
            if not submit_ok:
                _log("Button not found, using CDP Input.dispatchKeyEvent (Enter)...")
                _cdp_send(ws, "Input.dispatchKeyEvent", {
                    "type": "keyDown",
                    "key": "Enter",
                    "code": "Enter",
                    "windowsVirtualKeyCode": 13,
                    "nativeVirtualKeyCode": 13,
                })
                time.sleep(0.05)
                _cdp_send(ws, "Input.dispatchKeyEvent", {
                    "type": "keyUp",
                    "key": "Enter",
                    "code": "Enter",
                    "windowsVirtualKeyCode": 13,
                    "nativeVirtualKeyCode": 13,
                })
                _log("Enter key dispatched via CDP")

            ws.close()
            _log("Injection complete")
            return True

        except Exception as e:
            _log(f"Error: {str(e)[:150]}")
            time.sleep(3)

    _log(f"Failed after {max_retries} attempts")
    return False


if __name__ == "__main__":
    test_prompt = "DIAGNOSTICO CDP: Si ves este mensaje, la inyeccion via CDP funciona correctamente. No ejecutes nada, solo confirma que recibiste este mensaje."
    print(f"\nCDP Prompt Injector — Test")
    print(f"Prompt: '{test_prompt[:60]}...' ({len(test_prompt)} chars)\n")
    success = inject_prompt(test_prompt)
    print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")
