import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("generate_sbom", Path(__file__).parents[1] / "generate_sbom.py")
gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gs)

LOCK = """
version = 1

[[package]]
name = "lfmap-workspace"
version = "0.0.0"
source = { virtual = "." }
dependencies = [{ name = "app" }, { name = "lib-with-extra", extra = ["more"] }]

[package.dev-dependencies]
dev = [{ name = "pytest" }]

[[package]]
name = "app"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "Leaf_Pkg" }, { name = "httpx2-jsfetch", marker = "sys_platform == 'emscripten'" }]
sdist = { url = "https://x/app.tar.gz", hash = "sha256:abc123" }

[[package]]
name = "lib-with-extra"
version = "2.0"
source = { registry = "https://pypi.org/simple" }

[package.optional-dependencies]
more = [{ name = "extra-dep" }]
other = [{ name = "never-used" }]

[[package]]
name = "leaf-pkg"
version = "3.1"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "extra-dep"
version = "4"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "never-used"
version = "9"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pytest"
version = "9"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "httpx2-jsfetch"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
"""


@pytest.fixture
def packages(tmp_path, monkeypatch):
    lock = tmp_path / "uv.lock"
    lock.write_text(LOCK, encoding="utf-8")
    monkeypatch.setattr(
        gs,
        "LICENSE_OVERRIDES",
        {"app": "MIT", "leaf-pkg": "Apache-2.0 OR MIT", "lib-with-extra": "BSD-3-Clause", "extra-dep": "MIT, ISC"},
    )
    return gs.load_lock(lock)


def test_closure_follows_extras_and_skips_dev_optional_and_not_shipped(packages):
    graph = gs.runtime_closure(packages)
    assert set(graph) == {"lfmap-workspace", "app", "lib-with-extra", "leaf-pkg", "extra-dep"}
    assert graph["app"] == ["leaf-pkg"]
    assert graph["lib-with-extra"] == ["extra-dep"]


def test_sbom_is_cyclonedx_with_licenses_hashes_and_graph(packages):
    graph = gs.runtime_closure(packages)
    sbom = gs.build_sbom(packages, graph)
    assert sbom["bomFormat"] == "CycloneDX" and sbom["specVersion"] == "1.6"
    by_name = {c["name"]: c for c in sbom["components"]}
    assert set(by_name) == {"app", "lib-with-extra", "leaf-pkg", "extra-dep"}
    assert by_name["app"]["purl"] == "pkg:pypi/app@1.0"
    assert by_name["app"]["hashes"] == [{"alg": "SHA-256", "content": "abc123"}]
    assert by_name["leaf-pkg"]["licenses"] == [{"expression": "Apache-2.0 OR MIT"}]
    assert by_name["extra-dep"]["licenses"] == [{"license": {"id": "MIT"}}, {"license": {"id": "ISC"}}]
    root = next(d for d in sbom["dependencies"] if d["ref"] == "lfmap")
    assert root["dependsOn"] == ["pkg:pypi/app@1.0", "pkg:pypi/lib-with-extra@2.0"]
    assert sbom["serialNumber"].startswith("urn:uuid:")


def test_output_is_reproducible(packages):
    graph = gs.runtime_closure(packages)
    first = gs.render_sbom(gs.build_sbom(packages, graph))
    second = gs.render_sbom(gs.build_sbom(packages, graph))
    assert first == second
    assert json.loads(first)["serialNumber"] == json.loads(second)["serialNumber"]


def test_notices_list_every_dependency_and_derived_part(packages):
    graph = gs.runtime_closure(packages)
    text = gs.render_notices(gs.components(packages, graph), [("comp", "a.py", "Src, MIT")])
    for name in ("app", "lib-with-extra", "leaf-pkg", "extra-dep"):
        assert f"| {name} |" in text
    assert "never-used" not in text and "pytest" not in text
    assert "| comp | `a.py` | Src, MIT |" in text


def test_derived_parts_reads_only_derivative_rows(tmp_path):
    register = tmp_path / "P.md"
    register.write_text(
        "| Component | Path | Origin | Sources | Written by | Evidence |\n| --- | --- | --- | --- | --- | --- |\n"
        "| a | `a.py` | In-house | — | x | #1 |\n"
        "| b | `b.py` | Derivative (own work) | Src @ abc, MIT | x | #2 |\n"
        "| c | `c.py` | Reference | Product | x | #3 |\n",
        encoding="utf-8",
    )
    assert gs.derived_parts(register) == [("b", "b.py", "Src @ abc, MIT")]


def test_committed_files_cover_the_real_register_and_lock():
    packages = gs.load_lock()
    graph = gs.runtime_closure(packages)
    notices = gs.NOTICES_PATH.read_text(encoding="utf-8")
    for name in graph:
        if name not in gs.check_licenses.WORKSPACE and name != gs.ROOT_PACKAGE:
            assert f"| {name} |" in notices
    for _, path, _ in gs.derived_parts():
        assert f"`{path}`" in notices
    committed = json.loads(gs.SBOM_PATH.read_text(encoding="utf-8"))
    assert {c["name"] for c in committed["components"]} == set(graph) - {gs.ROOT_PACKAGE}


def test_check_mode_flags_stale_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gs, "SBOM_PATH", tmp_path / "sbom.json")
    monkeypatch.setattr(gs, "NOTICES_PATH", tmp_path / "N.md")
    monkeypatch.setattr(gs, "generate", lambda: ("{}\n", "notices\n"))
    assert gs.main(["--check"]) == 1  # missing files
    assert gs.main([]) == 0
    assert gs.main(["--check"]) == 0
    (tmp_path / "N.md").write_text("old\n", encoding="utf-8")
    assert gs.main(["--check"]) == 1
    assert "STALE" in capsys.readouterr().out
