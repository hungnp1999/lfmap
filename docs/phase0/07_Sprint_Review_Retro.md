# LFMAP Phase 0 — Sprint Review, Release Notes và Retrospective

Phiên bản 1.0 · 2026-10-19

Phase 0 được coi là một Sprint/Increment theo Scrum. Vai trò Scrum trong dự án một người: **Product Owner** = Hùng; **Scrum Master / Planner / Reviewer** = Claude (Managing Agent); **Developers** = Hùng, model local qwen2.5-coder:14b, Claude.

## 1. Sprint Goal

"Có bộ khung để plugin đầu tiên chỉ cần viết logic": plugin `echo` chạy qua SDK, CLI, MCP và CI xanh (Exit criteria Roadmap Phase 0).

Kết quả: **Đạt** (2026-10-18 17:08Z, Claude Code desktop gọi `echo_say` → `XIN CHÀO`).

## 2. Sprint Backlog và kết quả

| Task Card | Roadmap | Việc | Người làm (theo kế hoạch) | Trạng thái | Bằng chứng |
|---|---|---|---|---|---|
| TC-00 | — | Tạo repo `lfmap`, chốt ADR | Hùng | Xong | Repo public, ADR 001–004, 008–010 Accepted 2026-10-18 |
| TC-01 | 0.8 | Ollama + model coder + embedding | Hùng | Xong | Ollama 0.40.1, qwen2.5-coder:14b (40.5 tok/s, 10.7/16 GB VRAM), bge-m3 (dim 1024) |
| TC-02 | 0.1 | Khung uv workspace | Hùng + local | Xong | `pyproject.toml`, `ruff.toml`, `.pre-commit-config.yaml` |
| TC-03 | 0.2 | `ToolError` | Local | Xong | `errors.py`, TC-001..004 |
| TC-04 | 0.2 | `Tool`, `@operation`, `invoke` | Local | Xong | `tool.py`, TC-010..017 |
| TC-05 | 0.3 | Manifest | Local | Xong | `manifest.py`, TC-020..023 |
| TC-06 | 0.3 | Discovery, `Registry` | Local | Xong | `registry.py`, TC-032..033 |
| TC-07a/b | 0.4 | CLI sinh tự động | Local / Claude | Xong | `cli.py`, TC-040..045 |
| TC-08 | 0.5 | MCP adapter | Claude | Xong | `mcp_adapter.py`, TC-050..058, TC-094 |
| TC-09 | 0.6 | Permission Manager | Local + review bảo mật | Xong | `permissions.py`, TC-070..086 |
| TC-10 | 0.3 | Plugin `echo` | Local | Xong | `plugins/lfmap-echo`, TC-030..031 |
| TC-11 | 0.7 | CI Windows + license + CodeQL | Local / Claude | Xong | `ci.yml`, `codeql.yml`, `check_licenses.py` |
| TC-12 | Exit | Kiểm tra Exit criteria | Hùng + Claude | Xong | Mục 1 |
| (PR #2) | 0.6 | Đóng 2 lỗ hổng quyền trong CLI/MCP | Claude | Xong | `config.py`; `--approve`; CHANGELOG mục Changed/Security |

Hạng mục bổ sung ngoài kế hoạch (PR #2): CLI/MCP trước đó dựng Permission Manager với biến rỗng, và MCP chạy operation có tác dụng phụ không cần duyệt. PR #2 đọc biến từ `config.toml` của người dùng và thêm `--approve`.

## 3. Increment

| Thành phần | Phiên bản | Commit |
|---|---|---|
| `lfmap-core` | 0.1.0 | `f63f0ee` |
| `lfmap-echo` | 0.1.0 | `f63f0ee` |
| PR | #1 "Add lfmap-core Phase 0 foundation and echo plugin" (`c08c673`), #2 "Close two permission gaps in the CLI and MCP adapters" (`f63f0ee`) | |

Release notes (tóm tắt CHANGELOG `[Unreleased]` tại `f63f0ee`):

- **Added:** uv workspace; `lfmap-core` 0.1.0 (`Tool`, `@operation`, `invoke`, `ToolError`, manifest, discovery, Permission Manager); CLI và MCP sinh tự động; plugin `lfmap-echo`; CI Windows + license check + CodeQL; `config.toml` người dùng; `lfmap serve mcp --approve`.
- **Changed:** biến quyền lấy từ config người dùng; biến mảng → nhiều root; biến không định nghĩa không cấp gì; root tương đối/mạng bị từ chối.
- **Security:** MCP từ chối operation có tác dụng phụ chưa duyệt; `external` không duyệt trước được.

Chưa gắn tag/release GitHub cho Phase 0 (không yêu cầu trong Exit criteria; phát hành là quyết định không đảo ngược, cần Hùng duyệt).

## 4. Definition of Done (DoD) áp dụng

| Tiêu chí | Đạt | Ghi chú |
|---|---|---|
| Code merge vào `main` qua PR | ✅ | PR #1, #2 |
| Test tự động pass trên Windows | ✅ | CI `test` xanh trên PR #2 |
| Lint + format sạch | ✅ | Bước Lint trong CI |
| CodeQL không cảnh báo mới | ✅ | `analyze` + `CodeQL` success |
| Giấy phép dependency hợp lệ | ✅ | Bước License check |
| CHANGELOG cập nhật | ✅ | `[Unreleased]` |
| README hướng dẫn dùng | ✅ | Quick start, folders and approvals |
| ADR liên quan Accepted | ✅ | 001–004, 008–010, 014 |
| Tài liệu bàn giao giai đoạn | ✅ | Bộ tài liệu này (bổ sung 2026-10-19) |

## 5. Retrospective

**Làm tốt**

- Chia Task Card nhỏ, có test cho trước giúp model local làm được phần lớn code, tiết kiệm hạn mức Claude gói Pro.
- Tái dùng bài học từ MarkitdownTool (mẫu `MCPServer` của `mcp==2.3.0`, kiểm tra đường dẫn kiểu `ensure_allowed_path`) rút ngắn phần khó nhất.
- Kiểm chứng sớm mâu thuẫn tên tool MCP (dấu chấm) và chốt ADR-014 trước khi code lan rộng.
- Review bảo mật sau merge phát hiện 2 lỗ hổng quyền và sửa ngay trong PR #2.

**Cần cải thiện**

- Lỗ hổng quyền lọt qua PR #1: test adapter không đi qua đường đọc `config.toml` như khi chạy thật (suy ra từ nội dung PR #2). Bài học: test tích hợp adapter phải đi qua đúng đường dựng quyền như khi chạy thật.
- Repo từng bị chuyển private làm CodeQL lỗi upload. Quy tắc: giữ public.
- Bộ tài liệu giai đoạn làm sau khi Phase đã đóng. Từ Phase 1: tài liệu giai đoạn là một mục trong DoD của Phase, viết dần theo PR.

**Hành động**

| # | Hành động | Chủ trì | Khi nào |
|---|---|---|---|
| A1 | Thêm "cập nhật tài liệu giai đoạn" vào checklist PR của Phase 1 | Claude | Phase 1 |
| A2 | Test tích hợp adapter dùng `user_dirs` + config thật | Claude / local | Đã áp dụng từ PR #2 |
| A3 | Viết bộ tài liệu Phase 1 trên khung của bộ này (cùng tên file, cùng mã FR/TC/RB) | Claude | Cuối Phase 1 |

## 6. Việc chuyển sang Phase sau (Product Backlog)

| Mục | Nguồn | Đích |
|---|---|---|
| `ToolContext` thêm `data_dir`, `settings`, `channel` | L1 | core 0.2 — xong PR #3 |
| Phê duyệt theo tầng T0–T3 + audit log (ADR-017) | L6 | core 0.2 — xong PR #5, #6 |
| TC-C1/C3 còn lại, TC-C5 | Kế hoạch core 0.2 | qwen, tối 2026-10-19 |
| Kiểm tra `exec`, `cloud_ai` | L2 | Roadmap 1.6 |
| Đối chiếu `min_core_version`, `input`/`output` manifest với code | L3 | Backlog core |
| REST adapter | L7 | Roadmap 1.3 |
| TOCTOU / junction | L5 | Backlog bảo mật |
