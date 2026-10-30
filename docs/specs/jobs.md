> Bản sao trong repo của Task Card 1.8 (gốc: project files `lfmap-core/TaskCards_1.8_jobs.md`). Kế hoạch triển khai: `docs/handoff/2026-10-20-jobs-j1-j4.md`. Theo phương án A (2026-10-20), cả bốn card do Claude Code làm, không giao qwen.

# Roadmap 1.8 — Job theo lịch (ADR-018, Accepted 2026-10-18)

Vai: Planner. 4 Task Card TC-J1…J4, theo mẫu Task Card trong `06_Prompt_Playbook.md`.

**Thứ tự:** làm sau TC-C1…C5 (core 0.2, `phase1-specs/01_Core_Prereqs.md`), vì cần `config.toml`, `data_dir`, `channel`, `approver` và bảng quyết định T0–T3 + `audit.jsonl` của TC-C4. Nếu ADR-017 bị sửa khi chốt, TC-J3 phải sửa theo.

**Gói Pro:** J1, J2, J4 giao model local (`qwen2.5-coder:14b`); J3 đụng phê duyệt nên Claude review bắt buộc. Gộp review J1+J2, rồi J3+J4.

| TC | Việc | Ai | Cỡ | Phụ thuộc |
|---|---|---|---|---|
| TC-J1 | `scripts/Invoke-LfmapJob.ps1` + log JSON | L | S | TC-C1 |
| TC-J2 | `jobs.toml` + `lfmap jobs list/run/register` | L | M | TC-J1, TC-C2 |
| TC-J3 | Kênh `job` + hàng đợi `lfmap approvals` | L, Claude review | M | TC-C4, TC-J2 |
| TC-J4 | `lfmap jobs doctor` | L | S | TC-J2 |

Quy ước chung (dán kèm mỗi card):

```text
Repo: lfmap (uv workspace, Python 3.12, Windows). Code, comments, docstrings in English.
Standard library first. Small functions. Type hints everywhere.
Do NOT add dependencies, edit files outside "Target files", or change public signatures given here.
User data folder: %LOCALAPPDATA%\lfmap\ (os.environ["LOCALAPPDATA"], fallback Path.home() / "AppData/Local").
Files are UTF-8; tests must pass on Windows and must not touch the real Task Scheduler or LOCALAPPDATA (use tmp_path + env vars).
```

---

### TC-J1: Script chạy job
- File đích: `scripts/Invoke-LfmapJob.ps1`, `docs/jobs.md`
- Ngữ cảnh tối thiểu: CLI trả exit code 0 (thành công), 1 (ToolError), 2 (lỗi khác). Lệnh dạng `uv run --directory <repo> lfmap jobs run <id>` (TC-J2).
- Việc cần làm:
  - Tham số: `-JobId` (bắt buộc), `-RepoPath` (mặc định thư mục cha của script), `-UvPath` (mặc định `Get-Command uv`; nếu không thấy thì thử `$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe`; vẫn không có thì exit 2).
  - Chạy `& $UvPath run --directory $RepoPath lfmap jobs run $JobId --json`, giữ stdout và stderr.
  - Ghi một dòng JSON vào `$env:LOCALAPPDATA\lfmap\logs\jobs-YYYY-MM-DD.jsonl`: `started`, `finished` (ISO 8601), `job`, `exit_code`, `stdout` (cắt 4000 ký tự), `stderr` (cắt 4000 ký tự). Tạo thư mục nếu thiếu. Encoding UTF-8.
  - Trả đúng exit code của lệnh con.
  - `docs/jobs.md`: một đoạn giải thích script và ví dụ chạy tay.
- Không được: dùng đường dẫn tương đối tới uv; in bí mật ra log; thêm module PowerShell ngoài.
- Input/Output mẫu: `pwsh -File scripts\Invoke-LfmapJob.ps1 -JobId echo-hello` → exit 0, log có `"exit_code": 0`.
- Kiểm chứng: chạy tay với job `echo-hello` của TC-J2 và với `-JobId khong-co`, xem đúng exit code (0 và 1) và 2 dòng log.
- Độ khó: S

### TC-J2: Khai báo job và lệnh `lfmap jobs`
- File đích: `packages/lfmap-core/src/lfmap_core/jobs.py` (mới), `packages/lfmap-core/src/lfmap_core/cli.py` (chỉ thêm nhóm lệnh `jobs`), `packages/lfmap-core/tests/test_jobs.py`
- Ngữ cảnh tối thiểu (dán nguyên):
  ```toml
  # %LOCALAPPDATA%\lfmap\jobs.toml  (env LFMAP_JOBS overrides the path)
  [[jobs]]
  id = "echo-hello"                 # ^[a-z][a-z0-9-]*$, unique
  plugin = "echo"
  operation = "say"
  input = { text = "xin chào" }
  schedule = { daily = "07:30" }    # or { weekly = "MON 07:30" } or { every_minutes = 60 }
  max_tier = 0                      # 0 = only T0 runs; 1 = T1 runs and is audited (ADR-018)
  enabled = true
  ```
  `run_operation(entry, name, payload, channel=..., approver=...)` từ TC-C2.
