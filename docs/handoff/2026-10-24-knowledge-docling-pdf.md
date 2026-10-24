# Bàn giao: knowledge dùng Docling cho PDF (task D3, Roadmap 1.2), 24/10

Nối tiếp [`2026-10-23-docling-backend.md`](2026-10-23-docling-backend.md) (task D1, PR #70, đã merge `16358e2`). Test viết sẵn: [`prep/2026-10-24-knowledge-docling/`](prep/2026-10-24-knowledge-docling/). Nếu code trên `main` không khớp với kế hoạch này, dừng lại và hỏi.

## Bối cảnh

L21: MarkItDown đọc PDF không ra heading Markdown, nên chunk của PDF có `heading_path` rỗng và trích dẫn của `get_context` chỉ có đường dẫn với vị trí ký tự. PR #70 thêm `--backend docling` vào plugin `markitdown` (extra tùy chọn, chỉ PDF, offline, model ở setting `docling_artifacts_path`, cấp heading suy từ số mục). Nhưng knowledge vẫn gọi `markitdown.convert` với backend mặc định, nên index chưa được lợi gì. Đây là lý do chính của Roadmap 1.2 (câu hỏi mở 1 của handoff D1, khuyến nghị làm ngay sau D2).

Code hiện tại liên quan (đọc ở `16358e2`):

- `extract.py`: `extractor_version()` là một chuỗi chung `markitdown/<markitdown>/<lfmap-markitdown>`; cache `cache/md/ab/<hash>.md` + `.json` (ghi `extractor_version`); `ToolError` có `reason_code` thành `SkipResult` (file `skipped` vĩnh viễn đến khi file đổi).
- `indexer.reindex`: đầu mỗi lần chạy, đánh dấu `pending` mọi file `indexed` có `contents.extractor_version` khác bản hiện tại, nên đổi version là đủ để trích lại, **không cần `full`** (`full` chỉ chunk lại từ cache).
- `scanner._classify`: file mới/đổi được coi `indexed` nếu đã có `contents` cùng hash và cùng version.
- Setting của `markitdown` (kể cả `docling_artifacts_path`) đi qua `context_for("markitdown", ...)`, knowledge không cần biết.

## Mục tiêu

Với `pdf_backend = "docling"` trong `[plugins.knowledge.settings]`, `lfmap knowledge reindex` trích PDF bằng Docling, chunk của PDF có `heading_path` lồng nhau (`1. Scope > 1.1 Responsibilities`), các định dạng khác không bị trích lại. Mặc định không đổi gì: không setting thì version, cache, kết quả giữ nguyên như hôm nay.

## Quyết định đã chốt

Claude tự quyết (đảo ngược được, trong phạm vi Roadmap 1.2 mà Hùng đã chốt GO lúc 15:40Z 23/10).

| # | Quyết định | Phương án loại |
|---|---|---|
| K1 | Setting `pdf_backend`: `"markitdown"` (mặc định) hoặc `"docling"`. Giá trị khác: `invalid_input` trước khi quét. Chỉ áp cho `.pdf`; định dạng khác luôn `markitdown`. | Tự bật Docling khi extra có mặt (đổi kết quả ngầm, chậm 100 lần); setting chung `backend` cho mọi định dạng (Docling chỉ đọc PDF trong extra) |
| K2 | Version theo backend: `markitdown` giữ đúng chuỗi cũ (không reindex khi nâng cấp lfmap); `docling` = `docling/<docling-slim>/<lfmap-markitdown>`. Version chọn **theo phần mở rộng của file** (`files.ext`), ở cả bước đánh dấu `pending`, `_classify` và `_extract_pending`. Bật/tắt Docling chỉ trích lại PDF. | Một version chung có tên backend (bật Docling sẽ trích lại toàn bộ DOCX/XLSX); cột mới trong `contents` (cần migration, không cần thiết) |
| K3 | Cache riêng theo backend: `ab/<hash>.md` (markitdown, như cũ) và `ab/<hash>.docling.md` (+ `.docling.json`). Tắt Docling quay về bản MarkItDown trong cache, không convert lại. `get_file.markdown_cached` đúng nếu có bất kỳ bản nào. | Ghi đè một file cache (đổi qua lại tốn 3 s/trang mỗi lần) |
| K4 | `pdf_backend = "docling"` mà backend không chạy được (thiếu extra, setting, model): `reindex` báo `backend_unavailable`, `reason_code = "docling_unavailable"` **trước khi mở catalog**, không quét, không ghi gì. Kiểm bằng `MarkitdownTool.health()["docling"]` (không import Docling). Trong `extract`, `docling_unavailable` được ném lại, không thành `SkipResult`. | Đánh dấu PDF `skipped` (mất khỏi index đến khi file đổi, lỗi cấu hình thành dữ liệu); tự lùi về MarkItDown (che lỗi cấu hình, job theo lịch không ai thấy) |
| K5 | OCR giữ setting `ocr` hiện có: `ocr = true` + Docling thì Docling gọi Tesseract (D4 của handoff D1), OCRmyPDF không chạy. | Setting OCR riêng cho Docling |
| K6 | `status` thêm `pdf_backend: str` (đọc thẳng setting, không ném lỗi). Không đổi `ReindexOutput`. | Thêm bộ đếm theo backend vào `ReindexOutput` (chưa ai cần) |
| K7 | Không thêm extra `docling` cho `lfmap-knowledge`: cài bằng `uv sync --all-packages --extra docling` như D2. | Extra chuyển tiếp `lfmap-markitdown[docling]` (thêm một dòng lock để giữ đồng bộ, lợi ích nhỏ khi chưa phát hành gói) |

## Phạm vi

Trong: `extract.py`, `scanner.py`, `indexer.py`, `catalog.py`, `schemas.py` (`StatusOutput.pdf_backend`) của `lfmap-knowledge`; README và CHANGELOG của `lfmap-knowledge`; CHANGELOG gốc `[Unreleased]`; `docs/specs/knowledge.md` §2 (thêm dòng setting).
Ngoài: plugin `markitdown` (không sửa), GPU, Docling cho DOCX/ảnh, giới hạn số trang/thời gian mỗi PDF, chạy song song nhiều PDF, extra cho knowledge (K7).

## Thiết kế

### API (test viết sẵn dựa vào đúng các tên này)

`packages/lfmap-knowledge/src/lfmap_knowledge/extract.py`:

```python
PDF_BACKENDS = ("markitdown", "docling")


def pdf_backend(settings: dict) -> str: ...  # default "markitdown"; anything else -> ToolError("invalid_input")
def backend_for(ext: str, pdf: str) -> str: ...  # pdf if ext.lower() == ".pdf" else "markitdown"
def extractor_version(
    backend: str = "markitdown",
) -> str: ...  # markitdown string unchanged; "docling/<docling-slim>/<lfmap-markitdown>"
def cache_path(
    cache_dir: Path, content_hash: str, backend: str = "markitdown"
) -> Path: ...  # ab/<hash>.md | ab/<hash>.docling.md
def require_backend(tool_ctx: ToolContext, backend: str, config: dict | None = None) -> None: ...  # K4


def extract(
    tool_ctx: ToolContext,
    path: Path,
    content_hash: str,
    cache_dir: Path,
    ocr: bool,
    config: dict | None = None,
    backend: str = "markitdown",
) -> ExtractResult | SkipResult: ...  # ConvertInput(path=..., ocr=..., backend=backend)
```

- `scanner.reconcile(..., extractor_version: str = "", pdf_extractor_version: str | None = None)`: `_classify` dùng `pdf_extractor_version` cho `.pdf` khi có.
- `indexer.reindex`: `pdf = pdf_backend(ctx.settings)` và `require_backend(ctx, pdf, config)` ngay sau khi kiểm `root`, trước `data_dir.mkdir` và `writer_lock`. Bước đánh dấu `pending` so `contents.extractor_version` với `extractor_version(pdf)` cho `files.ext = '.pdf'` và `extractor_version()` cho phần còn lại (một câu `UPDATE` với `CASE` là đủ).
- `_extract_pending`: thêm `f.ext` vào `SELECT`, mỗi dòng `backend = backend_for(row["ext"], pdf)`, `version = extractor_version(backend)`, truyền `backend` vào `extract`.
- `catalog.get_file`: `markdown_cached = any(cache_path(cache_dir, h, b).exists() for b in PDF_BACKENDS)`.
- Thông báo lỗi K4 trỏ người dùng tới `lfmap markitdown info` (trường `docling_available`).

Bản code tham chiếu đã chạy qua cả bộ test (`packages/lfmap-knowledge`: 245 passed, ruff sạch) nằm ở project files `lfmap-core/knowledge-docling-d3/reference-src.patch` (khoảng 70 dòng). Chỉ dùng để đối chiếu; Working Agent tự viết.

### Cấu hình

```toml
[plugins.markitdown.settings]
docling_artifacts_path = 'D:\Development\lfmap-tools\docling-spike\models'

[plugins.knowledge.settings]
pdf_backend = "docling"   # "markitdown" (default) | "docling": PDFs only, needs the markitdown docling extra
```

## Danh sách task

| Task | Nội dung | Môi trường | Tiêu chí hoàn thành |
|---|---|---|---|
| D3a (cỡ S) | Code như mục Thiết kế, test, tài liệu | **Cloud** (Claude Code). Không cần model: test giả converter và giả `docling_installed`/`missing_models`. Không giao qwen: đụng logic version/cache của index | Dưới đây |
| D3b (cỡ S) | Reindex thật trên DIEP-ANH | **Local** DIEP-ANH, sau D2 đạt và D3a merge | Mục "Chạy thật" |

Tiêu chí D3a:

1. Chép `prep/2026-10-24-knowledge-docling/test_pdf_backend.py` sang `packages/lfmap-knowledge/tests/`, bỏ 2 dòng chú thích đầu. Không sửa test để cho qua; nếu test sai, ghi lý do trong PR.
2. Test cũ không sửa (chữ ký cũ vẫn chạy nhờ tham số mặc định). `uv run pytest` xanh; `ruff check .`, `ruff format --check .` sạch.
3. Không reindex ngầm: với setting mặc định, `extractor_version()` và `cache_path(...)` trả đúng như trước (test `test_markitdown_version_and_cache_path_unchanged`).
4. README `lfmap-knowledge` (setting `pdf_backend`, cần extra `docling` của markitdown + `docling_artifacts_path`, khoảng 3 s/trang, chỉ PDF bị trích lại), CHANGELOG knowledge và gốc, `docs/specs/knowledge.md` §2.
5. CI Windows xanh, CodeQL không cảnh báo mới, Provenance xanh.

## Chạy thật (D3b, thêm vào danh sách DIEP-ANH)

Điều kiện: D2 đạt (test model pass, heading lồng nhau trên `headings.pdf`, bảng 5 cột). Trước `uv sync`, dừng các tiến trình `lfmap serve mcp` (chúng khóa `lfmap.exe`, đã chặn D2 đêm 23/10).

```powershell
cd D:\Development\lfmap
git pull
uv sync --all-packages --extra ocr --extra docling
uv run lfmap knowledge status --json      # ghi số PDF indexed trước khi bật
```

Thêm `pdf_backend = "docling"` vào `[plugins.knowledge.settings]` trong `%LOCALAPPDATA%\lfmap\config.toml`, rồi:

```powershell
Measure-Command { uv run lfmap knowledge reindex --json | Out-File D:\Tmp\d3b-reindex.json }
uv run lfmap knowledge status --json
```

Ghi lại: thời gian reindex và số trang PDF xấp xỉ; `extracted` chỉ gồm PDF (DOCX/XLSX không bị trích lại); `errors` và `skipped`; 3 câu `get_context` về nội dung PDF có `heading_path` khác rỗng; tắt setting rồi reindex: `extracted` là số PDF nhưng chạy nhanh (lấy từ cache). Nếu thời gian quá lâu cho job theo lịch, báo lại trước khi để setting bật.

## Chuẩn bị sẵn

- Test viết sẵn (10 test, PR này), đã kiểm bằng bản code tham chiếu: 245 passed (235 cũ + 10 mới) trên Linux, ruff sạch.
- Bản code tham chiếu: project files `lfmap-core/knowledge-docling-d3/reference-src.patch`.
- Config DIEP-ANH đã có `docling_artifacts_path` (D2 bước 5), model 669 MB ở `D:\Development\lfmap-tools\docling-spike\models`.

## Rủi ro

- **Chậm:** 3,1 s/trang CPU (spike). Kho 1.000 trang PDF mất khoảng 50 phút lần đầu; các lần sau chỉ PDF mới/đổi. Reindex qua MCP có thể quá thời gian chờ của client: chạy lần đầu bằng CLI hoặc job theo lịch.
- **Bộ nhớ trong tiến trình lâu dài:** `get_backend` giữ converter (~700 MB model) trong tiến trình. Với `lfmap serve mcp` chạy cả ngày, RAM đó ở lại sau reindex. Chấp nhận ở 1.2; nếu thành vấn đề thì thêm cách giải phóng sau.
- **Nâng `docling-slim`** đổi version, nên mọi PDF bị trích lại ở reindex sau. Đúng ý (kết quả Docling có thể đổi), nhưng tốn thời gian: chỉ nâng có chủ đích.
- **Kết quả D2 chưa có** khi viết bàn giao này (D2 đang chờ Hùng cho dừng `lfmap serve mcp`). Thiết kế D3a không phụ thuộc chi tiết đầu ra của Docling (test dùng converter giả); D3b phải chờ D2. Nếu D2 cho thấy heading sai cấp, sửa ở plugin (`fix_heading_levels`), không ở knowledge.
- **Hai file trùng nội dung khác phần mở rộng** (`x.pdf` và `x.bin` cùng byte): dùng chung `contents`, version theo file nào trích sau. Hiếm, không xử lý.

## Câu hỏi còn mở

1. Có bật `pdf_backend = "docling"` mặc định trên DIEP-ANH sau D3b không? Khuyến nghị: bật nếu reindex lần đầu xong trong một đêm; quyết sau khi có số đo D3b.

## Cập nhật tài liệu dự án

- ROADMAP 1.2: ✅ khi D2 đạt và D3a merge; ghi "knowledge: setting `pdf_backend`".
- DECISIONS: không ADR mới (trong phạm vi Roadmap 1.2 đã chốt).
- Known limitations: L21 giải được khi `pdf_backend = "docling"`; thêm ghi chú tốc độ reindex PDF.

## Prompt khởi động cho Claude Code

```text
Repo hungnp1999/lfmap. Task D3a of docs/handoff/2026-10-24-knowledge-docling-pdf.md (Roadmap 1.2):
knowledge setting pdf_backend = "docling" so PDFs are extracted by the markitdown Docling backend and
get a heading_path. Read the handoff first; follow CLAUDE.md (English code, security rules).
1. Copy docs/handoff/prep/2026-10-24-knowledge-docling/test_pdf_backend.py to
   packages/lfmap-knowledge/tests/ and delete its first two comment lines. Do not weaken the tests;
   if one is wrong, say why in the PR. Do not change existing tests.
2. extract.py: PDF_BACKENDS, pdf_backend, backend_for, extractor_version(backend), cache_path(..., backend),
   require_backend, extract(..., backend) exactly as in the handoff. The markitdown version string and
   cache path must stay identical to today.
3. scanner.reconcile gains pdf_extractor_version; indexer.reindex validates the setting and calls
   require_backend before touching the catalog, marks pending per file extension, and
   _extract_pending picks the backend per file. catalog.get_file: markdown_cached for any backend.
   StatusOutput gains pdf_backend.
4. README and CHANGELOG of lfmap-knowledge, root CHANGELOG [Unreleased], docs/specs/knowledge.md section 2.
5. uv run pytest; ruff check .; ruff format --check .
```
