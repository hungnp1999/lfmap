# Bàn giao: LFMAP Flows tối thiểu (Phase 2a, sau ADR-024)

- Ngày: 2026-11-06
- Issue: #155 (chọn bước tiếp theo của Phase 2a sau ADR-024). Lịch tuần: #156.
- Spec: [`docs/specs/flows.md`](../specs/flows.md) (RT-04)
- Liên quan: ADR-024 (không framework; dừng chờ duyệt = proposal `flows.resume`, T2), ADR-018 (job, hàng đợi approvals), ADR-021 (tự xây, clean room với n8n), handoff EventBus [`2026-10-29-eventbus.md`](2026-10-29-eventbus.md), báo cáo spike [`docs/research/2026-11-04-framework-spike.md`](../research/2026-11-04-framework-spike.md)
- Người duyệt: anh Hùng, cổng 1 (06/11 17:00)

## Bối cảnh

- Exit Phase 2: một workflow end-to-end chạy không cần tay ngoài bước duyệt (email có đính kèm → convert → ingest → tóm tắt → chờ duyệt).
- Đã có: jobs theo lịch + hàng đợi approvals (1.8), EventBus SQLite + adapter Events (2a.3), spike 2a.1 với cơ chế dừng bằng file + `resume` (ADR-024). Thiếu: thứ nối các bước thành một luồng. Handoff EventBus ghi rõ rủi ro "duyệt xong bằng CLI thì chuỗi sự kiện dừng ở đó cho tới khi Flows quyết định cách nối lại".
- Chưa có: plugin `email`, bước AI tóm tắt (Agent Router 2a.2), Tauri.

## Mục tiêu

Một luồng khai báo trong `flows.toml` tự khởi động (lịch hoặc sự kiện), chạy các operation có sẵn tới trần tầng của nó, dừng bền ở bước duyệt, và chạy tiếp khi anh duyệt bằng `lfmap approvals approve` ở một tiến trình mới.

