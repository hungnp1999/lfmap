# LFMAP Phase 1 — Runbook xử lý sự cố

Phiên bản 1.0 · 2026-10-22 · Mốc code `b002710`. `core/` = `packages/lfmap-core/src/lfmap_core/`, `kn/` = `packages/lfmap-knowledge/src/lfmap_knowledge/`, `md/` = `plugins/lfmap-markitdown/src/lfmap_markitdown/`.

Cách dùng: tìm triệu chứng, chạy bước chẩn đoán, mở đúng file ở cột "Code". Sự cố của khung Phase 0 (discovery, manifest, quyền cơ bản, CI) vẫn tra `docs/phase0/06_Runbook.md` (RB-01 … RB-06).

## 1. Bản đồ khoanh vùng nhanh

| Thông báo / dấu hiệu | Tầng | Mở file |
|---|---|---|
| `permission_denied: <plugin.op> needs approval (T2, overwrite)` + `hint` | Phê duyệt | `core/approval.py::Gate`, `_hint` |
| `... needs approval (T3, ...)` dù đã `--yes`/`--approve` | Phê duyệt T3 (đúng thiết kế) | `core/approval.py::decide` |
| `Queued for approval` + `approval_id`, job exit 1 | Hàng đợi job | `core/approvals.py`, `core/approval.py::job_decision` |
| `approve`/`add-folder`/`grant` báo cần terminal | Lệnh chỉ TTY | `core/cli.py::_interactive` |
| Dòng `read_outside_roots` trong audit | Đọc ngoài root ở CLI tương tác | `core/runtime.py::_outside_read_audit` |
| Task trong `\LFMAP\` Last Result `0x80070002` | Task Scheduler không tìm thấy `pwsh` | `core/jobs.py::find_pwsh` (sửa ở PR #34) |
| `jobs doctor` FAIL/warn | Máy chưa sẵn sàng chạy job | `core/jobs_doctor.py`, `docs/jobs.md` |
| `Error [invalid_input] ... reason_code: office_gui_only / needs_ocr / garbled_text / too_large` | markitdown phân loại | `md/tool.py`, `md/quality.py`, `md/formats.py` |
| `backend_unavailable ... ocr_unavailable` | Thiếu extra OCR hoặc Tesseract | `md/backends/ocr.py` |
| `backend_unavailable ... indexer_busy` | Hai reindex cùng lúc | `kn/store.py::writer_lock` |
| `embed_skipped_reason` khác rỗng; `mode_used = keyword` | Ollama không trả lời | `kn/embed.py`, `kn/indexer.py::_embed` |
| `backend_unavailable ... ollama_unreachable`, hoặc `Vector search needs Ollama` | Ollama tắt khi `mode=vector` | `kn/embed.py`, `kn/search.py::_vector_side` |
| `invalid_input ... loopback` | `ollama_url` không phải localhost | `kn/embed.py::check_loopback` |
| Kết quả thiếu một thư mục khi hỏi qua Claude | Root `secret` hoặc không còn trong cấu hình (đúng thiết kế) | `kn/search.py::hidden_root_ids`, `kn/tool.py::_shown_roots` |
| `not_found: File is not in the catalog` | File chưa reindex, ngoài root, hoặc root bị ẩn | `kn/catalog.py::find_file` |
| `root is not a knowledge root` | `reindex --root` sai | `kn/indexer.py::reindex` |

## 2. Sự cố thường gặp

### RB-07 Bị hỏi hoặc bị từ chối khi chạy operation có tác dụng phụ

1. Đọc `tier` và `hint` trong lỗi. `uv run lfmap audit tail -n 10` để xem quyết định vừa ghi.
2. T1 bị hỏi/từ chối: xem `[approval] T1` hoặc `[approval.operations]` trong `config.toml` (có thể đang `ask`/`deny`).
3. T2 qua MCP: client không có elicitation thì phải duyệt trước: `serve mcp --approve plugin.op` (8 giờ) hoặc `lfmap approvals grant plugin.op --for 2h`.
4. T3: chỉ grant (≤ 24 giờ), đích duyệt trước còn hạn, hoặc trả lời prompt ở terminal có TTY. `--yes`, `--approve`, elicitation không bao giờ đủ, có chủ ý.
5. `deny` trong policy thắng mọi thứ.
6. Tái hiện: `uv run pytest packages/lfmap-core/tests/test_approval.py -q`.

### RB-08 Job không chạy hoặc chạy lỗi

1. `uv run lfmap jobs doctor` → sửa theo cột `->`.
2. Xem log: `Get-Content "$env:LOCALAPPDATA\lfmap\logs\jobs-$(Get-Date -Format yyyy-MM-dd).jsonl" -Tail 5` (`exit_code`, `stderr`).
3. Không có dòng log nào: task không chạy được. Task Scheduler → task → History / Last Run Result:
   - `0x80070002`: task cũ dùng `pwsh` trần; chạy `uv run lfmap jobs register` (ghi đường dẫn đầy đủ).
   - Chỉ chạy khi đã đăng nhập: logon type `InteractiveToken`; đặt "Run whether user is logged on or not".
   - Máy ngủ: tick "Wake the computer" hoặc tắt sleep khi cắm điện.
4. Sau mỗi lần `register` phải đặt lại logon/wake (`/F` thay task).
5. Chạy tay để xem lỗi trực tiếp: `pwsh -NoProfile -File .\scripts\Invoke-LfmapJob.ps1 -JobId <id>; $LASTEXITCODE` (0 ok, 1 ToolError hoặc đang chờ duyệt, 2 lỗi khác hoặc không tìm thấy uv).
6. `uv sync` trong lúc job hay MCP đang chạy có thể bị khóa `lfmap.exe`; đóng Claude, chờ job xong rồi sync.

### RB-09 Đề xuất của job

1. `uv run lfmap approvals pending` không thấy đề xuất: có thể đã hết hạn → `%LOCALAPPDATA%\lfmap\approvals\expired\`.
2. `approve` báo cần terminal: chạy ở Windows Terminal trên chính máy (Remote Control và Claude không làm thay được).
3. `approve` từ chối id: id phải đúng mẫu `YYYYMMDDTHHMMSSZ-<job>-<8 hex>`; file bị sửa tay (tầng thấp hơn khai báo, trường lạ) không được duyệt.
4. Approve xong nhưng lời gọi cần tầng cao hơn: bị hỏi lại, đúng thiết kế.
5. Đề xuất không bao giờ bị xóa tự động; dọn tay `done`, `rejected`, `expired` nếu muốn.

### RB-10 markitdown không chuyển được file

| `reason_code` | Nguyên nhân | Xử lý |
|---|---|---|
| `office_gui_only` | `.doc .rtf .odt .ppt .odp .ods` | Dùng app MarkitdownTool (ADR-011) |
| `needs_ocr` | PDF scan hoặc ảnh | `--ocr` (cần extra `[ocr]` + Tesseract) |
| `garbled_text` | Lớp chữ PDF hỏng (font mã hóa sai) | `--ocr`; `--force-ocr` để thay cả lớp chữ |
| `ocr_unavailable` | Chưa cài extra hoặc Tesseract | `uv sync --all-packages --extra ocr`; `uv run lfmap markitdown info` xem `tesseract_path` |
| `too_large` | Quá `max_file_bytes` (200 MB) | Tăng setting nếu chấp nhận |
| `unsupported_format` | Đuôi không hỗ trợ | — |

- OCR tiếng Việt lỗi: `info` phải liệt kê `vie` trong `ocr_languages`; nếu không, đặt `tessdata_dir` trỏ tới thư mục có `vie.traineddata`.
- `export` báo `output_dir` ngoài root: thêm thư mục bằng `config add-folder ... --as exports`; phải là đường dẫn tuyệt đối.

### RB-11 knowledge reindex chậm, lỗi hoặc thiếu file

1. `uv run lfmap knowledge status --json`: `files_by_status`, `ollama_available`, `indexer_busy`.
2. File `skipped`: xem `reason_code` bằng `uv run lfmap knowledge search_files --status skipped --json` (`unsupported_format`, `too_large`, `cloud_only`, `office_gui_only`, `needs_ocr`…). PDF scan chỉ vào chỉ mục khi bật `ocr = true` và có extra.
3. File `error/extract_failed`: đã thử 3 lần; sửa file (đổi nội dung) thì thử lại; xem lỗi bằng `uv run lfmap markitdown convert --path <file>`.
4. Không thấy file trong thư mục: tên bắt đầu `.`/`~$`, file ẩn/hệ thống, khớp `exclude`, nằm sau junction/symlink, hoặc OneDrive chỉ-trên-cloud — đều bỏ qua có chủ ý.
5. `indexer_busy` kéo dài: một process khác đang reindex (job theo giờ?). Nếu chắc không còn process nào, khóa OS đã tự nhả khi process chết; file `indexer.lock` còn lại là vô hại.
6. Lần đầu chậm: embed ~2 file/s với bge-m3 trên DIEP-ANH (số đo K14). Chạy khi Ollama sẵn, hoặc reindex không embed rồi để job sau embed.
7. Chỉ mục vector hỏng: đổi tên `%LOCALAPPDATA%\lfmap\knowledge\vectors` rồi reindex (embed lại từ cache, không trích lại). Hỏng nặng: `reindex --full`.
8. Tái hiện: `uv run pytest packages/lfmap-knowledge/tests/test_indexer.py -q`.

### RB-12 Claude không tìm thấy tài liệu hoặc trích dẫn sai

1. `claude mcp list` → `lfmap` phải `Connected`, server chạy với `--plugins knowledge` (xem RB-03 Phase 0).
2. So kết quả kênh `cli` và `mcp`: `uv run lfmap knowledge search --query "..."`. CLI thấy mà Claude không thấy → root `secret` hoặc root không còn trong `${knowledge}` (đúng thiết kế).
3. Tìm từ khóa không dấu kém: dùng `hybrid` (mặc định) và kiểm Ollama đang chạy (`mode_used`).
4. Claude cắt bớt ngữ cảnh: giảm `token_budget` (ước lượng 3 ký tự/token là thô) hoặc tăng `min_relative_score` (mặc định 0,5; 0 giữ mọi hit).
5. Trích dẫn: `char_start/char_end` trỏ vào Markdown cache (`cache\md\<2 ký tự>\<hash>.md`), không phải file gốc; heading theo Markdown đã trích.
6. Kiểm dữ liệu đã gửi: bảng `egress_log` trong `catalog.db` (UG §6).

### RB-13 CI đỏ ở phần Phase 1

| Bước | Nguyên nhân thường gặp | Xử lý |
|---|---|---|
| License check | Dependency mới kéo giấy phép ngoài `allowed` (vd LGPL từ `[ocr]` lọt vào mặc định) | Giữ OCR trong extra; thêm `EXCEPTIONS` chỉ sau review + License Register |
| `uv sync --frozen` | `uv.lock` lệch | `uv lock`, commit |
| Lint | Markdown/code chưa format | `uv run ruff format .` (định dạng cả code block trong `.md`), `uv run ruff check --fix .` |
| Test chỉ đỏ trên Windows | Đường dẫn, khóa file, junction | Chạy trên DIEP-ANH; test `store` dùng `msvcrt.locking` |
| CodeQL `py/path-injection` | Đường dẫn dùng trước `require_read/write` | Giữ `realpath` + `startswith` inline (CLAUDE.md) |

## 3. Nhật ký thay đổi cần biết khi tra sự cố

| Ngày | Thay đổi | PR |
|---|---|---|
| 2026-10-19 | Phê duyệt theo tầng thay `--approve` cứng của Phase 0; `--approve` hết hạn sau 8 giờ | #5, #6 |
| 2026-10-19 | Đọc ngoài root ở CLI tương tác; `config add-folder`, `audit tail` | #9 |
| 2026-10-20 | Đích T3 duyệt trước | #17 |
| 2026-10-22 | Task dùng đường dẫn `pwsh` đầy đủ; doctor kiểm `pwsh` | #34 |
| 2026-10-22 | knowledge đủ 7 operation; root bị ẩn trên MCP trước reindex | #38 |
