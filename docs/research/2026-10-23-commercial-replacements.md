# Kế hoạch nghiên cứu thay thế thành phần cho thương mại hoá

- Ngày: 2026-10-23 · Người soạn: Claude (Managing Agent) · Yêu cầu: anh Hùng
- Trạng thái: kế hoạch nghiên cứu, không đổi ADR. Đề xuất ADR ở mục 6 chỉ là **draft** chờ anh Hùng.
- Căn cứ: ADR-005/006/007 (Accepted 2026-10-23), License Register 2026-10-23, code `main` tại `6429077`.
- Không phải tư vấn pháp lý. Giấy phép ghi "cần xác minh" là chưa đọc file LICENSE gốc.

## 1. Nguyên tắc

1. **Dùng ngay cho cá nhân/nội bộ** (anh Hùng đã duyệt): n8n, Open WebUI, NATS, Valkey, Ollama, Office COM.
2. **Không thay sớm.** Chỉ giữ ba thứ từ bây giờ, chi phí gần bằng 0:
   - **Điểm nối (seam):** mỗi thành phần chỉ được chạm qua một interface/giao thức chuẩn, để đổi được mà không sửa plugin.
   - **Theo dõi giấy phép:** biết sớm khi upstream đổi giấy phép.
   - **Hồ sơ phương án:** bảng ứng viên có sẵn, khi đến lúc chỉ cần spike rồi làm.
3. Thực hiện thay thế khi có **tín hiệu kích hoạt** (mục 4), không theo ngày.

## 2. Đánh giá từng thành phần

Mức rủi ro thương mại: **Cao** = không được đóng gói/vận hành cho khách nếu không trả phí; **TB** = được nhưng có điều kiện dễ vi phạm; **Thấp** = permissive, chỉ rủi ro quản trị upstream.

