# Handoff: Agent chạy bằng tài khoản Windows riêng (ADR-023)

- Ngày: 2026-10-30
- Liên quan: ADR-023 (Accepted 2026-10-30), ADR-017, ADR-018, issue #108, PR #107, PR #109
- Người duyệt: anh Hùng (gate:po cho AA-3, vì chạm luồng job và bất biến bảo mật)

## Bối cảnh

ADR-023 yêu cầu ranh giới tự cấp quyền phải do hệ điều hành giữ. Ngày 30/10 có hai kết quả:

1. **Spike Windows Hello trên pc-01.** Kết quả lưu ở `D:\Tmp\hello-spike\results.md`.
   - Hộp thoại do `CredentialUIBroker.exe` sở hữu, integrity 0x200A. Một process cùng tài khoản ở mức Medium không đọc được hộp thoại qua UI Automation, không bấm được OK/Cancel, còn `PostMessage` thì bị UIPI chặn.
   - Hộp thoại nằm trên desktop Default, không phải secure desktop. Vì vậy PIN vẫn có thể bị keylog.
2. **Lỗ lớn hơn ở file.** `grants.json`, `config.toml` và `jobs.toml` nằm trong `%LOCALAPPDATA%\lfmap` của anh Hùng. Một agent cùng tài khoản ghi thẳng vào các file này được, không cần qua CLI. Vì vậy chỉ thêm Hello vào CLI thì chưa đủ.

Anh Hùng chọn (05:36Z): **tài khoản agent riêng + ACL**.

## Mục tiêu

- Mọi Working Agent trên pc-01 chạy bằng tài khoản chuẩn `lfmap-agent`, không có quyền admin: Claude Code (local và Remote Control), Antigravity, qwen-loop.
- Agent không ghi được dữ liệu, cấu hình, quyền và bí mật của tài khoản người.
- Không đoạn code nào do agent sửa được tự chạy dưới tài khoản người khi chưa qua review.

## Quyết định đã chốt

