# Spike: Docling backend (Roadmap 1.2)

Version 0.1 · 2026-10-23 · Status: research spike, no product code. Recommendation: **conditional GO** (section 9).

Spike scripts live outside the repo, in the project files folder `lfmap-core/docling-1.2/` (`make_pdfs.py`, `compare.py`, `Run-DoclingSpike.ps1`, MarkItDown baseline output).

## 1. Question

Should the `markitdown` plugin get an optional `--backend docling` (Roadmap 1.2), mainly to fix L21 (PDFs produce no Markdown headings, so `heading_path` is empty in knowledge citations) and to read tables and multi-column layouts better? Can it stay local-first, license-clean and solo-maintainable?

## 2. Current version and packaging (PyPI, 2026-10-23)

| Item | Value |
|---|---|
| `docling` | 2.142.0, MIT. A meta-package: it only requires `docling-slim[standard]==2.142.0`. |
| `docling-slim` | 2.142.0, MIT. Modular: the core has 9 small dependencies; everything else is an extra (`format-pdf`, `models-local`, `convert-core`, `feat-ocr-*`, `cli`, ...). |
| Core libraries | `docling-core` 2.104.0, `docling-parse` 7.23.0, `docling-ibm-models` 4.0.4, all MIT. |
| Release cadence | 2.0.0 to 2.142.0 in about two years: several releases a week. Pin exactly. |

Resolved for Python 3.12 (uv, `--python-platform`):

| Install | Wheels | Download | Notes |
|---|---|---|---|
| `docling==2.142.0`, Windows x64 | 105 | 339 MB | `torch` 2.14.1 CPU wheel 124 MB, `opencv-python-headless` 44 MB, `scipy` 37 MB, `rapidocr` 27 MB |
| `docling-slim[format-pdf,models-local,convert-core]`, Windows x64 | 74 | 261 MB | no OpenCV, RapidOCR, Office/email/tree-sitter parsers |
| `docling==2.142.0`, Linux x64 (PyPI) | 122 | 3.4 GB | PyPI's Linux `torch` pulls the CUDA 13 stack (cuDNN 651 MB, cuBLAS 543 MB, ...); installed venv 6.0 GB, the slim set 5.7 GB |

On Windows the PyPI `torch` wheel is CPU-only, so the default install stays small. GPU use on the RTX 5060 Ti would need the CUDA wheel from `download.pytorch.org` (about 3 GB more); not needed for document conversion volumes.

Combined resolution with the current plugin dependencies (`markitdown[...]==0.1.8`, `pypdfium2`, `ocrmypdf==17.13.0`, `pillow`, `lancedb`) succeeds without conflicts; `magika` stays 0.6.3 and `onnxruntime` 1.20.1, as in today's lock.

## 3. Models and network egress

Docling's standard PDF pipeline needs model weights, which it downloads from Hugging Face on first use unless `artifacts_path` points to a local copy:

| Model | Source | License (model card) | Used for |
|---|---|---|---|
| Layout "heron" (RT-DETRv2, 43M parameters) | `huggingface.co/docling-project/docling-layout-heron` (revision `main`) | Apache-2.0 | page layout: headings, paragraphs, tables, figures |
| TableFormer (accurate/fast) | `huggingface.co/docling-project/docling-models` (revision `v2.3.0`) | CDLA-Permissive-2.0 (weights) and Apache-2.0 | table structure |
| RapidOCR PP-OCR ONNX models | `www.modelscope.cn/models/RapidAI/RapidOCR/...` (URLs in `rapidocr/default_models.yaml`) | Apache-2.0 | OCR when RapidOCR is installed (the default `OcrAutoOptions` tries ocrmac on macOS, Nemotron on Linux, then RapidOCR with onnxruntime, EasyOCR, RapidOCR with torch) |

Observed in the cloud container (egress to Hugging Face is blocked there):

- A default `DocumentConverter().convert(pdf)` calls `huggingface.co` at conversion time and fails with `httpx.ProxyError 403`. It does not fall back to text-only extraction.
- With `PdfPipelineOptions(artifacts_path=...)` pointing to a folder without the models, Docling raises `RuntimeError` ("must point to a folder containing all models") and makes **no** network call. That is the switch for offline operation; `HF_HUB_OFFLINE=1` is a second guard.
- `docling-tools models download layout tableformer -o <dir>` fetches the weights once (default destination `~/.cache/docling/models`).
- `PdfPipelineOptions.enable_remote_services` exists and defaults to `False`; keep it so.
- RapidOCR would download its models from `modelscope.cn` on first OCR. Docling also supports `TesseractCliOcrOptions(lang=[...], tesseract_cmd=...)`, which reuses the Tesseract the `ocr` extra already needs (including `vie`). Use that and keep RapidOCR out.

