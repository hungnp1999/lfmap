# Provenance register

Where the code of each LFMAP component comes from (ADR-021, research task RT-13). `docs/DEVELOPMENT_PROVENANCE.md` records *where each commit was made*; this file records *what each component is built from*. Together they support license compliance and the owner's authorship claims.

Third-party libraries used as dependencies, unchanged, are not listed here: `scripts/check_licenses.py` and the License Register cover them.

## Origin categories

| Origin | Meaning | What a row must name |
| --- | --- | --- |
| **In-house** | Written for LFMAP from the owner's specs. | — |
| **Derivative** | Copied or adapted from existing code under a permissive license (MIT, BSD, Apache-2.0), or from the owner's own earlier projects. | Source project, license, commit, files; copyright notices kept; for Apache-2.0 sources, changed files marked and `NOTICE` kept. |
| **Reference** | Behaviour, documentation or protocol of another product studied; none of its code read. Required for fair-code, AGPL, SSPL, BSL and trademark-restricted sources (n8n, Open WebUI, Windmill, Redis 8+). | Product and the public documents used, plus a clean-room log entry (below). |

A component can mix origins; then each part gets its own row.

## How the code is written

All components follow the same process (ADR-004, Roadmap 1.7, project governance of 2026-10-22): the owner decides the architecture and approves the ADRs, specs and task cards; Claude (Anthropic) in Claude Code sessions writes most code and tests from those specs; the local model qwen2.5-coder:14b (Apache-2.0 weights, run with Ollama) writes some small cards with strict tests; every change is reviewed and merged through a pull request with tests and CodeQL. The **Written by** column says which assistant produced a component. Commit trailers (`Co-Authored-By`, `Claude-Session`, `Dev-Environment`) and pull request bodies are the detailed record.

## Register

Checked at `606342b` (2026-10-23) by reading module headers, searching the tree for porting and copyright markers, and reading the merge commits. This is not a code-similarity scan.

### Packages

| Component | Path | Origin | Sources | Written by | Evidence |
| --- | --- | --- | --- | --- | --- |
| lfmap-core: `Tool`, `@operation`, `ToolError`, manifest, registry, runtime, Permission Manager, config, CLI and MCP adapters | `packages/lfmap-core/src/lfmap_core/{tool,errors,manifest,registry,runtime,permissions,config,cli,mcp_adapter}.py` | In-house | Uses Typer, MCP SDK, Pydantic as libraries | Claude Code | #1, #2, later #48 (per-call tiers) |
| lfmap-core: `ToolContext` data dir, settings, channel | `runtime.py`, `tool.py` | In-house | — | Claude | #3 |
| lfmap-core: approval tiers, grants, audit | `approval.py`, `grants.py` | In-house | — | Claude Code | #5, #6, #17 |
| lfmap-core: reads outside roots, `plugins health`, `config`, `audit tail` | `cli.py`, `permissions.py`, `config.py` | In-house | A qwen2.5-coder draft of TC-C1/C3/C5 was used as a reference only | Claude | #9 |
| lfmap-core: jobs, approval queue, `jobs doctor` | `jobs.py`, `approvals.py`, `jobs_doctor.py` | In-house | Windows Task Scheduler and `schtasks` documented behaviour | Claude Code | #25, #27, #29 |
| lfmap-core: onnxruntime telemetry opt-out | `telemetry.py` | In-house | onnxruntime documented `ORT_DISABLE_TELEMETRY` setting | Claude Code | #62 |
| lfmap-knowledge: skeleton, schemas, catalog store | `packages/lfmap-knowledge/src/lfmap_knowledge/{__init__,schemas,store}.py`, `lfmap.toml` | In-house | — | qwen2.5-coder:14b, review fixes by Claude | #18 |
| lfmap-knowledge: scanner | `scanner.py` | In-house | — | Claude (qwen draft rewritten in review) | #18 |
| lfmap-knowledge: extract, FTS, embed | `extract.py`, `fts.py`, `embed.py` | In-house | Ollama `/api/embed` HTTP API (MIT) as a protocol | qwen2.5-coder:14b via qwen-loop, reviewed and corrected by Claude; later changes to `embed.py` by Claude Code | #26; #45, #46, #51 |
| lfmap-knowledge: chunker | `chunker.py` | In-house | — | Claude (qwen run did not converge) | #26, #54 |
| lfmap-knowledge: vector store, catalog queries, edges, indexer, search, tool | `vectors.py`, `catalog.py`, `edges.py`, `indexer.py`, `search.py`, `tool.py` | In-house | LanceDB and SQLite FTS5 used as libraries; reciprocal rank fusion from the published method (Cormack, Clarke and Büttcher, 2009) | Claude Code | #31, #32, #33, #36, #38, #40, #44, #45, #46, #54 |

