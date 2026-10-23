# G0 baselines: license watch, import guard, dependency share, provenance

- Date: 2026-10-23 · Research plan: `docs/research/2026-10-23-commercial-replacements.md` (tasks RT-01, RT-02, RT-11, RT-13, stage G0) · ADR-021
- Environment: Claude Code cloud session (Linux). Nothing here needed the owner's PC.

## RT-01 License watch

`scripts/license_watch.py` (standard library only) fetches 11 license files from the default branch of each upstream repository, hashes them with SHA-256 and compares them with `docs/research/license-watch.json`. Exit 1 means a text changed (trigger K1: review within a week, then `--update`); exit 2 means a fetch failed. The `License watch` workflow runs it on the 1st of every month and can be started by hand; a failed run is the alert.

Baseline (2026-10-23), with what the text says today:

| Name | File | License as read |
| --- | --- | --- |
| n8n | `LICENSE.md`, `LICENSE_EE.md` | Sustainable Use License; Enterprise License for `.ee` files |
| open-webui | `LICENSE` | "Open WebUI License": BSD-3-Clause plus a branding clause (no removal of "Open WebUI" branding above 50 end users in 30 days without permission or an enterprise license), CLA, `LICENSE_HISTORY` for older code |
| nats-server | `LICENSE` | Apache-2.0 |
| valkey | `COPYING` | BSD-3-Clause |
| ollama | `LICENSE` | MIT (repository; the desktop app's terms are not covered by this file) |
| librechat | `LICENSE` | MIT |
| activepieces | `LICENSE` | MIT, except `packages/ee/` and `packages/server/api/src/app/ee`, which have their own license |
| node-red | `LICENSE` | Apache-2.0 |
| markitdown | `LICENSE` | MIT |
| lancedb | `LICENSE` | Apache-2.0 |

This settles two "to verify" notes of the plan: Ollama's repository is MIT, and Activepieces is MIT outside its `ee` folders, so only the core outside those folders may be read or derived from (RT-04).

Limits: the script sees the main license file only. A license change announced elsewhere (a new `LICENSE_HISTORY` entry, terms on a website, a relicensed sub-folder) needs a human reading the release notes when K1 fires.

## RT-02 Import guard (seam S1)

`packages/lfmap-core/tests/test_import_guard.py` fails when any package or plugin imports a NATS, Valkey/Redis, Open WebUI or n8n client module (plain imports, `from` imports, `importlib.import_module` and `__import__` with a literal name), or when `uv.lock` contains one of their client distributions, which also catches transitive dependencies. Two self-tests prove the guard turns red on such an import or lock entry. Today: none found.

## RT-11 Dependency share

`scripts/dependency_share.py` runs in an environment synced with `uv sync --no-dev`. CI prints it on Windows after the license check, so every pull request shows the numbers for the shipping platform. Baseline in `docs/research/dependency-share-baseline.json`:

| Metric | Baseline (Linux x86_64, Python 3.12, 2026-10-23) |
| --- | --- |
| 1. Third-party runtime distributions | 76 |
| 2. Installed third-party code against LFMAP source | 622 MiB against 0.25 MiB (third-party share 99.96 %) |
| 3. Background services besides the model runtime | 0 (only Ollama, optional, for embeddings) |

What each direct dependency brings (bytes that leave the install if it is dropped):

| Direct dependency | Distributions | Size |
| --- | --- | --- |
| lancedb (`lfmap-knowledge`) | 6 | 342 MiB (lancedb 179, pyarrow 160) |
| markitdown + extras (`lfmap-markitdown`) | 29 | 181 MiB (includes magika, onnxruntime, sympy, pandas, lxml, pdfminer) |
| typer (`lfmap-core`) | 7 | 6 MiB |
| mcp (`lfmap-core`) | 18 | 6 MiB |

Reading:

- The byte share will stay near 100 % for any Python product that ships compiled libraries; track its trend and metric 1, not the absolute value.
- LanceDB is more than half of the install. The plan already watches sqlite-vec as the way to drop it; this baseline shows that switch is the single largest reduction available.
- `onnxruntime` already arrives through `markitdown` → `magika` (file type detection), not only through Docling. On Windows `magika` pins `onnxruntime<=1.20.1`, so the telemetry found by the Docling spike (1.29+) does not apply while that pin holds; the `ORT_DISABLE_TELEMETRY=1` task should cover the markitdown plugin too, for the day the pin is lifted.
- Windows numbers differ (for example `pywin32`); compare releases on the same platform, using the CI log.

## RT-13 Provenance register

`docs/PROVENANCE.md`: origin categories (in-house, derivative, reference with clean-room), one row per module group of every package and plugin and the repository tooling, the assistant that wrote it, and the pull requests that prove it. Result: everything is in-house except four markitdown plugin files ported from MarkitdownTool @ `923ff35`, which is the owner's own MIT project, so no third-party code is copied today. The clean-room log is empty: no reference source has been studied yet. The owner's copyright dossier can cite this file and `docs/DEVELOPMENT_PROVENANCE.md`.
