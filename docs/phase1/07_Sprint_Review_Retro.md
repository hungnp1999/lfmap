# LFMAP Phase 1 — Sprint Review, Release Notes và Retrospective

Phiên bản 0.9 bản nháp · 2026-10-22

Phase 1 được coi là một Increment theo Scrum, chạy 2026-10-19 → 2026-10-22. Vai trò: **Product Owner** = Hùng; **Managing Agent** (Scrum Master / Planner / Reviewer) = Claude trong project (coordinator + thread), theo phân cấp Hùng chốt 2026-10-22; **Developers / Working Agents** = phiên Claude Code (Cloud và trên DIEP-ANH), qwen2.5-coder:14b qua `qwen-loop` (card S).

## 1. Sprint Goal

"Từ một thư mục PDF/DOCX trên máy, hỏi Claude và nhận câu trả lời có trích dẫn đoạn nguồn; toàn bộ nội dung tài liệu chỉ rời máy ở mức đoạn được truy xuất" (Exit criteria Roadmap Phase 1).

Kết quả: **Đạt về chức năng trên dữ liệu mẫu** (TC-916, 2026-10-22: citation, `untrusted`, root `secret` ẩn trên MCP, `egress_log` một dòng mỗi lời gọi). **[CHỜ: thử trên thư mục PDF/DOCX thật của Hùng (TC-918)]**. Hạng mục 1.2, 1.3, 1.6 chưa làm (xem §6).

## 2. Sprint Backlog và kết quả

### Core 0.2 (điều kiện tiên quyết)

| Card | Việc | Người làm | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| TC-C2 | ToolContext `data_dir`, `settings`, `channel`; `context_for` | Claude | Xong | PR #3 |
| TC-C4a | `approval.py`: tầng, policy, bảng quyết định, audit | Claude Code Cloud | Xong | PR #5 |
| TC-C4b | `grants.py`, Gate, MCP elicitation, `approvals grant/revoke/list` | Claude | Xong | PR #6 |
| TC-C1, C3, C5 | Đọc ngoài root ở CLI tương tác; `plugins health`, `config path/add-folder`, `audit tail` | Claude (bản qwen tối 19/10 dùng làm tham chiếu) | Xong | PR #9 |
| — | Nâng `lfmap-core` 0.2.0 | Claude | Xong | PR #14 |
| — | Đích T3 duyệt trước `[approval.destinations]` | Claude | Xong | PR #17 |

### 1.1 Plugin markitdown

| Card | Việc | Trạng thái | Bằng chứng |
|---|---|---|---|
| TC-M1, M2 | Khung, schema, định dạng; `quality.py` port | Xong | PR #10 |
| TC-M3, M4 | Backend MarkItDown, `classify`, `convert` | Xong | PR #11 |
| TC-M5 … M7 | OCR extra, `info`/`health`, `export` | Xong | PR #12 |
| TC-M8 | Fixture tương đương + `expected.json` từ MarkitdownTool 2.4.0 | Xong | PR #13, #15 |
| TC-M9 | README, thử MCP thật trên Windows | Xong | PR #15, TC-910 |
| — | Test ngoại tuyến, `min_core_version = 0.2.0` | Xong | PR #16 |

### 1.4 + 1.5 lfmap-knowledge

