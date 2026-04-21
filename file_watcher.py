"""
Orchestra — File Watcher / Report Vigilance System
Detects when the Developer agent has completed its task by monitoring
the appearance and stability of the dev_report_XX.md file.

Two strategies:
1. Fast polling (default): Checks every N seconds for file existence + stabilization
2. OS-level file watching (optional): Uses watchdog if installed for instant detection

The stability check ensures the file is fully written before reading it,
by verifying the file size doesn't change across consecutive checks.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from config import (
    WATCHER_POLL_INTERVAL,
    WATCHER_STABLE_CHECKS,
    WATCHER_STABLE_DELAY,
    WATCHER_MIN_SIZE,
    AG_REPORT_TIMEOUT,
)


def _log(prefix: str, msg: str) -> None:
    """Print a structured log message with timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] [{prefix}] {msg}")


def _is_file_stable(path: Path, checks: int = WATCHER_STABLE_CHECKS,
                    delay: float = WATCHER_STABLE_DELAY) -> bool:
    """
    Verify the file is fully written by checking that its size
    doesn't change across consecutive checks.

    This prevents reading a file while Antigravity is still writing to it.

    Args:
        path: Path to the file to check
        checks: Number of consecutive stable readings required
        delay: Seconds between readings

    Returns:
        True if the file size is stable across all checks
    """
    if not path.exists():
        return False

    sizes: list[int] = []
    for _ in range(checks + 1):
        try:
            sizes.append(path.stat().st_size)
        except OSError:
            return False
        if len(sizes) > 1:
            time.sleep(delay)

    # All sizes must be equal and above minimum
    if len(set(sizes)) == 1 and sizes[0] >= WATCHER_MIN_SIZE:
        return True
    return False


def wait_for_report(
    report_path: Path,
    timeout: int = AG_REPORT_TIMEOUT,
    poll_interval: float = WATCHER_POLL_INTERVAL,
) -> WatchResult:
    """
    Wait for the developer agent to write its report file.

    Uses fast polling with stability verification to detect the report
    as quickly as possible while ensuring the file is fully written.

    Detection time after file creation: < poll_interval + (STABLE_CHECKS * STABLE_DELAY)
    With defaults: < 3 + (2 * 2) = ~7 seconds

    Args:
        report_path: Absolute path to the expected dev_report_XX.md file
        timeout: Maximum seconds to wait before giving up
        poll_interval: Seconds between file existence checks

    Returns:
        WatchResult with status, content, and timing information
    """
    _log("WATCHER", f"Vigilando: {report_path.name}")
    _log("WATCHER", f"Timeout: {timeout}s | Poll: {poll_interval}s | "
                     f"Estabilización: {WATCHER_STABLE_CHECKS}x{WATCHER_STABLE_DELAY}s")

    start_time = time.monotonic()
    last_progress_time = start_time
    check_count = 0

    while True:
        elapsed = time.monotonic() - start_time

        # Timeout check
        if elapsed >= timeout:
            _log("WATCHER:TIMEOUT", f"El developer no generó reporte en {timeout}s")
            return WatchResult(
                status="TIMEOUT",
                content=None,
                elapsed_seconds=elapsed,
                checks_performed=check_count,
            )

        check_count += 1

        # Check if file exists
        if report_path.exists():
            file_size = report_path.stat().st_size

            if file_size < WATCHER_MIN_SIZE:
                # File exists but too small — still being created
                _log("WATCHER", f"Archivo detectado pero muy pequeño ({file_size}B), esperando...")
            elif _is_file_stable(report_path):
                # File is stable — read it
                detection_time = time.monotonic() - start_time
                try:
                    content = report_path.read_text(encoding="utf-8")
                    _log("WATCHER:OK", f"Reporte recibido ({len(content)} chars) "
                                       f"en {detection_time:.1f}s tras {check_count} checks")
                    return WatchResult(
                        status="OK",
                        content=content,
                        elapsed_seconds=detection_time,
                        checks_performed=check_count,
                    )
                except (OSError, PermissionError) as e:
                    _log("WATCHER:WARN", f"Error leyendo archivo (puede estar bloqueado): {e}")
                    # Will retry on next iteration
            else:
                _log("WATCHER", f"Archivo en escritura ({file_size}B), esperando estabilización...")

        # Progress messages
        now = time.monotonic()
        if now - last_progress_time >= 60:
            minutes = int(elapsed // 60)
            remaining = int((timeout - elapsed) // 60)
            _log("WATCHER", f"{minutes} min esperando... ({remaining} min restantes)")
            last_progress_time = now

        time.sleep(poll_interval)


class WatchResult:
    """Result of file watching operation."""

    __slots__ = ("status", "content", "elapsed_seconds", "checks_performed")

    def __init__(
        self,
        status: str,
        content: str | None,
        elapsed_seconds: float,
        checks_performed: int,
    ):
        self.status = status          # "OK", "TIMEOUT", "ERROR"
        self.content = content        # File content if OK, None otherwise
        self.elapsed_seconds = elapsed_seconds
        self.checks_performed = checks_performed

    @property
    def is_ok(self) -> bool:
        return self.status == "OK"

    @property
    def is_timeout(self) -> bool:
        return self.status == "TIMEOUT"

    def __repr__(self) -> str:
        return (f"WatchResult(status={self.status!r}, "
                f"chars={len(self.content) if self.content else 0}, "
                f"elapsed={self.elapsed_seconds:.1f}s, "
                f"checks={self.checks_performed})")