### Plugins

| Component | Path | Origin | Sources | Written by | Evidence |
| --- | --- | --- | --- | --- | --- |
| lfmap-echo | `plugins/lfmap-echo/` | In-house | — | Claude Code | #1 |
| lfmap-markitdown: tool, schemas, formats, MarkItDown backend | `plugins/lfmap-markitdown/src/lfmap_markitdown/{tool,schemas,formats,__init__}.py`, `backends/{base,markitdown}.py` | In-house | Calls Microsoft MarkItDown (MIT) as a library; no MarkItDown code copied | Claude Code | #10, #11, #12 |
| lfmap-markitdown: text-layer quality checks | `quality.py` | Derivative (own work) | MarkitdownTool `document_core.py` @ `923ff35`, MIT, © Nguyễn Phú Hùng (same author), relicensed Apache-2.0 here by the copyright holder | Claude Code (port) | #10; module docstring |
| lfmap-markitdown: OCR backend | `backends/ocr.py` | Derivative (own work) | MarkitdownTool `document_core.py` @ `923ff35`, as above; calls OCRmyPDF (MPL-2.0) and Tesseract (Apache-2.0) as programs | Claude Code (port) | #12; module docstring |
| lfmap-markitdown: Docling backend and heading levels | `backends/docling.py`, `headings.py` | In-house | Calls Docling (`docling-slim`, MIT) as a library; no Docling code copied | Claude Code | #69 |
| lfmap-markitdown: folder scan for export | `scan.py` | Derivative (own work) | MarkitdownTool `document_core.scan_folder` @ `923ff35`, as above | Claude Code (port) | #12; module docstring |
| lfmap-markitdown: test samples and quality tests | `tests/pdf_samples.py`, `tests/test_quality.py` | Derivative (own work) | MarkitdownTool `tests/` @ `923ff35`, as above | Claude Code (port) | #10, #13; module docstrings |
| lfmap-powershell | `plugins/lfmap-powershell/` | In-house | PowerShell 7 command-line behaviour (documented by Microsoft) | Claude Code | #43, #48 |

### Repository tooling

| Component | Path | Origin | Sources | Written by | Evidence |
| --- | --- | --- | --- | --- | --- |
| License check | `scripts/check_licenses.py` | In-house | — | Claude Code | #1, #10, #18, #43 |
| Job runner script | `scripts/Invoke-LfmapJob.ps1` | In-house | — | Claude Code | #25 |
| License watch, dependency share | `scripts/license_watch.py`, `scripts/dependency_share.py` | In-house | — | Claude Code | RT-01, RT-11 |
| CI, CodeQL, provenance check, commit hook | `.github/`, `.githooks/`, `.claude/hooks/` | In-house | GitHub Actions and CodeQL documented configuration | Claude Code | #1, #60 |

## Clean-room log

One entry each time a Reference source is studied for an in-house replacement (RT-04 Flows, RT-05 chat UI, ...): date, product, public documents read (URLs), who read them, and the spec written from them. The session that writes the code receives only that spec.

| Date | Product | Public material used | Spec produced |
| --- | --- | --- | --- |
| — | — | none yet | — |

## Keeping the register current

- A pull request that adds a package, plugin or module, or copies code from anywhere, adds or updates its row here in the same pull request.
- Copied code keeps its original copyright notice in the file header and names the source commit, as the markitdown ports above do.
- Before a release (trigger K4), re-run the marker search and compare the rows with `THIRD_PARTY_NOTICES` and the SBOM (RT-10).
