"""Fail when an installed runtime dependency has a license outside the plugins' allowed lists.

Run in an environment synced without dev tools: `uv sync --no-dev` then
`uv run --no-sync python scripts/check_licenses.py`. Allowed licenses are the union of
`[dependencies.licenses].allowed` in every plugin manifest plus the extra entries below.
"""

import re
import sys
import tomllib
from importlib.metadata import Distribution, distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Workspace packages are Apache-2.0 by ADR-010; listed here so a missing metadata field cannot hide them.
WORKSPACE = {"lfmap-core", "lfmap-echo", "lfmap-workspace"}
# Reviewed exceptions: name -> reason. Keep in sync with 04_License_Register.md.
EXCEPTIONS: dict[str, str] = {
    "cffi": "MIT-0 (MIT without the attribution clause), more permissive than MIT",
}

ALIASES = {
    "MIT LICENSE": "MIT",
    "APACHE SOFTWARE LICENSE": "Apache-2.0",
    "APACHE LICENSE 2.0": "Apache-2.0",
    "APACHE 2.0": "Apache-2.0",
    "APACHE-2.0": "Apache-2.0",
    "BSD LICENSE": "BSD-3-Clause",
    "BSD": "BSD-3-Clause",
    "3-CLAUSE BSD LICENSE": "BSD-3-Clause",
    "PYTHON SOFTWARE FOUNDATION LICENSE": "PSF-2.0",
    "ISC LICENSE (ISCL)": "ISC",
    "MOZILLA PUBLIC LICENSE 2.0 (MPL 2.0)": "MPL-2.0",
}


def allowed_licenses() -> set[str]:
    allowed: set[str] = set()
    for manifest in ROOT.glob("plugins/*/src/*/lfmap.toml"):
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        allowed.update(data.get("dependencies", {}).get("licenses", {}).get("allowed", []))
    return allowed


def licenses_of(dist: Distribution) -> set[str]:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return {part for part in re.split(r"\s+(?:OR|AND)\s+|[()]", expression) if part.strip()}
    found = {c.rsplit("::", 1)[1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")}
    found.discard("OSI Approved")
    if not found and meta.get("License") and len(meta["License"]) < 60:
        found = {meta["License"].strip()}
    return {ALIASES.get(name.upper(), name) for name in found}


def main() -> int:
    allowed = allowed_licenses()
    failures = 0
    for dist in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        if name.lower() in WORKSPACE or name.lower() in EXCEPTIONS:
            continue
        found = licenses_of(dist)
        expression = dist.metadata.get("License-Expression") or ""
        if " AND " in expression and not found <= allowed:
            print(f"FAIL  {name}: {expression} (every part of an AND expression must be allowed)")
            failures += 1
        elif not found:
            print(f"WARN  {name}: license not declared in metadata, check manually")
        elif found & allowed:
            print(f"ok    {name}: {', '.join(sorted(found))}")
        else:
            print(f"FAIL  {name}: {', '.join(sorted(found))}")
            failures += 1
    print(f"Allowed: {', '.join(sorted(allowed))}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
