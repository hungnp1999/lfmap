"""Seam S1 (ADR-021, RT-02): no package or plugin depends on n8n, Open WebUI, NATS or Valkey/Redis.

Those products run beside LFMAP and talk to it only through its public MCP/REST interfaces, so they
can be replaced later. The guard checks Python imports in every workspace package and every
distribution in uv.lock, which also catches transitive dependencies.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIRS = [*ROOT.glob("packages/*"), *ROOT.glob("plugins/*")]

# top-level module -> product it would tie LFMAP to
FORBIDDEN_MODULES = {
    "nats": "NATS",
    "valkey": "Valkey",
    "redis": "Redis/Valkey",
    "hiredis": "Redis/Valkey",
    "open_webui": "Open WebUI",
    "n8n": "n8n",
    "n8n_sdk_python": "n8n",
}
# normalised distribution name -> product
FORBIDDEN_DISTRIBUTIONS = {
    "nats-py": "NATS",
    "nats-client": "NATS",
    "valkey": "Valkey",
    "valkey-glide": "Valkey",
    "redis": "Redis/Valkey",
    "hiredis": "Redis/Valkey",
    "open-webui": "Open WebUI",
    "n8n": "n8n",
    "n8n-sdk-python": "n8n",
}


def _module_names(tree: ast.AST) -> list[str]:
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if called in {"import_module", "__import__"} and isinstance(node.args[0].value, str):
                names.append(node.args[0].value)
    return names


def forbidden_imports(directories: list[Path]) -> list[str]:
    found = []
    for directory in directories:
        for path in sorted(directory.rglob("*.py")):
            if ".venv" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name in _module_names(tree):
                top = name.split(".")[0]
                if top in FORBIDDEN_MODULES:
                    found.append(f"{path.relative_to(directory.parent)}: {name} ({FORBIDDEN_MODULES[top]})")
    return found


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def forbidden_locked(lock_text: str) -> list[str]:
    names = re.findall(r'^name = "([^"]+)"', lock_text, flags=re.MULTILINE)
    products = {name: FORBIDDEN_DISTRIBUTIONS.get(_normalise(name)) for name in names}
    return [f"{name} ({product})" for name, product in products.items() if product]


def test_workspace_packages_found() -> None:
    names = {path.name for path in PACKAGE_DIRS}
    assert {"lfmap-core", "lfmap-knowledge", "lfmap-markitdown"} <= names


def test_no_forbidden_imports() -> None:
    assert forbidden_imports(PACKAGE_DIRS) == []


def test_no_forbidden_distribution_in_lock() -> None:
    assert forbidden_locked((ROOT / "uv.lock").read_text(encoding="utf-8")) == []


def test_guard_catches_forbidden_import(tmp_path: Path) -> None:
    plugin = tmp_path / "lfmap-bad"
    (plugin / "src").mkdir(parents=True)
    (plugin / "src" / "a.py").write_text("import nats.aio\nfrom open_webui import x\n", encoding="utf-8")
    (plugin / "src" / "b.py").write_text("import importlib\nimportlib.import_module('valkey')\n", encoding="utf-8")
    (plugin / "src" / "ok.py").write_text("import natsort\nfrom . import redis\n", encoding="utf-8")
    found = forbidden_imports([plugin])
    assert len(found) == 3
    assert any("nats.aio (NATS)" in line for line in found)


def test_guard_catches_forbidden_distribution() -> None:
    lock = '[[package]]\nname = "nats-py"\n\n[[package]]\nname = "Redis"\n\n[[package]]\nname = "natsort"\n'
    assert forbidden_locked(lock) == ["nats-py (NATS)", "Redis (Redis/Valkey)"]
