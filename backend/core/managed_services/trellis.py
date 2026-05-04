"""AL\\CE — TRELLIS external-process managed-service adapter.

TRELLIS runs as a sibling Python microservice in its own venv (see
``scripts/start-trellis.ps1``).  This wrapper is **health-only** by
default: AL\\CE does not auto-spawn the process — when the service URL
is unreachable we report ``down`` cleanly and let the user start it
themselves.  The class also supports a launcher path so future code can
opt in to subprocess management.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

import httpx
from loguru import logger

from backend.core.service_orchestrator import (
    ManagedService,
    ServiceHealth,
)


def resolve_trellis_launcher(name: str) -> tuple[Path | None, Path | None]:
    """Return the bundled launcher script and working directory for *name*.

    Args:
        name: ``"trellis"`` or ``"trellis2"``.

    Returns:
        ``(launcher, cwd)`` when the script exists, otherwise ``(None, None)``.
    """
    script_name = "start-trellis.ps1" if name == "trellis" else "start-trellis2.ps1"
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parents[3]
    candidate = base / "scripts" / script_name
    if candidate.exists():
        return candidate, base
    return None, None


def _port_from_service_url(service_url: str) -> int | None:
    """Extract an explicit TCP port from a TRELLIS service URL."""
    try:
        return urlparse(service_url).port
    except ValueError:
        return None


def _listening_pid_on_port(port: int) -> int | None:
    """Return the PID listening on *port* on Windows, if one exists."""
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    needle = f":{port}"
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[3].upper() != "LISTENING":
            continue
        local_address = parts[1]
        if local_address.endswith(needle):
            try:
                return int(parts[4])
            except ValueError:
                return None
    return None


async def _kill_windows_process_tree(pid: int) -> None:
    """Force-kill a Windows process tree rooted at *pid*."""
    if os.name != "nt":
        return

    def _run_taskkill() -> None:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    await asyncio.to_thread(_run_taskkill)


class TrellisManagedService(ManagedService):
    """Health-only wrapper around the TRELLIS HTTP microservice.

    Args:
        name: Logical name (``"trellis"`` or ``"trellis2"``).
        service_url: Base URL of the TRELLIS HTTP server.
        launcher: Optional path to a launcher script.  When provided and
            executable, ``start()`` will spawn it; otherwise ``start()``
            is a no-op and the service is treated as user-managed.
        cwd: Working directory for the launcher.
        health_interval_s: Seconds between health probes.
        startup_grace_s: Seconds to wait after launch before the first
            probe is allowed to mark the service as ``down``.
    """

    kind = "external_process"
    depends_on: list[str] = []
    restart_policy = "never"

    def __init__(
        self,
        *,
        name: str = "trellis",
        service_url: str,
        launcher: Path | None = None,
        cwd: Path | None = None,
        model: str = "",
        trellis_dir: str = "",
        port: int | None = None,
        health_interval_s: float = 10.0,
        startup_grace_s: float = 30.0,
    ) -> None:
        self.name = name
        self._service_url = service_url.rstrip("/")
        self._launcher = launcher
        self._cwd = cwd
        self._model = model
        self._trellis_dir = trellis_dir
        self._port = port or _port_from_service_url(service_url)
        self.health_interval_s = health_interval_s
        self._startup_grace_s = startup_grace_s
        self._proc: subprocess.Popen[bytes] | None = None
        self._started_at: float | None = None
        self._last_launcher_error: str | None = None
        self._launch_log_path: Path | None = None
        self._launch_log_file: BinaryIO | None = None

    def configure(
        self,
        *,
        service_url: str,
        launcher: Path | None,
        cwd: Path | None,
        model: str,
        trellis_dir: str,
        port: int | None = None,
    ) -> None:
        """Update launch parameters used by the next ``start()`` call."""
        self._service_url = service_url.rstrip("/")
        self._launcher = launcher
        self._cwd = cwd
        self._model = model
        self._trellis_dir = trellis_dir
        self._port = port or _port_from_service_url(service_url)
        self._last_launcher_error = None

    def _launcher_argv(self) -> list[str]:
        """Build the command line for the configured launcher."""
        if self._launcher is None:
            return []
        launcher_str = str(self._launcher)
        if os.name == "nt" and launcher_str.lower().endswith(".ps1"):
            argv = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", launcher_str,
            ]
        elif launcher_str.lower().endswith((".cmd", ".bat")):
            argv = ["cmd.exe", "/c", launcher_str]
        else:
            argv = [launcher_str]

        if self._model:
            argv.extend(["-Model", self._model])
        if self._port is not None:
            argv.extend(["-Port", str(self._port)])
        if self._trellis_dir:
            dir_flag = "-TrellisDir" if self.name == "trellis" else "-Trellis2Dir"
            argv.extend([dir_flag, self._trellis_dir])
        if os.name == "nt" and launcher_str.lower().endswith(".ps1"):
            argv.append("-NoPrompt")
        return argv

    def _close_launch_log(self) -> None:
        """Close the launcher log file handle, if one is open."""
        if self._launch_log_file is None:
            return
        try:
            self._launch_log_file.close()
        finally:
            self._launch_log_file = None

    def _open_launch_log(self, argv: list[str]) -> BinaryIO | None:
        """Open a per-service launcher log and write the command header."""
        self._close_launch_log()
        base = self._cwd
        if base is None and self._launcher is not None:
            base = self._launcher.parent.parent
        if base is None:
            return None
        try:
            log_dir = base / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / f"{self.name}-launcher.log"
            handle = path.open("ab", buffering=0)
            header = (
                "\n"
                f"[{datetime.now(timezone.utc).isoformat()}] launching {self.name}\n"
                f"cwd: {base}\n"
                f"argv: {argv!r}\n"
                "--- output ---\n"
            )
            handle.write(header.encode("utf-8", errors="replace"))
            self._launch_log_path = path
            self._launch_log_file = handle
            return handle
        except OSError as exc:
            logger.warning(
                "TRELLIS '{}' could not open launcher log: {}", self.name, exc,
            )
            self._launch_log_path = None
            return None

    def _log_hint(self) -> str:
        """Return a short diagnostic hint pointing at the launcher log."""
        if self._launch_log_path is None:
            return ""
        return f"; log={self._launch_log_path}"

    async def _is_service_reachable(self, timeout_s: float = 3.0) -> bool:
        """Return ``True`` when the configured service responds to health."""
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.get(f"{self._service_url}/health")
            return resp.status_code < 500
        except httpx.HTTPError:
            return False

    async def _wait_for_existing_listener(self, timeout_s: float = 20.0) -> bool:
        """Wait for an already-bound service port to become healthy."""
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            if await self._is_service_reachable(timeout_s=2.0):
                return True
            await asyncio.sleep(1.0)
        return False

    async def start(self) -> None:
        """Spawn the launcher subprocess if available; otherwise no-op."""
        if await self._is_service_reachable():
            self._last_launcher_error = None
            self._started_at = None
            logger.info("TRELLIS '{}' already reachable; reusing it", self.name)
            return

        if self._port is not None and _listening_pid_on_port(self._port) is not None:
            logger.info(
                "TRELLIS '{}' port {} already has a listener; waiting for health",
                self.name,
                self._port,
            )
            if await self._wait_for_existing_listener():
                self._last_launcher_error = None
                self._started_at = None
                logger.info("TRELLIS '{}' listener is healthy; reusing it", self.name)
                return
            message = (
                f"port {self._port} is already in use, but {self._service_url}/health "
                "did not become reachable"
            )
            self._last_launcher_error = message
            raise RuntimeError(message)

        if self._launcher is None or not Path(self._launcher).exists():
            message = f"launcher not configured/found: {self._launcher}"
            self._last_launcher_error = message
            raise FileNotFoundError(message)
        if self._proc is not None:
            if self._proc.poll() is None:
                return  # already running
            self._close_launch_log()
            self._proc = None
            self._started_at = None

        argv = self._launcher_argv()
        log_file = self._open_launch_log(argv)
        stdout_target = log_file if log_file is not None else subprocess.DEVNULL
        stderr_target = subprocess.STDOUT if log_file is not None else subprocess.DEVNULL
        self._last_launcher_error = None

        try:
            self._proc = subprocess.Popen(
                argv,
                cwd=str(self._cwd) if self._cwd else None,
                stdout=stdout_target,
                stderr=stderr_target,
            )
            self._started_at = asyncio.get_event_loop().time()
            logger.info(
                "TRELLIS '{}' spawned (pid={}, dir={!r}, model={!r})",
                self.name,
                self._proc.pid,
                self._trellis_dir,
                self._model,
            )
        except Exception as exc:
            self._last_launcher_error = f"launcher spawn failed: {exc}{self._log_hint()}"
            logger.warning("TRELLIS '{}': {}", self.name, self._last_launcher_error)
            self._proc = None
            self._close_launch_log()
            raise RuntimeError(self._last_launcher_error) from exc

    async def stop(self) -> None:
        """Terminate the spawned process gracefully then force-kill.

        Always returns within ~8s so the orchestrator's 10s stop timeout
        will not trip.
        """
        proc = self._proc
        if proc is None or proc.poll() is not None:
            self._proc = None
            self._close_launch_log()
            await self._stop_listening_process()
            return
        try:
            # Try graceful termination first.
            if os.name == "nt":
                await _kill_windows_process_tree(proc.pid)
            else:
                proc.send_signal(signal.SIGTERM)
                try:
                    await asyncio.to_thread(proc.wait, timeout=5.0)
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "TRELLIS '{}' did not exit on SIGTERM — killing",
                        self.name,
                    )
                    proc.kill()
                    try:
                        await asyncio.to_thread(proc.wait, timeout=3.0)
                    except subprocess.TimeoutExpired:
                        logger.error(
                            "TRELLIS '{}' did not respond to SIGKILL", self.name,
                        )
            if os.name == "nt":
                try:
                    await asyncio.to_thread(proc.wait, timeout=3.0)
                except subprocess.TimeoutExpired:
                    logger.warning("TRELLIS '{}' taskkill did not reap parent", self.name)
        finally:
            self._proc = None
            self._started_at = None
            self._close_launch_log()
            await self._stop_listening_process()

    async def _stop_listening_process(self) -> None:
        """Stop any process still bound to the configured service port."""
        if os.name != "nt" or self._port is None:
            return
        pid = _listening_pid_on_port(self._port)
        if pid is None:
            return
        logger.info(
            "TRELLIS '{}' stopping listener pid={} on port {}",
            self.name,
            pid,
            self._port,
        )
        await _kill_windows_process_tree(pid)

    async def health(self) -> ServiceHealth:
        """Probe ``GET /health`` (or root) on the TRELLIS service."""
        now = datetime.now(timezone.utc)
        launcher_exit_detail: str | None = None
        returncode = self._proc.poll() if self._proc is not None else None
        if self._proc is not None and returncode is not None:
            launcher_exit_detail = (
                f"launcher exited code={returncode}{self._log_hint()}"
            )
            self._proc = None
            self._started_at = None
            self._close_launch_log()

        if self._last_launcher_error is not None:
            return ServiceHealth(
                status="down",
                detail=self._last_launcher_error,
                last_check=now,
            )

        # Honour startup grace so a freshly spawned process isn't
        # immediately reported as ``down``.
        if (
            self._started_at is not None
            and asyncio.get_event_loop().time() - self._started_at
            < self._startup_grace_s
        ):
            return ServiceHealth(
                status="starting",
                detail=f"warm-up{self._log_hint()}",
                last_check=now,
            )
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._service_url}/health")
            if resp.status_code < 500:
                detail = f"reachable ({resp.status_code})"
                with contextlib.suppress(Exception):
                    data = resp.json()
                    if data.get("busy"):
                        elapsed = data.get("current_job_elapsed_s", 0)
                        model = data.get("current_job_name") or "model"
                        detail = f"generating {model} ({elapsed}s)"
                return ServiceHealth(
                    status="up",
                    detail=detail,
                    last_check=now,
                )
            return ServiceHealth(
                status="degraded",
                detail=f"HTTP {resp.status_code}",
                last_check=now,
            )
        except httpx.HTTPError as exc:
            detail = f"unreachable: {exc.__class__.__name__}"
            if launcher_exit_detail is not None:
                detail = f"{launcher_exit_detail}; {detail}"
            return ServiceHealth(
                status="down",
                detail=detail,
                last_check=now,
            )
