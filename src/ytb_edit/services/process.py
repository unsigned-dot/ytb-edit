"""Exécution annulable de processus externes (FFmpeg, ffprobe).

Sous Windows, chaque processus est rattaché à un « Job Object » configuré pour
tuer ses membres quand l'application se termine, même en cas de plantage :
aucun FFmpeg orphelin ne peut survivre.
"""

import collections
import logging
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ytb_edit.core.errors import OperationCancelled

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0  # pas de console qui clignote


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr_tail: str


def run(
    args: Sequence[str],
    *,
    is_cancelled: Callable[[], bool] = lambda: False,
    on_stdout_line: Callable[[str], None] | None = None,
    timeout: float | None = None,
) -> ProcessResult:
    """Lance ``args`` et attend la fin, en surveillant l'annulation (~100 ms).

    Si ``on_stdout_line`` est fourni, la sortie standard est transmise ligne par
    ligne au lieu d'être accumulée. Lève ``OperationCancelled`` en cas d'annulation.
    """
    log.debug("Commande : %s", subprocess.list2cmdline(list(args)))
    proc = subprocess.Popen(
        list(args),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_CREATION_FLAGS,
    )
    _attach_to_job(proc)

    stdout_lines: list[str] = []
    stderr_tail: collections.deque[str] = collections.deque(maxlen=30)

    def read_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_stdout_line:
                try:
                    on_stdout_line(line.rstrip("\n"))
                except Exception:
                    log.exception("Erreur dans le traitement de la sortie")
            else:
                stdout_lines.append(line)

    def read_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line.rstrip("\n"))

    readers = [
        threading.Thread(target=read_stdout, daemon=True),
        threading.Thread(target=read_stderr, daemon=True),
    ]
    for reader in readers:
        reader.start()

    elapsed = 0.0
    try:
        while True:
            try:
                proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                elapsed += 0.1
                if is_cancelled():
                    raise OperationCancelled(f"Processus interrompu : {args[0]}") from None
                if timeout is not None and elapsed > timeout:
                    raise TimeoutError(f"Délai dépassé ({timeout} s) : {args[0]}") from None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for reader in readers:
            reader.join(timeout=2)

    return ProcessResult(proc.returncode, "".join(stdout_lines), "\n".join(stderr_tail))


# ---------------------------------------------------------------------------
# Windows Job Object
# ---------------------------------------------------------------------------

_job_handle = None
_job_lock = threading.Lock()


def _attach_to_job(proc: subprocess.Popen) -> None:
    if not _IS_WINDOWS:
        return
    try:
        job = _get_job()
        import ctypes

        if not ctypes.windll.kernel32.AssignProcessToJobObject(job, int(proc._handle)):  # type: ignore[attr-defined]
            log.debug("AssignProcessToJobObject a échoué (%s)", ctypes.GetLastError())
    except Exception:
        log.debug("Job Object indisponible", exc_info=True)


def _get_job():  # pragma: no cover - Windows uniquement
    global _job_handle
    with _job_lock:
        if _job_handle is not None:
            return _job_handle

        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError("CreateJobObjectW a échoué")
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise OSError("SetInformationJobObject a échoué")
        # Le handle n'est jamais fermé : Windows le ferme à la fin du processus
        # Python, ce qui tue alors tous les processus rattachés.
        _job_handle = job
        return job
