"""run.py command line: gate command options reach the package, defaults stay unchanged."""

import os
from pathlib import Path

import run
from common.models import DEFAULT_PYTEST, DEFAULT_RUFF

CASES = Path(__file__).resolve().parent.parent / "cases"


def _package(tmp_path: Path, *extra: str):
    folder = tmp_path / "pkg"
    folder.mkdir(exist_ok=True)
    (folder / "package.toml").write_text('id = "p1"\ngoal = "g"\n', encoding="utf-8")
    args = run.parse_args(["run", "--variant", "plain", "--package", str(folder), *extra])
    return run.build_package(args)


def test_defaults_unchanged(tmp_path: Path) -> None:
    package, replay = _package(tmp_path)
    assert package.pytest_cmd == DEFAULT_PYTEST
    assert package.ruff_cmd == DEFAULT_RUFF
    assert replay is None


def test_options_default_to_none() -> None:
    args = run.parse_args(["run", "--variant", "plain", "--case", "x"])
    assert args.pytest_cmd is None
    assert args.ruff_cmd is None


def test_options_reach_package(tmp_path: Path) -> None:
    package, _ = _package(tmp_path, "--pytest-cmd", "uv run pytest -q", "--ruff-cmd", "uv run ruff")
    expected_pytest = ["uv", "run", "pytest", "-q"]
    assert package.pytest_cmd == expected_pytest
    assert package.ruff_cmd == ["uv", "run", "ruff"]


def test_only_pytest_option_leaves_ruff_default(tmp_path: Path) -> None:
    package, _ = _package(tmp_path, "--pytest-cmd", "py -m pytest")
    assert package.pytest_cmd == ["py", "-m", "pytest"]
    assert package.ruff_cmd == DEFAULT_RUFF


def test_quoted_argument_stays_one_token() -> None:
    if os.name == "nt":
        return
    assert run.split_cmd('python -m pytest -k "a b"') == ["python", "-m", "pytest", "-k", "a b"]


def test_case_source_applies_options() -> None:
    args = run.parse_args(
        ["run", "--variant", "plain", "--case", "K4-clean", "--cases-dir", str(CASES), "--ruff-cmd", "ruff"]
    )
    package, replay = run.build_package(args)
    assert package.ruff_cmd == ["ruff"]
    assert package.pytest_cmd == DEFAULT_PYTEST
    assert replay is not None and len(replay) == 1
