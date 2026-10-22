# Bàn giao: plugin `powershell` (Roadmap 1.6), 22/10 chiều

Spec: [`docs/specs/powershell.md`](../specs/powershell.md). Test viết sẵn: [`prep/2026-10-22-powershell/`](prep/2026-10-22-powershell/). Nếu code trên `main` không khớp với kế hoạch này, dừng lại và hỏi.

## Bối cảnh

Phase 1 còn ba hạng mục chưa làm: 1.2 Docling, 1.3 REST, 1.6 powershell. K14 đang chạy bench trên DIEP-ANH (GPU bận), Hùng ở văn phòng. 1.6 chạy được hoàn toàn trên Cloud: không thêm dependency, không cần GPU, CI Windows có sẵn `pwsh` để chạy test thật.

## Mục tiêu

Agent (MCP), CLI và job chạy được script PowerShell 7 do người dùng đưa vào allow-list, với tham số có kiểu và được kiểm tra. Không bao giờ chạy lệnh tùy ý. Kết quả Roadmap 1.6: "chạy script được duyệt từ MCP".

## Quyết định đã chốt (Claude, rủi ro thấp, không sửa ADR)

Chi tiết và phương án loại ở spec mục 2 (P1–P7). Tóm tắt:

- Allow-list nằm trong `config.toml` (`[plugins.powershell.settings.scripts.<id>]`). Không operation nào ghi file này, nên agent không tự thêm script được. Loại: file `scripts.toml` riêng, operation `add`.
- `run` là `external`, tức **T3** theo ADR-017 ("chạy lệnh ngoài"). Qua MCP chỉ chạy khi có quyền có thời hạn tạo ở terminal (`lfmap approvals grant powershell.run --tier T3 --for 2h`). Job thì vào hàng đợi approvals. Loại: tầng riêng cho từng script (phải sửa ADR-017, để sau nếu cần, cần Hùng duyệt).
- Mỗi script ghim SHA-256. Chạy bản sao đúng các byte đã kiểm, trong thư mục tạm của plugin, thư mục làm việc là thư mục của script.
- Đường dẫn script phải nằm trong `[paths] scripts` và đi qua `require_read` (chặn UNC trước I/O).
- Tham số có kiểu (`string`, `int`, `switch`, `choice`), truyền bằng danh sách đối số cho `pwsh -NoProfile -NonInteractive -NoLogo -File`. Không qua shell, không dùng `-Command`.
- Exit code khác 0 là kết quả bình thường. Quá thời gian thì kill cả cây tiến trình.

## Phạm vi

Trong: plugin mới `plugins/lfmap-powershell` (spec mục 6), nối vào workspace, `"scripts"` trong `FOLDER_NAMES`, README plugin, CHANGELOG.
Ngoài: tham số kiểu đường dẫn, tầng theo script, map exit code sang lỗi job, Windows PowerShell 5.1, REST.

## Thiết kế

Spec mục 3–7. API đã chốt từng hàm; test viết sẵn đã chạy xanh trên một bản cài tham chiếu (bỏ đi, không commit), kể cả hai test với `pwsh` 7.4 thật trên Linux.

## Danh sách task

| Task | Nội dung | Môi trường | Tiêu chí hoàn thành |
|---|---|---|---|
| PS1 (một phiên, cỡ M) | Toàn bộ plugin theo spec mục 6 | **Cloud** (Claude Code). Không giao qwen: có phần bảo mật (B6 chỉ cho card S) | Xem dưới |

Tiêu chí hoàn thành PS1:

