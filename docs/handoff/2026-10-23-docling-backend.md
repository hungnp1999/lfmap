# Bàn giao: backend Docling cho PDF (Roadmap 1.2), 23/10 tối

Spike và số đo: [`docs/specs/docling-spike.md`](../specs/docling-spike.md) (v0.2, PR #58, #68). Test viết sẵn: [`prep/2026-10-23-docling/`](prep/2026-10-23-docling/). Nếu code trên `main` không khớp với kế hoạch này, dừng lại và hỏi.

## Bối cảnh

MarkItDown đọc PDF không ra heading Markdown (L21), nên `heading_path` trong trích dẫn của knowledge trống với PDF, và gộp nhầm cột bảng. Spike 1.2 chạy trên DIEP-ANH (CPU, 23/10): Docling ra 30/30 heading, bảng đúng 5 cột, OCR được trang scan qua Tesseract, chạy offline hoàn toàn, 3,1 s/trang (MarkItDown 0,02 s/trang). Hùng chốt lúc 15:40Z 2026-10-23: **GO, extra tùy chọn, chỉ PDF**, chấp nhận luôn các dòng giấy phép mới.

## Mục tiêu

`lfmap markitdown convert <file.pdf> --backend docling` (và `export`, SDK, MCP, cùng một Tool Spec) cho Markdown có heading lồng nhau và bảng đúng cột, không tải gì từ mạng. MarkItDown vẫn là mặc định.

## Quyết định đã chốt

| # | Quyết định | Phương án loại |
|---|---|---|
| D1 | Extra `docling` của `lfmap-markitdown` = `docling-slim[format-pdf,models-local,convert-core]==2.142.0` + `opencv-python-headless>=4.10,<6` (TableFormer cần `cv2`). Ghim đúng bản, import Docling chỉ trong hàm. | Gói `docling` đầy đủ (kéo RapidOCR, parser Office, 339 MB); cài mặc định |
| D2 | Chỉ PDF. File khác với `--backend docling` vẫn đi MarkItDown, kết quả ghi `backend = "markitdown"` (export một thư mục trộn được). | Báo lỗi cho file không phải PDF (export thư mục trộn sẽ hỏng) |
| D3 | Setting `docling_artifacts_path` bắt buộc. Thiếu setting, thiếu extra, hoặc thư mục thiếu model: `backend_unavailable`, `reason_code = "docling_unavailable"`, không bao giờ tự tải. Tiến trình đặt `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` trước khi import Docling; `ORT_DISABLE_TELEMETRY` đã có từ #62. Manifest giữ `network = false`. | Để Docling tự tải từ Hugging Face lần đầu |
| D4 | OCR dùng Tesseract CLI (`TesseractCliOcrOptions`, dùng lại `find_tesseract()`, `ocr_languages`, `tessdata_dir`). Không RapidOCR (tải model từ modelscope.cn). Với backend docling, OCRmyPDF không chạy. | RapidOCR; OCRmyPDF rồi mới Docling (chậm gấp đôi) |
| D5 | Hậu xử lý cấp heading theo số mục: Docling ra mọi heading là `##`; `## 1.1 X` thành `### 1.1 X`, `## 2.3.4 X` thành `####`, tối đa `######`. Heading không đánh số giữ `##`. Hàm thuần `fix_heading_levels` trong `headings.py`, chạy trong `DoclingBackend.to_markdown`. | Sửa cấp trong `DoclingDocument` trước khi export (gắn chặt với API Docling, khó test không có model) |
| D6 | **typer:** `docling-core` 2.104.0 (bản mới nhất, bắt buộc với `docling-slim` 2.142.x) đòi `typer<0.27`, còn `lfmap-core` ghi `typer>=0.27.3`. uv khóa một phiên bản cho cả workspace kể cả extra chưa cài, nên hạ chặn dưới của `lfmap-core` xuống `typer>=0.26`; lock chọn 0.26.8. Đã thử trên bản sao: 706 passed, 12 skipped. Claude tự quyết (đảo ngược được): khi `docling-core` nới chặn trên thì nâng lại. | `override-dependencies` bỏ qua ràng buộc của docling-core (giấu xung đột thật); khai báo `conflicts` (uv chỉ hỗ trợ giữa các extra, không giữa dependency chính và extra) |
| D7 | Giấy phép (Hùng chấp nhận cùng GO): `EXCEPTIONS` trong `scripts/check_licenses.py` thêm `torch` (Apache-2.0, BSD, BSL-1.0, MIT, LLVM-exception, đều permissive) và `regex` (Apache-2.0 AND CNRI-Python); `ALIASES` thêm `"APACHE 2.0 LICENSE": "Apache-2.0"` (metadata của `transformers` 5.20.2 ghi như vậy). Đã chạy logic của checker trên 75 gói Windows của extra: chỉ ba gói này trượt. Model: layout heron Apache-2.0, TableFormer CDLA-Permissive-2.0 (giữ file license đi kèm model). `opencv-python-headless` Apache-2.0 (code OpenCV), đóng gói MIT. | |

## Phạm vi

Trong: `backends/docling.py`, `headings.py`, field `backend` ở `ConvertInput`/`ExportInput`, `info`/`health` báo Docling, extra trong `pyproject.toml`, `uv.lock`, `check_licenses.py`, README và CHANGELOG của plugin, CHANGELOG gốc, ghi chú giới hạn.
Ngoài: knowledge chọn backend Docling khi index PDF (task D3 dưới), GPU (CUDA wheel), DOCX/PPTX/XLSX qua Docling, ảnh qua Docling, tải model bằng lệnh của lfmap.

## Thiết kế

### API (test viết sẵn dựa vào đúng các tên này)

`plugins/lfmap-markitdown/src/lfmap_markitdown/backends/docling.py`:

```python
LAYOUT_MODEL = "docling-project--docling-layout-heron"
TABLE_MODEL = "docling-project--docling-models"


def docling_installed() -> bool: ...  # find_spec("docling") and find_spec("cv2"), no import
def docling_version() -> str: ...  # importlib.metadata version of "docling-slim", "" when absent
def missing_models(artifacts_path: str) -> list[str]: ...  # [LAYOUT_MODEL, TABLE_MODEL] order, subfolders absent
def force_offline() -> None: ...  # os.environ HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1 (overwrite)


@dataclass(frozen=True)
class DoclingOptions:
    artifacts_path: str
    ocr: bool = False
    full_page_ocr: bool = False
    languages: tuple[str, ...] = ("eng",)
    tesseract_cmd: str | None = None
    tessdata_dir: str | None = None
    device: str = "auto"  # setting docling_device: auto | cpu | cuda
    threads: int = 4  # setting docling_threads


class DoclingBackend:
    name = "docling"

    def __init__(self, options: DoclingOptions) -> None: ...  # force_offline(), then import docling, build converter
    def version(self) -> str: ...
    def to_markdown(self, stream: BinaryIO, extension: str, filename: str) -> str: ...


@functools.lru_cache(maxsize=2)
def get_backend(options: DoclingOptions) -> DoclingBackend: ...  # init costs ~5 s and ~700 MB of models
```

Converter: `PdfPipelineOptions(artifacts_path=..., do_ocr=options.ocr, do_table_structure=True, enable_remote_services=False, accelerator_options=AcceleratorOptions(device=..., num_threads=...))`; khi `ocr`: `ocr_options = TesseractCliOcrOptions(lang=list(languages), tesseract_cmd=..., path=tessdata_dir)` và `mode=OcrMode.FULL_PAGE` nếu `full_page_ocr` (`force_full_page_ocr` đã deprecated ở 2.142). `DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=...)}, allowed_formats=[InputFormat.PDF])`. `to_markdown` đọc stream vào `BytesIO`, `convert(DocumentStream(name=filename, stream=...), raises_on_error=True)`, `export_to_markdown()`, rồi `fix_heading_levels`. Một `threading.Lock` quanh `convert` (MCP server có thể gọi song song). Docling không bao giờ nhận đường dẫn: plugin đọc qua handle đã kiểm quyền như hiện nay.

`plugins/lfmap-markitdown/src/lfmap_markitdown/headings.py`: `fix_heading_levels(markdown: str) -> str`. Chỉ đổi dòng bắt đầu đúng `## ` ngoài khối code rào (```` ``` ```` hoặc `~~~`). Số mục: 1 đến 3 chữ số mỗi phần, tối đa 6 phần, cho phép `\.` (Docling có thể escape), dấu chấm cuối tùy chọn, sau đó phải có khoảng trắng và chữ. Cấp = số phần + 1, tối đa 6.

### Luồng trong `tool.py`

- `ConvertInput`/`ExportInput`: `backend: Literal["markitdown", "docling"] = "markitdown"` (CLI sinh `--backend`).
- `backend == "docling"` và file `.pdf`: kiểm khả dụng (extra, setting, model) trước, rồi phân loại như cũ. Cần OCR (scan, garbled, `force_ocr`) mà `ocr=false`: lỗi `needs_ocr` như cũ. `ocr=true`: `DoclingOptions(ocr=True, full_page_ocr=<cần OCR hoặc force_ocr>)`, thiếu Tesseract thì `backend_unavailable`/`ocr_unavailable`. `stage = "ocr_markdown"` khi có OCR toàn trang, ngược lại `"markdown"`. Lỗi khác từ Docling: `internal` như MarkItDown.
- `export` với `backend = "docling"`: kiểm khả dụng **một lần trước khi ghi gì**, không phải từng file.
- Lấy backend qua `docling_backend.get_backend(...)` (import module, không import tên), để test thay được.
- `InfoOutput` thêm `docling_available: bool` (extra + setting + đủ model) và `docling_version: str`; `health()` thêm `"docling": bool`, không đổi `ok`.
- `ReasonCode` thêm `"docling_unavailable"`.
- Settings mới (`[plugins.markitdown.settings]`): `docling_artifacts_path`, `docling_device` (`auto`), `docling_threads` (4).

## Danh sách task

| Task | Nội dung | Môi trường | Tiêu chí hoàn thành |
|---|---|---|---|
| D1 (cỡ M) | Code như mục Thiết kế, extra, lock, license | **Cloud** (Claude Code). Không giao qwen: có phần offline/bảo mật và đụng lock. Model không tải được trên Cloud nên test model tự skip | Dưới đây |
| D2 (cỡ S) | Chạy thật trên DIEP-ANH: test model + PDF của spike | **Local** DIEP-ANH (Windows, có model) | Mục "Chạy thật" |
| D3 (cỡ S, PR riêng, sau D2) | knowledge: setting `pdf_backend = "docling"`, cache tag gồm backend; reindex `full` để PDF có `heading_path` | Cloud, kiểm trên DIEP-ANH | Đề xuất, chờ D2 |

Tiêu chí D1:

1. Chép `prep/2026-10-23-docling/test_headings.py` và `test_docling.py` sang `plugins/lfmap-markitdown/tests/`, bỏ 2 dòng chú thích đầu. Không sửa test để cho qua; nếu test sai, ghi lý do trong PR.
2. `uv run pytest` xanh (test model skip); `ruff check .`, `ruff format --check .` sạch; `uv sync --no-dev` + `check_licenses.py` qua.
3. Lock: chỉ thêm gói của extra và hạ typer; `onnxruntime` vẫn 1.20.1, `magika` 0.6.3 (không kéo telemetry, xem spike §3).
4. CI Windows xanh, CodeQL không cảnh báo mới, Provenance xanh.
5. README plugin (cài extra, tải model một lần, setting, ví dụ), CHANGELOG plugin và gốc.

## Chạy thật (D2, thêm vào danh sách DIEP-ANH)

Thư mục model đã có từ spike: `D:\Development\lfmap-tools\docling-spike\models` (669 MB). Trong `D:\Development\lfmap` sau khi PR D1 merge:

```powershell
git pull
uv sync --all-packages --extra ocr --extra docling
$env:LFMAP_DOCLING_ARTIFACTS = "D:\Development\lfmap-tools\docling-spike\models"
uv run pytest plugins/lfmap-markitdown -q --basetemp=D:\Tmp\lfmap-pytest
```

Rồi thêm `docling_artifacts_path` vào `[plugins.markitdown.settings]` trong `%LOCALAPPDATA%\lfmap\config.toml`, chép 4 PDF của spike vào một thư mục `${documents}` và chạy `uv run lfmap markitdown convert <file> --backend docling --json` (scan thêm `--ocr`). Ghi lại: cấp heading của `headings.pdf` và `long30.pdf`, tiêu đề "Quality Manual" nằm ở đâu, bảng 5 cột, thời gian, có cửa sổ console Tesseract nhấp nháy không.

## Chuẩn bị sẵn

- Spike, số đo và script (`lfmap-core/docling-1.2/` trong project files), model trên DIEP-ANH.
- Test viết sẵn (PR này). Đã đọc mã nguồn `docling-slim` 2.142.0 để chốt tên API (`TesseractCliOcrOptions.path`, `OcrMode`, tên thư mục model, `DocumentStream`).
- Lock thử: `uv lock` với extra mới và `typer>=0.26` giải được; thêm khoảng 980 dòng (torch Linux kéo gói CUDA vào lock, không cài trừ khi bật extra trên Linux).

## Rủi ro

- **Docling ra bản rất dày** (vài bản mỗi tuần): ghim đúng bản; chỉ nâng có chủ đích, chạy lại D2.
- **Hạ typer 0.27.3 → 0.26.8** cho cả workspace: test xanh trên Linux; CI Windows kiểm lại CLI.
- **Cấp heading theo số mục** sai với tài liệu đánh số kiểu La Mã, "Điều 1.", "Chương I": giữ `##` (không tệ hơn hôm nay). Ghi vào giới hạn đã biết.
- **Tesseract do Docling gọi** không đặt `CREATE_NO_WINDOW`: có thể nhấp nháy console khi chạy từ GUI/MCP. Kiểm ở D2.
- **Chậm** (3,1 s/trang CPU, khởi tạo 5 s): chỉ opt-in; `get_backend` giữ converter trong process.

## Câu hỏi còn mở

1. D3 (knowledge dùng Docling cho PDF) có làm ngay sau D2 không? Khuyến nghị: có, vì đây là lý do chính của 1.2 (L21). Tốc độ reindex PDF sẽ chậm hơn nhiều.
2. GPU (CUDA wheel 2,6 GB, cần duyệt tải từ download.pytorch.org): để sau, không cần cho 1.2.

## Cập nhật tài liệu dự án

- ROADMAP 1.2: ✅ khi D1 merge và D2 đạt; ghi "extra tùy chọn, chỉ PDF, offline".
- DECISIONS: không ADR mới (Hùng chốt GO trong phạm vi Roadmap 1.2).
- License Register: thêm các dòng ở spike §4 (Docling, PyTorch, transformers và họ HF, regex) và bảng model (heron Apache-2.0, TableFormer CDLA-Permissive-2.0), thêm `opencv-python-headless` (Apache-2.0 / MIT, Ship, chỉ trong extra `docling`).
- Known limitations: L21 giải được khi dùng `--backend docling`; giới hạn mới về heading không đánh số.

## Prompt khởi động cho Claude Code

```text
Repo hungnp1999/lfmap. Task D1 of docs/handoff/2026-10-23-docling-backend.md (Roadmap 1.2):
optional Docling backend for PDFs in plugins/lfmap-markitdown. Read the handoff and
docs/specs/docling-spike.md section 6 first; follow CLAUDE.md (English code, license check,
security rules).
1. Copy docs/handoff/prep/2026-10-23-docling/test_headings.py and test_docling.py to
   plugins/lfmap-markitdown/tests/ and delete their first two comment lines. Do not weaken the
   tests; if one is wrong, say why in the PR.
2. Add the `docling` extra (handoff D1), lower lfmap-core to "typer>=0.26" (D6), run uv lock.
   Check onnxruntime stays 1.20.1.
3. Write headings.py and backends/docling.py with exactly the API in the handoff, then wire
   tool.py, schemas.py, formats.py. Docling is imported only inside DoclingBackend.
4. scripts/check_licenses.py: EXCEPTIONS torch, regex; ALIASES "APACHE 2.0 LICENSE".
5. README and CHANGELOG of the plugin, root CHANGELOG [Unreleased].
6. uv run pytest; ruff check .; ruff format --check .; uv sync --no-dev and check_licenses.py.
```
