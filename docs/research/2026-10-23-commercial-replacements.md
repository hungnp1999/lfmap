# Kế hoạch nghiên cứu thay thế thành phần cho thương mại hoá

- Ngày: 2026-10-23 · Người soạn: Claude (Managing Agent) · Yêu cầu: anh Hùng
- Bản 1.1 (2026-10-23): theo chỉ đạo của anh Hùng, **ưu tiên tự xây hoặc làm sản phẩm phái sinh** trên cơ sở tham khảo sản phẩm hiện có, thay vì đổi sang một sản phẩm bên thứ ba khác. Mục tiêu: tỷ trọng phụ thuộc phần mềm bên thứ ba thấp nhất có thể.
- Trạng thái: kế hoạch nghiên cứu. **ADR-021 Accepted** (anh Hùng chốt 2026-10-23), ADR-006 đã sửa theo: EventBus tự xây trên SQLite, NATS chỉ khi nhiều máy.
- Căn cứ: ADR-005/006/007 (Accepted 2026-10-23), License Register 2026-10-23, code `main`.
- Không phải tư vấn pháp lý. Giấy phép ghi "cần xác minh" là chưa đọc file LICENSE gốc.

## 1. Nguyên tắc

1. **Dùng ngay cho cá nhân/nội bộ** (anh Hùng đã duyệt): n8n, Open WebUI, NATS, Valkey, Ollama, Office COM.
2. **Thứ tự ưu tiên khi thay một thành phần:**
   1. **Tự xây** (in-house): viết mới trong LFMAP, tham khảo hành vi, tài liệu, giao thức của sản phẩm hiện có.
   2. **Phái sinh** (derivative): fork hoặc chép có chọn lọc mã của dự án **permissive** (MIT, BSD, Apache-2.0), giữ thông báo bản quyền, rồi sở hữu và bảo trì phần đó như mã của mình.
   3. **Dùng sản phẩm có sẵn** chỉ khi hai cách trên không hợp lý (mục 3).
3. **Tự xây có giới hạn.** Nguyên tắc solo-maintainable vẫn đứng trên. Không viết lại thứ là hạ tầng phổ thông, ổn định, permissive và rất khó làm (SQLite, Python, runtime suy luận model). Những thứ đó đi sau một interface mỏng để luôn đổi được.
4. **Không thay sớm.** Từ bây giờ chỉ làm ba việc gần như không tốn chi phí: tạo **điểm nối (seam)**, **theo dõi giấy phép**, và giữ **hồ sơ phương án**. Việc xây thật bắt đầu theo **tín hiệu kích hoạt** (mục 5).

## 2. Ranh giới pháp lý khi tự xây và làm phái sinh

Đây là điều kiện để mã tự xây được coi là của anh Hùng và đăng ký quyền tác giả được (phần hồ sơ đăng ký làm ở thread riêng).

| Nguồn tham khảo | Được làm | Không được làm |
|---|---|---|
| MIT, BSD, Apache-2.0 (Node-RED, Activepieces lõi, LibreChat, llama.cpp...) | đọc mã, fork, chép có chọn lọc, sửa, bán | xoá thông báo bản quyền; với Apache-2.0: bỏ file NOTICE hoặc không ghi chú file đã sửa |
| MPL-2.0 | dùng nguyên bản (ADR-015) | sửa file mà không công bố mã file đó |
| Fair-code, giấy phép có điều khoản riêng, AGPL, SSPL, BSL (n8n, Open WebUI, Windmill, Redis ≥ 8...) | đọc **tài liệu công khai, giao thức, hành vi** để học ý tưởng | chép mã, dịch mã sang ngôn ngữ khác, đọc mã rồi viết lại gần như nguyên dạng, dùng tên/thương hiệu |

