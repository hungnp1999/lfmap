# Bàn giao: mỗi flow một subscription (#178)

## Bối cảnh

- FL-3 (#176) dùng một subscription bền `flows` với `covering_pattern` (mẫu hẹp nhất phủ mọi flow event đang bật). Khi tập flow đổi, `attach` hủy rồi đăng ký lại, xóa các delivery đang xếp hàng của các flow không đổi (chỉ ghi log). Mẫu rộng (`*.*.*`, `>`) còn kéo cả `flows.run.*` vào handler chỉ để bỏ qua.
- Issue: https://github.com/hungnp1999/lfmap/issues/178 (P2, `exec:CC`, milestone Phase 2b). Phần của #168. Hùng duyệt làm 11/11.
- Phải xong trước plugin `email` (trigger event thật đầu tiên). Không phụ thuộc #231/#239 nhưng cùng chạm `flows_triggers.py`: nếu JF-1/JF-2 merge trước, merge `origin/main` trước khi push.

## Mục tiêu

Mỗi flow event hợp lệ có đúng một subscription `flows-<id>` với mẫu của chính nó. Đổi hoặc bỏ một flow chỉ ảnh hưởng subscription của flow đó.

## Quyết định đã chốt (từ issue)

- Tên `flows-<id>` (id flow đã khớp `[a-z][a-z0-9-]*`). Bỏ `covering_pattern`; handler chỉ khởi động flow của nó, không lọc theo mẫu.
- Giữ nguyên: `run_id = ev-<event id>-<flow id>`; chỉ flow qua `check_flow` được đăng ký; `flows.toml` không đọc được thì để nguyên mọi subscription.
- `flows_run.py` không được dài thêm (trần 230 dòng code, test hiện có).

## Điểm thiết kế cần chốt trong PR (Claude Code tự quyết, ghi vào PR)

1. **Liệt kê subscription cũ để dọn.** `EventBus` Protocol hiện không có cách liệt kê (chỉ `SqliteBus.counts()`). Flow đã bị xóa khỏi `flows.toml` thì không còn id để hủy. Khuyến nghị: thêm `subscriptions() -> dict[str, str]` (tên -> mẫu) vào Protocol, `InProcessBus` và `SqliteBus`, cập nhật `docs/specs/events.md`; attach hủy mọi `flows-*` không thuộc tập flow hợp lệ. Phương án loại: dò theo `counts()` (bỏ sót subscription không có delivery) hoặc chỉ hủy theo flow còn khai báo (rò subscription của flow đã xóa).
2. **Subscription `flows` cũ (FL-3).** Hủy một lần khi attach, ghi log một dòng; các delivery còn lại của nó bị bỏ (lần chuyển đổi duy nhất, chấp nhận vì chưa có flow event thật nào chạy).
3. **Đổi mẫu của một flow:** `subscribe` báo `invalid_input` khi tên đã có với mẫu khác (`events_sqlite.py:143`); chỉ hủy và đăng ký lại `flows-<id>` đó, log cảnh báo nói rõ flow nào mất delivery đang chờ.
4. Giá trị trả về của `attach` đổi thành danh sách (hoặc dict id -> mẫu) các subscription đang có; cập nhật chỗ gọi (`events_adapter.attach_handlers`) nếu cần.
5. Handler giữ `flows.*` và `*.requested` bỏ qua như phòng thủ thêm (rẻ), dù `check_flow` đã chặn.

## Phạm vi file

`packages/lfmap-core/src/lfmap_core/{flows_triggers.py, events.py, events_sqlite.py}` (chỉ nếu chọn `subscriptions()`), `events_adapter.py` (chỉ nếu đổi kiểu trả về), tests `test_flows_triggers.py` (+ test bus), `ARCHITECTURE.md` (module map dòng `flows_triggers.py`, Flow bước 6), `docs/specs/flows.md` mục 6 (và dòng 90), `docs/specs/events.md` nếu thêm `subscriptions()`, một changelog fragment `changelog.d/178-flows-subscription-per-flow.changed.md` (không sửa `CHANGELOG.md`). Không đụng `flows_run.py`, adapter, `cli.py`.

## Test đóng băng (tên cố định)

Viết lại các test FL-3 liên quan; giữ nguyên mọi test không nhắc `covering_pattern`.

- `test_attach_subscribes_one_flows_dash_id_per_enabled_event_flow` (thay `test_attach_subscribes_flows_once_with_the_union...`)
- `test_changing_one_pattern_replaces_only_that_subscription` (hai flow; delivery đang chờ của flow kia còn nguyên và vẫn chạy sau drain)
- `test_removing_or_disabling_a_flow_unsubscribes_only_its_subscription`
- `test_a_flow_removed_from_flows_toml_loses_its_subscription` (cần liệt kê subscription)
- `test_the_legacy_flows_subscription_is_removed_once`
- `test_an_unusable_flows_file_leaves_all_subscriptions_and_queued_events_alone` (giữ ý của test hiện có, đổi tên)
- `test_the_handler_starts_only_its_own_flow` và `test_flows_run_events_never_start_a_flow` (giữ)
- Xóa `test_covering_pattern_...`; thêm vào test cấu trúc: `"covering_pattern" not in` source của `flows_triggers.py`.
- Giữ `test_flows_run_stays_within_the_230_line_cap`.

## Môi trường, ưu tiên, cổng

Cloud, [CC], P2, một PR. Không `gate:po`. `/security-review`: chỉ bắt buộc nếu PR chạm `events_sqlite.py`/Protocol (subprocess, mạng, đường dẫn thì không; vẫn nên chạy nhanh). Merge khi test + CodeQL xanh, PR không draft (squash).

## Rủi ro

- Mất delivery đang chờ một lần khi chuyển từ `flows` cũ sang `flows-<id>` (đã chấp nhận, ghi trong CHANGELOG).
- Nhiều subscription: mỗi event được claim nhiều lần (một lần mỗi flow khớp); chi phí tăng nhỏ, thay vì handler tự lọc.
- Xung đột với #231/#239 trong `flows_triggers.py`: fetch + merge `origin/main` trước khi push.

## Cập nhật tài liệu dự án

Không có (không đổi ADR). Ghi chú trong PR: ADR-024 không đổi.

## Prompt khởi động (Claude Code, Cloud)

```text
Work on lfmap issue #178 (https://github.com/hungnp1999/lfmap/issues/178). Read CLAUDE.md, ARCHITECTURE.md, docs/specs/flows.md section 6 and docs/handoff/2026-11-11-flows-subscription-per-flow.md first, then do exactly that handoff: one PR, branch from up-to-date main, changelog fragment (no CHANGELOG.md edit), fetch and merge origin/main before pushing. Do not touch flows_run.py. Decide the "list subscriptions" design point as the handoff recommends and say what you chose in the PR body. Run uv run pytest and ruff before pushing. Closes #178. Every commit needs Dev-Environment: cloud and Claude-Session trailers. Final summary to Hùng in Vietnamese.
```
