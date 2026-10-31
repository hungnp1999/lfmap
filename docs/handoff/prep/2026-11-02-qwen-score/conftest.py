"""Run the frozen scoring tests against the reference solution.

Registers reference_scoring.py as `common.scoring`, only while pytest runs in this folder. To run the same test
files against the real module, pass --noconftest from spikes/2a1-framework (see the card).
"""

import importlib.util
import sys
import types
from pathlib import Path

REFERENCE = Path(__file__).resolve().parent / "reference_scoring.py"


def _register() -> None:
    package = types.ModuleType("common")
    package.__path__ = []
    spec = importlib.util.spec_from_file_location("common.scoring", REFERENCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["common"] = package
    sys.modules["common.scoring"] = module
    package.scoring = module
    spec.loader.exec_module(module)


_register()
