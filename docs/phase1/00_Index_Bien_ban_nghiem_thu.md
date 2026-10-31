# LFMAP Phase 1 — Hồ sơ nghiệm thu giai đoạn

> **Phiên bản 1.1 (2026-10-22): đã nghiệm thu MVP Phase 1** (Hùng, 15:41Z, phương án A). TC-918 (thư mục PDF/DOCX thật) đạt cùng ngày, ghi bổ sung ở bản 1.1. Bản 1.2: retro bổ sung việc sau nghiệm thu (PR #43 … #51) và hành động A8–A11. Bản 1.3 (2026-10-31): **đóng Phase 1b** (§6).

| Mục | Giá trị |
|---|---|
| Dự án | LFMAP — Local-First Modular Automation Platform (`hungnp1999/lfmap`, Apache-2.0) |
| Giai đoạn | Phase 1 — MVP: Document → Knowledge → Answer (Roadmap 1.1–1.8) và điều kiện tiên quyết lfmap-core 0.2 |
| Thời gian | 2026-10-19 → 2026-10-22; hồ sơ lập 2026-10-22 |
| Mốc nghiệm thu | Commit `b002710` trên `main` (PR #3 … #39) |
| Chưa làm | 1.2 Docling, 1.3 REST (chuyển Phase 1b). 1.6 `powershell` xong sau mốc (PR #43, 2026-10-22) |
| Phase 1b | Đóng 2026-10-31: 1.2 xong, 1.3 dời sang đầu Phase 2 (ADR-003), quyền theo script xong (§6) |
| Product Owner | Hùng |
| Lập hồ sơ | Claude (Managing Agent) |

## 1. Danh mục hồ sơ

| # | Tài liệu | Dùng khi |
|---|---|---|
| 00 | Hồ sơ nghiệm thu (file này) | Kết luận, ký nhận, truy vết tổng |
| 01 | [Kiến trúc (SAD)](01_Architecture.md) | Module mới, luồng phê duyệt/job/reindex/get_context, dữ liệu, ADR, giới hạn L8–L23 |
| 02 | [Quy trình nghiệp vụ (BPD)](02_BPD.md) | BP-08 … BP-15: khai thư mục, phê duyệt theo tầng, hỏi tài liệu, job, giao việc |
| 03 | [Đặc tả chức năng (FS)](03_FS.md) | FR-14 … FR-35, NFR-08 … NFR-15 |
| 04 | [Test case và báo cáo kiểm thử (TC)](04_TC_Test_Report.md) | TC-101 … TC-414 (pytest), TC-901 … TC-919 (CI, UAT) |
| 05 | [Hướng dẫn sử dụng (UG)](05_UG.md) | Cài, cấu hình, markitdown, knowledge, Claude, job |
| 06 | [Runbook xử lý sự cố](06_Runbook.md) | RB-07 … RB-13 |
| 07 | [Sprint Review, Release Notes, Retro](07_Sprint_Review_Retro.md) | Backlog đã làm, DoD, bài học, việc chuyển tiếp |

Mã nối tiếp bộ hồ sơ Phase 0 (`docs/phase0/`): `BP-xx` quy trình, `FR-xx`/`NFR-xx` yêu cầu, `TC-xxx` test case, `RB-xx` sự cố, `Lx` giới hạn đã biết.

## 2. Đối chiếu Exit criteria và hạng mục

**Exit criteria:** từ một thư mục PDF/DOCX trên máy, hỏi Claude và nhận câu trả lời có trích dẫn đoạn nguồn, toàn bộ nội dung tài liệu chỉ rời máy ở mức đoạn được truy xuất.

| Tiêu chí | Kết quả | Bằng chứng |
|---|---|---|
| Claude hỏi qua MCP, nhận đoạn trích có trích dẫn (path, heading) | Đạt trên dữ liệu mẫu | TC-916 (2026-10-22) |
| Chỉ đoạn được truy xuất rời máy, có nhật ký | Đạt | TC-412, TC-414, TC-916: `egress_log` một dòng mỗi lời gọi, root `secret` ẩn trên MCP |
| Thư mục PDF/DOCX thật trên máy | Đạt (TC-918): 8 file docx/pdf/pptx/xlsx, 841 chunk, 3 câu hỏi qua MCP có trích dẫn, 3 dòng `egress_log` | TC-918 |
| CI xanh | Đạt | Mọi PR #3 … #39 merge khi test Windows + CodeQL xanh |

| Roadmap | Hạng mục | FR | Code | Test | Kết quả |
|---|---|---|---|---|---|
| core 0.2 | Config, ToolContext, phê duyệt T0–T3, grants, đích duyệt trước, lệnh quản trị | FR-14 … 19 | `core/{config,runtime,tool,approval,grants,cli,mcp_adapter}.py` | TC-101 … 108 | Đạt |
| 1.1 | Plugin `markitdown` đạt Plugin DoD | FR-24 … 27 | `plugins/lfmap-markitdown/` | TC-301 … 308, 910 | Đạt |
| 1.2 | Backend Docling | — | `plugins/lfmap-markitdown/` (`backend = "docling"`), `kn/` (`pdf_backend`) | Test trong PR #70, #75, #80 | Xong ở Phase 1b (§6) |
| 1.3 | REST adapter | — | — | — | Dời sang đầu Phase 2 (ADR-003, PR #57) |
| 1.4 | `lfmap-knowledge`: catalog, scanner, chunk, embed, LanceDB, cạnh | FR-28 … 34 | `packages/lfmap-knowledge/` | TC-401 … 414, 911, 915 | Đạt (bench 10k TC-917 đạt) |
| 1.5 | MCP knowledge (`knowledge_search`, `knowledge_get_context`…; egress_log) | FR-33, 35 | `kn/search.py`, `kn/tool.py` | TC-412, 414, 916 | Đạt (TC-918) |
| 1.6 | Plugin `powershell` (allow-list script) | — | `plugins/lfmap-powershell/` | Test trong PR #43 | Xong sau mốc (PR #43, `68a042f`); đặc tả `docs/specs/powershell.md`. Hùng chốt 15:41Z tách quyền riêng cho từng script: ADR-020 (sửa ADR-017) merge ở PR #48 |
| 1.7 | Vòng Planner → Task Card → Local Agent → Review (`qwen-loop`) | — | ngoài repo | TC-919 | Đạt (2026-10-21) |
| 1.8 | Job theo lịch + hàng đợi phê duyệt | FR-20 … 23 | `core/{jobs,approvals,jobs_doctor}.py`, `scripts/Invoke-LfmapJob.ps1` | TC-201 … 203, 912 | Đạt (TC-912, 913, 914) |

(`core/` = `packages/lfmap-core/src/lfmap_core/`, `kn/` = `packages/lfmap-knowledge/src/lfmap_knowledge/`)

## 3. Kết quả kiểm thử

- 555 case pytest: CI Windows xanh ở từng PR; chạy lại 2026-10-22 trên Linux tại `b002710`: **545 pass, 10 skip** (chỉ-Windows, OCR, font Arial).
- 4 kiểm tra CI (license, lint, smoke CLI, CodeQL): đạt.
- UAT trên DIEP-ANH: đạt TC-910, 911, 912, 915, 916, 919; đạt thêm TC-913 (approve), 914 (doctor), 917 (bench 10k); TC-918 (thư mục thật) đạt.
- Số đo K14 (TC-917, DIEP-ANH): reindex 10.000 file lần đầu 6.187 s (embed 1,87 file/s); sau PR #44 (gom lô vector) 3.556 s, embed 3,75 file/s; lần hai 45,8 s, sau PR #44 7,2 s (2,0 s trong core); yêu cầu < 60 s **đạt**.
- Lỗi tồn đọng mức chặn: không có. Giới hạn đã biết L8–L23 ở `01_Architecture.md` §9.

## 4. Kết luận và đề xuất

Phần đã làm của Phase 1 (core 0.2, 1.1, 1.4, 1.5, 1.6, 1.7, 1.8) **đạt chức năng và DoD**, kể cả TC-918 (thư mục thật). 1.2 và 1.3 chưa làm, chuyển Phase 1b. **MVP Phase 1 đã được nghiệm thu** (§5).

Đề xuất của Managing Agent (Hùng chốt):

| Phương án | Nội dung | Khuyên |
|---|---|---|
| A | Khi TC-913, 914, 917, 918 đạt: nghiệm thu **MVP Phase 1** (Exit criteria), chuyển 1.2, 1.3, 1.6 thành Phase 1b làm tiếp, cập nhật Roadmap | ✔ Exit criteria không cần 1.2/1.3/1.6; giữ được nhịp; ba hạng mục độc lập với nhau |
| B | Chờ làm xong 1.2, 1.3, 1.6 rồi mới nghiệm thu một lần | Đúng chữ Roadmap nhưng giữ hồ sơ mở thêm nhiều ngày |

Quyết định của Hùng: **A** (2026-10-22 15:41Z). 1.6 đã xong trước khi chốt (PR #43), nên Phase 1b gồm 1.2 Docling, 1.3 REST và việc tách quyền theo từng script `powershell`.

## 5. Ký nhận

| Vai trò | Người | Quyết định | Ngày |
|---|---|---|---|
| Product Owner | Hùng | ☑ Nghiệm thu MVP Phase 1 (phê duyệt trong project thread "Hồ sơ nghiệm thu Phase 1") | 2026-10-22 |
| Lập hồ sơ / Reviewer | Claude (Managing Agent) | Đề nghị phương án A khi các ô chờ đạt | 2026-10-22 |

## 6. Đóng Phase 1b (2026-10-31)

Phase 1b gồm ba hạng mục chuyển từ nghiệm thu MVP (§4) và các giới hạn L20–L23 phát hiện ở TC-918.

| Hạng mục | Kết quả | Bằng chứng |
|---|---|---|
| 1.2 Backend Docling | Xong. Spike GO (PR #68, #71); plugin `markitdown` có `backend = "docling"` tùy chọn (PR #70); `lfmap-knowledge` có `pdf_backend = "docling"` (PR #75); thiếu dữ liệu ngôn ngữ Tesseract báo `ocr_unavailable` (PR #80); `fpdf2`, `img2pdf` vào ngoại lệ giấy phép đã duyệt (PR #81) | Chạy thật trên pc-01 (D3b, 2026-10-28) |
| 1.3 REST adapter | Không làm ở Phase 1b. Theo ADR-003, REST chỉ bật khi có client cần; giữ đặc tả `docs/specs/rest.md`, làm R1 khi đầu Phase 2 có client (Workspace hoặc Flows) | PR #57 |
| Quyền riêng theo từng script `powershell` | Xong: `min_tier` + `Tool.call_tier`, mỗi script trong allow-list có `tier` (mặc định T3) | ADR-020, PR #48 |

| Giới hạn | Trạng thái 2026-10-31 |
|---|---|
| L20 heading `.docx` sai | Đã sửa (chunker); chỉ mục cũ cần `reindex --full` |
| L21 PDF không có heading | Đã xử lý bằng `pdf_backend = "docling"` (tùy chọn, cần cài extra); mặc định markitdown vẫn không có heading |
| L22 `.doc`/Office cũ | Còn mở: chuyển bằng MarkitdownTool rồi index `.md`. Thiết kế đường Office tự động chưa xếp lịch |
| L23 `get_context` đầy ngân sách | Đã sửa (PR #69): cắt theo điểm từng danh sách đã co giãn. Bench `bench/iso-vi` (PR #90): ở 0,5 câu keyword dùng 671 thay vì 1.782 token, precision 0,88 thay vì 0,57, không mất file gold |

Kết luận: Phase 1b **đóng**, không còn hạng mục nào của Roadmap 1.x đang làm. Milestone "Phase 1b" trên GitHub không có issue nào và được đóng cùng PR này. Việc còn lại chuyển Phase 2: R1 REST, L22 (đường Office), các mục backlog ở `07` §6.