1. Tài khoản `lfmap-agent` là local standard user. Mật khẩu do anh Hùng đặt và cất. Không có trong repo hay trong memory.
2. **Ranh giới chính là hồ sơ người dùng (profile) của Windows.** Tài khoản chuẩn không đọc được `C:\Users\<người>`. Các file sau tự động nằm ngoài tầm agent: `%LOCALAPPDATA%\lfmap` của người (config, grants, jobs, approvals, audit), Credential Manager, khóa SSH và token của người.
3. Agent dùng `%LOCALAPPDATA%\lfmap` của chính nó. Ở đó nó tự có config và grants, nhưng chỉ chạm được những gì tài khoản `lfmap-agent` được phép. Vì vậy **không cần kiểm tra SID trong `cli.py`** như bản nháp ADR đã đề xuất. Kiểm tra console (#107) và mã xác nhận (#109) vẫn giữ.
4. Thư mục agent được ghi: `D:\Development\*` và `D:\Tmp\`. Thư mục tài liệu của người: mặc định không cấp. Cần thì cấp chỉ-đọc, từng thư mục một, ghi vào sổ ở mục "Rủi ro".
5. **Mã chạy dưới tài khoản người lấy từ bản runtime.** Bản này là `D:\lfmap-runtime` (một clone của `main`), ACL cho agent chỉ đọc. Job Task Scheduler (ADR-018) và MCP server do ứng dụng của anh Hùng mở đều trỏ vào đây, không trỏ `D:\Development\lfmap`. Anh Hùng cập nhật bằng `git pull --ff-only` khi `main` có PR đã merge.
6. Ollama giữ một bản cài, nghe ở loopback, dùng chung cho cả hai tài khoản. GPU dùng chung.
7. Git của agent:
   - Có khóa ký SSH riêng `git_signing_pc01_agent`, đăng ký trên GitHub, ghi vào `docs/DEVELOPMENT_PROVENANCE.md`.
   - Nhãn `Dev-Environment: pc-01` không đổi, vì cùng máy.
   - Đẩy code bằng fine-grained token chỉ cho 3 repo dự án, có hạn 90 ngày.

## Phạm vi

Trong phạm vi: tạo tài khoản, ACL, bản runtime, chuyển job/MCP sang runtime, chạy Claude Code và Remote Control bằng tài khoản agent, cập nhật tài liệu.

Ngoài phạm vi: Antigravity chuyển sau, khi hết thời gian thử nghiệm (12/11). Ký bản ghi bằng Hello cũng không làm.

## Danh sách task

| # | Việc | Ai | Ghi chú |
| --- | --- | --- | --- |
| AA-1 | Chạy script cài đặt bằng quyền admin: tạo `lfmap-agent`, ACL `D:\Development` và `D:\Tmp` (Modify), tạo `D:\lfmap-runtime` (agent Read & Execute), clone `main` vào đó | anh Hùng | Script: `/mnt/project-files/lfmap-core/agent-account/Setup-LfmapAgent.ps1`. Đọc trước khi chạy. Khoảng 15 phút |
| AA-2 | Đăng nhập tài khoản agent một lần: cài `uv`, Claude Code; `claude login`; tạo khóa ký và token GitHub; bật Remote Control cho `D:\Development\lfmap` | anh Hùng | Tạo khóa và token là việc của người (bí mật). Khoảng 20 phút |
| AA-3 | Code: `jobs.toml` có `[runtime] root` (mặc định `repo_root()` như hiện nay); `jobs register` ghi root vào lệnh Task Scheduler; `jobs doctor` cảnh báo khi root nằm trong thư mục mà tài khoản khác ghi được (đọc ACL bằng `icacls`, không thêm dependency) | Claude Code trên pc-01 | security-review, gate:po. Cập nhật ARCHITECTURE (bất biến), CHANGELOG, `docs/specs/jobs*` |
| AA-4 | Smoke dưới tài khoản agent: `uv sync`, `uv run pytest`, gọi Ollama, ghi thử vào `D:\Tmp`. Thử đọc `C:\Users\<người>\AppData\Local\lfmap` và Credential Manager của người: phải bị từ chối | Claude Code (tài khoản agent) | Ghi kết quả vào `docs/research/2026-10-30-agent-account-smoke.md` |
| AA-5 | Đăng ký lại job và MCP của anh Hùng sang `D:\lfmap-runtime`; `jobs doctor` sạch | anh Hùng + Claude | Sau AA-3 |
| AA-6 | Tài liệu: ADR-023 phần Hệ quả, `DEVELOPMENT_PROVENANCE.md` (khóa ký mới), `AGENTS.md` (Antigravity chuyển sau), memory dự án | Claude | Docs-only |

Thứ tự: AA-1 → AA-2 → AA-4 → AA-3 → AA-5 → AA-6. AA-3 có thể viết song song trên Cloud.

## Rủi ro

- **Hùng chạy `uv run` hay `git` trong `D:\Development\lfmap`.** Code hoặc hook mà agent đã sửa sẽ chạy dưới tài khoản người. Quy tắc: tài khoản người chỉ chạy lfmap từ `D:\lfmap-runtime`, review và merge trên GitHub. Nếu vẫn cần mở repo dev thì coi như chạy code chưa tin cậy.
- **Office/Microsoft 365 cấp phép theo người dùng.** Tài khoản agent có thể phải đăng nhập Office riêng để chạy route Office của MarkitdownTool. AA-4 sẽ kiểm tra.
- **Remote Control và Claude Code cần đăng nhập Claude riêng dưới tài khoản agent.** Cùng gói Pro. Hạn mức dùng chung.
- **Keylog PIN Windows Hello.** Không còn quan trọng, vì Hello không phải ranh giới đã chọn.
- **Sổ thư mục cấp cho agent.** Hiện chỉ có `D:\Development`, `D:\Tmp` và `D:\lfmap-runtime` (chỉ đọc).

## Câu hỏi còn mở

1. Thư mục tài liệu thật nào cần cấp chỉ-đọc cho agent (ví dụ thư mục mẫu của knowledge)? Mặc định là không thư mục nào.
2. Có giữ quyền admin cho tài khoản người hằng ngày không, hay tách thêm tài khoản admin? Đề xuất: giữ nguyên, ngoài phạm vi.

## Cập nhật tài liệu dự án

- `03_Decisions_ADR.md`, ADR-023: mục (2) ghi kết quả spike; mục (3) được chọn; sửa phần Hệ quả (bỏ kiểm tra SID, thêm bản runtime).
- `ARCHITECTURE.md`: bất biến "ranh giới tự cấp quyền là tài khoản Windows; tài khoản người chỉ chạy code từ bản runtime đã review".
- `AGENTS.md`, handoff Antigravity: Antigravity chuyển sang tài khoản agent sau thời gian thử nghiệm.

## Prompt khởi động cho Claude Code (AA-3)

> Đọc `docs/handoff/2026-10-30-agent-account.md` và ADR-023. Làm task AA-3 trên nhánh `feature/jobs-runtime-root`. Thêm `[runtime] root` vào `jobs.toml`, dùng nó trong `jobs register` và `scripts/Invoke-LfmapJob.ps1`, rồi thêm kiểm tra ACL vào `jobs doctor` qua `icacls` (đường dẫn tuyệt đối `%SystemRoot%\System32\icacls.exe`, không qua shell). Viết test cho cả hai, chạy `uv run pytest` và ruff, chạy `/security-review`. Mở PR nháp có `Closes` issue AA-3, gắn nhãn `gate:po`.
