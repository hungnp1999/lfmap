# SBOM and third-party notices (RT-10)

Two files are generated, never edited by hand:

- `docs/sbom/lfmap.cdx.json`: CycloneDX 1.6 SBOM of LFMAP with its runtime dependencies, licenses, SHA-256 of each source distribution and the dependency graph.
- `THIRD_PARTY_NOTICES.md` (repository root): one row per runtime dependency (name, version, license, PyPI page) and one row per Derivative part of `docs/PROVENANCE.md`.

## Update

After changing `uv.lock`, a plugin dependency or a Derivative row of the provenance register:

```powershell
uv sync --frozen --no-dev
uv run --no-sync python scripts/generate_sbom.py
uv sync
```

Commit both files. CI runs `scripts/generate_sbom.py --check` in the runtime-only environment and fails when either file differs from what the script would write.

## What is included

- Everything reachable from the workspace root's runtime dependencies in `uv.lock`, including extras a dependency asks for (`markitdown[pdf]`). The dev group and the optional `ocr` and `docling` extras of `lfmap-markitdown` are not included: they are opt-in, and a build that ships them must regenerate with them (add the extras to the root dependencies first).
- Environment markers are ignored so the result is the same on every platform (Windows-only packages such as `pywin32` are listed). `NOT_SHIPPED` in the script names the reviewed exceptions (`httpx2-jsfetch`, Pyodide only).
- Licenses follow `scripts/check_licenses.py` (`License-Expression`, then classifiers). `LICENSE_OVERRIDES` pins the packages that are not installed on every platform, and `pypdfium2`, whose metadata adds a non-SPDX entry. A plain list such as `MIT, ISC` means the metadata does not say whether the licenses are alternatives or cumulative; check the package before release.
- The notices list licenses, not their texts. Each package keeps its license file in its `.dist-info` folder; the release bundle ships those next to `THIRD_PARTY_NOTICES.md`.

The output has no timestamp and the serial number is derived from the content, so rerunning gives identical files.