- Việc cần làm:
  - Pydantic `Job`, `Schedule` (đúng một trong ba khóa), `JobsFile`; `extra="forbid"`. `load_jobs(path: Path | None = None) -> list[Job]`: thiếu file → `[]`; sai → `ToolError("invalid_input")`.
  - `lfmap jobs list [--json]`: id, plugin.operation, lịch, enabled.
  - `lfmap jobs run <id> [--json]`: chạy job qua `run_operation(..., channel="job", approver=<TC-J3>)`; trước TC-J3 dùng approver tạm từ chối mọi thứ trên T0. Job tắt → `ToolError("invalid_input")`.
  - `task_command(job, repo, uv, script) -> list[str]`: dựng lệnh `schtasks /Create /TN "\LFMAP\<id>" /TR "pwsh -NoProfile -File <script> -JobId <id>" /SC DAILY|WEEKLY|MINUTE ... /F`. Hàm thuần, không chạy gì.
  - `lfmap jobs register [--dry-run]`: với mỗi job bật, in lệnh (`--dry-run`) hoặc chạy `subprocess.run(task_command(...), check=False)`; job tắt hoặc đã xóa khỏi file → `schtasks /Delete /TN "\LFMAP\<id>" /F`. Chỉ đụng task trong thư mục `\LFMAP\`.
  - Đăng ký với tùy chọn chạy cả khi chưa đăng nhập cần mật khẩu Windows: chỉ in hướng dẫn trong `docs/jobs.md` (Task Scheduler → task → "Run whether user is logged on"), không nhận mật khẩu qua CLI.
- Không được: tự viết vòng lặp lập lịch; chạy `schtasks` trong test; dùng `--yes` khi gọi operation.
- Input/Output mẫu: `task_command(Job(id="echo-hello", schedule={"daily": "07:30"}, ...), ...)` chứa `"/SC", "DAILY", "/ST", "07:30"` và `"/TN", "\\LFMAP\\echo-hello"`.
- Kiểm chứng: `uv run pytest packages/lfmap-core/tests/test_jobs.py` (parse hợp lệ/lỗi, list, run echo qua registry giả, task_command cho 3 kiểu lịch); `uv run lfmap jobs register --dry-run`.
- Độ khó: M

### TC-J3: Kênh `job` và hàng đợi phê duyệt
- File đích: `packages/lfmap-core/src/lfmap_core/approvals.py` (mới), `approval.py` (TC-C4; chỉ thêm kênh `job`), `tool.py` (chỉ mở rộng `channel` Literal thêm `"job"`), `cli.py` (nhóm lệnh `approvals`), `packages/lfmap-core/tests/test_approvals.py`
- Ngữ cảnh tối thiểu: dán nguyên mục 4 "Phê duyệt theo tầng" của `phase1-specs/01_Core_Prereqs.md` và mục (3) của ADR-018.
- Việc cần làm:
  - Với `channel == "job"`: T0 → allow; T1 → allow + audit nếu `job.max_tier >= 1`, không thì như T2; T2/T3 → không chạy mà ghi đề xuất. Không bao giờ elicit, bỏ qua `preapproved`.
  - Đề xuất là file JSON `%LOCALAPPDATA%\lfmap\approvals\pending\<utc-ts>-<job>-<uuid8>.json`: `id`, `created`, `expires` (mặc định +7 ngày, đọc `config.toml` `[jobs] approval_ttl_days`), `job`, `plugin`, `operation`, `input`, `tier`, `reason`, `detail`. Nếu operation hỗ trợ `dry_run` thì gọi với `ctx.dry_run=True` và lưu `preview` (output dạng JSON, cắt 8000 ký tự). Kết quả lệnh job: `ToolError("permission_denied", "Queued for approval", {"approval_id": ...})`, exit 1.
  - `lfmap approvals pending [--json]` (chốt 2026-10-21; `approvals list` vẫn là danh sách grants): đề xuất còn hạn. Hết hạn → chuyển sang `approvals\expired\`.
  - `lfmap approvals approve <id>`: chỉ chạy ở CLI tương tác (`sys.stdin.isatty()`, không thì `permission_denied`); in tóm tắt, hỏi xác nhận, chạy lại đúng `plugin/operation/input` với `channel="cli"` và approver cho phép đúng một lần ở tầng đã ghi; ghi audit; chuyển file sang `approvals\done\`.
  - `lfmap approvals reject <id>`: chuyển sang `approvals\rejected\`, ghi audit.
  - Không lộ `approve` qua MCP (agent không được tự duyệt). `list` qua MCP để sau.
- Không được: nới roots/UNC; cho job dùng `--approve`; lưu nội dung tài liệu ngoài `preview` đã cắt; xóa file đề xuất (chỉ chuyển thư mục).
- Kiểm chứng: `uv run pytest packages/lfmap-core/tests/test_approvals.py`: bảng tầng × `max_tier` cho kênh job; FakeTool `write` (local_write) với `max_tier=0` tạo 1 đề xuất và không ghi file; approve trong CliRunner giả lập TTY ghi file và 1 dòng audit; approve khi không TTY bị từ chối; đề xuất hết hạn chuyển sang `expired`.
- Độ khó: M

### TC-J4: `lfmap jobs doctor`
- File đích: `packages/lfmap-core/src/lfmap_core/jobs_doctor.py` (mới), `cli.py` (lệnh `jobs doctor`), `packages/lfmap-core/tests/test_jobs_doctor.py`, `docs/jobs.md`
- Việc cần làm: mỗi kiểm tra trả `Check(name, ok: bool | None, detail, fix)` (`None` = không xác định). In bảng; `--json`. Exit 0 nếu không có `False`.
  - `uv`: tìm được `uv.exe` theo cùng luật TC-J1.
  - `jobs_file`: `jobs.toml` đọc được, mọi plugin/operation tồn tại trong registry.
  - `tasks`: `schtasks /Query /TN "\LFMAP\" /FO CSV` liệt kê đủ task cho mọi job bật.
  - `logon_mode`: `schtasks /Query /TN <task> /XML`, có `<LogonType>Password</LogonType>` hoặc `S4U` thì ok, `InteractiveToken` thì cảnh báo "chỉ chạy khi đã đăng nhập".
  - `wake`: XML có `<WakeToRun>true</WakeToRun>`.
  - `sleep`: `powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE`, báo giá trị AC; 0 = không ngủ.
  - `ollama`: `GET http://localhost:11434/api/version` (timeout 2 giây). Chỉ kiểm khi có plugin khai báo dùng Ollama.
  - Mỗi lệnh hệ thống chạy qua một hàm `_run(args) -> str` để test thay bằng giả.
