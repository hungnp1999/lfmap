"""Turn off third-party telemetry before plugins import their dependencies."""

import os

# onnxruntime 1.29+ official builds send 1DS telemetry to Microsoft unless this is set
# before the runtime initializes (onnxruntime docs/Privacy.md).
TELEMETRY_OFF: dict[str, str] = {"ORT_DISABLE_TELEMETRY": "1"}


def disable_telemetry() -> None:
    """Set each opt-out variable, keeping any value the user already set."""
    for name, value in TELEMETRY_OFF.items():
        os.environ.setdefault(name, value)