Quy tắc làm việc:
- **Phòng sạch (clean-room) nhẹ** cho nhóm thứ ba: phiên Claude Code viết mã không được nạp mã nguồn của n8n, Open WebUI, Windmill, Redis. Chỉ nạp spec do Claude soạn từ tài liệu công khai.
- **Sổ nguồn gốc (provenance):** mỗi module ghi một dòng "tự viết / phái sinh từ X (giấy phép, commit) / tham khảo hành vi của Y". Sổ này vừa phục vụ tuân thủ giấy phép, vừa là bằng chứng nguồn gốc cho hồ sơ quyền tác giả (theo Luật SHTT Việt Nam, tác phẩm phái sinh chỉ được bảo hộ khi không gây phương hại đến quyền tác giả của tác phẩm gốc; chi tiết để thread hồ sơ SHTT xác minh).

## 3. Tiêu chí: tự xây, phái sinh, hay giữ

Tự xây khi **đủ cả ba**: (a) là năng lực lõi tạo ra giá trị riêng của LFMAP; (b) phần LFMAP thật sự cần nhỏ hơn nhiều so với sản phẩm gốc; (c) một người bảo trì được với test tự động.
Phái sinh khi có (a) nhưng phần cần dùng lớn hoặc khó, và có sẵn mã permissive tốt.
Giữ phụ thuộc khi là hạ tầng phổ thông, permissive, ổn định, và đã nằm sau interface.

## 4. Đánh giá từng thành phần

| Thành phần | Rủi ro thương mại | Điểm nối | **Hướng ưu tiên** | Tham khảo (giấy phép) | Dự phòng có sẵn |
|---|---|---|---|---|---|
| **n8n** | **Cao**: Sustainable Use License; nhúng/bán cần Embed License | chỉ gọi LFMAP qua REST/MCP (ADR-005) | **Tự xây** "LFMAP Flows" trong `lfmap-core`: định nghĩa luồng bằng TOML (trigger → các bước gọi operation → bước duyệt), chạy trên jobs (ADR-018) + EventBus, duyệt theo tầng ADR-017. Trình soạn luồng dạng kéo thả để sau, trong Tauri | n8n, Windmill: **chỉ tài liệu/hành vi** (clean-room). Node-RED (Apache-2.0), Activepieces lõi (MIT): được đọc và phái sinh | Node-RED |
| **Open WebUI** | **TB**: BSD-3 + điều khoản thương hiệu, văn bản đổi 2 lần trong 18 tháng | UI chỉ nói chuyện với API tương thích OpenAI + MCP/REST của LFMAP | **Tự xây** chat trong Tauri app (Roadmap Phase 2), chỉ phần LFMAP cần: hội thoại, trích dẫn nguồn, gọi tool, màn duyệt | Open WebUI: **chỉ hành vi/UX** (clean-room). LibreChat (MIT), assistant-ui (MIT, cần xác minh): được phái sinh | LibreChat |
| **NATS** | **Thấp** (Apache-2.0, CNCF); rủi ro quản trị upstream | **Chưa có**: `lfmap-core` chưa có `EventBus` Protocol (manifest chỉ có cờ `events: bool`) | **Tự xây** `EventBus`: in-process + hàng đợi bền trên SQLite (bảng outbox, WAL, nhiều process đọc) cho sự kiện giữa các process trên một máy. NATS chỉ cần nếu sau này có nhiều máy (Team Edition) | NATS JetStream (Apache-2.0): tham khảo ngữ nghĩa ack/redelivery | NATS |
| **Valkey** | **Thấp** (BSD-3) | chưa dùng | **Không cần**: bảng key-value/TTL trên SQLite trong `lfmap-core` nếu có nhu cầu cache | — | Valkey |
| **Ollama** | **Thấp** (MIT, cần xác minh app desktop); công ty đơn lẻ | `Embedder` Protocol (`lfmap_knowledge/search.py`, `indexer.py`) | **Giữ** (hạ tầng khó, phổ thông). Viết client mỏng theo API tương thích OpenAI để đổi runtime chỉ bằng config | llama.cpp `llama-server` (MIT) | llama.cpp |
| **Model weights** | **TB**: mỗi model/kích cỡ một giấy phép | bảng Model trong License Register; tên model trong config | **Giữ**, chỉ chọn model Apache-2.0/MIT cho phần phân phối. Không tự huấn luyện model | — | — |
| **MarkItDown** | **Thấp** (MIT) | `Backend` Protocol (`lfmap_markitdown/backends/base.py`) | **Phái sinh dần**: khi một converter cần sửa sâu (vd. heading .docx, L20), chép converter đó vào plugin và sở hữu nó, giữ thông báo MIT | MarkItDown (MIT) | Docling (MIT, cần xác minh model) |
| **Office COM** | **TB**: phụ thuộc máy khách có Office | `Backend` Protocol; reason_code `needs_office` | **Giữ** trong GUI MarkitdownTool (ADR-011). Tự đọc .doc/.ppt nhị phân quá tốn công | — | LibreOffice headless (MPL-2.0) |
| **LanceDB** | **Thấp** (Apache-2.0) | `VectorStore` Protocol | **Giữ**; theo dõi sqlite-vec (MIT/Apache) như đường giảm một phụ thuộc khi 1.0 | — | sqlite-vec |
| **PyInstaller, OCRmyPDF, Tesseract** | **Thấp** | `check_licenses.py` + THIRD_PARTY_NOTICES | **Giữ** (công cụ build/OCR) | — | — |

