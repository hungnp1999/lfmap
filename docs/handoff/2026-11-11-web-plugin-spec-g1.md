# Bàn giao: đặc tả plugin `web` (#218, nhóm G1)

## Bối cảnh

- Issue gốc: #218 (khoảng trống của core lộ ra từ kịch bản nghiệm thu S1 "tìm gói thầu", `docs/specs/acceptance-scenarios.md`). Thuộc #191.
- G1 trong bảng đăng ký: plugin `web` lấy trang từ một tập host cho phép, có giới hạn tần suất, giới hạn kích thước, không cookie, chỉ dữ liệu công khai. Cần spec trước, dùng lại mẫu loopback/egress của `docs/specs/model-client.md`; trường audit `host`, `bytes_in`.
- Hùng đã duyệt làm spec (11/11). Chỉ viết spec, chưa viết code.

## Mục tiêu

Một Module Spec `docs/specs/web-plugin.md` đủ chặt để một phiên Cloud sau đó code mà không phải hỏi lại, kèm danh sách test đóng băng. Spec phải đủ cho S1: hai site công khai (baodauthau.vn, muasamcong.mof.gov.vn), hằng ngày, đọc trang HTML/văn bản.

## Quyết định đã chốt (từ #218 và model-client.md)

- Dữ liệu công khai, data class `normal`; không gửi gì của người dùng ra ngoài ngoài URL và header tối thiểu.
- Allow-list host do chủ máy sửa trong `config.toml` (như thư mục và `[models]`); không operation hay flow nào ghi được. Plugin chỉ nêu URL, không đổi được allow-list.
- Không cookie, không đăng nhập, không POST trong v1, không chạy script.
- Phương án đã loại: trình duyệt headless (G4 sẽ xem site có export/RSS/API trước); thư viện HTTP bên thứ ba (stdlib trước).

## Phạm vi

Viết một file: `docs/specs/web-plugin.md`. Thêm một dòng vào `ARCHITECTURE.md` chỉ nếu spec thay đổi invariant (dự kiến: câu "no network beyond loopback" cần ghi chú thêm ngoại lệ fetch công khai; chỉ soạn đoạn đề xuất trong spec, không sửa ADR). Changelog fragment `changelog.d/218-web-spec.docs.md`. Không code, không plugin mới, không đổi adapter.

## Nội dung spec phải trả lời (mỗi mục có kết luận, không để mở trừ mục "Câu hỏi mở")

1. Mục đích, non-goals (JS rendering, đăng nhập, POST, crawl theo link, tải file nhị phân lớn).
2. Module và cấu trúc plugin (`plugins/lfmap-web`, mẫu `plugins/lfmap-echo`), adapter bật, `[permissions]` (`network = true`, `cloud_ai = false`).
3. Cấu hình `config.toml` (ví dụ `[web] allowed_hosts`, `rate_limit_per_host`, `max_bytes`, `timeout_s`): mặc định an toàn khi không có bảng `[web]` là từ chối mọi host.
4. Operation: tên, schema vào/ra. Gợi ý: `web.fetch {url}` -> `{url_final, status, content_type, text, bytes, truncated}`, và có thể lưu bản sao vào `data_dir` của plugin để làm mẫu test (spec tự quyết, nêu lý do).
5. Quy tắc mạng: chỉ `https` (http chỉ khi owner bật cho từng host?); host so khớp chính xác (không wildcard v1?); chuyển hướng chỉ được trong allow-list và tối đa N lần; chặn IP riêng/loopback/link-local sau khi phân giải DNS (SSRF, DNS rebinding: kiểm IP đã kết nối); bỏ qua biến proxy môi trường; xác minh chứng chỉ mặc định; không userinfo trong URL; giới hạn độ dài URL; chỉ content-type văn bản.
6. Giới hạn: kích thước tối đa, thời gian tối đa, tần suất mỗi host (trạng thái giữ ở đâu giữa các lần chạy: trong tiến trình hay file `data_dir`), số lần gọi mỗi lần chạy flow.
7. Tier và cổng: đọc dữ liệu công khai nên T0 hay T1? Trả lời dứt khoát, và nói rõ hành xử trong job/flow chạy không người (phải chạy được không cần duyệt, vì S1 chạy theo lịch). Đối chiếu ADR-009/017/018/020 và ADR-025 (data class); nếu cần ghi chú ADR thì soạn đoạn đề xuất cho Hùng, không sửa ADR.
8. Audit/egress: dòng `audit()` mỗi lần fetch với trường allow-list `host`, `bytes_in` (và `status`); không ghi URL đầy đủ nếu URL có thể chứa dữ liệu? (quyết định và lý do); không ghi nội dung trang.
9. Văn bản trang là dữ liệu không tin cậy: không thực thi, không theo lệnh trong trang; đầu ra chỉ là văn bản cho bước sau (G3 lọc từ khóa, markitdown nếu cần HTML sang Markdown).
10. Mã lỗi: chỉ `ToolError` (`invalid_input`, `permission_denied`, `backend_unavailable` với `reason`), kèm bảng.
11. Test đóng băng: tên cố định, dùng server giả `http.server` trên loopback + socket guard, CI offline. Tối thiểu: `test_host_not_in_allowlist_refused`, `test_redirect_outside_allowlist_refused`, `test_private_ip_refused_after_dns`, `test_no_cookies_no_proxy`, `test_size_limit_truncates_or_refuses`, `test_rate_limit_per_host`, `test_audit_line_host_bytes_in`, `test_no_config_denies_all`, `test_non_text_content_type_refused`, `test_url_userinfo_refused`.
12. Cách kiểm thật: bước chạy trên DIEP-ANH với trang đã lưu từ hai site (G4 quyết định có cần fetch trực tiếp hay không); nêu việc `res:Local`.
13. Phân tích rủi ro ngắn và cái gì dễ/khó đổi sau này (như §12 của model-client.md).
14. Chia task cho phiên code sau (WEB-1 core fetch + config, WEB-2 plugin + flow-step test, có `/security-review`), ước lượng file chạm.
15. Câu hỏi mở dành cho Hùng (tối đa 3).

