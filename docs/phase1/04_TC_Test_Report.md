# LFMAP Phase 1 — Test Case và Báo cáo kiểm thử

Phiên bản 0.9 bản nháp · 2026-10-22 · Mốc code `b002710`

## 1. Chiến lược kiểm thử

| Mức | Công cụ | Phạm vi | Nơi chạy |
|---|---|---|---|
| Unit | pytest | Từng module core, markitdown, knowledge | Máy dev, CI, Cloud |
| Tích hợp adapter | `CliRunner`, `MCPServer.call_tool` trong process, `user_dirs` + `config.toml` tạm | CLI/MCP đi đúng đường dựng quyền như khi chạy thật (bài học A2 Phase 0) | CI |
| Đa process | `multiprocessing` | `indexer.lock`, LanceDB đọc khi đang ghi | CI, TC-K0 trên DIEP-ANH |
| Giả lập hệ thống | `_schtasks`, `_run`, `_http_get` thay bằng giả; server HTTP giả cho Ollama | Job, doctor, embedder: không đụng Task Scheduler/`LOCALAPPDATA` thật | CI |
| Ngoại tuyến | `socket.socket` bị chặn | markitdown không gọi mạng | CI |
| Tương đương | `expected.json` ghi từ MarkitdownTool 2.4.0 | Phân loại markitdown | CI |
| Test chuẩn bị sẵn | Test viết trước trong `docs/handoff/prep/`, xanh với bản tham chiếu bỏ đi | K4–K14, J1–J4 | Trước mỗi phiên code |
| Tĩnh | ruff, CodeQL `security-extended` | Toàn repo | CI |
| Chấp nhận (UAT) | Thủ công / Remote Control | Windows, Ollama, Task Scheduler, Claude Code thật | DIEP-ANH |

Quy ước bỏ qua có chủ đích (skip): test chỉ-Windows (hoa thường, junction), test cần extra `[ocr]` + Tesseract, test cần font Arial. Trên CI Windows chỉ còn OCR bị skip (không có Tesseract).

Chạy lại: `uv run pytest` (toàn bộ) hoặc `uv run pytest packages/lfmap-knowledge/tests/test_search.py -q`.

## 2. Danh mục test case

Mỗi dòng là một nhóm (một file test); số trong ngoặc là số case pytest đã thu thập (tính cả tham số). Đường dẫn: `core/` = `packages/lfmap-core/tests/`, `md/` = `plugins/lfmap-markitdown/tests/`, `kn/` = `packages/lfmap-knowledge/tests/`.

### Core 0.2

| TC | File (case) | Kiểm tra chính | FR |
|---|---|---|---|
| TC-101 | `core/test_config.py` (5) | Thiếu file = rỗng; TOML hỏng; biến mảng; `[paths]` phải là chuỗi; UNC trong config bị từ chối | FR-14 |
| TC-102 | `core/test_runtime.py` (8) | `build_tool` điền channel, settings (sai kiểu → lỗi); `context_for` giữ quyền/kênh/`dry_run`; `default_context` không quyền | FR-15 |
| TC-103 | `core/test_explicit_read.py` (13) | Mặc định chỉ roots; CLI truyền channel + explicit_read; đọc ngoài root có audit, trong root không; vẫn chặn UNC; không nới ghi | FR-18 |
| TC-104 | `core/test_approval.py` (42) | `base_tier`, bảng quyết định tầng × kênh × policy × preapproved × elicitation; T3 không nới được; `deny` thắng; grant; đích duyệt trước theo mức dữ liệu và hạn; audit chỉ nhận khóa đã định | FR-16, FR-17 |
| TC-105 | `core/test_grants.py` (6) | Parse thời hạn; giới hạn 7 ngày / 24 giờ; hết hạn; mục hỏng không cấp; revoke | FR-17 |
| TC-106 | `core/test_cli.py` (11) | Lệnh sinh tự động; T1 chạy không hỏi; T2 hỏi ở TTY, cần `--yes` khi không TTY; T3 bỏ qua `--yes`; grant cần TTY | FR-16, FR-19 |
| TC-107 | `core/test_cli_config.py` (12) | `config path`; `add-folder` tạo file, giữ comment, cần TTY, từ chối UNC/tên lạ; `audit tail`; `plugins health` | FR-14, FR-19 |
| TC-108 | `core/test_mcp_adapter.py` (18) | T1 chạy + audit; T2 qua `--approve`, elicitation, từ chối khi không có back-channel; `--approve` hết hạn 8 giờ; T3 từ chối dù `--approve`, chạy khi có grant; policy deny | FR-16, FR-17 |
| TC-109 | `core/test_permissions.py` (17), `test_errors.py` (4), `test_manifest.py` (7), `test_tool.py` (7), `test_smoke.py` (1), `plugins/lfmap-echo/tests` (4) | Hồi quy Phase 0 (TC-001 … TC-086) | FR-01 … FR-13 |

