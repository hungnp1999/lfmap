import os
import sys
import time

import pytest

from lfmap_core import ToolError
from lfmap_powershell.runner import run_process


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_captures_exit_code_and_both_streams(tmp_path):
    result = run_process(_python("import sys; print('out'); print('err', file=sys.stderr)"), tmp_path, 30, 1000)
    assert result.exit_code == 0
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"
    assert not result.timed_out
    assert not result.stdout_truncated and not result.stderr_truncated
    assert result.duration_ms >= 0


def test_non_zero_exit_is_a_result_not_an_error(tmp_path):
    assert run_process(_python("raise SystemExit(3)"), tmp_path, 30, 1000).exit_code == 3


def test_output_is_decoded_as_utf8(tmp_path):
    code = "import sys; sys.stdout.buffer.write('Báo cáo đã xong'.encode('utf-8'))"
    assert run_process(_python(code), tmp_path, 30, 1000).stdout == "Báo cáo đã xong"


def test_invalid_utf8_is_replaced(tmp_path):
    result = run_process(_python("import sys; sys.stdout.buffer.write(b'a\\xffb')"), tmp_path, 30, 1000)
    assert result.stdout == "a�b"


def test_output_is_truncated_to_max_chars(tmp_path):
    result = run_process(_python("print('x' * 5000)"), tmp_path, 30, 1000)
    assert len(result.stdout) == 1000
    assert result.stdout_truncated


def test_runs_in_cwd(tmp_path):
    result = run_process(_python("import os; print(os.getcwd())"), tmp_path, 30, 1000)
    assert os.path.realpath(result.stdout.strip()) == os.path.realpath(tmp_path)


def test_stdin_is_closed(tmp_path):
    result = run_process(_python("import sys; print(repr(sys.stdin.read()))"), tmp_path, 10, 1000)
    assert result.stdout.strip() == "''"
    assert not result.timed_out


def test_timeout_kills_the_whole_tree(tmp_path):
    # The grandchild keeps the output pipes open; if it survived, collecting output would block for 30 s.
    child = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); time.sleep(30)"
    )
    started = time.monotonic()
    result = run_process(_python(child), tmp_path, 1, 1000)
    assert time.monotonic() - started < 15
    assert result.timed_out
    assert result.exit_code is None


def test_missing_program_is_backend_unavailable(tmp_path):
    with pytest.raises(ToolError) as error:
        run_process([str(tmp_path / "no-such-program")], tmp_path, 5, 1000)
    assert error.value.code == "backend_unavailable"
