"""Generate the CycloneDX SBOM and THIRD_PARTY_NOTICES.md from the locked runtime dependencies (RT-10).

    uv sync --frozen --no-dev
    uv run --no-sync python scripts/generate_sbom.py            # write both files
    uv run --no-sync python scripts/generate_sbom.py --check    # exit 1 when a committed file is stale

The package set and versions come from `uv.lock`: everything reachable from the workspace root's runtime
dependencies, extras included, dev group and optional extras of the plugins (`ocr`, `docling`) excluded.
Environment markers are ignored so the result does not depend on the platform; `NOT_SHIPPED` lists the
reviewed exceptions. Licenses come from installed metadata (same rules as `check_licenses.py`) unless
`LICENSE_OVERRIDES` pins them, which is needed for packages that are not installed on every platform.
Output has no timestamp and a content-derived serial number, so it is reproducible.
"""

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import tomllib
import uuid
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "uv.lock"
PROVENANCE = ROOT / "docs" / "PROVENANCE.md"
SBOM_PATH = ROOT / "docs" / "sbom" / "lfmap.cdx.json"
NOTICES_PATH = ROOT / "THIRD_PARTY_NOTICES.md"
ROOT_PACKAGE = "lfmap-workspace"
WORKSPACE_LICENSE = "Apache-2.0"  # ADR-010
# Reachable through uv.lock but never installed for a shipped build.
NOT_SHIPPED = {"httpx2-jsfetch": "only for sys_platform == 'emscripten' (Pyodide)"}
# Pinned because the package is not installed on every platform, so metadata cannot decide.
LICENSE_OVERRIDES = {
    "colorama": "BSD-3-Clause",
    "pyreadline3": "BSD-3-Clause",
    "pypdfium2": "Apache-2.0 OR BSD-3-Clause",  # metadata also lists 'dependency licenses' (bundled PDFium, BSD-style)
    "pywin32": "PSF-2.0",
    "tzdata": "Apache-2.0",
}

_spec = importlib.util.spec_from_file_location("check_licenses", Path(__file__).with_name("check_licenses.py"))
check_licenses = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_licenses)


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_lock(path: Path = LOCK) -> dict[str, dict]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {normalize(pkg["name"]): pkg for pkg in data["package"]}


def _edges(pkg: dict, extras: set[str]) -> list[tuple[str, set[str]]]:
    """Dependencies of `pkg` (plus the chosen extras) as (normalized name, extras wanted from that dependency)."""
    raw = list(pkg.get("dependencies", []))
    for extra in sorted(extras):
        raw += pkg.get("optional-dependencies", {}).get(extra, [])
    return [(normalize(e["name"]), set(e.get("extra", []))) for e in raw]


def runtime_closure(packages: dict[str, dict], root: str = ROOT_PACKAGE) -> dict[str, list[str]]:
    """Return name -> sorted runtime dependency names for everything reachable from `root`.

    An edge naming extras (`markitdown[pdf]`) adds that extra's dependencies to the target package.
    """
    extras: dict[str, set[str]] = {root: set()}
    todo = [root]
    while todo:
        name = todo.pop()
        for dep, wanted in _edges(packages[name], extras[name]):
            if dep in NOT_SHIPPED or dep == name:
                continue
            if dep not in extras:
                extras[dep] = set(wanted)
                todo.append(dep)
            elif not wanted <= extras[dep]:
                extras[dep] |= wanted
                todo.append(dep)
    return {
        name: sorted({dep for dep, _ in _edges(packages[name], extras[name])} - NOT_SHIPPED.keys() - {name})
        for name in extras
    }


def declared_license(name: str) -> str:
    """An SPDX expression when metadata gives one; otherwise the declared names joined with ', ' (unspecified)."""
    if name in LICENSE_OVERRIDES:
        return LICENSE_OVERRIDES[name]
    try:
        dist = distribution(name)
    except PackageNotFoundError:
        raise SystemExit(
            f"{name}: not installed and no LICENSE_OVERRIDES entry; run `uv sync --frozen --no-dev` first"
        ) from None
    expression = dist.metadata.get("License-Expression")
    if expression:
        return expression
    return ", ".join(sorted(check_licenses.licenses_of(dist))) or "NOASSERTION"


def sbom_licenses(declared: str) -> list[dict]:
    if re.search(r"\s(?:AND|OR|WITH)\s", declared):
        return [{"expression": declared}]
    return [
        {"license": {"id": part} if re.fullmatch(r"[A-Za-z0-9.+-]+", part) else {"name": part}}
        for part in declared.split(", ")
    ]


