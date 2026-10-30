"""Issue #106: TTY-only commands need a real console. On Windows `isatty()` is True for stdin from NUL."""

import os
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from lfmap_core import cli
from lfmap_core.cli import build_app
from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError

runner = CliRunner()

TTY_ONLY = [
    ["approvals", "grant", "fake-plugin.write", "--tier", "T2", "--for", "1h"],
    ["approvals", "revoke", "fake-plugin.write"],
    ["config", "add-folder", ".", "--as", "documents"],
    ["events", "retry", "0" * 32, "adapter-fake-plugin"],
    ["events", "prune"],
]


class FakeStdin:
    def __init__(self, tty: bool) -> None:
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(cli, "_WINDOWS", True)
    monkeypatch.setattr(cli, "_console_window", lambda: True)


@pytest.mark.parametrize("args", TTY_ONLY, ids=lambda a: " ".join(a[:2]))
def test_tty_only_commands_refuse_without_a_console(registry, windows, monkeypatch, args) -> None:
    monkeypatch.setattr(cli, "_console_stdin", lambda: False)
    monkeypatch.setattr(cli.sys, "stdin", FakeStdin(tty=True))  # what NUL looks like to isatty()
    result = runner.invoke(build_app(registry), args)
    assert isinstance(result.exception, ToolError)
    assert result.exception.code == "permission_denied"
    assert "interactive terminal" in result.exception.message
    assert not (app_dir() / "grants.json").exists()
    assert not (app_dir() / "events.db").exists()


@pytest.mark.parametrize("args", TTY_ONLY, ids=lambda a: " ".join(a[:2]))
def test_tty_only_commands_refuse_a_console_without_a_window(registry, windows, monkeypatch, args) -> None:
    monkeypatch.setattr(cli, "_console_stdin", lambda: True)
    monkeypatch.setattr(cli, "_console_window", lambda: False)
    result = runner.invoke(build_app(registry), args)
    assert isinstance(result.exception, ToolError)
    assert result.exception.code == "permission_denied"
    assert "interactive terminal" in result.exception.message
    assert not (app_dir() / "grants.json").exists()


def test_console_probe_lets_a_person_through(registry, windows, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_console_stdin", lambda: True)
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    result = runner.invoke(build_app(registry), TTY_ONLY[0], input="ABC234\n")
    assert result.exit_code == 0, result.output
    assert (app_dir() / "grants.json").exists()


def test_windows_uses_the_console_probe_not_isatty(windows, monkeypatch) -> None:
    monkeypatch.setattr(cli.sys, "stdin", FakeStdin(tty=True))
    monkeypatch.setattr(cli, "_console_stdin", lambda: False)
    assert cli._interactive() is False
    monkeypatch.setattr(cli, "_console_stdin", lambda: True)
    assert cli._interactive() is True
    monkeypatch.setattr(cli, "_console_window", lambda: False)
    assert cli._interactive() is False


@pytest.mark.parametrize("tty", [True, False])
def test_other_platforms_keep_isatty(monkeypatch, tty) -> None:
    monkeypatch.setattr(cli, "_WINDOWS", False)
    monkeypatch.setattr(cli.sys, "stdin", FakeStdin(tty=tty))
    assert cli._interactive() is tty


def test_a_broken_stdin_is_not_interactive(monkeypatch) -> None:
    class Broken:
        def isatty(self) -> bool:
            raise ValueError("I/O operation on closed file")

        def fileno(self) -> int:
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(cli.sys, "stdin", Broken())
    assert cli._console_stdin() is False
    for windows in (True, False):
        monkeypatch.setattr(cli, "_WINDOWS", windows)
        assert cli._interactive() is False


@pytest.mark.skipif(sys.platform != "win32", reason="NUL as stdin is a Windows case")
@pytest.mark.parametrize("args", [["events", "prune"], ["approvals", "grant", "echo.say", "--tier", "T3"]])
def test_stdin_from_nul_is_refused_in_a_real_process(user_dirs, args) -> None:
    code = f"import sys; sys.argv = {['lfmap', *args]!r}; from lfmap_core.cli import main; main()"
    env = {**os.environ, "LOCALAPPDATA": str(user_dirs / "localappdata")}
    result = subprocess.run(
        [sys.executable, "-c", code], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=120
    )
    assert result.returncode == 1, result.stderr
    assert "Error [permission_denied]" in result.stderr
    assert not (user_dirs / "localappdata" / "lfmap" / "grants.json").exists()
