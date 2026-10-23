import os
import subprocess
import sys


def test_onnxruntime_loads_with_telemetry_off() -> None:
    code = (
        "import os, sys\n"
        "import lfmap_markitdown.backends.markitdown\n"
        "assert 'onnxruntime' in sys.modules\n"
        "print(os.environ.get('ORT_DISABLE_TELEMETRY'))"
    )
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "1"