- Không được: sửa bất kỳ thiết lập nào (doctor chỉ đọc); cần quyền admin.
- Kiểm chứng: `uv run pytest packages/lfmap-core/tests/test_jobs_doctor.py` với `_run` giả cho từng trường hợp ok/cảnh báo/lỗi; chạy thật `uv run lfmap jobs doctor` trên máy anh.
- Độ khó: S

## Exit của hạng mục 1.8

- Job `echo-hello` (T0) chạy đúng giờ khi máy đang ở màn hình khóa, có dòng log.
- Một job gọi operation `local_write` với `max_tier = 0` chỉ tạo đề xuất; `lfmap approvals approve` thực thi và ghi audit.
- `lfmap jobs doctor` không còn mục `False`.

## Addendum AA-3 (ADR-023, 2026-10-30): runtime root

Handoff `docs/handoff/2026-10-30-agent-account.md`, issue #114.

- `jobs.toml` accepts an optional `[runtime]` table with one key, `root`: an absolute path with a drive letter.
  UNC, `\\?\`, `\\.\`, `//`, relative and drive-relative paths and `"` are refused (`invalid_input`). Missing
  table or key: the root is `repo_root()`, the checkout `lfmap` runs from.
- `lfmap jobs register` uses `--repo`, else that root, for both `-File <root>\scripts\Invoke-LfmapJob.ps1` and
  `-RepoPath <root>` in the task action.
- `scripts/Invoke-LfmapJob.ps1` exits 2 when `-RepoPath` (full path, case-insensitive) is not the parent of its
  own `scripts` folder.
- `lfmap jobs doctor` adds `runtime_root` (FAIL: no runner script in the root; warn: a task's `<Arguments>` has
  no `-RepoPath "<root>"`) and `runtime_acl` (warn: an allow ACE on the root, effective or inherit-only, gives
  an account other than the current user, SYSTEM `S-1-5-18`, Administrators `S-1-5-32-544` or Creator Owner
  `S-1-3-0` any of write data, append, delete child, DELETE, WRITE_DAC, WRITE_OWNER, GENERIC_WRITE,
  GENERIC_ALL; an unknown rights code counts as write). The ACL comes from
  `%SystemRoot%\System32\icacls.exe <root> /save <temp file>` (UTF-16 SDDL, compared by SID) and the user from
  `%SystemRoot%\System32\whoami.exe /user /fo csv /nh`; both run as argument lists through `_run`, no shell.