| Thành phần | Dùng hiện tại | Rủi ro thương mại | Điểm nối cô lập | Ứng viên thay thế (giấy phép) | Ưu tiên |
|---|---|---|---|---|---|
| **n8n** | workflow cá nhân (ADR-005) | **Cao**: Sustainable Use License, nhúng/bán cần Embed License trả phí, `.ee` cần Enterprise | n8n chỉ gọi LFMAP qua **REST/MCP** (ADR-005); không package nào import n8n | (1) **Workflow gốc của LFMAP**: `jobs.toml` + Task Scheduler (ADR-018) + Event Bus (Phase 2), Blueprint đã định hướng; (2) Node-RED (Apache-2.0); (3) Activepieces (lõi MIT, thư mục `ee` thương mại); (4) Kestra (Apache-2.0, cần xác minh; JVM, nặng). Loại: Windmill (AGPLv3 + phần đóng) | **1** |
| **Open WebUI** | chat UI local (ADR-007) | **TB**: BSD-3 + điều khoản thương hiệu, văn bản đổi 2 lần trong 18 tháng | UI chỉ nói chuyện với **Ollama (API tương thích OpenAI) + MCP/REST** của LFMAP; không chứa logic LFMAP | (1) **Tauri app riêng** (Roadmap Phase 2) dùng thư viện chat React (assistant-ui, MIT, cần xác minh); (2) LibreChat (MIT); (3) AnythingLLM (MIT cho repo chính; app mobile có điều khoản riêng); Jan (Apache-2.0, cần xác minh) | 2 |
| **NATS** | chưa dùng, Phase 2 (ADR-006) | **Thấp** (Apache-2.0, CNCF). Rủi ro quản trị: Synadia từng muốn đổi sang BSL (2025, đã giải quyết) | **Chưa có**: `lfmap-core` chưa có interface `EventBus` (manifest chỉ có cờ `events: bool`). Cần định nghĩa trước khi viết dòng NATS đầu tiên | in-process bus (mặc định); hàng đợi SQLite/file (đã có kiểu ADR-018); Valkey Streams (BSD-3); ZeroMQ (pyzmq BSD-3, libzmq MPL-2.0) | 3 (làm seam trước Phase 2) |
| **Valkey** | chưa dùng (ADR-006) | **Thấp** (BSD-3, Linux Foundation) | Chưa có; nếu dùng, qua interface `KVCache` nhỏ | SQLite (Public Domain); diskcache (Apache-2.0, cần xác minh). Loại: Redis ≥ 8 (AGPL/SSPL/RSAL), Dragonfly (BSL, cần xác minh) | 5 |
| **Ollama** | embed bge-m3, model local | **Thấp** (MIT; app desktop nằm trong repo MIT theo nguồn thứ cấp, cần xác minh). Rủi ro: công ty đơn lẻ, có dịch vụ cloud trả phí | `Embedder` Protocol (`lfmap_knowledge/search.py`, `indexer.py`); URL loopback trong config | llama.cpp `llama-server` (MIT, API tương thích OpenAI, có endpoint embedding); ONNX Runtime (MIT) nhúng thẳng | 4 |
| **Model weights** | qwen2.5-coder:14b (Internal, dev), bge-m3 (Ship) | **TB**: mỗi model/kích cỡ một giấy phép (vd. Qwen2.5-Coder 3B riêng; Llama có điều khoản người dùng và tên gọi) | bảng Model trong License Register; tên model trong config | chọn model Apache-2.0/MIT cho phần Ship; ma trận giấy phép theo model khi cần model chat trong sản phẩm | 3 |
| **Microsoft Office COM** | đọc .doc/.ppt cũ, chỉ GUI MarkitdownTool (ADR-011) | **TB**: không phân phối Office, nhưng tính năng phụ thuộc máy khách có Office | `Backend` Protocol (`lfmap_markitdown/backends/base.py`); reason_code `needs_office` | LibreOffice headless (MPL-2.0, gọi process, ~350 MB, rủi ro tải tài nguyên từ xa); Docling (MIT, cần xác minh giấy phép model đi kèm) | 6 |
| **Docling models** | 1.2 (Phase 1b) | **TB** đến khi đọc giấy phép model | `Backend` Protocol | MarkItDown (MIT) làm mặc định | khi bật 1.2 |
| **PyInstaller, OCRmyPDF, LibreOffice, Tesseract** | build / OCR | **Thấp**: GPL + bootloader exception; MPL-2.0 nguyên bản (ADR-015); Apache-2.0 | `scripts/check_licenses.py` + THIRD_PARTY_NOTICES | không cần thay; chỉ cần sinh notices tự động khi phát hành | 7 |

Tóm lại: chỉ **n8n** là rủi ro cao thật, và nó đã ở ngoài sản phẩm. Việc đáng làm sớm nhất không phải thay n8n mà là **tạo seam `EventBus`** trước Phase 2, vì đó là điểm nối duy nhất còn thiếu.

## 3. Điều kiện để "đổi được mà không ảnh hưởng cấu phần khác"

Mỗi điều kiện kiểm chứng được bằng test hoặc CI, không chỉ là cam kết:

| # | Điều kiện | Kiểm chứng |
|---|---|---|
| S1 | Không package nào trong `packages/`, `plugins/` phụ thuộc n8n, Open WebUI, NATS client hay Valkey client trực tiếp | `check_licenses.py` + test import-guard (đề xuất RT-02) |
| S2 | Event bus đi qua `EventBus` Protocol trong `lfmap-core`, có bộ contract test chạy với mọi implementation | RT-03 |
| S3 | Embedding/LLM local qua `Embedder` (và sau này `ChatModel`) Protocol, cấu hình bằng URL + tên model | đã có cho Embedder |
| S4 | UI chỉ dùng MCP/REST công khai của LFMAP | REST spec `docs/specs/rest.md` |
| S5 | Workflow của anh Hùng trong n8n chỉ gọi LFMAP qua REST/MCP, không dùng node `.ee` | kiểm kê định kỳ (RT-07) |

## 4. Tín hiệu kích hoạt ("thời cơ chín muồi")

