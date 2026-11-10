# Bàn giao: lớp dữ liệu nối vào tầng duyệt và mã TOTP (ADR-025, #197)

## Bối cảnh

- ADR-025 được anh Hùng chốt 2026-11-10 04:17Z: 4 lớp `scratch | normal | private | secret`, đường dẫn không khai = `private`, đọc `secret` ở T1 (ghi nhật ký, không hỏi), ghi vào `secret` ít nhất T2, mã TOTP cho lệnh tự cấp quyền.
- Đặc tả: [`docs/specs/data-classes.md`](../specs/data-classes.md). Việc này phải xong trước spec `organizer`.
- Mã liên quan đã có trên `main`: `approval.py` (Gate, `decide`, `audit`), `approvals.py` (JobApprover, ApprovedGate), `permissions.py`, `runtime.py`, `tool.py`, `cli.py` (`_require_code`), `models_router.py` (PR #221, #225, #226), `lfmap-knowledge` (`root_sensitivity`).

## Mục tiêu

Chủ máy khai mức quan trọng của từng thư mục một lần trong `config.toml`; cổng duyệt dùng thông tin đó để hỏi ít hơn ở dữ liệu nháp và bảo vệ chặt hơn ở dữ liệu mật; `knowledge` và ModelRouter dùng chung một bảng; lệnh tự cấp quyền hỏi mã 6 số từ điện thoại.

## Quyết định đã chốt

| Quyết định | Nguồn | Phương án loại |
| --- | --- | --- |
| 4 lớp, mặc định `private`; đọc `secret` = T1 | ADR-025, Hùng 10/11 | 3 lớp + cờ `scratch`; đọc `secret` = T2 |
| Lớp chỉ đặt trong `config.toml` của chủ; hạ lớp cần TTY + mã | ADR-025 (3) | Nhãn trong catalog `knowledge` |
| TOTP RFC 6238 bằng thư viện chuẩn, khoá mã hoá DPAPI | ADR-025 (4) | Thư viện ngoài; passkey (để Phase 3, #199) |

Bảy quyết định thiết kế thêm của spec (mục 14 của spec) là loại đảo ngược được, Claude đã tự chọn và ghi lý do. Hai điểm anh Hùng nên đọc trước khi chốt file này:

1. **Chỗ nối vào cổng (G1).** ADR ghi "một lời gọi trong `approval.py`", nhưng cổng không nhìn thấy đường dẫn. Spec nối ở `PermissionManager` (nâng tầng cho `secret`, plugin không bỏ qua được) và ở `ctx.require_approval(paths=...)` (hạ tầng cho `scratch`, plugin phải tự khai). Khối lượng vì thế lớn hơn ước lượng "khoảng 60 dòng" của ADR.
2. **TOTP không chặn được tiến trình chạy bằng chính tài khoản của anh** (spec mục 9.6). Ranh giới vẫn là tài khoản `lfmap-agent` (ADR-023). TOTP chỉ thêm một lớp.

## Phạm vi

Trong phạm vi: DC-1 đến DC-5 và DC-7. Ngoài phạm vi: nhãn đi theo output của bước flow (DC-6, làm sau), bỏ `allow_cloud_unlabelled`, bật route cloud, mã QR khi đăng ký, passkey, spec `organizer`.

## Thiết kế

Xem spec. Tóm tắt một dòng cho mỗi phần: `data_classes.py` là hàm thuần (bảng lớp, `adjust`); `data_guard.py` nhận sự kiện đường dẫn từ `PermissionManager` và gọi approver với tầng đã điều chỉnh; audit thêm `data_class`, `action_tier`; `totp.py` + `auth.py` lo mã 6 số; ModelRouter lấy lớp cao nhất giữa lớp plugin khai và nhãn của lời gọi.

## Danh sách task

Roadmap: Phase 2 (lõi security S1). Mỗi task một Issue, một PR, một phiên. Tất cả chạy **Cloud** (không cần Office/GPU), trừ DC-7.

| Task | Loại | Ưu tiên | Blocked by | Model đề xuất | Cổng |
| --- | --- | --- | --- | --- | --- |
| DC-1 `data_classes.py` | [CC] | P1 | file này được chốt | Sonnet | không |
| DC-2 guard, audit, `markitdown.export` | [CC] | P1 | DC-1 | **Opus** (đụng cổng duyệt; anh Hùng quyết) | `security-review` |
| DC-3 TOTP | [CC] | P1 | không (song song với DC-1/DC-2) | Sonnet | `security-review` |
| DC-4 lệnh `lfmap data`, doctor | [CC] | P2 | DC-1, DC-3 | Sonnet | `security-review` (ghi `config.toml`) |
| DC-5 `knowledge` + ModelRouter | [CC] | P2 | DC-2 | Sonnet | `security-review` |
| DC-6 nhãn qua bước flow | [CC] | P3 | DC-5; mở Issue riêng, chưa có thẻ | Opus | gate:po khi muốn bỏ `allow_cloud_unlabelled` |
| DC-7 cài đặt trên pc-01 | [PO] | P2 | DC-2, DC-3, DC-4 đã merge và runtime đã cập nhật | - | việc của anh Hùng |

Song song tối đa: DC-1 và DC-3 (không trùng file). DC-2 và DC-3 cùng sửa `cli.py`/`ARCHITECTURE.md` ở vùng khác nhau: phiên sau merge `origin/main` trước khi push.

### DC-1 (một PR)

Phạm vi file: `packages/lfmap-core/src/lfmap_core/data_classes.py` (mới), `packages/lfmap-core/tests/test_data_classes.py` (mới), một changelog fragment. Không sửa file khác.

1. `DataClass`, thứ tự `scratch < normal < private < secret`, `highest()`, `egress_level()` (spec mục 2 G3, mục 4).
2. `load_class_map(config)`: kiểm tra theo 6 quy tắc của spec mục 4; từ chối UNC/đường dẫn thiết bị bằng kiểm tra chuỗi **trước** mọi lời gọi hệ thống file.
3. `ClassMap.class_of`, `ClassMap.class_under` (spec 4.1), so khớp bằng `startswith` nội tuyến + dấu phân cách.
4. `adjust(action_tier, access, data_class)` đúng bảng spec 5.1.
5. Module lá: không import `approval.py`.

Test đóng băng: `test_adjust_table`, `test_adjust_never_lowers_t3`, `test_adjust_clamp`, `test_class_of_most_specific`, `test_class_default_private`, `test_class_under_takes_nested_highest`, `test_class_map_refuses_remote_before_io`, `test_class_map_invalid`.

Hoàn thành khi: test trên xanh, ruff xanh, không file nào khác đổi.

### DC-2 (một PR)

Phạm vi file: `data_guard.py` (mới, tối đa 120 dòng mã), `permissions.py`, `tool.py`, `runtime.py`, `approval.py`, `approvals.py`, `plugins/lfmap-markitdown/src/lfmap_markitdown/tool.py` (một dòng: thêm `paths=[output_dir]`), test mới `test_data_guard.py`, `ARCHITECTURE.md`, `docs/approvals.md`, changelog fragment. Không sửa `cli.py`, `mcp_adapter.py`, `flows_run.py`.

1. `PermissionManager`: callback tuỳ chọn `on_path(access, resolved)`, gọi sau khi đường dẫn qua kiểm tra root và trong `_typed_read`.
2. `ClassGuard` theo spec 5.3 (đọc, tạo, phá huỷ; memo mỗi lời gọi theo mục khớp; nhãn lời gọi; dự phòng khi `adjust` lỗi).
3. `ctx.require_approval(..., paths=())`, `ctx.data_label`, `ctx.mark_data(path)`.
4. Ba approver (`Gate`, `JobApprover`, `ApprovedGate`) nhận `data_class`, `action_tier` và ghi vào dòng audit; dòng `secret` luôn được ghi; `AUDIT_FIELDS` thêm hai trường.
5. `build_tool` dựng guard khi bảng lớp không rỗng và có approver; `context_for` dùng chung guard của lời gọi cha.
6. Không có `[data.classes]` thì hành vi và dòng audit giữ nguyên từng byte.

Test đóng băng: `test_no_table_no_change`, `test_secret_read_audited_once`, `test_secret_write_asks`, `test_scratch_overwrite_is_t1`, `test_scratch_not_lowered_when_mixed`, `test_overwrite_without_paths_unchanged`, `test_external_never_lowered`, `test_adjust_error_keeps_secret_floor`, `test_junction_into_scratch_classified_by_target`, `test_context_for_shares_guard`. Các bộ test cũ nêu ở cuối spec mục 11 phải xanh mà không sửa.

Hoàn thành khi: test xanh; `ARCHITECTURE.md` có module mới và bất biến của spec mục 10; `/security-review` đã chạy và từng phát hiện được trả lời trong PR.

### DC-3 (một PR)

Phạm vi file: `totp.py`, `auth.py` (mới), `cli.py` (`_require_code`, nhóm lệnh `auth`, `approvals approve` cho đề xuất T3), `backup.py` chỉ khi cần để loại `auth.json` (hiện danh sách file là allow-list nên có thể không cần sửa: kiểm tra và ghi vào PR), test mới `test_totp.py`, `test_auth.py`, bổ sung `test_cli.py`, `docs/approvals.md`, `ARCHITECTURE.md`, changelog fragment.

1. `totp.py` thuần theo spec 9.2.
2. `auth.py` theo spec 9.3: `Protector` tiêm vào được, DPAPI qua `ctypes` chỉ trên Windows, ghi `last_step` trước khi trả kết quả, khoá 5 phút sau 5 lần sai, file hỏng thì từ chối.
3. `lfmap auth enroll|status|reset` theo spec 9.4.
4. `_require_code`: đã đăng ký thì hỏi TOTP, chưa thì giữ mã gõ ngẫu nhiên; đề xuất có tầng T3 hỏi mã khi `approve`.

Test đóng băng: `test_totp_rfc6238_vectors`, `test_totp_single_use`, `test_totp_window`, `test_auth_lockout`, `test_auth_corrupt_fails_closed`, `test_auth_never_logged`, `test_require_code_uses_totp_when_enrolled`, `test_t3_proposal_needs_code`.

Hoàn thành khi: test xanh trên CI (Linux, protector giả); `/security-review` đã chạy. Phần DPAPI thật được kiểm ở DC-7.

### DC-4 (một PR)

Phạm vi file: `cli.py` (nhóm lệnh `data`), `config.py` (sửa một dòng trong `[data.classes]`), `jobs_doctor.py` (hai kiểm tra), test bổ sung `test_cli_config.py`, `test_jobs_doctor.py`, `docs/approvals.md`, changelog fragment.

Theo spec mục 7. Test đóng băng: `test_classify_lowering_needs_code`, `test_classify_keeps_comments`, `test_unclassify_last_entry_turns_off`.

### DC-5 (một PR)

Phạm vi file: `models_router.py`, `packages/lfmap-knowledge/src/lfmap_knowledge/{indexer.py, tool.py, search.py}`, test bổ sung, README của `knowledge`, changelog fragment.

Theo spec mục 8.1 đến 8.3. Test đóng băng: `test_router_uses_call_label`, `test_knowledge_root_class_from_shared_map`, `test_knowledge_legacy_sensitivity_fallback`, `test_knowledge_marks_label`. Không bật route cloud, không đổi `allow_cloud_unlabelled`.

### DC-7 [PO] (anh Hùng, pc-01, một buổi tối, khoảng 15 phút)

Chỉ làm sau khi DC-2, DC-3, DC-4 đã merge và `D:\lfmap-runtime` đã cập nhật. Thread sẽ chuẩn bị một script kiểm tra trước (dry-run) theo quy tắc script không giám sát.

1. Viết `[data.classes]` trong `config.toml` (thread đề xuất bảng từ các thư mục anh đang dùng; anh sửa và tự lưu).
2. `lfmap auth enroll` ở cửa sổ console của anh, nhập khoá vào app Authenticator trên điện thoại, gõ mã xác nhận.
3. `lfmap jobs doctor`: hai dòng `data_classes` và `auth` phải OK.
4. Thử: `lfmap approvals grant echo.echo --tier T1 --for 30m` phải hỏi mã 6 số; `lfmap data explain <một thư mục mật>` trả `secret`.

## Chuẩn bị sẵn

- Không cần dữ liệu thật: mọi test dùng thư mục tạm.
- Vector kiểm tra RFC 6238 đã ghi trong spec 9.5.
- 7 lỗi `test_jobs_doctor` trên Linux là có từ trước.

## Rủi ro

Bảng đầy đủ ở spec mục 13. Ba điểm cần theo dõi khi review: (1) không còn đường dẫn nào đi vòng qua `PermissionManager`; (2) lỗi trong `adjust` không được làm mất bảo vệ `secret`; (3) khoá TOTP và URI `otpauth` không xuất hiện trong log, audit hay bản sao lưu.

Tuyến dự phòng: nếu DC-2 phình quá 120 dòng ở `data_guard.py` hoặc phải sửa adapter, phiên dừng lại và báo; không tự nới phạm vi.

## Câu hỏi mở

Không có câu hỏi chặn việc. Một điểm để anh Hùng biết: sau khi có bảng lớp, job `knowledge.reindex` theo lịch trên thư mục `secret` cần `max_tier = 1`, nếu không mỗi lần chạy sẽ thành một đề xuất chờ duyệt.

## Cập nhật tài liệu dự án

- `03_Decisions_ADR.md`, ADR-025 phần Hệ quả: sửa "một lời gọi trong `approval.py`, khoảng 60 dòng" thành "nối ở `PermissionManager` và `require_approval(paths=)`, xem `docs/specs/data-classes.md`"; thêm câu "`scratch` tính là `normal` khi xét gửi ra ngoài".
- `02_Plugin_Contract.md` v0.2 mục 7: `require_approval(paths=)`, `ctx.data_label`, `ctx.mark_data` (spec mục 12).
- `05_Roadmap.md` Phase 2: S1 tách thành DC-1 đến DC-5; DC-6 là điều kiện trước route cloud đầu tiên.
- `docs/specs/model-client.md` mục 4 quy tắc 5: ghi chú rằng điều kiện "nhãn đi theo dữ liệu" được DC-5 đáp ứng trong một lời gọi và DC-6 qua bước flow (sửa khi DC-5 merge).

## Prompt khởi động (dán nguyên văn vào phiên Claude Code Cloud, repo lfmap)

### Prompt DC-1

```
Task DC-1 of lfmap #197 (ADR-025 data classes). Read docs/handoff/2026-11-10-adr-025-data-classes.md (section DC-1) and docs/specs/data-classes.md (sections 2, 4, 5.1, 11). Branch from up-to-date main.
Create only packages/lfmap-core/src/lfmap_core/data_classes.py and packages/lfmap-core/tests/test_data_classes.py plus one changelog fragment changelog.d/197-data-classes-core.added.md. Touch no other file.
Write the frozen tests first with exactly these names: test_adjust_table (all 32 rows), test_adjust_never_lowers_t3, test_adjust_clamp, test_class_of_most_specific, test_class_default_private, test_class_under_takes_nested_highest, test_class_map_refuses_remote_before_io (patch os.path.realpath and assert it is not called for UNC, \\?\, \\.\ and // keys), test_class_map_invalid.
Rules: leaf module, no import from approval.py; standard library and pydantic only; string-only os.path checks before realpath; the final containment test is realpath followed by an inline startswith guard on the same variable; compare with os.path.normcase; type hints everywhere; few comments.
Run uv run pytest packages/lfmap-core/tests/test_data_classes.py, then uv run pytest, uv run ruff check . and uv run ruff format --check . (7 test_jobs_doctor failures on Linux are pre-existing). Merge origin/main before push. Commit trailers Dev-Environment: cloud and Claude-Session. Open a draft PR from the template, "Refs #197" (not Closes). Do not merge; report the PR link.
```

### Prompt DC-2 (chỉ chạy sau khi DC-1 đã merge)

```
Task DC-2 of lfmap #197 (ADR-025: the class guard in the approval gate). Read docs/handoff/2026-11-10-adr-025-data-classes.md (section DC-2) and docs/specs/data-classes.md (sections 5, 6, 10, 11, 12). data_classes.py (DC-1) must be on main: check with git log origin/main; if it is missing, stop and tell me. Branch from up-to-date main.
File scope: data_guard.py (new, at most 120 code lines), permissions.py, tool.py, runtime.py, approval.py, approvals.py, plugins/lfmap-markitdown/src/lfmap_markitdown/tool.py (only add paths=[output_dir] to the existing require_approval call), new packages/lfmap-core/tests/test_data_guard.py, ARCHITECTURE.md, docs/approvals.md, changelog.d/197-data-guard.added.md. Do not touch cli.py, mcp_adapter.py, flows_run.py or any adapter. If the work needs a file outside this list or the guard exceeds 120 lines, stop and report.
Write the frozen tests first with exactly the names listed in the DC-2 card. Existing suites test_approval.py, test_approvals.py, test_call_tier.py, test_permissions.py, test_explicit_read.py, test_models_router.py and test_plugin_compat.py must pass unedited: without [data.classes] nothing changes, byte for byte in audit lines.
Key rules: raising for secret happens in the PermissionManager hook and never depends on the plugin; lowering for scratch only through require_approval(paths=...), only when every declared path and every path written in this call is scratch; T3 is never lowered; a secret decision line is always audited; any exception from adjust keeps the action tier, and keeps T1 read / T2 write for secret; classification uses paths core resolved itself (realpath then inline startswith).
Run the full test suite and ruff. Update ARCHITECTURE.md (module map and the invariants of spec section 10). Merge origin/main before push; trailers Dev-Environment: cloud and Claude-Session; draft PR with "Refs #197" and the "Cap nhat tai lieu du an" list (Plugin Contract wording of spec section 12). Then run /security-review on the diff and answer every finding in the PR. Do not merge; report the PR link.
```

### Prompt DC-3 (có thể chạy song song với DC-1)

```
Task DC-3 of lfmap #197 (ADR-025 item 4: TOTP for self-granting commands). Read docs/handoff/2026-11-10-adr-025-data-classes.md (section DC-3) and docs/specs/data-classes.md (sections 9, 10, 11). Branch from up-to-date main.
File scope: packages/lfmap-core/src/lfmap_core/totp.py and auth.py (new), cli.py (_require_code, a new "auth" command group with enroll, status, reset, and the T3 branch of approvals approve), tests test_totp.py and test_auth.py (new) and additions to test_cli.py, docs/approvals.md, ARCHITECTURE.md, changelog.d/197-totp.added.md. Check whether backup.py already leaves auth.json out (its file list is an allow-list); change it only if needed and say which in the PR.
Write the frozen tests first with exactly the names in the DC-3 card. Use the RFC 6238 vectors of spec section 9.5. No new dependency: hmac, hashlib, struct, base64, secrets, ctypes only. DPAPI (CryptProtectData/CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN) sits behind an injectable Protector so tests run on Linux with a fake; on non-Windows auth enroll refuses with backend_unavailable.
Rules: verify with hmac.compare_digest; accept the current and the previous 30 s step only; never accept a step <= last_step; write last_step before returning success (temp file + os.replace); 5 failures lock for 5 minutes with an "auth locked" audit line; a corrupt auth.json fails closed and is not "not enrolled"; the secret and the otpauth URI are printed once at enrolment and never written to audit.jsonl, logs or exceptions; when not enrolled the typed random code works exactly as today.
Run the full test suite and ruff. Merge origin/main before push; trailers Dev-Environment: cloud and Claude-Session; draft PR with "Refs #197". Then run /security-review on the diff and answer every finding in the PR. Do not merge; report the PR link.
```

Prompt cho DC-4 và DC-5 sẽ được viết khi DC-2 và DC-3 đã merge, vì chúng phụ thuộc tên hàm thật của hai PR đó.
