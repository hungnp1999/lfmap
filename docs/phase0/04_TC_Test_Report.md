# LFMAP Phase 0 — Test Case và Báo cáo kiểm thử

Phiên bản 1.0 · 2026-10-19 · Mốc code `f63f0ee`

## 1. Chiến lược kiểm thử

| Mức | Công cụ | Phạm vi | Nơi chạy |
|---|---|---|---|
| Unit | pytest | Từng module core, plugin echo | Máy dev, CI |
| Tích hợp adapter | `typer.testing.CliRunner`, `MCPServer.list_tools/call_tool` trong tiến trình | CLI, MCP với plugin giả `fake-plugin` | Máy dev, CI |
| Discovery thật | entry point của `lfmap-echo` đã cài | Registry | Máy dev, CI |
| Smoke CLI | `lfmap echo say --text "xin chao" --json` | Cài đặt + CLI | CI Windows |
| Tĩnh | ruff, CodeQL `security-extended` | Toàn repo | CI |
| Chấp nhận (UAT) | Thủ công | Claude Code gọi `echo_say` qua MCP | DIEP-ANH, 2026-10-18 |

Fixture dùng chung (`packages/lfmap-core/tests/conftest.py`): `registry` chứa `fake-plugin` với `greet` (không tác dụng phụ, input phẳng) và `write` (`local_write`, input lồng `names: list[str]`); `external_registry` giống vậy nhưng `write` là `external`; `user_dirs` trỏ `LOCALAPPDATA`/`LFMAP_CONFIG` vào thư mục tạm.

Chạy lại: `uv run pytest` (toàn bộ) hoặc `uv run pytest packages/lfmap-core/tests/test_permissions.py -q` (một module).

## 2. Danh mục test case

Đường dẫn: `core-tests/` = `packages/lfmap-core/tests/`, `echo-tests/` = `plugins/lfmap-echo/tests/`.

### FR-01 Lỗi chuẩn — `core-tests/test_errors.py`

| TC | Test | Kiểm tra | Kỳ vọng |
|---|---|---|---|
| TC-001 | `test_to_dict` | `to_dict()` | Đủ 3 khóa đúng giá trị |
| TC-002 | `test_details_default_to_empty_dict` | `details=None` | `{}` |
| TC-003 | `test_str` | `str(error)` | `"code: message"` |
| TC-004 | `test_is_exception` | Kế thừa | Là `Exception` |

### FR-02/03 Tool, operation, invoke — `core-tests/test_tool.py`, `test_smoke.py`

| TC | Test | Kiểm tra | Kỳ vọng |
|---|---|---|---|
| TC-010 | `test_version` | `lfmap_core.__version__` | `0.1.0` |
| TC-011 | `test_operations` | `Tool.operations()` | Đúng tên, model, description từ docstring |
| TC-012 | `test_invoke` | Gọi hợp lệ | Output model đúng |
| TC-013 | `test_invoke_invalid_payload` | Payload sai | `invalid_input` có `details.errors` |
| TC-014 | `test_invoke_unknown_operation` | Tên không có | `not_found` |
| TC-015 | `test_bad_signature` | Method sai chữ ký | `TypeError` nêu tên method |
| TC-016 | `test_duplicate_operation` | Trùng tên operation | `TypeError` |
| TC-017 | `test_health_default` | `health()` | `{"ok": True}` |

### FR-04 Manifest — `core-tests/test_manifest.py`

| TC | Test | Kiểm tra | Kỳ vọng |
|---|---|---|---|
| TC-020 | `test_load_valid` | `fixtures/echo.lfmap.toml` | Đọc đủ trường, default đúng |
| TC-021 | `test_invalid_schema[4 tham số]` | `id` sai mẫu (`Echo_1`), `version` không SemVer, `side_effects` lạ, khóa gõ sai (`netwrok`) | `invalid_input` |
| TC-022 | `test_invalid_toml` | TOML hỏng | `invalid_input` |
| TC-023 | `test_missing_file` | Không có file | `not_found` |