Model sizes on disk could not be measured here (Hugging Face blocked); the DIEP-ANH run records them (section 8).

### Side finding: onnxruntime telemetry

Not Docling itself, but found while testing: `onnxruntime` 1.31.0 (Linux wheel) contains a Microsoft 1DS telemetry client. A bare `import onnxruntime` followed by 20 s idle tried three times to connect to `mobile.events.data.microsoft.com:443`. `onnxruntime` 1.20.1 (the version in today's `uv.lock`, via `magika` 0.6.3) has no such client and made no attempt. With `ORT_DISABLE_TELEMETRY=1` set before import, 1.31.0 made no attempt either. Third-party reports say the default changed around 1.29. Today lfmap is not affected, but any upgrade that lifts `onnxruntime` (for example `magika` 1.x, which the Knowledge spec mentions) would add silent egress. Recommendation: set `ORT_DISABLE_TELEMETRY=1` in the process environment early in core (before plugins import), and add a lock check or test that flags `onnxruntime >= 1.29`. Separate small task, not part of 1.2. Done: `lfmap_core` sets it on import (`lfmap_core/telemetry.py`).

## 4. Licenses (runtime dependencies)

All 105 packages of the full `docling` install on Windows were checked against PyPI metadata. No GPL, LGPL, AGPL, SSPL or fair-code license. Against `scripts/check_licenses.py` with the `markitdown` manifest's `allowed` list, the slim install adds two packages that need a reviewed exception:

| Package | License expression | Why the checker would fail | Proposed handling |
|---|---|---|---|
| `torch` 2.14.1 | `Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT` | `BSL-1.0` and the `WITH LLVM-exception` term are not in `allowed` | EXCEPTIONS entry: every part is permissive (BSL-1.0 is Boost, permissive). Check the bundled third-party notices of the Windows wheel before shipping. |
| `regex` 2026.9.29 | `Apache-2.0 AND CNRI-Python` | `CNRI-Python` not in `allowed` | EXCEPTIONS entry: CNRI-Python is the permissive Python 1.6 license. |

Already covered: `numpy`, `pillow`, `pypdfium2` (existing exceptions), `certifi` and `tqdm` (MPL-2.0, allowed). Everything else is MIT, BSD, Apache-2.0, ISC or PSF.

Proposed License Register lines (the register lives outside this repo):

| Component | Role | License | Class | Notes |
|---|---|---|---|---|
| Docling (`docling-slim`, `docling-core`, `docling-parse`, `docling-ibm-models`) | PDF layout/table parsing, optional backend | MIT | Ship | 2.142.0; only in the `docling` extra of `lfmap-markitdown` |
| PyTorch (`torch`, `torchvision`) | inference runtime for Docling models | BSD-3-Clause family (torch: Apache-2.0, BSD, BSL-1.0, MIT parts) | Ship | CPU wheel on Windows; reviewed exception in `check_licenses.py` |
| transformers, huggingface-hub, safetensors, tokenizers, accelerate | model loading | Apache-2.0 | Ship | through `docling-ibm-models` |
| regex | dependency of transformers | Apache-2.0 AND CNRI-Python | Ship | reviewed exception |

Model table:

| Model | Version | License | Class | Checked |
|---|---|---|---|---|
| docling-layout-heron | HF `main` (pin a commit when implementing) | Apache-2.0 | Ship | 2026-10-23, model card via search; confirm on DIEP-ANH from the downloaded `README.md` |
| TableFormer (`docling-models`) | HF `v2.3.0` | CDLA-Permissive-2.0 (weights) / Apache-2.0 | Ship | same; CDLA-Permissive-2.0 allows use and redistribution, keep the license text with the weights |

## 5. Output quality (MarkItDown baseline)

Three synthetic PDFs (`make_pdfs.py`, no real data): `headings.pdf` (title, H1 and H2 sections), `table.pdf` (5-column register with a spanned cell), `scanned.pdf` (one image-only page, slightly rotated).

MarkItDown 0.1.8, run in the container:

| File | Result |
|---|---|
| `headings.pdf` | Text is complete, but **no `#` headings**: "Quality Manual", "1. Scope", "1.1 Responsibilities" are plain lines. This is L21. |
| `table.pdf` | Pipe table produced, but the first two columns are **merged** ("Code Title" header, "QP-01 Procedure 1" cells); the spanned row falls out of the table as a plain line. |
| `scanned.pdf` | Empty output (expected: the plugin routes it to OCR). |

The Docling side of the comparison could not run here because the models cannot be downloaded in the cloud container. It is moved to DIEP-ANH (`Run-DoclingSpike.ps1`, section 8). Pass criteria for the GO: Docling emits `#`/`##` headings for `headings.pdf`, keeps 5 separate columns in `table.pdf`, and gets the scanned text through Tesseract CLI OCR, all with `HF_HUB_OFFLINE=1`.

## 6. Fit with the `Backend` interface

```python
class Backend(Protocol):
    name: str

    def version(self) -> str: ...
    def to_markdown(self, stream: BinaryIO, extension: str, filename: str) -> str: ...
```

Docling fits without changing the protocol:

- `DocumentConverter.convert()` accepts `DocumentStream(name=filename, stream=BytesIO(...))`, so the plugin keeps reading through its own permission-checked handle; Docling never opens a path.
- `to_markdown` returns `result.document.export_to_markdown()`. `version()` returns `importlib.metadata.version("docling-slim")`.
- Options (artifacts path, OCR engine and languages, table mode, threads) go into the backend's constructor from `ctx.settings`, like the OCR settings today.

Changes needed in the plugin (implementation task, not this spike):

1. New extra `docling = ["docling-slim[format-pdf,models-local,convert-core]==2.142.0"]`; import Docling only inside the backend module, as the `ocr` backend does with OCRmyPDF.
2. `ConvertInput`/`ExportInput` gain `backend: Literal["markitdown", "docling"] = "markitdown"`; the CLI flag `--backend docling` is generated from it. `ConvertOutput.backend` already exists.
3. Settings: `docling_artifacts_path` (required; without it the backend reports `backend_unavailable` and never downloads), `docling_ocr` (`tesseract` default, uses `find_tesseract()` and `ocr_languages`).
4. Docling handles scanned pages itself, so for `backend = "docling"` the OCRmyPDF detour is skipped; `ocr=true` turns on Docling's OCR.
5. The backend sets `HF_HUB_OFFLINE=1` and `ORT_DISABLE_TELEMETRY=1` for its process. The plugin manifest keeps `network = false`.
6. Scope: PDF only in 1.2 (and images through OCR). DOCX/PPTX/XLSX stay on MarkItDown; Docling's Office parsers bring no gain worth the extra dependencies now.
7. `info`/`health` report whether the extra is installed and the models folder is complete.
8. License check: add `torch` and `regex` to `EXCEPTIONS`, plus the register lines above.

Model weights are downloaded once with `docling-tools models download layout tableformer -o <folder>`; the folder is then added to `[paths]` and the setting. No adapter-specific code.

## 7. Solo-maintainability verdict

Acceptable, as an optional extra only.

- For: MIT code, permissive model licenses, IBM-originated project with very active maintenance, a modular `docling-slim` package, a documented offline mode, and a plug-in point (`Backend`) that already exists.
- Against: heavy dependency tree (PyTorch, transformers), very fast release cadence with frequent minor changes, model files to manage outside pip, and slow CPU inference compared with MarkItDown (to be measured).
- Containment: exact pin, extra not installed by default, lazy import, upgrade only on purpose with the comparison script, models in a declared folder, no automatic downloads.

## 8. DIEP-ANH run (open)

`Run-DoclingSpike.ps1` (project files `lfmap-core/docling-1.2/`) installs the slim set into `D:\Development\lfmap-tools\docling-spike`, records the installed size and wheel count, downloads the layout and TableFormer weights once from Hugging Face, then converts the three PDFs with `HF_HUB_OFFLINE=1`, Tesseract CLI OCR and the local models, and writes both Markdown versions and timings. `-Gpu` optionally times the CUDA path. Results to record here: installed size, model size, first-run and per-page time on CPU, the three quality checks of section 5, and the model `README.md` licenses.

## 9. Recommendation

**Conditional GO** for Roadmap 1.2 as the optional `docling` extra described in section 6, PDF only, offline by construction (`artifacts_path` required, Tesseract CLI OCR, no RapidOCR, telemetry off).

Condition: the DIEP-ANH run meets the pass criteria of section 5 and converts a typical page in a time acceptable for reindexing (target: under 5 s per page on CPU). If headings do not appear or CPU time is far worse, NO-GO: keep MarkItDown, and fix L21 with a cheap heuristic in the knowledge chunker instead.

Separate follow-up regardless of the decision: guard against `onnxruntime` telemetry (section 3).