| Card | Việc | Người làm | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| TC-K0 | Spike LanceDB + FTS5 + Ollama | Hùng trên DIEP-ANH | Đạt | TC-911 |
| TC-K1 … K3 | Khung, store, scanner | qwen | Xong | PR #18 |
| TC-K4, K6, K7 | extract, fts, embed | qwen-loop + review (K4, K7 có sửa) | Xong | PR #26 |
| TC-K5 | chunker | qwen không hội tụ, viết lại trong review | Xong | PR #26 |
| TC-K8 | LanceDB vector store | Claude Code Cloud | Xong | PR #31 |
| TC-K12 | `search_files`, `get_file` | Claude Code Cloud (chuyển từ qwen: card M) | Xong | PR #32 |
| TC-K13 | edges, `related` | Claude Code Cloud | Xong | PR #33 |
| TC-K9 | reindex, status | Claude Code Cloud | Xong | PR #36, TC-915 |
| TC-K10, K11 | search, get_context, nối 7 operation | Claude Code Cloud | Xong | PR #38 |
| TC-K14 | README, job reindex mẫu, thử thật | Claude + Hùng | Một phần: README + job (PR #39), MCP thật đạt (TC-916); **[CHỜ: bench 10k (TC-917), thư mục thật (TC-918)]** | |

### 1.7 Vòng Planner → Task Card → Local Agent → Review

| Việc | Trạng thái | Bằng chứng |
|---|---|---|
| B1–B6: `qwen_loop.py` (ngoài repo sản phẩm, `D:\Development\lfmap-tools`), chạy thật đợt K4–K7, review B5, quyết định B6 | Đạt 2026-10-21 | Handoff PR #22, #23; kết quả PR #26; TC-919 |

### 1.8 Job theo lịch

| Card | Việc | Trạng thái | Bằng chứng |
|---|---|---|---|
| TC-J1, J2 | `Invoke-LfmapJob.ps1`; `jobs.toml`, `jobs list/run/register` | Xong | PR #25 |
| TC-J3 | Kênh `job`, `approvals pending/approve/reject` | Xong | PR #27 |
| TC-J4 | `jobs doctor` | Xong | PR #29 |
| — | `pwsh` đường dẫn đầy đủ (lỗi tìm thấy khi thử thật) | Xong | PR #34 |
| Exit 1.8 | Job T0 chạy ở màn hình khóa; đề xuất + approve; doctor không FAIL | Một phần: TC-912 đạt; **[CHỜ: approve (TC-913), doctor (TC-914)]** | |

### Hạng mục chưa làm

| # | Hạng mục | Lý do |
|---|---|---|
| 1.2 | Backend Docling (`--backend docling`) | Ưu tiên đường chính 1.1 → 1.4 → 1.5; interface `Backend` đã chừa sẵn |
| 1.3 | Adapter REST sinh tự động | Chưa có client cần REST; kênh `rest` đã có trong ẩn root và `egress_log` |
| 1.6 | Plugin `powershell` với allow-list | Cần kiểm tra `permissions.exec` (L2 Phase 0) trước |

Việc hỗ trợ (docs/handoff, không phải code sản phẩm): PR #7, #8 (hồ sơ Phase 0), #19, #20, #24, #28, #30, #35, #37 (handoff + test chuẩn bị sẵn), hook `uv sync` cho phiên Cloud (`f286d3a`).

## 3. Increment

| Thành phần | Phiên bản | Commit |
|---|---|---|
| `lfmap-core` | 0.2.0 | `b002710` |
| `lfmap-echo` | 0.1.0 | không đổi |
| `lfmap-markitdown` | 0.1.0 (mới) | `b002710` |
| `lfmap-knowledge` | 0.1.0 (mới) | `b002710` |

Release notes (tóm tắt CHANGELOG `[Unreleased]` tại `b002710`):

- **Added:** core 0.2 (`ToolContext` đầy đủ, `context_for`, phê duyệt T0–T3, `audit.jsonl`, grants, đích duyệt trước, đọc ngoài root ở CLI tương tác, `plugins health`, `config path/add-folder`, `audit tail`); plugin `lfmap-markitdown` (classify, convert, export, info, OCR extra); `lfmap-knowledge` (7 operation: status, reindex, search_files, get_file, search, get_context, related); job theo lịch (`jobs list/run/register/doctor`, `approvals pending/approve/reject`, `Invoke-LfmapJob.ps1`); README knowledge + job reindex mỗi giờ.
- **Changed:** CLI và MCP quyết định phê duyệt theo tầng (T1 chạy không hỏi, có audit; T2 hỏi; T3 cần grant hoặc TTY); `--approve` hết hạn sau 8 giờ; license check quét cả `packages/*`.
- **Fixed:** task theo lịch khởi chạy `pwsh` bằng đường dẫn đầy đủ (`0x80070002`).

Chưa gắn tag/release GitHub (phát hành là quyết định không đảo ngược, cần Hùng duyệt).

## 4. Definition of Done (DoD) áp dụng

| Tiêu chí | Đạt | Ghi chú |
|---|---|---|
| Code merge vào `main` qua PR | ✅ | PR #3 … #39 |
| Test tự động pass trên Windows | ✅ | CI mỗi PR; 545 pass / 10 skip khi chạy lại trên Linux |
| Lint, format, CodeQL, license | ✅ | Điều kiện merge |
| CHANGELOG cập nhật | ✅ | Root + CHANGELOG từng plugin |
| README sản phẩm cho plugin | ✅ | markitdown, knowledge, `docs/jobs.md` |
| ADR liên quan Accepted | ✅ | 011 … 018 Accepted; knowledge theo phạm vi cắt gọn D6 (không watch, không tóm tắt LLM), không trái ADR-012 |
| Plugin DoD markitdown (spec §8) | ✅ | Tương đương, ngoại tuyến, license, export T1/T2 qua MCP, knowledge gọi qua `context_for` |
| DoD knowledge (spec §9): MCP thật, reindex lần 2 không làm lại, top-5 như cũ sau khi xóa vectors, secret không qua MCP, không mạng ngoài loopback | ✅ | TC-409, TC-412, TC-915, TC-916, TC-407 |
| DoD knowledge: 10.000 file, reindex lần hai < 60 s, ghi vào CHANGELOG | ⏳ | **[CHỜ: TC-917]** |
| Exit 1.8 | ⏳ | **[CHỜ: TC-913, TC-914]** |
| Exit Phase 1 trên thư mục PDF/DOCX thật | ⏳ | **[CHỜ: TC-918]** |
| Tài liệu bàn giao giai đoạn | ✅ | Bộ tài liệu này (bản nháp 0.9) |

## 5. Retrospective

**Làm tốt**

- Handoff + test chuẩn bị sẵn (xanh với bản tham chiếu bỏ đi) cho phép giao từng card cho một phiên Claude Code mà không phải giải thích lại; K8, K12, K13 chạy song song sáng 22/10 và merge trong khoảng một giờ.
- Phê duyệt theo tầng (ADR-017) giữ được an toàn mà agent vẫn làm việc được: tạo file mới qua MCP chạy, ghi đè phải hỏi, T3 không agent nào tự duyệt được.
- Thử thật trên DIEP-ANH bắt được lỗi môi trường mà CI không thấy (`pwsh` alias Store → `0x80070002`, PR #34) và xác nhận K0, K9, K14 trên Windows + Ollama.
- Review dữ liệu rò rỉ có checklist riêng (handoff K10/K11 §6) và test đi qua `tool.py` trên kênh `mcp`; phát hiện thêm trường hợp root vừa đổi sang `secret` trước reindex và vá trong cùng PR #38.
- Tiết kiệm hạn mức Pro: card S cho qwen, gom review theo lô, việc chỉ người làm được gom vào một danh sách tối.

**Cần cải thiện**

- qwen không hợp với card M: đợt K4–K7 chỉ 3/4 xanh theo test, K5 phải viết lại; quyết định B6 giới hạn qwen ở card S có test chặt.
- Spec lệch với code đã merge: K12 trong spec có trường `glob` nhưng schema K1 không có (giải bằng glob trong `query`); ADR-018 ghi `approvals list` cho hàng đợi nhưng chốt `approvals pending`. Spec cần cập nhật khi quyết định đổi.
- Lệnh chỉ chạy ở TTY (`approve`, `add-folder`) và bộ lọc auto-mode của Claude Code trên DIEP-ANH làm thử thật phụ thuộc Hùng có mặt; các bước Exit 1.8 và K14 bị dồn sang ca tối.
- `jobs register` ghi đè thiết lập logon/wake: dễ quên, đã ghi trong `docs/jobs.md` và doctor cảnh báo, nhưng vẫn là bước tay.
- Hành động A1 của Phase 0 ("viết tài liệu giai đoạn dần theo PR") chỉ làm được một phần: handoff viết dần, còn bộ hồ sơ này vẫn soạn ở cuối Phase.

**Hành động**

| # | Hành động | Chủ trì | Khi nào |
|---|---|---|---|
| A4 | Cập nhật `docs/specs/knowledge.md` (bỏ `glob`, ghi `shown_roots`) và ADR-018 (`approvals pending`) | Claude | Trước nghiệm thu |
| A5 | Gom mọi bước cần TTY vào checklist tối duy nhất; thiết lập auto-mode Claude Code trên DIEP-ANH (`/auto-mode-setup`) | Hùng | Ca tối 22/10 |
| A6 | Sửa cảnh báo LanceDB `_distance` (L18) | Claude Code Cloud | Xong 2026-10-22, PR #40 |
| A7 | Cập nhật `docs/phase1/` mỗi PR của 1.2, 1.3, 1.6 thay vì cuối giai đoạn | Claude | Tiếp theo |

## 6. Việc chuyển tiếp (Product Backlog)

| Mục | Nguồn | Đích đề xuất |
|---|---|---|
| Docling backend | Roadmap 1.2 | Sau nghiệm thu MVP; Cloud |
| REST adapter (OpenAPI `/docs`) | Roadmap 1.3, L7 | Sau nghiệm thu MVP; Cloud |
| Plugin `powershell` + kiểm tra `exec` | Roadmap 1.6, L2 | Cần Windows; Local |
| `min_core_version` được core đối chiếu | L3, L9 | Backlog core |
| `audit.jsonl` theo `LFMAP_CONFIG`; audit lần đọc bị từ chối | L10 | Backlog core |
| Hook tiến độ chung (thay stderr của knowledge) | L11 | Backlog core |
| `preview` cho đề xuất job (dry run trong Plugin Contract) | L13, ADR-018 | Backlog |
| TOCTOU / junction | L5 | Backlog bảo mật |
| Case-study `lfmap-isomp` (ADR-019) | Roadmap backlog | Sau Phase 1 Exit |
| ADR-005/006/007 còn Proposed | Roadmap Phase 2 | Đầu Phase 2 |
