import os
import subprocess
import sys

import pytest

from lfmap_core.telemetry import TELEMETRY_OFF, disable_telemetry


def _env_after_import(env: dict[str, str]) -> str:
    code = "import os, lfmap_core; print(os.environ.get('ORT_DISABLE_TELEMETRY'))"
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def test_import_sets_onnxruntime_opt_out():
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    assert _env_after_import(env) == "1"


def test_import_keeps_user_value():
    env = dict(os.environ, ORT_DISABLE_TELEMETRY="0")
    assert _env_after_import(env) == "0"


def test_disable_telemetry_sets_missing_values(monkeypatch: pytest.MonkeyPatch):
    for name in TELEMETRY_OFF:
        monkeypatch.delenv(name, raising=False)
    disable_telemetry()
    for name, value in TELEMETRY_OFF.items():
        assert os.environ[name] == value