### Job theo lịch (1.8)

| TC | File (case) | Kiểm tra chính | FR |
|---|---|---|---|
| TC-201 | `core/test_jobs.py` (36) | Parse `jobs.toml` (hợp lệ, sai, trùng id, thiếu file, `LFMAP_JOBS`); `jobs list/run`; kênh `job`; job tắt; plugin/op lạ; `task_command` 3 kiểu lịch + `pwsh` đầy đủ; `register` tạo/xóa, `--dry-run`, chỉ thư mục `\LFMAP\`; T1 với `max_tier = 1` chạy + audit | FR-20, FR-21 |
| TC-202 | `core/test_approvals.py` (51) | Bảng `job_decision`; job không bao giờ hỏi/không dùng grant; `max_tier = 0` chỉ xếp hàng `local_write`; nâng tầng lúc chạy cũng xếp hàng; đề xuất trùng gộp; `deny` không xếp hàng; TTL; hết hạn → `expired`; approve/reject cần TTY, chạy đúng một lần, trả lời "không" giữ `pending`; id xấu bị từ chối trước I/O; file giả mạo/tầng bị hạ không được duyệt; không file nào bị xóa; MCP không có tool duyệt | FR-22 |
| TC-203 | `core/test_jobs_doctor.py` (26) | Tên và thứ tự kiểm tra; uv/pwsh thiếu; task thiếu/thừa/`pwsh` trần; S4U ok; sleep đọc giá trị AC mọi ngôn ngữ; không `schtasks`/`powercfg` → không xác định; Ollama chỉ kiểm khi cần; doctor chỉ đọc; exit 0/1, `--json` | FR-23 |

### Plugin markitdown (1.1)

| TC | File (case) | Kiểm tra chính | FR |
|---|---|---|---|
| TC-301 | `md/test_schemas.py` (4) | Manifest khớp class; nhóm định dạng không chồng nhau; `max_chars` > 0 | FR-24 … FR-27 |
| TC-302 | `md/test_quality.py` (33) | Từ hỏng/đúng nhiều ngôn ngữ; lớp chữ PDF đúng/hỏng theo trang; trang rỗng; quá ít chữ không chấm; PDF không đọc được | FR-24 |
| TC-303 | `md/test_backend.py` (5) | `convert_stream` ra Markdown; báo phiên bản | FR-25 |
| TC-304 | `md/test_tool.py` (15) | docx; PDF chữ đủ điều kiện; PDF scan/ảnh cần OCR; định dạng không hỗ trợ; quá cỡ; ngoài root bị từ chối; cắt `max_chars`; `force_ocr`; `info`/`health` | FR-24, FR-25, FR-27 |
| TC-305 | `md/test_ocr.py` (4) | Ảnh → PDF có chữ; ngôn ngữ có `eng`; thiếu Tesseract | FR-25 |
| TC-306 | `md/test_export.py` (11) | File đơn, thư mục, `recursive`; file đã có → `exists`; ghi đè hỏi một lần, từ chối không ghi gì; tạo mới không cần duyệt; `output_dir` ngoài root/tương đối; không vào junction/symlink; `max_files` | FR-26 |
| TC-307 | `md/test_parity.py` (13) | Phân loại khớp MarkitdownTool 2.4.0 trên mọi fixture; fixture < 2 MB | FR-24, NFR-10 |
| TC-308 | `md/test_offline.py` (1) | `info`, `classify`, `convert`, `export` chạy khi socket bị chặn | NFR-08 |

### lfmap-knowledge (1.4, 1.5)

| TC | File (case) | Kiểm tra chính | FR |
|---|---|---|---|
| TC-401 | `kn/test_schemas.py` (14) | Input phẳng; giới hạn `limit`/`token_budget`; output `untrusted`; manifest khớp, discovery | FR-30 … FR-34 |
| TC-402 | `kn/test_store.py` (8) | Schema, migrate hai lần, ràng buộc, pragma; readonly không ghi; process thứ hai nhận `indexer_busy`; khóa nhả sau lỗi | FR-28 |
| TC-403 | `kn/test_scanner.py` (10) | Mới/đổi/không đổi/xóa; BLAKE2b-256; nội dung đã biết → `indexed`; định dạng lạ vẫn vào catalog; quá cỡ không hash; exclude, ẩn, `~$`; không vào thư mục liên kết; tên fold | FR-28 |
| TC-404 | `kn/test_extract.py` (9) | Ghi cache, lần hai dùng cache; `.doc` → skip; phiên bản extractor khác/sidecar hỏng → trích lại; không còn file tạm; giữ xuống dòng | FR-29 |
| TC-405 | `kn/test_chunker.py` (11) | Offset trỏ đúng; heading lồng; gộp đoạn ngắn; cắt đoạn dài và câu không dấu chấm; bảng nhỏ giữ nguyên, bảng dài lặp tiêu đề | FR-29 |
| TC-406 | `kn/test_fts.py` (12) | Fold `đ`; mọi từ phải khớp; tìm không dấu; vô hiệu cú pháp FTS5; truy vấn rỗng; xóa nội dung; thứ tự, limit | FR-29 |
| TC-407 | `kn/test_embed.py` (13) | Loopback nhận, IP khác từ chối; cần quyền `network`; lô 32; danh sách rỗng không gửi; server tắt → `backend_unavailable`; sai số vector; bỏ qua proxy | FR-29, NFR-08 |
| TC-408 | `kn/test_vectors.py` (14) | Upsert thay theo id, kiểm độ dài/chiều; search; `vector_of`; xóa theo hash chặn injection; bảng riêng theo model; `drop`; ANN từ ngưỡng 50k | FR-29 |
| TC-409 | `kn/test_indexer.py` (23) | Lần đầu trích + chunk + embed; lần hai không trích không embed; file giống hệt chung nội dung; đổi/xóa + GC; xóa `vectors\` embed lại không trích; `full` dựng lại từ cache; model mới bảng mới; Ollama tắt không lỗi; lỗi trích thử 3 lần; root thiếu không xóa gì; root bỏ khỏi cấu hình; `root` phải hợp lệ; writer thứ hai busy; `status` trước/sau; tiến độ | FR-30, NFR-11, NFR-12 |
| TC-410 | `kn/test_catalog.py` (27) | `search_files`: mọi từ khớp bỏ dấu, glob, `%`/`_` là ký tự thường, root/ext/status/`modified_after`, limit + total; `get_file`: chunk, duplicates, cache; ngoài catalog/root → `not_found`; root bị loại | FR-31, FR-35 |
| TC-411 | `kn/test_edges.py` (20) | `GENERATED_FROM` hai chiều, idempotent; `REFERENCES` tương đối trong root, bỏ link không an toàn (cả sau decode); `related` đủ lý do, lý do mạnh nhất thắng, limit, không chính nó, ẩn root bị loại, không có vector vẫn chạy | FR-34 |
| TC-412 | `kn/test_search.py` (26) | keyword fold; vector theo nghĩa, thiếu Ollama → lỗi; hybrid dùng cả hai, lùi về keyword; chunk → file đầu theo `rel_path` + duplicates; bỏ file xóa, vector cũ; root `secret` và root ngoài danh sách bị ẩn trên `mcp`/`rest`, không lọt qua vector/duplicates; `egress_log` đúng một dòng mỗi lời gọi `mcp`, không ghi ở kênh local/kết quả rỗng; `get_context` theo ngân sách, citation đúng | FR-32, FR-33, FR-35 |
| TC-413 | `kn/test_tool.py` (3) | Tiến độ ra stderr ở `cli`; Ollama tắt: reindex chỉ keyword, `status` báo | FR-30 |
| TC-414 | `kn/test_tool_queries.py` (11) | Qua `tool.py` trên kênh `mcp`: mọi operation ẩn root `secret`, root vừa đổi sang secret ẩn trước reindex, `egress_log`; `get_file` ngoài roots bị từ chối; mô tả nói kết quả là dữ liệu | FR-31 … FR-35 |

### Kiểm tra ngoài pytest và UAT

| TC | Bước | Kỳ vọng | Kết quả |
|---|---|---|---|
| TC-901 | `uv sync --frozen --no-dev` + `check_licenses.py` (CI) | Không `FAIL` | Đạt ở mọi PR đã merge |
| TC-902 | `ruff check .`, `ruff format --check .` (CI) | Sạch | Đạt |
| TC-903 | `lfmap echo say --text "xin chao" --json` (CI) | JSON đúng | Đạt |
| TC-904 | CodeQL Python + Actions | Không cảnh báo mở | Đạt (điều kiện merge) |
| TC-910 (UAT) | markitdown qua MCP stdio thật trên Windows: `info`, `classify`, `convert`, đọc ngoài root bị từ chối, `export` tạo file (T1, có audit), ghi đè bị từ chối khi chưa duyệt (T2, có audit) | Như mô tả | Đạt, 2026-10-20 (TC-M9, PR #15) |
| TC-911 (UAT) | TC-K0 spike trên DIEP-ANH: ghi LanceDB 20k vector trong khi 2 process đọc; FTS5; bge-m3 | 0 lỗi đọc | Đạt 2026-10-20: 0 lỗi; 49,6 ms ở 20k, 197,7 ms ở 100k (vét cạn); p95 đọc ~550 ms khi đang ghi; 7,5 chunk/s |
| TC-912 (UAT) | Job `echo-hello` (T0) chạy theo lịch khi máy ở màn hình khóa (S4U) | Có dòng log, exit 0 | Đạt 2026-10-22: task chạy S4U, Last Result 0 |
| TC-913 (UAT) | Job `markitdown.export` với `max_tier = 0` chỉ tạo đề xuất; `lfmap approvals approve` thực thi và ghi audit | Có `hello.md`, `pending` trống, audit có `approve` | Phần xếp hàng đạt (đề xuất `20261022T055248Z-export-test-c33c1fbb`). **[CHỜ: Hùng chạy `approve` ở DIEP-ANH, ca tối 22/10]** |
| TC-914 (UAT) | `lfmap jobs doctor` trên DIEP-ANH | Không có `FAIL` | **[CHỜ: xác nhận kết quả từ thread "Việc trên DIEP-ANH chiều 22/10"]** |
| TC-915 (UAT) | K9 trên thư mục thật `D:\Tmp\kb-test` (20 file `.md`) | Lần 2 không trích/embed; xóa vectors thì embed lại | Đạt 2026-10-22: lần 1 extracted 20, embedded 20, 62 s; lần 2 0/0; lần 3 sau khi đổi tên `vectors` embedded 20; 278 chunk; 0 lỗi |
| TC-916 (UAT) | K14 qua MCP (LOCALAPPDATA tách riêng, `a1bcf38`): `knowledge_get_context`, `knowledge_search` | Citation đúng; `untrusted`; tôn trọng ngân sách; root `secret` ẩn trên `mcp`, hiện trên `cli`; `egress_log` một dòng mỗi lời gọi có hit; top-5 như cũ sau khi dựng lại vectors | Đạt 2026-10-22 |
| TC-917 (UAT) | K14 bench 10.000 file trên DIEP-ANH | Reindex lần hai < 60 s | **[CHỜ: thời gian reindex lần đầu = …; lần hai = … s; nguồn: thread "Việc trên DIEP-ANH chiều 22/10"]** (đang chạy: trích ~13–14 phút, embed ~2 file/s) |
| TC-918 (UAT, Exit) | Thư mục PDF/DOCX thật do Hùng chọn: hỏi Claude Code, xem trích dẫn và `egress_log` | Câu trả lời có trích dẫn đường dẫn + heading; chỉ đoạn được truy xuất rời máy | **[CHỜ: Hùng chọn thư mục; kết quả thử]** |
| TC-919 (quy trình) | Vòng qwen-loop chạy thật đợt K4–K7 (Roadmap 1.7) | Có báo cáo B5, quyết định B6 | Đạt 2026-10-21: 3/4 card xanh theo test, K5 viết lại trong review; PR #26 |

## 3. Kết quả

| Lần chạy | Môi trường | Kết quả |
|---|---|---|
| CI mỗi PR #3 … #39 | GitHub Actions `windows-latest` + CodeQL | Xanh (điều kiện merge) |
| Chạy lại khi lập tài liệu (2026-10-22) | Linux container, Python 3.12, commit `b002710` | **545 pass, 10 skip** |
| UAT | DIEP-ANH, xem bảng trên | 6 đạt, 4 chờ (TC-913 phần approve, TC-914, TC-917, TC-918) |

10 skip trên Linux: 1 hoa thường (chỉ Windows), 1 junction (chỉ Windows), 4 OCR (cần extra + Tesseract), 4 font Arial.

Tổng: 555 case pytest (423 hàm test; tăng 495 case so với 60 của Phase 0) + 4 kiểm tra CI + 10 UAT/quy trình. Không có lỗi tồn đọng mức chặn trong phần đã làm. Lỗi phát hiện qua UAT và đã sửa: `pwsh` alias Store không chạy được từ Task Scheduler (`0x80070002`) → PR #34.

## 4. Ma trận truy vết yêu cầu → test

| Roadmap | FR / NFR | Test case |
|---|---|---|
| core 0.2 | FR-14 … FR-19 | TC-101 … TC-108 |
| 1.1 | FR-24 … FR-27, NFR-08, 09, 10 | TC-301 … TC-308, TC-901, TC-910 |
| 1.4 | FR-28 … FR-34, NFR-11, 12, 13 | TC-401 … TC-414, TC-911, TC-915, TC-917 |
| 1.5 | FR-33, FR-35 | TC-412, TC-414, TC-916, TC-918 |
| 1.7 | — | TC-919 |
| 1.8 | FR-20 … FR-23, NFR-15 | TC-201 … TC-203, TC-912 … TC-914 |
| Phase 0 (hồi quy) | FR-01 … FR-13 | TC-109 |
| 1.2, 1.3, 1.6 | — | Chưa làm |