def derived_parts(path: Path = PROVENANCE) -> list[tuple[str, str, str]]:
    """Rows of the provenance register whose origin is Derivative: (component, path, sources)."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 4 and cells[2].startswith("Derivative"):
            rows.append((cells[0], cells[1].strip("`"), cells[3]))
    return rows


def components(packages: dict[str, dict], graph: dict[str, list[str]]) -> list[dict]:
    result = []
    for name in sorted(graph):
        if name == ROOT_PACKAGE:
            continue
        pkg = packages[name]
        first_party = "virtual" in pkg["source"] or "editable" in pkg["source"] or name in check_licenses.WORKSPACE
        license_id = WORKSPACE_LICENSE if first_party else declared_license(name)
        result.append(
            {"name": name, "version": pkg["version"], "license": license_id, "first_party": first_party, "pkg": pkg}
        )
    return result


def build_sbom(packages: dict[str, dict], graph: dict[str, list[str]]) -> dict:
    items = components(packages, graph)

    def ref(name: str) -> str:
        return f"pkg:pypi/{name}@{packages[name]['version']}"

    entries = []
    for item in items:
        entry: dict = {
            "type": "application" if item["name"] == "lfmap-core" else "library",
            "bom-ref": ref(item["name"]),
            "name": item["name"],
            "version": item["version"],
            "purl": ref(item["name"]),
            "scope": "required",
        }
        if item["license"] != "NOASSERTION":
            entry["licenses"] = sbom_licenses(item["license"])
        sdist = item["pkg"].get("sdist", {}).get("hash", "")
        if sdist.startswith("sha256:"):
            entry["hashes"] = [{"alg": "SHA-256", "content": sdist.removeprefix("sha256:")}]
        entries.append(entry)
    body = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": "lfmap",
                "name": "lfmap",
                "licenses": [{"license": {"id": WORKSPACE_LICENSE}}],
            },
            "tools": {"components": [{"type": "application", "name": "scripts/generate_sbom.py"}]},
        },
        "components": entries,
        "dependencies": [
            {"ref": "lfmap", "dependsOn": [ref(d) for d in graph[ROOT_PACKAGE]]},
            *(
                {"ref": ref(name), "dependsOn": [ref(d) for d in graph[name]]}
                for name in sorted(graph)
                if name != ROOT_PACKAGE
            ),
        ],
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {**body, "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, digest)}"}


def render_sbom(sbom: dict) -> str:
    return json.dumps(sbom, indent=2, ensure_ascii=False) + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_notices(items: list[dict], derived: list[tuple[str, str, str]]) -> str:
    lines = [
        "# Third-party notices",
        "",
        "Generated by `scripts/generate_sbom.py` from `uv.lock` and `docs/PROVENANCE.md`. Do not edit by hand;",
        "run `uv run --no-sync python scripts/generate_sbom.py` and commit the result. The CycloneDX SBOM is",
        "`docs/sbom/lfmap.cdx.json`. LFMAP itself is Apache-2.0 (see `LICENSE`).",
        "",
        "## Runtime dependencies",
        "",
        "Each package keeps its own license text, shipped in its `.dist-info` folder; the release bundle must",
        "include those files next to this list.",
        "",
        "| Package | Version | License | Source |",
        "| --- | --- | --- | --- |",
    ]
    for item in items:
        if item["first_party"]:
            continue
        name = item["name"]
        lines.append(f"| {name} | {item['version']} | {_cell(item['license'])} | https://pypi.org/project/{name}/ |")
    lines += [
        "",
        "## Derived code",
        "",
        "Code adapted from existing sources (register: `docs/PROVENANCE.md`). Original copyright notices stay in",
        "the file headers.",
        "",
        "| Component | Path | Source and license |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {_cell(c)} | `{_cell(p)}` | {_cell(s)} |" for c, p, s in derived]
    return "\n".join(lines) + "\n"


def generate() -> tuple[str, str]:
    packages = load_lock()
    graph = runtime_closure(packages)
    items = components(packages, graph)
    return render_sbom(build_sbom(packages, graph)), render_notices(items, derived_parts())


def _shown(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when the committed files differ")
    args = parser.parse_args(argv)
    sbom, notices = generate()
    targets = {SBOM_PATH: sbom, NOTICES_PATH: notices}
    if args.check:
        stale = [p for p, text in targets.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        for path in stale:
            print(f"STALE {_shown(path)}: run `uv run --no-sync python scripts/generate_sbom.py`")
        return 1 if stale else 0
    for path, text in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {_shown(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
