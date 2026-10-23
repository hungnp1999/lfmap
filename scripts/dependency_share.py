"""Measure how much of an LFMAP install is third-party software (RT-11, ADR-021).

Run in an environment synced without dev tools, like `check_licenses.py`:
`uv sync --no-dev` then `uv run --no-sync python scripts/dependency_share.py [--json] [--write PATH]`.

Three numbers, compared at every release:
1. third-party runtime distributions installed;
2. installed bytes of those distributions against the bytes of LFMAP's own source (`src/` of every
   package and plugin, tests excluded);
3. background services LFMAP needs beside itself, other than the model runtime (target: 0).
"""

import argparse
import json
import platform
import re
import sys
from datetime import UTC, datetime
from importlib.metadata import Distribution, distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = {"lfmap-core", "lfmap-echo", "lfmap-knowledge", "lfmap-markitdown", "lfmap-powershell", "lfmap-workspace"}
# Services a user must run beside LFMAP: name -> (kind, who needs it). Update when a plugin adds one.
SERVICES: dict[str, tuple[str, str]] = {
    "ollama": ("model-runtime", "lfmap-knowledge embeddings; optional, keyword search works without it"),
}


def installed_bytes(dist: Distribution) -> int:
    total = 0
    for file in dist.files or []:
        path = Path(str(dist.locate_file(file)))
        if path.is_file():
            total += path.stat().st_size
    return total


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements(dist: Distribution, extras: set[str]) -> list[tuple[str, set[str]]]:
    """Requirements of `dist` for the given extras. Markers other than `extra` are not evaluated;
    a requirement counts when it is installed, which matches the platform that ran the sync."""
    found = []
    for line in dist.requires or []:
        spec, _, marker = line.partition(";")
        match = re.match(r"\s*([A-Za-z0-9._-]+)\s*(?:\[([^\]]*)\])?", spec)
        extra = re.search(r"extra\s*==\s*['\"]([^'\"]+)['\"]", marker)
        if match and (extra is None or extra.group(1) in extras):
            found.append(
                (_normalise(match.group(1)), {e.strip() for e in (match.group(2) or "").split(",") if e.strip()})
            )
    return found


def _closure(roots: list[tuple[str, set[str]]], by_name: dict[str, Distribution]) -> set[str]:
    seen: set[tuple[str, frozenset[str]]] = set()
    stack = list(roots)
    while stack:
        name, extras = stack.pop()
        if name not in by_name or (name, frozenset(extras)) in seen:
            continue
        seen.add((name, frozenset(extras)))
        stack.extend(_requirements(by_name[name], extras))
    return {name for name, _ in seen}


def removable_bytes(dists: list[Distribution]) -> list[dict]:
    """Bytes that would leave the install if one direct dependency of the workspace were dropped."""
    by_name = {_normalise(d.metadata["Name"]): d for d in dists}
    sizes = {name: installed_bytes(d) for name, d in by_name.items()}
    workspace = {name for name in by_name if name in WORKSPACE}
    direct = [r for name in sorted(workspace) for r in _requirements(by_name[name], set()) if r[0] not in WORKSPACE]
    everything = _closure(direct, by_name)
    result = []
    for name in sorted({r[0] for r in direct}):
        rest = _closure([r for r in direct if r[0] != name], by_name)
        gone = everything - rest
        result.append({"name": name, "distributions": len(gone), "bytes": sum(sizes[n] for n in gone)})
    return sorted(result, key=lambda item: -item["bytes"])


def own_source_bytes(root: Path = ROOT) -> int:
    sources = [*root.glob("packages/*/src"), *root.glob("plugins/*/src")]
    return sum(path.stat().st_size for src in sources for path in src.rglob("*") if path.is_file())


def measure(dists: list[Distribution], own_bytes: int) -> dict:
    third_party = sorted(
        ((d.metadata["Name"], installed_bytes(d)) for d in dists if d.metadata["Name"].lower() not in WORKSPACE),
        key=lambda item: -item[1],
    )
    third_bytes = sum(size for _, size in third_party)
    services = [name for name, (kind, _) in SERVICES.items() if kind != "model-runtime"]
    return {
        "measured": datetime.now(UTC).strftime("%Y-%m-%d"),
        "platform": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "third_party_distributions": len(third_party),
        "third_party_bytes": third_bytes,
        "lfmap_source_bytes": own_bytes,
        "third_party_share": round(third_bytes / (third_bytes + own_bytes), 4) if third_bytes + own_bytes else 0.0,
        "services_besides_model_runtime": len(services),
        "services": {name: {"kind": kind, "used_by": used_by} for name, (kind, used_by) in SERVICES.items()},
        "largest": [{"name": name, "bytes": size} for name, size in third_party[:15]],
        "removable_by_direct_dependency": removable_bytes(dists),
    }


def report(result: dict) -> str:
    mb = 1024 * 1024
    lines = [
        f"Platform: {result['platform']}",
        f"1. Third-party runtime distributions: {result['third_party_distributions']}",
        f"2. Installed third-party code: {result['third_party_bytes'] / mb:.1f} MiB; LFMAP source: "
        f"{result['lfmap_source_bytes'] / mb:.2f} MiB; third-party share: {result['third_party_share']:.2%}",
        f"3. Background services besides the model runtime: {result['services_besides_model_runtime']} "
        f"(all services: {', '.join(result['services']) or 'none'})",
        "Largest third-party distributions:",
    ]
    lines += [f"   {item['bytes'] / mb:8.1f} MiB  {item['name']}" for item in result["largest"]]
    lines.append("Removed with each direct dependency (distributions, size):")
    lines += [
        f"   {item['bytes'] / mb:8.1f} MiB  {item['name']} ({item['distributions']})"
        for item in result["removable_by_direct_dependency"]
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--write", type=Path, help="also write the JSON result to this file")
    args = parser.parse_args(argv)
    result = measure(list(distributions()), own_source_bytes())
    text = json.dumps(result, indent=2) + "\n"
    print(text if args.json else report(result))
    if args.write:
        args.write.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
