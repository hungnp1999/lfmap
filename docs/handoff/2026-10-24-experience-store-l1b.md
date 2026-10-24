# Bàn giao: sổ kinh nghiệm cho qwen (L1b)

Ngày chốt: 2026-10-24. Hùng duyệt task T4 trong kế hoạch 24/10. Nguồn quyết định: [`docs/research/2026-10-23-local-model-tiers.md`](../research/2026-10-23-local-model-tiers.md) §9a (Hùng chọn Level 1 ngày 2026-10-23) và §10 hàng L1b. Liên quan: [`2026-10-21-qwen-loop.md`](2026-10-21-qwen-loop.md) (vòng qwen B1–B6).

## Bối cảnh

Đợt K4–K7 (2026-10-21) cho thấy qwen2.5-coder:14b lặp lại cùng loại lỗi giữa các card: định nghĩa fixture, thiếu import, mất docstring, câu trả lời rỗng, lỗi biên (file tạm, cache hỏng, host name). Vòng đầu xanh 0/4, cuối cùng xanh theo test 3/4. Mỗi lần Claude phải viết lại cùng nhắc nhở vào prompt.

Hùng muốn model nhỏ "lên tay nghề" theo thời gian như người thợ, nhưng không fine-tune (Level 2) và không chỉ trông vào model mới (Level 3).

## Mục tiêu

`qwen_loop.py` tự đưa vào mỗi prompt: (1) các bài học từ review trước, (2) 1–2 lời giải đã duyệt giống card nhất. Đo được tay nghề qua tỉ lệ "xanh vòng đầu" từng đợt.

Tiêu chí hoàn thành:
- Test đơn vị xanh (Cloud): có. 56 test (`test_qwen_loop` 32 cũ, `test_experience` 24 mới), ruff sạch.
- Đợt qwen kế tiếp ghi lại mỗi prompt mang bài học và ví dụ nào (`summary.csv` cột `lessons`, `examples`; `report.md`; `metrics.csv`).

## Quyết định đã chốt

| # | Quyết định | Lý do | Phương án đã loại |
|---|---|---|---|
| 1 | Level 1: sổ bài học + ví dụ đã duyệt, không đổi trọng số | Hùng chốt 2026-10-23 | Level 2 LoRA (quá công, điều khoản Anthropic); Level 3 chỉ đổi model |
| 2 | Python thuần, module `experience.py` cạnh `qwen_loop.py` trong `lfmap-tools` | Không dependency mới (`tomllib`, `csv`, `math`); ngoài sản phẩm như qwen-loop | Đặt trong monorepo lfmap; dùng thư viện vector |
| 3 | Embedding: gọi thẳng Ollama `/api/embed` với `bge-m3`, chỉ URL loopback, bỏ proxy (dùng lại kiểm tra của `qwen_loop.py`) | Đã có sẵn trên DIEP-ANH, dữ liệu không rời máy | Đi qua `lfmap-knowledge` (kéo LanceDB vào công cụ nhỏ) |
| 4 | Vector ví dụ lưu cache `embedding.json` theo model + SHA-256 prompt; so khớp cosine, ngưỡng 0,4, tối đa 2, không bao giờ lấy chính card | Ít ví dụ (vài chục) nên duyệt tuần tự là đủ | Chỉ mục ANN |
| 5 | Bài học: tối đa 10, chọn theo `seen` rồi `last_seen`; đặt ngay trước đoạn "NOW WRITE ..." cuối prompt và giữ trong prompt sửa lỗi. Ví dụ chỉ ở vòng 1, đặt đầu prompt | Model nhỏ chú ý phần cuối; ví dụ dài nên không lặp ở vòng sửa | Đưa ví dụ vào mọi vòng (đầy ngữ cảnh) |
| 6 | "Không khớp 3 đợt thì nghỉ" hiểu là: lỗi không bị bắt lại (không `bump`) trong 3 đợt chạy có sổ; bài nghỉ vẫn nằm trong file (`retired = true`), `bump` đưa trở lại | §9a không nói rõ "khớp" là gì; hiểu theo lỗi tái diễn giữ danh sách ngắn mà không xoá gì | Nghỉ theo việc glob có khớp card hay không |
| 7 | Mặc định bật khi có thư mục `experience\`; `--no-experience` chạy prompt gốc và chỉ ghi một dòng "off" vào `metrics.csv` (không tính đợt) | So sánh có/không có sổ trên cùng card (T9) | Cờ bật thủ công mỗi lần |
| 8 | Ví dụ chỉ nhận code do Working model viết (Claude sửa trong review vẫn được); card Claude viết lại (K5) không phải ví dụ | Đúng §9a | Thêm cả K5 |
| 9 | Định dạng card giữ nguyên; chỉ thêm khoá tuỳ chọn `tags` để khớp bài học theo chủ đề | Card cũ và TC-V1 (T9) chạy không đổi | Bắt buộc `tags` |

## Phạm vi

- Trong phạm vi: `experience.py`; tích hợp vào `qwen_loop.py run`; lệnh `lesson add|bump|list` và `accept`; chỉ số xanh vòng đầu; dữ liệu gieo (11 bài học, 4 ví dụ); README.
- Ngoài phạm vi: fine-tune; Leading Agent tự viết bài học (để sau khi ADR-022 được chấp nhận); giao diện; đổi model; tự xoá file.

## Thiết kế

```text
experience\
  lessons.toml            batch = N, [[lesson]] id, rule, applies_to, tags, seen, last_seen, last_batch, source, retired
  examples\<card id>\     example.toml (targets, tests, tags, accepted, ref, source, claude_fixes), prompt.md,
                          files\<đường dẫn repo> (code sau review), embedding.json (cache)
  metrics.csv             time, batch, experience on/off, cards, first_round_green, green, mean_rounds, lessons_used,
                          examples_used, embed_model