| Mã | Tín hiệu | Việc phải làm khi xảy ra |
|---|---|---|
| K1 | Upstream đổi giấy phép hoặc điều khoản (do RT-01 phát hiện) | đánh giá trong 1 tuần; nếu xấu đi: chạy giai đoạn G2 cho thành phần đó |
| K2 | Bắt đầu Phase 2 (Event Bus, Tauri) | G1 cho NATS (seam) và chat UI |
| K3 | Có người dùng thứ hai ngoài anh Hùng (đồng nghiệp, khách thử, pilot) | G2 cho mọi thành phần **Cao/TB** mà người đó sẽ chạm vào |
| K4 | Quyết định bán/phân phối một gói (Phase 3 hoặc plugin lẻ) | G3: thay xong trước khi phát hành; SBOM + notices |
| K5 | Workflow quan trọng chỉ chạy được nhờ tính năng riêng của n8n | G2 cho n8n, chuyển workflow đó sang LFMAP |

## 5. Lộ trình nghiên cứu theo giai đoạn

| Giai đoạn | Khi nào | Chi phí | Nội dung |
|---|---|---|---|
| **G0 — Canh chừng** | từ nay | rất thấp, chạy tự động | RT-01 theo dõi giấy phép; RT-02 import-guard; giữ bảng mục 2 cập nhật |
| **G1 — Chuẩn bị seam + hồ sơ** | trong Phase 1b/đầu Phase 2 (K2) | 1 phiên Cloud mỗi task | RT-03 `EventBus` Protocol; RT-04, RT-05 so sánh bằng tài liệu; RT-06 ma trận giấy phép model |
| **G2 — Spike** | khi có K1/K3/K5 | 1–2 phiên Cloud mỗi thành phần | dựng ứng viên số 1 trong container Linux, chạy đúng một luồng thật của LFMAP, đo, ghi kết quả |
| **G3 — Thay thế** | K4 | theo handoff riêng | ADR mới (supersede ADR-005/006/007 tương ứng), handoff, task Claude Code |

## 6. Task nghiên cứu nhỏ chạy trên Cloud

Mỗi task là một phiên Claude Code Cloud, đầu ra là file trong `docs/research/` hoặc PR nhỏ. Không task nào cần máy DIEP-ANH.

| Mã | Giai đoạn | Việc | Đầu ra | Tiêu chí xong |
|---|---|---|---|---|
| RT-01 | G0 | Script stdlib tải file LICENSE của n8n, open-webui, nats-server, valkey, ollama, librechat, activepieces, node-red; so SHA-256 với lần trước; routine Cloud chạy hằng tháng, báo khi đổi | `scripts/license_watch.py` + `docs/research/license-watch.json` | lần chạy đầu ghi baseline; thử sửa hash giả thì báo đổi |
| RT-02 | G0 | Test import-guard: fail nếu `packages/`, `plugins/` khai báo hoặc import `nats`, `valkey`, `redis`, `n8n` ngoài adapter được phép | test trong `lfmap-core` | CI xanh; thử thêm import thì đỏ |
| RT-03 | G1 | Spec + Protocol `EventBus` (publish/subscribe, tên sự kiện `<plugin>.<operation>.requested` theo ADR-014), implementation in-process, bộ contract test dùng lại được cho NATS sau này | `docs/specs/events.md` + code nhỏ | contract test xanh với in-process |
| RT-04 | G1 | So sánh workflow engine: workflow gốc LFMAP vs Node-RED vs Activepieces vs Kestra: giấy phép (đọc LICENSE gốc), chạy native Windows, nhúng/phân phối được, số dịch vụ nền | `docs/research/workflow-engines.md` | bảng có nguồn; khuyến nghị một hướng |
| RT-05 | G1 | So sánh nền chat UI cho Tauri: assistant-ui, LibreChat, AnythingLLM, Jan: giấy phép, MCP client, rebrand được không | `docs/research/chat-ui.md` | như trên |
| RT-06 | G1 | Ma trận giấy phép model chạy được trên 16 GB VRAM (Qwen, Llama, Gemma, Mistral, Phi, embedding) theo từng kích cỡ | bổ sung bảng Model của License Register (đề xuất) | mỗi dòng có link model card |
| RT-07 | G1 | Kiểm kê workflow n8n của anh Hùng (xuất JSON, không chứa bí mật) → map sang `jobs.toml`/EventBus; chỉ làm khi đã có workflow | `docs/research/n8n-inventory.md` | mỗi workflow có hướng thay |
| RT-08 | G2 | Spike `llama-server` thay Ollama cho `Embedder` (bge-m3 GGUF), so vector và tốc độ trong container CPU | `docs/research/llamacpp-embedder.md` | cosine ≥ 0,99 so với Ollama trên mẫu nhỏ |
| RT-09 | G2 | Spike Node-RED (hoặc ứng viên RT-04 chọn) gọi REST của LFMAP chạy một job thật | ghi chú + ví dụ flow | flow chạy được trong container |
| RT-10 | G3 | SBOM (CycloneDX) + sinh THIRD_PARTY_NOTICES tự động cho gói phát hành | script + CI | notices đủ mọi dòng Ship |

