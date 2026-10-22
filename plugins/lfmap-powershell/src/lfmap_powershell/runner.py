"""Run one process without a shell, with a timeout that kills its whole tree and capped output."""

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from lfmap_core import ToolError

# After the process ends (or is killed), how long to wait for the pipes to close.
_DRAIN_S = 5


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    duration_ms: int


class _Reader(threading.Thread):
    """Keep the first `limit` bytes of a stream and drain the rest, so the child never blocks on a full pipe."""

    def __init__(self, stream: IO[bytes], limit: int) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.limit = limit
        self.data = bytearray()
        self.overflow = False

    def run(self) -> None:
        with self.stream:
            for chunk in iter(lambda: self.stream.read1(65536), b""):
                room = self.limit - len(self.data)
                if room > 0:
                    self.data += chunk[:room]
                if len(chunk) > room:
                    self.overflow = True

    def text(self, max_chars: int) -> tuple[str, bool]:
        text = bytes(self.data).decode("utf-8", errors="replace")
        return text[:max_chars], self.overflow or len(text) > max_chars


def _kill_tree(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
        subprocess.run(
            [taskkill, "/T", "/F", "/PID", str(process.pid)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
    process.kill()


def run_process(argv: list[str], cwd: str | os.PathLike[str], timeout_s: float, max_chars: int) -> ProcessResult:
    """Start `argv` in `cwd`. A non-zero exit code is a result; starting failures are backend_unavailable."""
    if sys.platform == "win32":
        platform_args: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
    else:
        platform_args = {"start_new_session": True}
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            cwd=Path(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **platform_args,
        )
    except OSError as error:
        raise ToolError("backend_unavailable", "Could not start the process", {"program": argv[0]}) from error
    # UTF-8 needs at most 4 bytes per character; the extra bytes only tell that the text was cut.
    readers = [_Reader(stream, max_chars * 4 + 4) for stream in (process.stdout, process.stderr)]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(process)
        process.wait()
    duration_ms = int((time.monotonic() - started) * 1000)
    for reader in readers:
        reader.join(_DRAIN_S)
    stdout, stdout_truncated = readers[0].text(max_chars)
    stderr, stderr_truncated = readers[1].text(max_chars)
    return ProcessResult(
        None if timed_out else process.returncode,
        stdout,
        stderr,
        stdout_truncated,
        stderr_truncated,
        timed_out,
        duration_ms,
    )