Tiêu chí hoàn thành (cả handoff):
- Spec mục 3–7 có code và test mục 10 xanh trên CI Linux và Windows.
- `flows_run.py` ≤ 230 dòng đo như spike (cả file); ngưỡng 150 của ADR-024 đã chạm ở FL-2 và Hùng chốt (a') ngày 2026-11-06, xem spec mục 9.
- Smoke FL-4 trên DIEP-ANH đạt: luồng do sự kiện kích hoạt dừng chờ duyệt, tiến trình thoát, duyệt ở cửa sổ mới thì luồng xong.

## Quyết định đã chốt

Claude tự quyết các lựa chọn kỹ thuật đảo ngược được. Quyết định 1 thay đổi thứ tự Roadmap nên anh duyệt ở cổng 1.

| # | Quyết định | Lý do | Phương án đã loại |
| --- | --- | --- | --- |
| 1 | **Bước tiếp theo là LFMAP Flows, Agent Router (2a.2) sau** | Exit Phase 2 là một luồng; Flows nối bốn phần đã có (jobs, EventBus, approvals, dừng/resume của `plain`) và chỉ thêm 3 module. Router lúc này không có gì để định tuyến: chưa có bước AI trong luồng nào, gọi cloud trả phí phải hỏi anh, ADR-022 còn Proposed | Router trước (chưa có nơi dùng, phần cloud chưa được phép); chuyển cả `plain` vào package (không có người dùng ngoài spike) |
| 2 | Bước AI trong luồng là một operation plugin như mọi bước khác | Router sau này chỉ là operation (hoặc plugin) mà một bước gọi; Flows không cần biết model | Kiểu bước `ai` riêng trong Flows (gắn Flows với Router) |
| 3 | Trigger: `manual`, `schedule` (tái dùng `Schedule` và `jobs register`), `event` (một subscription `flows` trên bus). Không có trigger theo dõi thư mục | ADR-006: không dịch vụ nền; lịch + export bỏ qua file đã có làm được việc đó | Watcher thư mục (cần daemon) |
| 4 | Tham chiếu `${trigger...}` / `${steps.<id>.output...}`, không toán tử; rẽ nhánh duy nhất là `when` (giá trị truthy) | Đủ cho 3 luồng mẫu (spec mục 11); không có ngôn ngữ biểu thức để bảo trì hay để bị lợi dụng | Biểu thức JS/Jinja kiểu n8n (lớn, rủi ro chạy code) |
| 5 | Trần `max_tier` 0 hoặc 1 (mặc định 0); bước vượt trần hoặc bước `approve` thì dừng, ghi một proposal `flows.resume` T2 | ADR-017/018/024 (3) | Cho luồng tự chạy T2 (trái ADR-017) |
| 6 | Kênh mới `flow` (`decide` coi như `job`) | Audit tách được lời gọi của luồng | Dùng lại kênh `job` (không phân biệt được trong audit) |
| 7 | Trạng thái: một file JSON mỗi run trong `app_dir()/flows/runs/`, ghi sau mỗi bước; output ≤ 64 KiB, chỉ mang tham chiếu | Như `plain` (ADR-024 (1)) và payload EventBus | Bảng SQLite riêng (thêm schema, chưa cần) |
| 8 | Resume từ chối nếu file luồng đổi SHA-256 từ lúc bắt đầu | Anh duyệt đúng luồng anh đã thấy | Chạy tiếp với bản mới (khó hiểu khi duyệt) |
| 9 | Không retry trong luồng; bước lỗi thì run `failed` | Bus đã retry việc giao sự kiện; retry hai tầng khó đoán | Retry theo bước |
| 10 | Module phẳng trong `lfmap_core`: `flows_refs.py`, `flows.py`, `flows_run.py`; chỉ stdlib + pydantic | Giống `jobs.py`, `events*.py`; không dependency mới | Package `lfmap-flows` riêng (chưa cần) |

## Phạm vi

- Trong phạm vi: ba module trên; kênh `flow` trong `tool.py`/`approval.py`; `approvals approve|reject` xử lý proposal `flows.resume`; lệnh `lfmap flows list|check|start|status|runs`; trigger event và schedule; sự kiện `flows.run.<status>`; tài liệu (ARCHITECTURE luồng "Flow", PROVENANCE, CHANGELOG, `docs/flows.md`).
- Ngoài phạm vi: plugin `email`/`file`, Agent Router, bước AI, vòng lặp, nhánh song song, luồng con, MCP/REST cho Flows, UI, nhiều máy.

## Thiết kế

Chi tiết trong spec. Tóm tắt:

```text
flows.toml ── lfmap flows check (registry, tham chiếu, trần)
trigger: manual | schedule (\LFMAP\flow-<id>) | event (subscription "flows")
        ▼
flows_run.start ── với mỗi bước: when? → resolve(input) → run_operation(channel="flow", JobApprover max_tier)
        │                                   └─ lưu output vào runs/<run_id>.json
        ├─ bước vượt trần / bước approve ── proposal flows.resume (T2) ── tiến trình thoát
        │        lfmap approvals approve <id> (TTY) ── resume: chạy bước đó (ApprovedGate) rồi tiếp
        └─ xong / lỗi / bị từ chối / hết hạn ── publish flows.run.<status>
```

## Danh sách task

Mỗi task một phiên Claude Code (hoặc một lượt qwen), một PR vào `main`, squash-merge khi test + CodeQL xanh.

| Task | Việc | Môi trường | Ưu tiên | Cỡ | Phụ thuộc |
| --- | --- | --- | --- | --- | --- |
| TC-F1 [QW] | `flows_refs.py` (hàm thuần, spec mục 4) | qwen 14b + L1b trên DIEP-ANH, Claude review | P3 | S | FL-1 đã viết test đóng băng của nó |
| FL-1 [CC] | `flows.py` + `lfmap flows list|check`; test mục 10 phần FL-1; viết `flows_refs.py` nếu TC-F1 chưa xong | Cloud, Sonnet | P2 | S–M | PR handoff này merge |
| FL-2 [CC] | `flows_run.py`, kênh `flow`, proposal `flows.resume`, `approvals approve|reject`, `flows start|status|runs` | Cloud, Sonnet, `/security-review` | P2 | M | FL-1 |
| FL-3 [CC] | trigger event + schedule, `flows.run.<status>`, ARCHITECTURE, PROVENANCE | Cloud, Sonnet, `/security-review` | P2 | S–M | FL-2 |
| AG-F1 [AG] | hướng dẫn `docs/flows.md` | Antigravity, `ag/flows-guide` | P3 | S | FL-3 |
| FL-4 [CC] | smoke Windows | Local DIEP-ANH, Remote Control | P2 | S | FL-3 |

1. **TC-F1 [QW] (tùy chọn).** Chỉ chạy khi có khung GPU trống (không phải cuối tuần này). Card do phiên FL-1 soạn trong `/mnt/project-files/qwen-loop/cards/TC-F1/` cùng test đóng băng `docs/specs/flows-tests/test_flows_refs.py`. Preflight: Ollama chạy, `qwen2.5-coder:14b` có sẵn, GPU không có job khác. Xong khi: test xanh trong ≤ 3 vòng, Claude review. Tuyến dự phòng: trượt 3 vòng hoặc quá 2026-11-10 thì FL-1/FL-2 tự viết (quy tắc B6), ghi bài học vào sổ L1b.
2. **FL-1 [CC].** Preflight: `main` mới nhất, `uv sync` xanh. Xong khi: mọi luật spec mục 3 và mục 4 có test; `lfmap flows check` thoát 1 khi có lỗi; không test nào chạm `LOCALAPPDATA` thật. Tuyến dự phòng: nếu một luật mục 3 không kiểm được lúc nạp (vd. input cần registry), ghi rõ trong PR và kiểm ở `check`, không bỏ luật.
3. **FL-2 [CC].** Preflight: FL-1 đã merge. Xong khi: test mục 10 phần FL-2 xanh, kể cả dừng → tiến trình mới → approve; số dòng `flows_run.py` ghi trong PR (≤ 230, spec mục 9); `/security-review` đã chạy và trả lời. Tuyến dự phòng: vượt 230 dòng thì dừng, báo con số và phần nào lớn; không tự bớt kiểm tra để đạt số.
4. **FL-3 [CC].** Preflight: FL-2 đã merge. Xong khi: test mục 10 phần FL-3 xanh; `jobs register` sinh đúng lệnh task cho luồng có lịch (không gọi Task Scheduler thật); ARCHITECTURE thêm luồng "Flow" và bất biến kênh `flow`; dòng PROVENANCE (in-house, tham khảo hành vi Node-RED/Activepieces, chỉ tài liệu n8n).
5. **AG-F1 [AG].** Card viết khi FL-3 merge (cùng mẫu AG-E1). Chỉ `docs/flows.md` và một câu liên kết trong `docs/jobs.md`. Antigravity tối đa 1–2 card/tuần.
6. **FL-4 [CC] (Local).** Remote Control trên DIEP-ANH trong `D:\Development\lfmap`. Preflight: anh duyệt phiên RC; `uv sync`; config thử trong thư mục tạm (`LOCALAPPDATA` riêng cho phiên). Luồng thử: trigger `markitdown.classify.completed` → `markitdown.export` vào thư mục export được phép → bước `approve`; chạy `lfmap events run --until-idle`, thấy run `awaiting_approval`, đóng cửa sổ, mở cửa sổ mới `lfmap approvals approve <id>`, run thành `completed`. Ghi kết quả vào `docs/research/` hoặc PR FL-3. Tuyến dự phòng: khác biệt Windows (đường dẫn, `os.replace` khi file đang mở) thì ghi lại và mở issue, không sửa trong smoke.

## Chuẩn bị sẵn

- Spec `docs/specs/flows.md` (PR này): định dạng, tham chiếu, chạy, trigger, CLI, bảo mật, trần dòng của `flows_run.py`, danh sách test, 3 luồng mẫu.
- Không có test đóng băng trong PR này: mỗi task viết test trước theo spec mục 10 (tiết kiệm hạn mức; spec đủ chi tiết để viết test).
- Không cần dữ liệu thật; mọi test dùng `tmp_path`, plugin `echo` và đồng hồ giả.

## Rủi ro

- Ngưỡng 150 dòng của ADR-024 đã chạm ở FL-2 (223 dòng); Hùng chốt 2026-11-06 giữ plain, trần 230 dòng cho `flows_run.py`, trigger của FL-3 ở module riêng. Giảm: phạm vi nhỏ (không vòng lặp, không song song).
- Output lớn (vd. `markitdown.convert` trả nguyên văn) làm file run phình: giới hạn 64 KiB, khuyến nghị dùng operation ghi file (`export`).
- Một sự kiện được giao hai lần: `run_id = "ev-" + event.id` nên không tạo run thứ hai.
- Anh sửa `flows.toml` khi một run đang chờ duyệt: resume từ chối, phải bắt đầu run mới.
- Hạn mức Pro: FL-1..FL-3 mỗi task một phiên Sonnet, không chạy song song với việc nặng khác.

## Câu hỏi mở (cổng 1): đã chốt 2026-11-06

Hùng đồng ý quyết định 1 (Flows trước Agent Router). Spec chat UI: bản đầu chỉ đọc, thao tác duyệt/tương tác sang Phase 3 cùng lõi security và diễn tập phòng vệ. Ma trận giấy phép: đồng ý bản hiện tại, rà soát hàng tháng. Câu 2 bên dưới (trần mặc định 0) giữ như đề xuất.

1. Quyết định 1: làm Flows trước Agent Router. Đề xuất: đồng ý.
2. Trần mặc định `max_tier = 0` (luồng chỉ tự chạy bước không tác dụng phụ; `markitdown.export` là T1 nên phải đặt `max_tier = 1` cho luồng thử). Đề xuất: giữ 0.

## Cập nhật tài liệu dự án

- `05_Roadmap.md` Phase 2, dòng LFMAP Flows: "spec 2026-11-06 (lfmap `docs/specs/flows.md`, handoff `docs/handoff/2026-11-06-lfmap-flows.md`)"; ghi Flows làm trước Agent Router.
- `03_Decisions_ADR.md`: không ADR mới. Ghi chú ở ADR-018 (Hệ quả): luồng dùng chung hàng đợi approvals (kênh `flow`, proposal `flows.resume`, trần `max_tier` của luồng). Ghi chú ở ADR-024 (Hùng chốt 2026-11-06): ngưỡng 150 dòng đã chạm ở Flows (223 dòng, phần thêm là logic riêng LFMAP do ADR-024 (3) và bảo mật đòi); không mở lại framework; trần 230 dòng cho `flows_run.py`; lần xét lại tiếp theo theo tính năng (nhánh song song, vòng lặp, nhiều máy), không theo số dòng.
- Kế hoạch RT (`commercial-replacements.md`): RT-04 "spec xong"; RT-09 làm ở FL-1..FL-4.
- Checklist thẻ của Planner 2a.2 (quyết định F7 số 3, chờ handoff Router): "kiểm hình dạng và số lượng phản hồi từ ngoài".

## Checklist thẻ của Planner 2a.2 (chờ handoff Router)

Handoff Router chưa có nên Planner 2a.2 chưa có checklist riêng; mục này giữ chỗ cho đến khi có (đường dự phòng của #164). Khi viết thẻ, Planner phải:

- [ ] Nếu thẻ gọi dịch vụ bên ngoài (Ollama, HTTP, tiến trình con): thẻ ghi rõ phải kiểm **hình dạng và số lượng phản hồi** (số phần tử trả về bằng số phần tử gửi đi, khóa bắt buộc có mặt, kiểu đúng) và báo `ToolError` khi sai, kèm một test hoặc probe dùng server giả trả thiếu phần tử. Nguồn: quyết định F7 số 3 (`count` là lỗ của thẻ TC-K7, `docs/specs/knowledge.md`; ghi chú thiết kế `docs/research/2026-11-05-f7-deterministic-checks.md`).

## Prompt khởi động cho Claude Code

FL-1:

```text
Repo hungnp1999/lfmap, task FL-1. Branch feature/flows-model from up-to-date main. Read CLAUDE.md,
docs/specs/flows.md (sections 2-4, 10) and docs/handoff/2026-11-06-lfmap-flows.md (task FL-1). Write the FL-1 tests of
spec section 10 first, then flows_refs.py and flows.py in packages/lfmap-core/src/lfmap_core/ and the commands
`lfmap flows list|check`. Also write docs/specs/flows-tests/test_flows_refs.py (the frozen test for qwen card TC-F1)
and the card in /mnt/project-files/qwen-loop/cards/TC-F1/ if that folder is reachable; skip the card if not.
Standard library + pydantic only. Tests must not touch the real LOCALAPPDATA. Update CHANGELOG [Unreleased].
Run uv run pytest, ruff check, ruff format --check. Every commit ends with Dev-Environment: cloud and Claude-Session
trailers. Open a PR "Part of #<FL issue>"; merge when tests + CodeQL are green and the PR is not a draft.
If the spec conflicts with the code or an ADR, stop and ask. Work in English; final summary only in Vietnamese.
```

FL-2:

```text
Repo hungnp1999/lfmap, task FL-2. Branch feature/flows-run from main after FL-1 merged. Read CLAUDE.md,
docs/specs/flows.md (sections 5, 7-10) and the FL-2 task in docs/handoff/2026-11-06-lfmap-flows.md, then
approval.py, approvals.py, tool.py, jobs.py and spikes/2a1-framework/variants/plain/flow.py (pause/resume pattern).
Write the FL-2 tests of spec section 10 first. Add channel "flow" (decide() treats it like "job"), flows_run.py,
the flows.resume proposal handling in `lfmap approvals approve|reject`, and `lfmap flows start|status|runs`.
Measure flows_run.py with the folder_lines rules, whole file (spec section 9) and put the number in the PR body; if it is
above 230, stop and report instead of trimming checks. Run /security-review and answer each finding.
Update CHANGELOG. Trailers as in FL-1. Work in English; final summary only in Vietnamese.
```

FL-3:

```text
Repo hungnp1999/lfmap, task FL-3. Branch feature/flows-triggers from main after FL-2 merged. Read CLAUDE.md,
docs/specs/flows.md (sections 5-6, 10, 12) and the FL-3 task in docs/handoff/2026-11-06-lfmap-flows.md.
Write the FL-3 tests first. Put the triggers in a new module flows_triggers.py and do not grow flows_run.py past 230 lines (spec section 9). Add the event trigger (one durable subscription "flows", run_id "ev-" + event.id),
the schedule trigger through `lfmap jobs register` (task \LFMAP\flow-<id> running `lfmap flows start <id>` via
scripts/Invoke-LfmapJob.ps1; no real Task Scheduler in tests) and the flows.run.<status> events. Add the "Flow"
main flow and the flow-channel invariant to ARCHITECTURE.md, a docs/PROVENANCE.md row, CHANGELOG.
Run /security-review. Trailers as in FL-1. PR "Closes #<FL issue>" only after FL-4 passes; otherwise "Part of".
Work in English; final summary only in Vietnamese.
```
