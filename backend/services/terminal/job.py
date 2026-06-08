"""AL\\CE — Win32 Job Object process-tree kill (Fase 7 E1).

A PTY shell that spawns children (``npm`` → ``node``, ``python`` → subprocess)
leaves grandchildren running when only the *direct* child is killed — the
documented limitation in :mod:`backend.plugins.terminal.executor`.  A Win32 Job
Object closes that gap: assign the shell process to a job created with
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` and the **entire tree** dies when the job
is terminated (or its handle closed).

This module is Windows-only and degrades gracefully: :meth:`ProcessJob.assign_pid`
returns ``None`` on any non-Windows platform or on any Win32 failure, and the
caller (the session manager) then falls back to a best-effort direct
``PtyProcess.terminate``.  Everything is best-effort and never raises — teardown
must not be able to wedge a session close.
"""

from __future__ import annotations

import sys

from loguru import logger

__all__ = ["ProcessJob"]

# JOBOBJECTINFOCLASS / limit flags (winnt.h).
_JobObjectExtendedLimitInformation = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

# Process access rights (winnt.h) needed to assign a pid to a job + terminate it.
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100


class ProcessJob:
    """A Win32 Job Object owning one process tree, with kill-on-close.

    Construct via :meth:`assign_pid`; never instantiate directly.  Hold the
    instance for the session's lifetime and call :meth:`terminate` (or
    :meth:`close`, which also kills) to take the whole tree down.
    """

    def __init__(self, job_handle: int, process_handle: int) -> None:
        self._job = job_handle
        self._proc = process_handle
        self._closed = False

    @classmethod
    def assign_pid(cls, pid: int | None) -> ProcessJob | None:
        """Create a kill-on-close job and assign the process *pid* to it.

        Args:
            pid: The child process id (e.g. the PTY shell's ``pid``).

        Returns:
            A live :class:`ProcessJob`, or ``None`` when unavailable (non-Windows,
            missing pid, or any Win32 call failing) — the caller then falls back
            to a direct terminate.
        """
        if sys.platform != "win32" or not pid:
            return None
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            create_job = kernel32.CreateJobObjectW
            create_job.restype = wintypes.HANDLE
            create_job.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]

            open_process = kernel32.OpenProcess
            open_process.restype = wintypes.HANDLE
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

            assign = kernel32.AssignProcessToJobObject
            assign.restype = wintypes.BOOL
            assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

            set_info = kernel32.SetInformationJobObject
            set_info.restype = wintypes.BOOL
            set_info.argtypes = [
                wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
            ]

            job = create_job(None, None)
            if not job:
                return None

            # JOBOBJECT_EXTENDED_LIMIT_INFORMATION with KILL_ON_JOB_CLOSE.  The
            # struct is laid out as BASIC_LIMIT_INFORMATION + IO_COUNTERS +
            # process/job memory limits; we only need the LimitFlags field, so
            # the layout below pins the offsets exactly.
            class _IO_COUNTERS(ctypes.Structure):  # noqa: N801 — mirrors winnt.h
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong),
                ]

            class _BASIC_LIMIT_INFORMATION(ctypes.Structure):  # noqa: N801 — mirrors winnt.h
                _fields_ = [
                    ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.POINTER(wintypes.ULONG)),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class _EXTENDED_LIMIT_INFORMATION(ctypes.Structure):  # noqa: N801 — mirrors winnt.h
                _fields_ = [
                    ("BasicLimitInformation", _BASIC_LIMIT_INFORMATION),
                    ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            info = _EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not set_info(
                job,
                _JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                kernel32.CloseHandle(job)
                return None

            proc = open_process(_PROCESS_TERMINATE | _PROCESS_SET_QUOTA, False, pid)
            if not proc:
                kernel32.CloseHandle(job)
                return None

            if not assign(job, proc):
                kernel32.CloseHandle(proc)
                kernel32.CloseHandle(job)
                return None

            return cls(int(job), int(proc))
        except Exception as exc:  # pragma: no cover — defensive on exotic hosts
            logger.debug("ProcessJob.assign_pid failed: {}", exc)
            return None

    def terminate(self, exit_code: int = 1) -> bool:
        """Terminate the whole job (the process and all descendants).

        Args:
            exit_code: The exit code reported for the killed processes.

        Returns:
            ``True`` if the Win32 call succeeded, ``False`` otherwise.
        """
        if self._closed:
            return False
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            ok = bool(kernel32.TerminateJobObject(self._job, exit_code))
            return ok
        except Exception as exc:  # pragma: no cover — best-effort
            logger.debug("TerminateJobObject failed: {}", exc)
            return False

    def close(self) -> None:
        """Close the job + process handles (kill-on-close fires here too)."""
        if self._closed:
            return
        self._closed = True
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle(self._proc)
            kernel32.CloseHandle(self._job)
        except Exception as exc:  # pragma: no cover — best-effort
            logger.debug("ProcessJob.close failed: {}", exc)