### FR-05/11/12 Discovery, SDK, plugin echo — `echo-tests/test_tool.py`

| TC | Test | Kiểm tra | Kỳ vọng |
|---|---|---|---|
| TC-030 | `test_say` | SDK `say()` | Text giữ nguyên, `length` đúng |
| TC-031 | `test_say_upper` | `upper=True` | Viết hoa |
| TC-032 | `test_manifest_matches_tool` | `load_entry(EchoTool)` | Manifest khớp class |
| TC-033 | `test_discovered_through_entry_point` | `Registry.discover()` | Có plugin `echo` |

### FR-06/08 CLI — `core-tests/test_cli.py`

| TC | Test | Kiểm tra | Kỳ vọng |
|---|---|---|---|
| TC-040 | `test_plugins_list` | `plugins list --json` | `[{"id":"fake-plugin","version":"1.2.3","operations":["greet","write"]}]` |
| TC-041 | `test_generated_command` | `--name Hùng --times 2 --shout` | `message: HELLO HÙNG HELLO HÙNG` (Unicode, bool flag, int) |
| TC-042 | `test_json_output` | `--json` | JSON đúng |
| TC-043 | `test_missing_required_option` | Thiếu `--name` | Exit 2 |
| TC-044 | `test_tool_error_propagates` | Tool raise `ToolError` | Ngoại lệ mang `code=not_found` tới `main()` (ánh xạ exit 1) |
| TC-045 | `test_nested_input_uses_json_and_confirms` | Input lồng, `--input-json`; trả lời `n`; rồi `--yes` | Lần 1 abort exit 1; lần 2 chạy, `message: a,b` |

### FR-07/08 MCP — `core-tests/test_mcp_adapter.py`

| TC | Test | Kiểm tra | Kỳ vọng |
|---|---|---|---|
| TC-050 | `test_tool_name` | `fake-plugin`+`greet`; tên > 64 ký tự | `fake_plugin_greet`; `ToolError` |
| TC-051 | `test_list_tools_schema` | `list_tools` | Description, `required=["name"]`, đủ 3 thuộc tính |
| TC-052 | `test_call_tool` | Gọi `greet` | `structured_content` đúng |
| TC-053 | `test_call_tool_error` | Tool raise `not_found` | Lỗi MCP chứa `not_found` |
| TC-054 | `test_side_effects_denied_without_approval` | Gọi `write` chưa duyệt | `permission_denied ... --approve fake-plugin.write` |
| TC-055 | `test_side_effects_run_when_approved` | `--approve fake-plugin.write` | Chạy, kết quả đúng |
| TC-056 | `test_annotations_and_description` | Annotation, mô tả | `greet` read-only; `write` không read-only, có "Requires approval..." |
| TC-057 | `test_unknown_approval_refused` | `--approve fake-plugin.nope` | `invalid_input` khi dựng server |
| TC-058 | `test_external_cannot_be_pre_approved` | Duyệt trước op `external` | `invalid_input`; `openWorldHint=True` |

### FR-09 Config — `core-tests/test_config.py`

| TC | Test | Kiểm tra | Kỳ vọng |
|---|---|---|---|
| TC-060 | `test_missing_config_is_empty` | `LFMAP_CONFIG` trỏ file chưa có | `{}` |
| TC-061 | `test_invalid_toml` | TOML hỏng | `invalid_input` |
| TC-062 | `test_plugin_variables` | `[paths]` chuỗi và mảng; `data_dir` | Giá trị đúng, `tmp` được tạo |
| TC-063 | `test_paths_must_be_strings` | `[1]` | `invalid_input` |
| TC-064 | `test_network_path_in_config_refused` | `\\server\share` trong config | `permission_denied` |

### FR-10 Permission Manager — `core-tests/test_permissions.py`