Thứ tự đề xuất: RT-01, RT-02 ngay (rẻ, chạy tự động); RT-03 trước khi viết NATS; còn lại theo tín hiệu.

## 7. ADR draft (chờ anh Hùng, chưa đưa vào 03_Decisions_ADR)

```markdown
### ADR-021: Thành phần Internal phải có điểm nối và tín hiệu thay thế
- Trạng thái: Proposed
- Ngày: 2026-10-23
- Bối cảnh: ADR-005/006/007 cho dùng n8n, Open WebUI, NATS, Valkey ở mức nội bộ. Anh Hùng muốn chuẩn bị thay thế dần các thành phần không hợp thương mại hoá mà không chặn tiến độ.
- Quyết định: (1) Mọi thành phần phân loại Internal hoặc có rủi ro thương mại TB/Cao chỉ được chạm qua một interface hoặc giao thức công khai (REST, MCP, API tương thích OpenAI, Protocol trong lfmap-core), có test hoặc CI kiểm chứng. (2) Giấy phép upstream của các thành phần đó được theo dõi tự động hằng tháng. (3) Việc thay thế bắt đầu theo tín hiệu K1–K5 trong `docs/research/2026-10-23-commercial-replacements.md`, không theo lịch.
- Phương án đã cân nhắc: thay ngay bằng thành phần permissive (chậm tiến độ, tốn công cho thứ chưa bán); không chuẩn bị gì (rủi ro bị động khi upstream đổi giấy phép hoặc khi có khách).
- Hệ quả: thêm RT-01 (license watch), RT-02 (import-guard), RT-03 (EventBus Protocol) vào backlog; ADR-006 "adapter Events viết theo interface" có tiêu chí kiểm chứng cụ thể.
```

## 8. Cập nhật tài liệu dự án (đề xuất, chưa làm)

- 05_Roadmap: Backlog thêm "RT-01..RT-03 (chuẩn bị thay thế thành phần Internal)"; Phase 2 ghi "EventBus Protocol trước NATS".
- 04_License_Register: thêm dòng ứng viên khi RT-04/05 xong (Node-RED, Activepieces, assistant-ui...) sau khi đọc LICENSE gốc.

## Nguồn (kiểm tra 2026-10-23)

- Decision pack ADR-005/006/007: `/mnt/project-files/lfmap-docs/ADR-005-007_decision-pack_2026-10-23.md`
- Activepieces license: https://www.activepieces.com/docs/about/license
- Node-RED license: https://nodered.org/about/license/
- Windmill: https://windmill.dev/brand ; https://isitreallyfoss.com/projects/windmill/
- AnythingLLM (MIT): https://www.amd.com/en/ecosystem/isv/consumer-partners/anythingllm.html ; điều khoản mobile: https://docs.anythingllm.com/mobile/terms
- Ollama app (nguồn thứ cấp): https://mindwiredai.com/?p=2302