Tóm lại: **tự xây ba thứ** (Flows thay n8n, chat UI thay Open WebUI, EventBus thay NATS/Valkey), **phái sinh dần** MarkItDown khi cần sửa, **giữ** phần còn lại sau interface. Riêng EventBus là việc nên làm sớm nhất, vì nó đồng thời bỏ được NATS và Valkey khỏi kế hoạch.

## 5. Điểm nối và chỉ số phụ thuộc

| # | Điều kiện | Kiểm chứng |
|---|---|---|
| S1 | Không package nào trong `packages/`, `plugins/` phụ thuộc n8n, Open WebUI, NATS client hay Valkey client | test import-guard (RT-02) |
| S2 | Sự kiện đi qua `EventBus` Protocol, có bộ contract test chung | RT-03 |
| S3 | Model local qua `Embedder` (và sau này `ChatModel`) Protocol, cấu hình bằng URL + tên model | đã có cho Embedder |
| S4 | UI chỉ dùng MCP/REST công khai của LFMAP | `docs/specs/rest.md` |
| S5 | Luồng n8n của anh Hùng chỉ gọi LFMAP qua REST/MCP, không dùng node `.ee` | kiểm kê (RT-07) |

**Chỉ số phụ thuộc** (đo mỗi lần phát hành, RT-11): số gói runtime bên thứ ba; tỷ lệ dung lượng mã cài đặt của bên thứ ba so với mã của LFMAP; số dịch vụ nền ngoài LFMAP (mục tiêu: chỉ runtime model). Mỗi lần tự xây hoặc phái sinh phải làm chỉ số giảm, hoặc ghi rõ lý do.

## 6. Tín hiệu kích hoạt ("thời cơ chín muồi")

| Mã | Tín hiệu | Việc phải làm khi xảy ra |
|---|---|---|
| K1 | Upstream đổi giấy phép hoặc điều khoản (RT-01 phát hiện) | đánh giá trong 1 tuần; nếu xấu đi: G2 cho thành phần đó |
| K2 | Bắt đầu Phase 2 | xây `EventBus` (RT-03 → RT-12), spec Flows và chat UI |
| K3 | Có người dùng thứ hai ngoài anh Hùng | G2 cho mọi thành phần Cao/TB mà người đó chạm vào |
| K4 | Quyết định bán/phân phối một gói | G3: xong bản tự xây trước khi phát hành; SBOM + notices + sổ nguồn gốc |
| K5 | Một luồng quan trọng chỉ chạy được nhờ tính năng riêng của n8n | đưa luồng đó vào LFMAP Flows trước |