## Danh sách task

| Task | Loại | Ưu tiên | Blocked by | Môi trường |
| --- | --- | --- | --- | --- |
| G1-spec | [CC] | P1 | không | Cloud, Sonnet |

Tuần này không dùng thẻ AG (Hùng 11/11). Không chạy song song với phiên khác sửa cùng file.

## Chuẩn bị sẵn

- `docs/specs/model-client.md` §2, §4, §5, §6, §9, §10 (mẫu loopback, audit, test đóng băng).
- `docs/specs/acceptance-scenarios.md` mục S1.
- `packages/lfmap-core/src/lfmap_core/` (`approval.py` allow-list trường audit, `permissions.py`), `plugins/lfmap-echo`.

## Rủi ro

- Mở lỗ SSRF/rò dữ liệu nếu allow-list hoặc kiểm IP sai: spec phải nêu rõ thứ tự kiểm và test cho từng bước.
- Phình phạm vi (crawler, trình duyệt): non-goals phải giữ.
- Spec mâu thuẫn invariant "no network beyond loopback": phải nêu cách xử lý, không tự sửa ADR.

## Câu hỏi mở

- Có cần http (không TLS) cho site nào không? (đề xuất: không).
- Lưu bản sao trang vào `data_dir` mặc định hay theo tham số?

## Cập nhật tài liệu dự án

- Danh sách trong PR body: (a) gạch G1 trong bảng #218 khi spec merge; (b) đề xuất ghi chú ADR về fetch công khai nếu thấy cần (gate:po).

## Prompt khởi động (dán vào phiên Claude Code Cloud, repo lfmap)

```
Task G1-spec of lfmap #218. Read docs/handoff/2026-11-11-web-plugin-spec-g1.md (the whole card), then docs/specs/model-client.md (sections 2, 4, 5, 6, 9, 10, 12), docs/specs/acceptance-scenarios.md (scenario S1) and plugins/lfmap-echo for the plugin layout. Branch from up-to-date main.
Write ONLY docs/specs/web-plugin.md (Module Spec, same structure and level of detail as model-client.md, answer every numbered point of the card with a conclusion) plus changelog.d/218-web-spec.docs.md. No code, no plugin files, no ADR edits (draft any ADR note text inside the spec for the owner). Frozen test names from the card must appear in the spec's test table with exact assertions. Merge origin/main before push, open a draft PR (body: summary, "Cap nhat tai lieu du an" list, open questions for the owner), do NOT write "Closes #218" (it is a tracking issue). Commit trailers: Dev-Environment: cloud and Claude-Session. Report the PR link.
```
