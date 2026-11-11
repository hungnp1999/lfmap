# Bàn giao: `lfmap doctor` kiểm tra Windows Security (#198, S3)

Issue: [#198](https://github.com/hungnp1999/lfmap/issues/198) (exec:CC, P2, security-review, Phase 2a). Gộp vào `lfmap doctor` của #195 K3 (đã merge, PR #253). Môi trường: Cloud (Claude Code, Sonnet) cho code; một bước xác minh thật trên pc-01 (DIEP-ANH) do Hùng chạy. Không dùng thẻ AG (Hùng 11/11).

## Mục tiêu

`lfmap doctor` có thêm nhóm `security`, **chỉ đọc**, báo:

1. Microsoft Defender real-time protection đang bật hay tắt.
2. Controlled Folder Access (CFA) bật/tắt/audit, và có phủ các thư mục của chủ: các thư mục khai trong `[paths]` của `config.toml`, thư mục app `%LOCALAPPDATA%\lfmap`, thư mục `[backup] folder` (#196).

Không bao giờ đổi cài đặt hệ thống. Chỉ công cụ có sẵn của Windows. Không thêm dependency. Ngoài Windows: nhóm `security` ghi một dòng "skipped (Windows only)" và không ảnh hưởng exit code.

## Quyết định đã chốt (đảo ngược được, đã ghi)

- **Không FAIL.** Mọi phát hiện của nhóm này là `warn` (`ok=None`), exit code của `lfmap doctor` không đổi. Lý do: Defender có thể tắt hợp lệ khi có antivirus bên thứ ba; CFA mặc định tắt (tính năng tự chọn). Phương án loại: FAIL khi Defender tắt (báo động giả).
- **Nguồn dữ liệu:** một lệnh `powershell.exe -NoProfile -NonInteractive -Command <script cố định>` chạy `Get-MpComputerStatus` và `Get-MpPreference`, in JSON (`ConvertTo-Json`). Script là hằng số trong code, **không ghép chuỗi từ đường dẫn hay cấu hình**. Đường dẫn tuyệt đối trong System32 (dùng lại `_system_tool` kiểu `jobs_doctor.py`: `WindowsPowerShell\v1.0\powershell.exe`), không tìm trên PATH. Phương án loại: đọc registry `HKLM\SOFTWARE\Microsoft\Windows Defender\...` (bị Group Policy/Tamper Protection che, kết quả có thể sai); WMI (thêm bề mặt, không đơn giản hơn).
- **Giá trị cần xác minh trên máy thật** (agent không được đoán, bước 5 bên dưới): `RealTimeProtectionEnabled` (bool) từ `Get-MpComputerStatus`; `EnableControlledFolderAccess` từ `Get-MpPreference` (theo tài liệu Microsoft: 0 tắt, 1 bật, 2 chỉ audit, 3 chặn ghi vào disk sector, 4 audit disk sector) và `ControlledFolderAccessProtectedFolders` (danh sách thư mục người dùng thêm). Nếu tên trường khác thực tế: dừng và báo, không sửa theo trí nhớ.
- **"Phủ" nghĩa là:** thư mục nằm trong (hoặc bằng) một thư mục CFA bảo vệ. Tập bảo vệ = thư mục người dùng thêm + mặc định của CFA (Documents, Pictures, Videos, Music, Favorites, Desktop trong profile). So sánh chuỗi sau `os.path.normcase`/`normpath`, từng phần tử đường dẫn (không so tiền tố chuỗi: `C:\Docs2` không nằm trong `C:\Doc`). Thư mục profile được chuyển hướng sang OneDrive nằm ngoài giới hạn: ghi vào `docs/KNOWN_LIMITATIONS` hoặc phần Rủi ro của PR, không cố đoán.
- Thư mục chưa khai (`[backup]` vắng, `[paths]` rỗng) thì bỏ qua mục đó, không lỗi. `[backup] folder` sai định dạng: dùng chuỗi thô, không gọi `backup.settings` (hàm đó có thể ném lỗi và doctor không được vỡ).
- Lỗi chạy PowerShell (không có, exit khác 0, JSON hỏng, hết thời gian): một check `unknown` dạng `warn`, kèm lý do. Có timeout (đề xuất 20 giây).

## Phạm vi file

- Mới: `packages/lfmap-core/src/lfmap_core/security_doctor.py` (khoảng 100 dòng code, hàm thuần cho phần phân tích để test không cần Windows).
- Sửa: `cli.py` (chỉ hàm `doctor_command`: thêm nhóm `security` ở cả đầu ra thường và `--json`, khóa JSON mới `"security"`), `ARCHITECTURE.md` (dòng module map lfmap-core + một câu invariant: doctor không bao giờ đổi cài đặt Windows), `packages/lfmap-core/README.md` nếu nhắc doctor, `docs/jobs.md` hoặc `docs/` chỗ đang mô tả `lfmap doctor` (nếu có).
- Mới: `packages/lfmap-core/tests/test_security_doctor.py`, `changelog.d/198-windows-security.added.md`.
- Không chạm: `permissions.py`, `approval.py`, `jobs_doctor.py` (chỉ import `_system_tool` nếu cần; nếu cần đổi tên hoặc chuyển, dừng và báo), `.claude/`, `pyproject.toml`.
- Cần file ngoài danh sách hoặc `security_doctor.py` quá 140 dòng code: dừng và báo.

## Thiết kế

```python
@dataclass(frozen=True)
class SecurityCheck:  # hoặc dùng lại jobs_doctor.Check (ok: True|None, name, detail, fix)
```

Ưu tiên dùng lại `jobs_doctor.Check` để đầu ra thống nhất. Các check:

| name | ok | khi nào |
| --- | --- | --- |
| `defender_realtime` | True | real-time bật |
| | None | tắt hoặc không đọc được; fix: "Windows Security > Virus & threat protection > Manage settings" |
| `cfa_enabled` | True | `1` |
| | None | `0` (tắt), `2` (chỉ audit), hoặc `3`/`4`/không đọc được; nói rõ giá trị |
| `cfa_covers` | True | CFA bật và mọi thư mục khai đều được phủ |
| | None | CFA tắt (không đánh giá, nói "n/a"), hoặc liệt kê thư mục chưa được phủ + fix "Windows Security > Ransomware protection > Controlled folder access > Protected folders" |

Hàm thuần: `parse_status(text: str) -> Status`, `covered(folder: str, protected: list[str]) -> bool`, `evaluate(status, folders) -> list[Check]`; hàm chạy `run_checks(runner=_run_powershell)` tiêm được runner để test.

`cli.py`: `doctor_command` gọi `security_doctor.run_checks()` và in nhóm `security` sau `events`. `--json`: `"security": [ {name, ok, detail, fix}, ... ]` hoặc `{"skipped": "Windows only"}`. Cờ `ok` tổng của doctor **không** xét nhóm này.

## Test đóng băng (Cloud, không cần Windows)

Tên chính xác trong `tests/test_security_doctor.py`; kỳ vọng viết tay, không suy ra bằng logic đang test:

`test_defender_on_is_ok`, `test_defender_off_warns_not_fails`, `test_cfa_off_warns`, `test_cfa_audit_warns`, `test_cfa_on_covers_declared_folders`, `test_cfa_on_reports_uncovered_folder`, `test_default_protected_folders_count`, `test_sibling_prefix_is_not_covered` (`C:\Docs2` vs `C:\Doc`), `test_case_and_slash_insensitive`, `test_missing_backup_and_paths_skipped`, `test_powershell_missing_is_warn_unknown`, `test_bad_json_is_warn_unknown`, `test_non_windows_skipped`, `test_doctor_exit_code_unchanged_by_security_warns`, `test_doctor_json_has_security_group`, `test_script_is_constant_and_absolute_path` (lệnh gọi dùng đường dẫn System32 tuyệt đối và script không chứa đường dẫn người dùng).

Các test của `test_doctor_cli.py`, `test_jobs_doctor.py` hiện có chạy nguyên văn; trên Linux 7 ca `test_jobs_doctor` fail sẵn (đã biết).

## Tiêu chí hoàn thành

- `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` xanh (trừ 7 ca có sẵn trên Linux).
- Có test không tạo, không ghi gì ngoài `tmp_path`; không có lệnh nào ngoài một lần gọi PowerShell chỉ-đọc.
- Changelog fragment, `ARCHITECTURE.md` cập nhật cùng PR. Không sửa `CHANGELOG.md`.
- PR nháp, `Closes #198`, chạy `/security-review` (chạm subprocess) và trả lời từng phát hiện trong PR.
- Commit có `Dev-Environment: cloud` (hook cloud không tự thêm: thêm tay) và `Claude-Session:`.
- Bước 5 (Hùng, pc-01): chạy `uv run lfmap doctor` (hoặc runtime clone sau khi merge) và dán nhóm `security` vào #198; nếu tên trường PowerShell sai, mở lại.

## Rủi ro

- Tên trường/giá trị PowerShell sai so với máy thật (xử lý bằng bước 5 và test dùng JSON mẫu lấy từ máy thật nếu có).
- Máy có antivirus bên thứ ba: `Get-MpComputerStatus` có thể báo Defender ở chế độ passive: vẫn là `warn`, `detail` nên nói "có thể do antivirus khác".
- CFA mặc định phủ cả thư mục profile đã chuyển sang OneDrive hay không: chưa chắc, ghi giới hạn.
- Lệnh PowerShell chậm (vài giây): timeout 20 giây, doctor vẫn chạy tiếp.
- Hai agent khác cùng sửa `cli.py`/`ARCHITECTURE.md`: merge `origin/main` trước khi push.

## Câu hỏi mở

Không. (Cập nhật tài liệu dự án: không có; ghi lại giới hạn OneDrive trong PR.)

## Prompt khởi động (dán vào phiên Claude Code Cloud trên repo lfmap, model Sonnet)

```text
Work on lfmap issue #198 (https://github.com/hungnp1999/lfmap/issues/198): read-only Windows Security checks in `lfmap doctor`. Read docs/handoff/2026-11-11-doctor-windows-security-198.md on main first, then CLAUDE.md and the doctor_command in packages/lfmap-core/src/lfmap_core/cli.py (lfmap doctor already exists, PR #253). Branch from up-to-date main; merge origin/main again before push.

Scope: new packages/lfmap-core/src/lfmap_core/security_doctor.py (about 100 code lines, pure parse/evaluate functions plus an injectable runner), the doctor_command group `security` in cli.py (text and --json), new tests/test_security_doctor.py, ARCHITECTURE.md, changelog.d/198-windows-security.added.md. If you need another file or the module passes 140 code lines, stop and report.

Write the frozen tests first, with exactly the names listed in the handoff, with hand-written expectations. Rules: strictly read-only, one fixed PowerShell script (constant, no user data in the command line) run by absolute System32 path with a timeout; every finding is warn (ok=None), never FAIL, exit code of `lfmap doctor` unchanged; non-Windows is skipped; compare folders by normalised path components, not string prefix; do not guess PowerShell field names or values beyond the handoff: if unsure, state it in the PR. No new dependency.

Run uv run pytest, uv run ruff check ., uv run ruff format --check . (7 test_jobs_doctor failures on Linux are pre-existing). Commit trailers: Dev-Environment: cloud (add by hand) and Claude-Session. Draft PR from the template with "Closes #198", then run /security-review and answer every finding in the PR. Do not merge. Final summary to Hung in Vietnamese, everything else in English.
```

## Checklist review của thread (sau khi có PR)

- Diff chỉ gồm file trong phạm vi; `security_doctor.py` không quá 140 dòng code.
- Đủ 16 test tên đúng; test cũ không bị sửa; CodeQL xanh.
- Script PowerShell là hằng số; không có đường dẫn người dùng trong dòng lệnh; không ghi/đổi cài đặt.
- Exit code của `lfmap doctor` không đổi bởi nhóm `security`; `--json` có khóa `security`.
- `/security-review` đã chạy và trả lời. Kết luận: Approve / Approve with changes / Reject. Merge squash chỉ khi PR không phải draft.