## 7. Lộ trình và task nghiên cứu trên Cloud

| Giai đoạn | Khi nào | Nội dung |
|---|---|---|
| **G0 — Canh chừng** | từ nay, tự động | RT-01, RT-02, RT-11 (baseline), RT-13 (sổ nguồn gốc) |
| **G1 — Spec tự xây** | Phase 1b / đầu Phase 2 (K2) | RT-03, RT-04, RT-05, RT-06 |
| **G2 — Bản mẫu tự xây** | K1/K3/K5 | RT-12, RT-08, RT-09 |
| **G3 — Thay thế** | K4 | ADR mới supersede ADR-005/006/007, handoff, task Claude Code; RT-10 |

Mỗi task là một phiên Claude Code Cloud; không task nào cần DIEP-ANH.

| Mã | GĐ | Việc | Đầu ra | Tiêu chí xong |
|---|---|---|---|---|
| RT-01 | G0 | Script stdlib tải LICENSE của n8n, open-webui, nats-server, valkey, ollama, librechat, activepieces, node-red, markitdown, lancedb; so SHA-256; routine hằng tháng | `scripts/license_watch.py` + `docs/research/license-watch.json` | baseline ghi được; hash giả thì báo đổi |
| RT-02 | G0 | Test import-guard cho S1 | test trong `lfmap-core` | CI xanh; thêm import cấm thì đỏ |
| RT-11 | G0 | Script đo chỉ số phụ thuộc (mục 5) trên `uv sync --no-dev` | `scripts/dependency_share.py` + baseline | in được 3 chỉ số; ghi baseline vào `docs/research/` |
| RT-13 | G0 | Sổ nguồn gốc: mẫu và dòng cho mọi module hiện có (gần như toàn bộ là tự viết) | `docs/PROVENANCE.md` | mỗi package/plugin có một dòng; phối hợp với thread hồ sơ SHTT |
| RT-03 | G1 | Spec + Protocol `EventBus` (publish/subscribe, tên `<plugin>.<operation>.requested` theo ADR-014), bản in-process, bộ contract test | `docs/specs/events.md` + code nhỏ | contract test xanh |
| RT-04 | G1 | Spec **LFMAP Flows**: định dạng TOML, trigger (lịch, sự kiện, file), bước, rẽ nhánh tối thiểu, bước duyệt T2/T3; học từ Node-RED/Activepieces (đọc mã được) và n8n (chỉ tài liệu) | `docs/specs/flows.md` | đủ để viết lại 3 luồng mẫu (email → convert → ingest → tóm tắt → duyệt là luồng exit Phase 2) |
| RT-05 | G1 | Spec chat UI trong Tauri: phạm vi tối thiểu, chọn thư viện React permissive hoặc phần phái sinh từ LibreChat | `docs/specs/chat-ui.md` | có danh sách màn hình, API dùng, nguồn phái sinh và giấy phép |
| RT-06 | G1 | Ma trận giấy phép model chạy được trên 16 GB VRAM theo từng kích cỡ | đề xuất bổ sung bảng Model của License Register | mỗi dòng có link model card |
| RT-07 | G1 | Kiểm kê luồng n8n của anh Hùng (xuất JSON, bỏ bí mật) → map sang LFMAP Flows; làm khi đã có luồng | `docs/research/n8n-inventory.md` | mỗi luồng có cách viết lại |
| RT-12 | G2 | Hàng đợi bền SQLite cho `EventBus` (outbox, ack, redelivery, nhiều process) | code + contract test | contract test RT-03 xanh; test 2 process trên Windows CI |
| RT-08 | G2 | Client mỏng API tương thích OpenAI cho `Embedder`; thử `llama-server` (bge-m3 GGUF) trong container CPU | ghi chú + code | cosine ≥ 0,99 so với Ollama trên mẫu nhỏ |
| RT-09 | G2 | Bản mẫu LFMAP Flows chạy một luồng thật qua jobs + EventBus | code + test | luồng mẫu chạy được, bước duyệt vào hàng đợi approvals |
| RT-10 | G3 | SBOM (CycloneDX) + sinh THIRD_PARTY_NOTICES tự động cho gói phát hành | script + CI | notices đủ mọi dòng Ship và mọi phần phái sinh |