1. Chép 3 file test từ `prep/2026-10-22-powershell/` sang `plugins/lfmap-powershell/tests/`, bỏ 2 dòng chú thích đầu. Không sửa test để cho qua; nếu thấy test sai, ghi lý do trong PR.
2. `uv run pytest` toàn bộ xanh; `ruff check` và `ruff format --check` sạch; `uv sync --no-dev` + `check_licenses.py` qua.
3. CI Windows xanh, gồm 2 test `test_real_pwsh_*` (chỉ chạy khi có `pwsh`; trên Cloud Linux chúng bị skip trừ khi phiên tự cài `pwsh`).
4. README plugin: cấu hình mẫu, lệnh lấy hash (`Get-FileHash`), lệnh grant, giới hạn (spec mục 7–8).
5. CHANGELOG `[Unreleased]`.
6. PR code: không tự merge. Báo thread "Task chạy tiếp chiều 22/10" review theo mục Rủi ro bên dưới rồi merge.

## Chuẩn bị sẵn

- Spec và test trong repo (PR docs này).
- Không cần dữ liệu, không cần DIEP-ANH. CI `windows-latest` có `pwsh`.
- Bản tham chiếu: `/mnt/project-files/lfmap-core/powershell-1.6/reference-src.patch` (chỉ để reviewer đối chiếu, không đưa cho phiên code).

## Rủi ro

- **Chạy lệnh với toàn quyền người dùng.** Plugin chỉ kiểm soát script nào và đối số nào. Giảm thiểu: T3, allow-list chỉ sửa tay, ghim hash, chạy bản sao. Review kiểm: không có `shell=True`, không có `-Command`, không có đường dẫn nào chưa qua `require_read`, bản sao bị xóa cả khi lỗi.
- **Quyền grant phủ mọi script** trong thời hạn của nó. Ghi trong README; giữ allow-list ngắn.
- **Đầu ra script về Claude.** Đã có `untrusted` và `notice`; README dặn không allow-list script in bí mật.
- **Mã hóa ký tự** trên Windows: script nên tự đặt UTF-8 (README).
- **Kill cây tiến trình trên Windows** chỉ kiểm được trên CI Windows (test timeout dùng Python làm tiến trình con).

## Câu hỏi còn mở

- Có muốn tầng riêng cho từng script (script chỉ đọc chạy không cần grant)? Cần ADR mới sửa ADR-017; chỉ làm nếu dùng thật thấy bất tiện.

## Cập nhật tài liệu dự án

- ROADMAP 1.6: "đang làm" khi PR code mở; ✅ khi merge.
- ROADMAP 1.3: đề xuất dời sang Phase 2 theo ADR-003 (REST chỉ bật khi có client: Tauri, n8n). Không ảnh hưởng Exit criteria Phase 1.
- DECISIONS: không có ADR mới. Nếu sau này cần tầng theo script thì thêm ADR sửa ADR-017.
- License Register: không có dependency mới.

## Prompt khởi động cho Claude Code

```text
Repo hungnp1999/lfmap, branch from up-to-date main. Task PS1: implement the new plugin
plugins/lfmap-powershell exactly as docs/specs/powershell.md says (Roadmap 1.6).
Read docs/handoff/2026-10-22-powershell-plan.md first; follow CLAUDE.md (security rules, English code).
1. Copy the three test files from docs/handoff/prep/2026-10-22-powershell/ to
   plugins/lfmap-powershell/tests/ and delete their first two comment lines. Do not weaken them.
2. Implement allowlist.py, runner.py, schemas.py, tool.py, lfmap.toml, pyproject.toml, README.md,
   LICENSE (copy the repo LICENSE) per spec section 6, and the workspace wiring
   (root pyproject, scripts/check_licenses.py WORKSPACE, "scripts" in lfmap_core.config.FOLDER_NAMES).
3. uv lock; uv run pytest; uv run ruff check . ; uv run ruff format --check .;
   uv sync --no-dev; uv run --no-sync python scripts/check_licenses.py; uv sync.
   Optional: install PowerShell 7 in the container so the two test_real_pwsh_* tests run.
4. CHANGELOG [Unreleased]. Open a PR "powershell: allow-listed script runner (Roadmap 1.6)".
   Do not merge it yourself; when CI and CodeQL are green, report back for review.
```
