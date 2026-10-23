# Bàn giao: REST adapter (Roadmap 1.3), 23/10 sáng

Spec: [`docs/specs/rest.md`](../specs/rest.md). Test viết sẵn: [`prep/2026-10-23-rest/`](prep/2026-10-23-rest/). Nếu code trên `main` không khớp với kế hoạch này, dừng lại và hỏi.

**Trạng thái: thiết kế xong, CHƯA code.** Hùng chốt 2026-10-23 02:09Z: giữ ADR-003, đợi Phase 2. Task R1 chỉ bắt đầu vào đầu Phase 2, khi n8n hoặc Tauri UI cần REST. Đến lúc đó kiểm lại phiên bản FastAPI/Starlette/Uvicorn trong `uv.lock` trước khi chạy test chuẩn bị sẵn.

## Bối cảnh

Phase 1 đã nghiệm thu (22/10); 1.2 Docling và 1.3 REST dời sang Phase 1b. lfmap-core đã có hai adapter sinh tự động: CLI (Typer) và MCP (stdio). Kênh `rest` đã có sẵn trong `Channel` của core, và `lfmap-knowledge` đã coi `rest` là kênh ra ngoài (ẩn root secret, ghi `egress_log`). Manifest đã có `[adapters] rest`, mặc định `false`. Còn thiếu: chính adapter và lệnh `lfmap serve rest`.

## Mục tiêu

Mọi operation của plugin bật `rest = true` thành `POST /tools/<plugin>/<operation>` trên server local, cùng Tool Spec với CLI/MCP (ADR-001), không có code riêng cho plugin nào. Kết quả Roadmap 1.3: "OpenAPI tại `/docs`".

## Quyết định đã chốt (Claude, rủi ro thấp, không sửa ADR)

Chi tiết và phương án loại ở spec mục 2 (R1–R9) và mục 8. Tóm tắt:

- **FastAPI + Uvicorn.** Chỉ thêm đúng một package mới (`fastapi`, MIT): Starlette và Uvicorn đã có trong `uv.lock` qua `mcp==2.3.0`. Khớp Blueprint, Plugin Contract §5 và License Register. Loại: stdlib `http.server` (không thêm gì nhưng tự viết routing, validate, OpenAPI), Starlette trần (phải tự sinh OpenAPI, và phải sửa chữ trong Plugin Contract).
- **Chỉ 127.0.0.1**, không có `--host`. Loại: mở ra LAN khi chưa có client.
- **Luôn cần bearer token** cho `/tools/`. Token tự sinh ở `%LOCALAPPDATA%\lfmap\rest_token`; muốn đổi thì xóa file rồi chạy lại. Kiểm tra theo thứ tự: Host loopback (chống DNS rebinding) → không nhận request có `Origin` (trình duyệt) → token (trước khi định tuyến) → `Content-Type: application/json`, tối đa 1 MiB. Không trả header CORS. Cùng mô hình với `api_server.py` của MarkitdownTool.
- **Tầng phê duyệt trên REST** (ADR-017 áp đúng như viết, không cần ADR mới): REST không hỏi người được (HTTP không có kênh ngược). T0 chạy; T1 chạy và ghi audit; **T2 từ chối** trừ khi có `serve rest --approve` (8 giờ, như MCP) hoặc grant; **T3 từ chối** trừ khi có grant tạo ở terminal hoặc đích đã duyệt trước. `--approve` không bao giờ phủ operation `external`. Loại: xác nhận qua HTTP (client là chương trình, tự trả lời được).
- **Lỗi** luôn là `{code, message, details}` với mã chuẩn của Plugin Contract §6; lỗi bất ngờ trả 500 `internal` không kèm chi tiết.
- **`/docs` là trang HTML tự chứa** sinh từ OpenAPI: không JavaScript, không tải gì từ CDN. Tắt Swagger UI/ReDoc của FastAPI. Loại: Swagger UI (tải JS từ CDN vào trang mà người dùng dán token).
- **Chỉ `echo` bật `rest = true`** trong PR code. Plugin thật bật trong PR riêng khi có client cần (đúng ADR-003). `powershell` giữ `false`.

## Phạm vi

Trong: `lfmap_core/rest_adapter.py`, lệnh `lfmap serve rest`, dependency `fastapi`, `echo` bật REST, README lfmap-core (mục REST), CHANGELOG.
Ngoài: bật REST cho markitdown/knowledge/powershell, CORS/`allowed_origins` cho Tauri, bind LAN/Docker cho n8n, upload file, streaming, nhiều token.

## Thiết kế

Spec mục 3–6. API đã chốt từng hàm (`route`, `token_path`, `load_or_create_token`, `build_app`, `serve`). Test viết sẵn đã chạy xanh trên một bản cài tham chiếu (bỏ đi, không commit): 52/52 ca, toàn bộ suite 735 passed trên Linux.

## Danh sách task

| Task | Nội dung | Môi trường | Tiêu chí hoàn thành |
|---|---|---|---|
| R1 (một phiên, cỡ M) | `rest_adapter.py` + `serve rest` + dependency + echo bật REST | **Cloud** (Claude Code). Không giao qwen: có phần bảo mật (B6 chỉ cho card S). Không cần DIEP-ANH: CI Windows chạy test | Xem dưới |
| R2 (khi có client, cỡ S) | Bật `rest = true` cho plugin client cần, cộng test gọi thật | Cloud | Test qua REST cho từng operation bật |

Tiêu chí hoàn thành R1:

1. Chép `prep/2026-10-23-rest/test_rest_adapter.py` sang `packages/lfmap-core/tests/`, bỏ 2 dòng chú thích đầu. Không sửa test để cho qua; nếu thấy test sai, ghi lý do trong PR.
2. `uv run pytest` toàn bộ xanh; `ruff check` và `ruff format --check` sạch; `uv sync --no-dev` + `check_licenses.py` qua với `fastapi` mới.
3. CI Windows xanh, CodeQL không có cảnh báo mới.
4. Smoke test tay (Cloud): `lfmap serve rest --plugins echo`, gọi `POST /tools/echo/say` bằng `curl` có token → 200; không token → 401; `Host: evil.example` → 403; mở `/docs`.
5. README lfmap-core: lệnh, chỗ lấy token, ví dụ PowerShell (spec mục 4), các tầng trên REST. CHANGELOG `[Unreleased]`.
6. PR code: không tự merge. Thread lập kế hoạch review theo mục Rủi ro rồi merge.

## Chuẩn bị sẵn

- Spec và test trong repo (PR docs này).
- Không cần dữ liệu, không cần DIEP-ANH.
- Bản tham chiếu: `/mnt/project-files/lfmap-core/rest-1.3/` (`rest_adapter.py`, `cli-serve-rest.patch`, README). Chỉ để reviewer đối chiếu, không đưa cho phiên code.
- Giấy phép đã kiểm (PyPI, 23/10): fastapi 0.161.1 MIT; starlette 1.9.0 (lock: 1.8.0) BSD-3-Clause; uvicorn 0.54.0 BSD-3-Clause; annotated-doc 0.0.5 MIT.

## Rủi ro

- **Một cổng mở trên máy.** Process nào chạy dưới user cũng đọc được file token. Giảm thiểu: chỉ loopback, Host/Origin check, chỉ plugin bật `rest`, T2/T3 không chạy nếu chưa duyệt. Review kiểm: token so bằng `hmac.compare_digest`, kiểm token trước khi định tuyến, không có `--host`, lỗi 500 không lộ chi tiết, không ghi token ra log.
- **FastAPI 0.x đôi khi phá vỡ API giữa các bản minor.** `uv.lock` ghim bản; test chuẩn bị sẵn bắt lỗi khi nâng.
- **Bảo trì một adapter không ai dùng** nếu code ngay. Đây là lý do khuyến nghị đợi client (Câu hỏi 1).
- **Kênh `rest` trả nội dung tài liệu** (knowledge search) cho bất kỳ ai có token khi plugin đó bật REST. Đã có ẩn root secret và `egress_log`; quyết định bật cho knowledge thuộc R2.

## Câu hỏi còn mở

1. ~~Code R1 bây giờ hay đầu Phase 2?~~ Đã chốt (Hùng, 2026-10-23): đầu Phase 2, khi n8n hoặc Tauri cần REST. ADR-003 giữ nguyên.
2. **n8n chạy trong Docker** không gọi được 127.0.0.1 của máy (nó dùng `host.docker.internal`). Khi dùng n8n: chạy n8n trực tiếp (`npx n8n`) trên loopback, hoặc ADR mới cho bind Docker/LAN. Liên quan ADR-005 (Proposed).
3. **Tauri UI** gửi `Origin` riêng; Phase 2 chọn giữa `[rest] allowed_origins` trong config.toml hoặc gọi SDK trực tiếp qua sidecar Python (không cần REST).

## Cập nhật tài liệu dự án

- ROADMAP 1.3: dời sang đầu Phase 2 (Hùng chốt 2026-10-23); ghi "thiết kế xong, code khi n8n/Tauri cần (ADR-003)"; ✅ khi PR R1 merge.
- DECISIONS: không có ADR mới. ADR-003 giữ nguyên.
- Plugin Contract §5: ghi "OpenAPI tại `/openapi.json`, `/docs` là trang tĩnh không JS" và §2 "lfmap-core chỉ phục vụ plugin có `rest = true`, luôn cần token, chỉ loopback".
- License Register: sửa dòng FastAPI (thêm phiên bản 0.161.x, "dependency của lfmap-core, adapter REST"); thêm dòng Starlette (BSD-3-Clause, Ship, đã có qua mcp), Uvicorn (BSD-3-Clause, Ship, đã có qua mcp), annotated-doc (MIT, Ship, đã có qua Typer).

## Prompt khởi động cho Claude Code

```text
Repo hungnp1999/lfmap, branch from up-to-date main. Task R1: implement the REST adapter in
lfmap-core exactly as docs/specs/rest.md says (Roadmap 1.3).
Read docs/handoff/2026-10-23-rest-adapter.md first; follow CLAUDE.md (security rules, license check,
English code).
1. Copy docs/handoff/prep/2026-10-23-rest/test_rest_adapter.py to packages/lfmap-core/tests/ and
   delete its first two comment lines. Do not weaken the tests; if one is wrong, say why in the PR.
2. Add "fastapi>=0.161.1" to packages/lfmap-core/pyproject.toml, run uv lock, and check that
   `uv sync --no-dev; uv run --no-sync python scripts/check_licenses.py` passes.
3. Write packages/lfmap-core/src/lfmap_core/rest_adapter.py (spec section 5) and `lfmap serve rest`
   in cli.py next to `serve mcp`. Bind 127.0.0.1 only; no --host option.
4. Set `rest = true` in plugins/lfmap-echo's manifest only.
5. README of lfmap-core (REST section), CHANGELOG [Unreleased].
6. uv run pytest; ruff check .; ruff format --check .; smoke test with curl (handoff criterion 4).
Open a PR (not draft when ready). Do not merge: the planning thread reviews it.
```
