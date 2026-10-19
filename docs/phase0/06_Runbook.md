# LFMAP Phase 0 — Runbook xử lý sự cố

Phiên bản 1.0 · 2026-10-19 · Mốc code `f63f0ee`. `core/` = `packages/lfmap-core/src/lfmap_core/`.

Cách dùng: tìm triệu chứng, chạy bước chẩn đoán, mở đúng file ở cột "Code". Không cần đọc lại cả repo.

## 1. Bản đồ khoanh vùng nhanh

| Thông báo / dấu hiệu | Tầng | Mở file |
|---|---|---|
| `Skipping plugin <x>: ...` (warning) | Discovery | `core/registry.py` |
| `... does not match the manifest schema` / `is not valid TOML` (lfmap.toml) | Manifest | `core/manifest.py` |
| `Manifest operations do not match the tool class` | Discovery | `core/registry.py::load_entry` |
| `Operation method 'x' must take one pydantic model...` | Khai báo tool | `core/tool.py::_spec` |
| `Error [invalid_input]: Input does not match the operation schema` | Gọi operation | `core/tool.py::invoke` |
| `Error [permission_denied]: Path is outside ...` / `resolves outside ...` | Quyền | `core/permissions.py::_require` |
| `Network and device paths are refused` | Quyền | `core/permissions.py::_is_remote` |
| `Permission ... uses undefined variable ${x}; it grants nothing` | Config | `core/permissions.py::_expand`, `core/config.py` |
| `config.toml is not valid TOML` / `[paths] values must be ...` | Config | `core/config.py` |
| MCP: `permission_denied: ... start the server with --approve` | MCP phê duyệt | `core/mcp_adapter.py::_make_tool` |
| MCP server không khởi động, `--approve names an unknown operation` / `cannot be pre-approved` | MCP phê duyệt | `core/mcp_adapter.py::_check_approvals` |
| `MCP tool name is not valid` | MCP | `core/mcp_adapter.py::tool_name` |
| `Error [internal]: ...`, exit 2 | Lỗi bất ngờ trong plugin | Stack trace của plugin; `core/cli.py::main` chỉ là nơi bắt |
| CI đỏ ở bước "License check" | Giấy phép | `scripts/check_licenses.py` |

## 2. Sự cố thường gặp

### RB-01 Plugin không xuất hiện trong `lfmap plugins list`

1. `uv sync` lại (entry point chỉ có sau khi cài package).
2. Chạy `uv run python -c "from importlib.metadata import entry_points; print(entry_points(group='lfmap.plugins'))"`; không có tên plugin → sửa `[project.entry-points."lfmap.plugins"]` trong `pyproject.toml` của plugin.
3. Có tên nhưng vẫn không hiện → xem warning `Skipping plugin` trên stderr; các nguyên nhân: tên entry point khác `plugin.id`; class không kế thừa `Tool`; `lfmap.toml` không nằm cạnh module của class hoặc sai schema; tên `[[operations]]` khác tên `@operation`.

### RB-02 Bị `permission_denied` khi đọc/ghi file hợp lệ

1. Mở `%LOCALAPPDATA%\lfmap\config.toml` (hoặc file `LFMAP_CONFIG` trỏ tới): biến dùng trong manifest có trong `[paths]` chưa? Biến thiếu = không cấp gì (có warning).
2. Đường dẫn có phải ổ mạng, `\\?\`, OneDrive dạng UNC không? Bị chặn có chủ ý.
3. File nằm trong root đọc nhưng operation cần ghi? Root đọc không ghi được.
4. Đường dẫn đi qua symlink/junction ra ngoài root? Bị chặn có chủ ý (`resolves outside`).
5. Tái hiện: `uv run pytest packages/lfmap-core/tests/test_permissions.py -q`.

### RB-03 Claude không thấy hoặc không gọi được tool lfmap

1. `claude mcp list` → `lfmap` phải `Connected`. Không → chạy tay `uv run --directory D:\Development\lfmap lfmap serve mcp --plugins echo`; lệnh phải đứng chờ (không lỗi). Lỗi `uv` không tìm thấy → đăng ký lại với đường dẫn đầy đủ `uv.exe`.
2. Server khởi động rồi thoát ngay → đọc stderr: thường là `--approve` sai hoặc `--plugins` có id không tồn tại (`Unknown plugin`).
3. Tool trả lỗi `permission_denied ... --approve` → operation có tác dụng phụ; đăng ký lại server với `--approve <plugin>.<op>` nếu anh đồng ý cho agent chạy nó.
4. Giao thức hỏng, client báo JSON lạ → có code ghi stdout ngoài lúc gọi tool (lúc import plugin). Tìm `print` ở cấp module trong plugin; trong lúc gọi tool, stdout đã được chuyển sang stderr.

### RB-04 CLI trả exit 2 không rõ lý do

- Có dòng `Usage:` → sai cú pháp/thiếu option bắt buộc; xem `lfmap <plugin> <op> --help`.
- `Error [internal]` → ngoại lệ không phải `ToolError` trong plugin. Plugin nên bọc lỗi backend thành `ToolError("backend_unavailable" | "internal", ...)`. Tái hiện bằng `run_operation` trong Python để có stack trace.

### RB-05 CI đỏ

| Bước | Nguyên nhân thường gặp | Xử lý |
|---|---|---|
| License check | Dependency mới có giấy phép ngoài `allowed` hoặc không khai báo | Tra License Register; nếu đã duyệt thì thêm vào `allowed` của manifest hoặc `EXCEPTIONS` + Register |
| `uv sync --frozen` | `uv.lock` lệch `pyproject.toml` | `uv lock` rồi commit |
| Lint | Chưa format | `uv run ruff format .`, `uv run ruff check --fix .` |
| Test chỉ đỏ trên Windows | Khác biệt đường dẫn/hoa thường | Chạy trên DIEP-ANH; xem TC-084, TC-085 |
| CodeQL `py/path-injection` | Dùng đường dẫn trước khi qua `require_read/write`, hoặc kiểm tra nằm trong hàm phụ | Giữ `realpath` + `startswith` inline (CLAUDE.md) |
| CodeQL upload lỗi "Code scanning is not enabled" | Repo chuyển sang private | Giữ repo public (CodeQL miễn phí chỉ cho public) |

### RB-06 `uv sync` lỗi Python

`requires-python = ">=3.12,<3.15"`: không dùng Python 3.15. `uv python install 3.12`, file `.python-version` đã ghim 3.12.

## 3. Nhật ký thay đổi cần biết khi tra sự cố

Sau Phase 0, core 0.2 đã đổi các vùng sau (đọc tài liệu Phase 1 khi sự cố nằm ở đây): `ToolContext` thêm `data_dir`, `settings`, `channel` (PR #3); phê duyệt theo tầng và audit log `approval.py` (PR #5); `grants.py`, Gate, MCP elicitation, `lfmap approvals` (PR #6). Runbook này mô tả hành vi tại `f63f0ee`.
