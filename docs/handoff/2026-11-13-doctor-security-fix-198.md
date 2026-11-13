# Bàn giao bổ sung: sửa nhóm `security` của `lfmap doctor` sau kiểm tra thật (#198)

Issue: [#198](https://github.com/hungnp1999/lfmap/issues/198) (mở lại 13/11). Bàn giao gốc: [2026-11-11-doctor-windows-security-198.md](2026-11-11-doctor-windows-security-198.md). Môi trường: Cloud (Claude Code, Sonnet), việc nhỏ. Một PR, `Refs #198` (đóng issue sau khi Hùng chạy lại trên pc-01).

## Kết quả kiểm tra thật trên pc-01 (13/11)

- `uv run lfmap doctor --json`: cả 3 check `security` là `unknown` vì PowerShell thoát mã 1.
- Chạy tay: `Get-MpPreference` lỗi `0x800106ba` (dịch vụ Defender không phục vụ yêu cầu). `Get-MpComputerStatus` chạy được và cho `AMServiceEnabled=False`, `AntivirusEnabled=False`, `RealTimeProtectionEnabled=False`. Dịch vụ `WinDefend` đang `Running`.
- `root/SecurityCenter2` `AntiVirusProduct` liệt kê hai sản phẩm: `Windows Defender` (`productState` 401664 = 0x62100) và `ESET Security` (`productState` 266240 = 0x41000).
- Kết luận: antivirus đang hoạt động trên DIEP-ANH là ESET; Defender ở trạng thái không phải antivirus chính, nên Controlled Folder Access (tính năng của Defender) không dùng được. Trạng thái này là **bình thường**, không phải lỗi.

## Vấn đề của code hiện tại

1. Một script gộp: một cmdlet lỗi làm mất cả hai kết quả, và lý do bị che (`CalledProcessError ... exit status 1`).
2. Chưa phân biệt "Defender tắt vì có antivirus khác" với "máy không có bảo vệ".
3. Không đọc `AntiVirusProduct`, nên không biết có antivirus khác.

## Quyết định đã chốt (đảo ngược được, đã ghi)

- Vẫn **chỉ đọc, không FAIL, exit code không đổi**.
- Thêm bước thứ ba vào cùng script cố định: `Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | Select-Object displayName, productState` (chỉ đọc; lỗi hoặc không có namespace trên Windows Server thì bỏ qua, không phải lỗi).
- Mỗi bước (Status, Preference, Products) bọc `try/catch` riêng; script in JSON `{"Status":..., "Preference":..., "Products":[...], "Errors":{"Status":..., "Preference":..., "Products":...}}`, mỗi lỗi chỉ lấy dòng đầu của thông báo, cắt 200 ký tự. Không đưa stderr thô vào kết quả.
- Giải mã `productState`: sản phẩm "đang bật" khi `(productState & 0xF000) == 0x1000`. Cách giải mã này suy ra từ hai số thật ở trên (ESET 0x41000 bật; Defender 0x62100 không bật) và từ kiến thức chung, **chưa kiểm với tài liệu Microsoft**: viết hằng số rõ ràng, nói trong PR là giả định, test bằng đúng hai số thật.
- Ngữ nghĩa mới:
  - `defender_realtime`: `True` nếu Defender real-time bật. Nếu tắt và có antivirus khác đang bật: `True` với detail "Defender real-time is off; <tên> is the active antivirus". Tắt và không có antivirus khác đang bật (hoặc không đọc được danh sách): `None` (warn) như hiện nay.
  - `cfa_enabled`: nếu `Preference` lỗi và `AMServiceEnabled` là False hoặc mã lỗi `0x800106ba`: `None` với "n/a: Defender is not the active antivirus, Controlled folder access is a Defender feature" (không báo "unknown").
  - `cfa_covers`: `n/a` như cũ khi CFA không bật.
  - Lỗi khác: `None`, detail "unknown: <dòng đầu của lỗi>".
- Cờ `AMServiceEnabled` thêm vào đối tượng `Status` của script.

## Phạm vi file

`packages/lfmap-core/src/lfmap_core/security_doctor.py` (hiện khoảng 130 dòng code; giới hạn mới 170, ghi trong `ARCHITECTURE.md`), `packages/lfmap-core/tests/test_security_doctor.py`, `ARCHITECTURE.md` (đổi con số 140 thành 170 và một cụm "knows an active third-party antivirus"), `docs/jobs.md` (một câu), `changelog.d/198-security-doctor-antivirus.changed.md`. Không chạm `cli.py` trừ khi bắt buộc (nếu cần, báo). Cần file khác hoặc quá 170 dòng: dừng và báo.

## Test đóng băng (viết trước, kỳ vọng viết tay)

Giữ nguyên các test hiện có (sửa mẫu JSON của `sample()` nếu cần, nhưng không đổi kỳ vọng). Thêm: `test_preference_error_keeps_status`, `test_status_error_keeps_preference`, `test_error_detail_is_first_line_only`, `test_defender_off_other_av_on_is_ok` (dùng đúng hai productState thật 401664 và 266240, tên `Windows Defender` và `ESET Security`), `test_defender_off_no_other_av_warns`, `test_cfa_na_when_defender_not_active`, `test_products_query_failure_is_not_an_error`, `test_script_still_read_only` (không có `Set-`, `Add-`, `Remove-`, `New-`, `Invoke-`, `Start-`, `Stop-`).

## Rủi ro

- Giải mã `productState` (đã nêu): nếu sai, sai chỉ làm doctor nói nhầm "ok" hoặc "warn", không gây hại hệ thống.
- Windows Server không có `SecurityCenter2`: được xử lý bằng bước 3 bọc `try/catch`.
- PowerShell 5.1 (`powershell.exe`) đọc `Get-CimInstance` bình thường; không dùng cú pháp chỉ có ở PowerShell 7.

## Câu hỏi mở

Không. (Cập nhật tài liệu dự án: không có.)

## Giao thức phiên (Hùng 13/11)

Mở PR **nháp ngay ở commit đầu tiên**. Báo cáo cuối đăng thành **comment trên PR**, dòng đầu là `DONE`. Thread sẽ review khi thấy `DONE` và CI xanh trên commit đầu của nhánh.

## Prompt khởi động (dán vào phiên Claude Code Cloud trên repo lfmap, model Sonnet)

```text
Follow-up fix for lfmap issue #198 (https://github.com/hungnp1999/lfmap/issues/198), a real run on the owner's machine showed the `security` group of `lfmap doctor` failing. Read docs/handoff/2026-11-13-doctor-security-fix-198.md on main first (it holds the findings, the decisions and the frozen test names), then docs/handoff/2026-11-11-doctor-windows-security-198.md and packages/lfmap-core/src/lfmap_core/security_doctor.py. Branch from up-to-date main; merge origin/main again before push.

Scope: security_doctor.py, tests/test_security_doctor.py, ARCHITECTURE.md (limit 140 -> 170 code lines and one phrase), docs/jobs.md (one sentence), changelog.d/198-security-doctor-antivirus.changed.md. If you need another file or pass 170 code lines, stop and report.

Write the frozen tests first with exactly the names in the handoff, hand-written expectations; use the two real productState values from the handoff. Rules: still strictly read-only with one fixed PowerShell script (constant, no user data); every finding is ok or warn, never FAIL, exit code of `lfmap doctor` unchanged; each cmdlet in its own try/catch so one failure keeps the others; error text is the first line only, cut to 200 characters; the productState decoding is an assumption, say so in the PR; do not guess other PowerShell facts.

Session protocol: open a DRAFT PR at your first commit (body "Refs #198"); post your final report as a PR comment whose first line is `DONE`. Run uv run pytest, uv run ruff check ., uv run ruff format --check . (7 test_jobs_doctor failures and 2 F401 in flows_triggers files on Linux/main are pre-existing). Commit trailers: Dev-Environment: cloud (add by hand) and Claude-Session. Run /security-review on the diff and answer findings in the PR. Do not merge. Final summary to Hung in Vietnamese, everything else in English.
```

## Checklist review của thread

- Diff chỉ gồm file trong phạm vi, `security_doctor.py` không quá 170 dòng code.
- Đủ 8 test mới tên đúng; test cũ không đổi kỳ vọng; CI và CodeQL xanh.
- Script vẫn chỉ đọc; không có đường dẫn người dùng trong dòng lệnh; lỗi chỉ lộ dòng đầu.
- Kết luận: Approve / Approve with changes / Reject. Sau merge: Hùng chạy lại `uv run lfmap doctor` trên DIEP-ANH và dán nhóm `security` vào #198.
