# LFMAP Phase 1 — Hồ sơ nghiệm thu giai đoạn

> **Bản nháp 0.9 (2026-10-22).** Các ô **[CHỜ: …]** được điền khi có số đo và kết quả thử trên DIEP-ANH (thread "Việc trên DIEP-ANH chiều 22/10") và khi Hùng quyết định nghiệm thu.

| Mục | Giá trị |
|---|---|
| Dự án | LFMAP — Local-First Modular Automation Platform (`hungnp1999/lfmap`, Apache-2.0) |
| Giai đoạn | Phase 1 — MVP: Document → Knowledge → Answer (Roadmap 1.1–1.8) và điều kiện tiên quyết lfmap-core 0.2 |
| Thời gian | 2026-10-19 → 2026-10-22; hồ sơ lập 2026-10-22 |
| Mốc nghiệm thu | Commit `b002710` trên `main` (PR #3 … #39) |
| Chưa làm | 1.2 Docling, 1.3 REST, 1.6 plugin `powershell` |
| Product Owner | Hùng |
| Lập hồ sơ | Claude (Managing Agent) |

## 1. Danh mục hồ sơ

| # | Tài liệu | Dùng khi |
|---|---|---|
| 00 | Hồ sơ nghiệm thu (file này) | Kết luận, ký nhận, truy vết tổng |
| 01 | [Kiến trúc (SAD)](01_Architecture.md) | Module mới, luồng phê duyệt/job/reindex/get_context, dữ liệu, ADR, giới hạn L8–L19 |
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
| Thư mục PDF/DOCX thật trên máy | **[CHỜ: TC-918, Hùng chọn thư mục]** | |
| CI xanh | Đạt | Mọi PR #3 … #39 merge khi test Windows + CodeQL xanh |

| Roadmap | Hạng mục | FR | Code | Test | Kết quả |
|---|---|---|---|---|---|
| core 0.2 | Config, ToolContext, phê duyệt T0–T3, grants, đích duyệt trước, lệnh quản trị | FR-14 … 19 | `core/{config,runtime,tool,approval,grants,cli,mcp_adapter}.py` | TC-101 … 108 | Đạt |
| 1.1 | Plugin `markitdown` đạt Plugin DoD | FR-24 … 27 | `plugins/lfmap-markitdown/` | TC-301 … 308, 910 | Đạt |
| 1.2 | Backend Docling | — | — | — | Chưa làm |
| 1.3 | REST adapter | — | — | — | Chưa làm |
| 1.4 | `lfmap-knowledge`: catalog, scanner, chunk, embed, LanceDB, cạnh | FR-28 … 34 | `packages/lfmap-knowledge/` | TC-401 … 414, 911, 915 | Đạt về chức năng; **[CHỜ: bench 10k, TC-917]** |
| 1.5 | MCP knowledge (`knowledge_search`, `knowledge_get_context`…; egress_log) | FR-33, 35 | `kn/search.py`, `kn/tool.py` | TC-412, 414, 916 | Đạt; **[CHỜ: TC-918]** |
| 1.6 | Plugin `powershell` | — | — | — | Chưa làm |
| 1.7 | Vòng Planner → Task Card → Local Agent → Review (`qwen-loop`) | — | ngoài repo | TC-919 | Đạt (2026-10-21) |
| 1.8 | Job theo lịch + hàng đợi phê duyệt | FR-20 … 23 | `core/{jobs,approvals,jobs_doctor}.py`, `scripts/Invoke-LfmapJob.ps1` | TC-201 … 203, 912 | Đạt phần job T0; **[CHỜ: TC-913 approve, TC-914 doctor]** |

(`core/` = `packages/lfmap-core/src/lfmap_core/`, `kn/` = `packages/lfmap-knowledge/src/lfmap_knowledge/`)

## 3. Kết quả kiểm thử

- 555 case pytest: CI Windows xanh ở từng PR; chạy lại 2026-10-22 trên Linux tại `b002710`: **545 pass, 10 skip** (chỉ-Windows, OCR, font Arial).
- 4 kiểm tra CI (license, lint, smoke CLI, CodeQL): đạt.
- UAT trên DIEP-ANH: đạt TC-910, 911, 912, 915, 916, 919; chờ TC-913 (approve), 914 (doctor), 917 (bench 10k), 918 (thư mục thật).
- Số đo K14: reindex 10.000 file lần đầu = **[CHỜ]**; lần hai = **[CHỜ]** s (yêu cầu < 60 s).
- Lỗi tồn đọng mức chặn: không có. Giới hạn đã biết L8–L19 ở `01_Architecture.md` §9.

## 4. Kết luận và đề xuất

Phần đã làm của Phase 1 (core 0.2, 1.1, 1.4, 1.5, 1.7, 1.8) **đạt chức năng và DoD**, trừ các ô chờ số đo/thử thật ở §2–§3. Ba hạng mục 1.2, 1.3, 1.6 chưa làm, nên Phase 1 theo nghĩa đủ Roadmap **chưa đóng**.

Đề xuất của Managing Agent (Hùng chốt):

| Phương án | Nội dung | Khuyên |
|---|---|---|
| A | Khi TC-913, 914, 917, 918 đạt: nghiệm thu **MVP Phase 1** (Exit criteria), chuyển 1.2, 1.3, 1.6 thành Phase 1b làm tiếp, cập nhật Roadmap | ✔ Exit criteria không cần 1.2/1.3/1.6; giữ được nhịp; ba hạng mục độc lập với nhau |
| B | Chờ làm xong 1.2, 1.3, 1.6 rồi mới nghiệm thu một lần | Đúng chữ Roadmap nhưng giữ hồ sơ mở thêm nhiều ngày |

Quyết định của Hùng: **[CHỜ: A hoặc B]**

## 5. Ký nhận

| Vai trò | Người | Quyết định | Ngày |
|---|---|---|---|
| Product Owner | Hùng | **[CHỜ]** ☐ Nghiệm thu MVP Phase 1 ☐ Chưa nghiệm thu | |
| Lập hồ sơ / Reviewer | Claude (Managing Agent) | Đề nghị phương án A khi các ô chờ đạt | 2026-10-22 |