run:  mở sổ → batch += 1, nghỉ bài học cũ → mỗi card: chọn bài học (glob/tag) + embed prompt, chọn 2 ví dụ
      → vòng 1 = WORKED EXAMPLES + prompt card + LESSONS + NOW WRITE → vòng sửa giữ LESSONS
      → summary.csv thêm first_round_green, lessons, examples → metrics.csv một dòng mỗi đợt
review: lesson add / lesson bump (Claude, sau mỗi review) ; accept <card> --ref <commit đã duyệt>
```

Embed lỗi (chưa có bge-m3, Ollama tắt) không làm hỏng card: chạy với bài học, `report.md` ghi lý do. Prompt vòng 1 với 2 ví dụ dài thêm khoảng 10 nghìn ký tự (~3k token), vẫn dưới `num_ctx` 16384.

Dữ liệu gieo:
- Bài học: `no-fixtures`, `complete-file`, `import-what-you-use` (mỗi bài seen 3), `keep-docstrings`, `atomic-write` (seen 2), `raise-from`, `validate-outside-data`, `follow-step-order`, `hostname-not-ip` (tag `network`), `corrupt-cache-is-miss` (tag `cache`, `files`), `keep-line-endings` (tag `files`). Nguồn: review K1–K3, B5 (K4–K7).
- Ví dụ: TC-K2 `store.py`, TC-K4 `extract.py`, TC-K6 `fts.py`, TC-K7 `embed.py`, code lấy tại `ae149fc` (merge PR #26). Không có TC-K5 (Claude viết lại), không có TC-V1 (T9 cần so sánh trước).

## Danh sách task

1. **L1b-1: code + test + dữ liệu gieo (Cloud, Claude Code).** Xong 2026-10-24.
   - Kết quả: `/mnt/project-files/qwen-loop/l1b/` gồm `qwen_loop.py`, `experience.py`, `test_qwen_loop.py`, `test_experience.py`, `README.md`, `experience\`, `SHA256SUMS.txt`. Dựa trên bản `qwen_loop.py` chạy đợt K4–K7 (`runs/2026-10-21/script/`).
2. **L1b-2: cài lên DIEP-ANH (Local, qua Remote Control, cần câu duyệt của Hùng).**
   - Claude chép bộ L1b qua quyền thư mục vào thư mục mới `D:\Development\lfmap-tools\qwen-loop\l1b-2026-10-24\` (không ghi đè gì).
   - Phiên Remote Control so SHA-256 của `D:\Development\lfmap-tools\qwen-loop\qwen_loop.py` với bản chạy đợt K4–K7 (`cdb3001f312dd8b0ec82f844b6ca6210f7a2c885422f056eb62fc87e776cdbd0`). Khác thì dừng và gộp, không ghi đè.
   - Giống thì đổi tên bản cũ thành `qwen_loop.py.bak-2026-10-21` (không xoá), chép bộ L1b lên `qwen-loop\`, chạy `py -3.12 -m unittest test_qwen_loop test_experience`, kiểm `ollama list` có `bge-m3`.
   - Xong khi: test xanh trên Windows, `py -3.12 qwen_loop.py lesson list` in 11 bài học.
3. **L1b-3: chạy thử một đợt card S (Local, qwen; gộp với T9 "Thẻ S cho qwen 24/10").**
   - TC-V1 (`lfmap-core` `versions.py`): 3 lần `--no-experience`, 3 lần có sổ; so xanh vòng đầu và số vòng trong `experience\metrics.csv`.
   - Xong khi: `summary.csv` của đợt có cột `lessons`/`examples` điền đủ.
4. **L1b-4: vòng phản hồi sau review (Cloud, Claude Code, mỗi đợt).** Claude review gộp, rồi `lesson add`/`bump` theo lỗi tìm thấy và `accept` card đạt.

## Chuẩn bị sẵn

- Code, test, dữ liệu gieo ở `/mnt/project-files/qwen-loop/l1b/` (SHA-256 trong `SHA256SUMS.txt`).
- `bge-m3` đã có trên DIEP-ANH (dùng cho `lfmap-knowledge`).
- Card TC-V1 ở `/mnt/project-files/qwen-loop/cards/TC-V1/`, test khoá trên nhánh `claude/project-thread-5g13hp`.

## Rủi ro

- Ví dụ không cùng chủ đề có thể làm qwen chép sai kiểu: ngưỡng 0,4 và câu "Do not copy code that does not fit your task"; đo bằng so sánh có/không có sổ.
- Prompt dài hơn làm chậm vòng 1 (~3k token, khoảng 10–20 s ở 40 tok/s đọc prompt): chấp nhận được; `--max-examples 0` để chỉ dùng bài học.
- Bản `qwen_loop.py` trên máy có thể mới hơn bản trong project files: bước L1b-2 so trước khi chép.
- Bài học viết quá chung không giúp gì: mỗi bài một câu, có nguồn; bài không tái diễn tự nghỉ sau 3 đợt.

## Câu hỏi còn mở

- Ngưỡng 0,4 của cosine bge-m3 chưa đo trên card thật; xem điểm trong `summary.csv` sau L1b-3 rồi chỉnh.
- Khi nào giao việc viết bài học cho Leading Agent (qwen3.8:27b): sau khi ADR-022 chốt.

## Cập nhật tài liệu dự án

- ROADMAP 1.7: ghi L1b (sổ kinh nghiệm) là phần của quy trình Planner → Task Card → Local Agent → Review.
- DECISIONS: không cần ADR mới (công cụ ngoài sản phẩm, đúng ADR-004); ghi chú cách hiểu "nghỉ sau 3 đợt" ở quyết định 6.

## Prompt khởi động cho Claude Code

Cho phiên Remote Control trên DIEP-ANH (L1b-2, L1b-3):

> Đọc `docs/handoff/2026-10-24-experience-store-l1b.md` trong `D:\Development\lfmap`. Làm task L1b-2: so SHA-256 của `D:\Development\lfmap-tools\qwen-loop\qwen_loop.py` với giá trị trong handoff, nếu khác thì dừng và báo. Nếu giống: đổi tên bản cũ thành `qwen_loop.py.bak-2026-10-21`, chép nội dung `qwen-loop\l1b-2026-10-24\` lên `qwen-loop\`, chạy `py -3.12 -m unittest test_qwen_loop test_experience` và `py -3.12 qwen_loop.py lesson list`. Sau đó L1b-3 với card TC-V1: 3 lần `--no-experience`, 3 lần có sổ, báo lại `experience\metrics.csv` và các `summary.csv`. Không commit, không xoá file.