| TC | Test | Kiểm tra | Kỳ vọng |
|---|---|---|---|
| TC-070 | `test_read_inside` | File và chính root | Trả `Path` đã resolve |
| TC-071 | `test_write_root_is_also_readable` | Đọc trong root ghi | Cho phép |
| TC-072 | `test_read_root_is_not_writable` | Ghi trong root đọc | `permission_denied` |
| TC-073 | `test_outside_and_dotdot` | Ngoài root; `data\..\secret.txt` | `permission_denied` |
| TC-074 | `test_sibling_prefix` | `data2` khi root `data` | `permission_denied` |
| TC-075..078 | `test_remote_paths[4 tham số]` | `\\host\share`, `//host/share`, `\\?\C:\`, `\\.\pipe` | `permission_denied` |
| TC-079 | `test_remote_root_refused` | Root mạng | `permission_denied` |
| TC-080 | `test_undefined_variable_grants_nothing` | Biến không có | Không root, từ chối |
| TC-081 | `test_list_variable_gives_one_root_per_value` | Biến mảng 2 giá trị | 2 root, root khác bị từ chối |
| TC-082 | `test_variable_inside_pattern` | `${documents}/sub` | Chỉ `sub` được phép |
| TC-083 | `test_relative_root_refused` | Root `docs` | `invalid_input` |
| TC-084 | `test_case_insensitive` | Viết hoa đường dẫn (chỉ Windows) | Cho phép |
| TC-085 | `test_symlink_escape` | Symlink trong root trỏ ra ngoài | `permission_denied` |
| TC-086 | `test_network` | `network=false`/`true` | Từ chối / cho phép |

### Kiểm tra ngoài pytest

| TC | Bước | Kỳ vọng | Nơi |
|---|---|---|---|
| TC-090 | `uv sync --frozen --no-dev` + `check_licenses.py` | Không `FAIL`, exit 0 | CI |
| TC-091 | `ruff check .`, `ruff format --check .` | Sạch | CI |
| TC-092 | `lfmap echo say --text "xin chao" --json` | JSON `{"text": "xin chao", "length": 8}` | CI |
| TC-093 | CodeQL Python + Actions | Không cảnh báo mở | CI |
| TC-094 (UAT) | Claude Code desktop gọi `echo_say` với `upper` | Trả `XIN CHÀO` | DIEP-ANH 2026-10-18 17:08Z |
| TC-095 (UAT) | `ollama list` | Có `qwen2.5-coder:14b`, `bge-m3` | DIEP-ANH 2026-10-18 |

## 3. Kết quả

| Lần chạy | Môi trường | Kết quả |
|---|---|---|
| PR #1 merge (2026-10-18) | Windows (DIEP-ANH) | 47 pass |
| CI PR #2 (2026-10-18) | GitHub Actions `windows-latest` + CodeQL | Xanh (điều kiện merge) |
| Chạy lại khi lập tài liệu (2026-10-19) | Linux container, Python 3.12, commit `f63f0ee` | **59 pass, 1 skip** (TC-084 chỉ chạy trên Windows) |
| UAT MCP (2026-10-18) | Claude Code desktop trên DIEP-ANH | `echo_say` → `XIN CHÀO` |

Tổng: 60 test case pytest (54 hàm; `test_invalid_schema` và `test_remote_paths` mỗi hàm 4 tham số) + 6 kiểm tra ngoài pytest. Không có lỗi tồn đọng mức chặn.

## 4. Ma trận truy vết yêu cầu → test

| Roadmap | FR | Test case |
|---|---|---|
| 0.1 | NFR-01, NFR-04 | TC-091, toàn bộ suite chạy bằng `uv` |
| 0.2 | FR-01, 02, 03, 11 | TC-001..017, TC-030..031 |
| 0.3 | FR-04, 05, 12 | TC-020..023, TC-032..033 |
| 0.4 | FR-06 | TC-040..045, TC-092 |
| 0.5 | FR-07 | TC-050..058, TC-094 |
| 0.6 | FR-08, 09, 10 | TC-045, TC-054..058, TC-060..086 |
| 0.7 | FR-13, NFR-05, 07 | TC-090, TC-091, TC-093 |
| 0.8 | — | TC-095 |