Thứ tự đề xuất: RT-01, RT-02, RT-11, RT-13 ngay (rẻ); RT-03 → RT-12 khi vào Phase 2; RT-04, RT-05 trước khi bắt đầu Tauri.

## 8. ADR-021 (Accepted 2026-10-23; văn bản chính thức trong 03_Decisions_ADR)

```markdown
### ADR-021: Ưu tiên tự xây và phái sinh để giảm phụ thuộc bên thứ ba
- Trạng thái: Accepted — anh Hùng chốt 2026-10-23 (sửa ADR-006)
- Ngày: 2026-10-23
- Bối cảnh: ADR-005/006/007 cho dùng n8n, Open WebUI, NATS, Valkey ở mức nội bộ. Anh Hùng muốn tỷ trọng phụ thuộc phần mềm bên thứ ba thấp nhất có thể và ưu tiên sản phẩm phái sinh hoặc tự xây trên cơ sở tham khảo sản phẩm hiện có.
- Quyết định: (1) Khi thay một thành phần: tự xây trước, phái sinh từ mã permissive thứ hai, dùng sản phẩm có sẵn sau cùng; giữ hạ tầng phổ thông (SQLite, runtime model, LanceDB) sau interface. (2) Không đọc hay chép mã của dự án fair-code, AGPL, SSPL, BSL hoặc có điều khoản thương hiệu khi tự xây; chỉ dùng tài liệu và hành vi công khai. (3) Mọi module có dòng trong sổ nguồn gốc `docs/PROVENANCE.md`. (4) Thành phần Internal chỉ được chạm qua interface/giao thức công khai, có test hoặc CI kiểm chứng; giấy phép upstream được theo dõi hằng tháng. (5) Việc xây thay thế bắt đầu theo tín hiệu K1–K5, không theo lịch. Kế hoạch: `docs/research/2026-10-23-commercial-replacements.md`.
- Phương án đã cân nhắc: đổi sang sản phẩm permissive có sẵn (vẫn phụ thuộc bên thứ ba); tự xây mọi thứ kể cả hạ tầng (vượt sức một người bảo trì); không chuẩn bị (bị động khi upstream đổi giấy phép hoặc khi có khách).
- Hệ quả: lfmap-core có thêm EventBus (in-process + SQLite) và LFMAP Flows ở Phase 2; NATS và Valkey không còn cần trong kế hoạch một máy (sửa ADR-006); Tauri có chat riêng. Thêm RT-01..RT-13 vào backlog.
```

## 9. Cập nhật tài liệu dự án

- Đã làm 2026-10-23: 03 thêm ADR-021 và sửa ADR-006; 05_Roadmap Phase 2 đổi sang EventBus tự xây, thêm LFMAP Flows, n8n là giai đoạn chuyển tiếp, Backlog thêm RT-01/02/11/13; 01 Blueprint dòng Messaging.
- 04_License_Register: thêm cột hoặc ghi chú "nguồn phái sinh" khi có phần phái sinh đầu tiên.

## Nguồn (kiểm tra 2026-10-23)

- Decision pack ADR-005/006/007: `/mnt/project-files/lfmap-docs/ADR-005-007_decision-pack_2026-10-23.md`
- Activepieces license: https://www.activepieces.com/docs/about/license
- Node-RED license: https://nodered.org/about/license/
- Windmill: https://windmill.dev/brand ; https://isitreallyfoss.com/projects/windmill/
- AnythingLLM (MIT): https://www.amd.com/en/ecosystem/isv/consumer-partners/anythingllm.html
- Ollama app (nguồn thứ cấp): https://mindwiredai.com/?p=2302
