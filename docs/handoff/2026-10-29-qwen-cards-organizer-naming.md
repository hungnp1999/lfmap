# Bàn giao: đợt thẻ S cho qwen, tên file an toàn cho organizer (TC-O1..O3)

Ngày chốt: 2026-10-29. Hùng chọn việc "soạn thẻ S tiếp theo cho qwen" (project chat, 2026-10-29 01:43Z). Working model: `qwen2.5-coder:14b` + sổ kinh nghiệm L1b (Hùng chốt 2026-10-28 sau bench W0, [`docs/research/2026-10-28-working-model-bench.md`](../research/2026-10-28-working-model-bench.md) §11). Quy tắc ADR-004 / Roadmap 1.7: qwen chỉ nhận thẻ S có test chặt.

## Bối cảnh

- Bench W0: 14b + sổ xanh vòng đầu 33 % trên 7 thẻ, nhưng hai thẻ mới TC-N1 (`topics.py`) và TC-N2 (`naming.py`) trượt 0/6 ở cả hai chế độ.
- Đọc log W0 (`qwen-bench\out\runs\A2-TC-N*`): 14b hiểu yêu cầu nhưng gộp quá nhiều quy tắc. Ở N1 nó cố nhét cú pháp wildcard vào một regex duy nhất; ở N2 nó bỏ bước tên thiết bị (`CON` không thành `_CON`), báo lỗi với tên đã làm sạch thay vì tên gốc, và cắt độ dài sai. Bản tham chiếu của Claude xanh trên cùng vòng lặp, nên thẻ không sai, chỉ quá to so với model.
- Thread "Chuẩn bị Phase 2a EventBus in-house" đã nhận các thẻ EventBus (TC-E1..E3: retry, payload, tên topic) và giao `topics.py` cho Claude Code. Đợt này vì vậy không đụng EventBus, để khỏi trùng.

## Mục tiêu

1. Có module `lfmap_core.naming` (tên file Windows an toàn và không trùng) cho plugin `organizer` của Phase 2a (2a.6, ADR-012), do Working model viết.
2. Đo một giả thuyết về cách viết thẻ: **tách thẻ trượt thành thẻ một chức năng, ghi thuật toán thành từng bước đánh số**, thì 14b có xanh không. So với TC-N2 ở W0 (cùng chức năng, 0/3 xanh với sổ).

Tiêu chí hoàn thành:
- Mỗi thẻ có `card.toml`, `prompt.md` chứa nguyên văn test, test đóng băng trên nhánh, bản tham chiếu xanh trong Cloud (pytest + ruff). Có: xem "Chuẩn bị sẵn".
- Sau khi chạy: kết quả từng thẻ (xanh vòng đầu, xanh trong 3 vòng, số vòng, `claude_fixes`), module ghép lại qua thêm 49 test của TC-N2, PR merge.

## Quyết định đã chốt

| # | Quyết định | Lý do | Phương án đã loại |
|---|---|---|---|
| 1 | Làm lại chức năng của TC-N2 (organizer), không làm EventBus | Thread Phase 2a đã soạn TC-E1..E3; N2 phục vụ 2a.6 và có sẵn 49 test làm test nghiệm thu | Thẻ EventBus riêng (trùng việc); tách TC-N1 (thread Phase 2a giao Claude Code) |
| 2 | Tách thành 3 thẻ độc lập, mỗi thẻ chạy được riêng trên cùng `base_ref` | Một thẻ trượt không chặn thẻ khác; chạy song song trong một lệnh | Chuỗi thẻ phụ thuộc nhau (thẻ sau cần kết quả thẻ trước được duyệt) |
| 3 | Thuật toán ghi từng bước đánh số, có tên biến (`original`, `taken`, `base`), hằng số viết sẵn | Lỗi W0 là bỏ bước hoặc đảo thứ tự, không phải hiểu sai mục đích | Chỉ mô tả hành vi (như N2) |
| 4 | Ba thẻ cùng ghi `naming.py`, mỗi thẻ chỉ chứa hàm của mình; Claude ghép khi review và thêm `safe_filename` (gọi `shorten_filename(clean_filename(...))`, 2 dòng) | Đích cuối là một module như N2; ghép là việc nối dây theo kế hoạch, không tính là `claude_fixes` | Ba module riêng (`naming_unique.py`...) làm API rời rạc |
| 5 | TC-O3 chép nguyên văn `split_extension` trong prompt | Giữ thẻ độc lập với TC-O1; khi ghép chỉ giữ một bản | O3 import từ O1 (phụ thuộc) |
| 6 | Hành vi giữ đúng spec của TC-N2 | Module ghép phải qua `test_naming.py` của N2 (commit `790748b`) | Đổi quy tắc cho dễ hơn |

## Phạm vi

Trong: `packages/lfmap-core/src/lfmap_core/naming.py` (mới), 3 file test mới, thẻ trong project files, handoff này.
Ngoài: plugin `organizer`, mọi thao tác file thật (module chỉ có hàm thuần), EventBus, đổi `qwen_loop.py`.

## Thiết kế

API cuối của `lfmap_core.naming` (sau khi ghép):

| Hàm | Thẻ | Việc |
| --- | --- | --- |
| `split_extension(name) -> (stem, ext)` | O1 (O3 chép) | Đuôi là phần từ dấu chấm cuối, nếu dấu chấm không ở đầu và đuôi (kể cả dấu chấm) ≤ 11 ký tự |
| `unique_name(name, existing) -> str` | O1 | NFC + `casefold`, đọc `existing` một lần, trả `stem (N)ext` với N nhỏ nhất ≥ 2 |
| `clean_filename(name, replacement="_") -> str` | O2 | Thay ký tự cấm và ký tự điều khiển, bỏ khoảng trắng đầu, chấm/khoảng trắng cuối, thêm `_` trước tên thiết bị (`CON`, `COM1`...), lỗi với tên gốc khi rỗng |
| `shorten_filename(name, max_length=255) -> str` | O3 | Cắt về `max_length`, giữ đuôi khi đuôi ngắn hơn giới hạn, bỏ chấm/khoảng trắng cuối |
| `safe_filename(name, replacement="_", max_length=255) -> str` | Claude khi ghép | `shorten_filename(clean_filename(name, replacement), max_length)`, đúng API của TC-N2 |

Mọi lỗi là `ToolError("invalid_input", ...)`; đầu vào không phải `str` có `details` là `repr(value)`.

## Danh sách task

| # | Task | Môi trường | Tiêu chí hoàn thành |
| --- | --- | --- | --- |
| Q1 | Soạn thẻ + test đóng băng + bản tham chiếu (thread này) | Cloud | Xong 2026-10-29: 35 + 41 + 27 test, tham chiếu xanh, module ghép qua cả 49 test N2 (152 test) |
| Q2 | Chạy 3 thẻ × 3 lần với sổ L1b (bản chụp sổ cho mỗi lần, như W0) | qwen trên DIEP-ANH (cần GPU) | `summary.csv` + `out\` chép về `/mnt/project-files/qwen-loop/runs/2026-10-29-O/` |
| Q3 | Review (checklist thường lệ), ghép `naming.py`, thêm `safe_filename`, thêm `test_naming.py` của N2, dòng `docs/PROVENANCE.md` (ADR-021), CHANGELOG, ghi `claude_fixes`; `lesson bump`/`lesson add`, `accept` thẻ tốt | Cloud (+ folder tools cho sổ) | PR này hết draft, CI xanh, merge |

Q2 có thể chạy chung một lệnh với TC-E1..E3 của thread Phase 2a nếu chúng xong trước (6 thẻ, khoảng 30 phút GPU với flash attention tắt).

## Chuẩn bị sẵn

- Thẻ: `/mnt/project-files/qwen-loop/cards/TC-O1/`, `TC-O2/`, `TC-O3/` (`card.toml`, `prompt.md` 5,2–5,6 KB), đã chép sẵn vào `D:\Development\lfmap-tools\qwen-loop\cards\` trên DIEP-ANH. Đã nạp thử bằng `load_card` của `qwen_loop.py` bản L1b.
- `base_ref = origin/claude/project-thread-ijq0vh` (nhánh của PR này). Trên đó chưa có `naming.py`, nên cả ba file test đỏ (ImportError) đúng thiết kế; CI của PR đỏ cho đến Q3.
- Bản tham chiếu (không đưa vào repo trước khi review): `/mnt/project-files/qwen-loop/reference/2026-10-29-TC-O/` (`TC-O1-naming.py`, `TC-O2-naming.py`, `TC-O3-naming.py`, `naming-assembled.py`).
- Test nghiệm thu khi ghép: `git show 790748b:packages/lfmap-core/tests/test_naming.py` (nhánh `claude/project-thread-il17dd` phải còn giữ).

## Lệnh chạy Q2 (DIEP-ANH, PowerShell, trong `D:\Development\lfmap-tools\qwen-loop`)

```powershell
git -C D:\Development\lfmap fetch origin claude/project-thread-ijq0vh
foreach ($r in 1..3) {
    $store = "out\2026-10-29-O-store-r$r"
    Copy-Item -Recurse experience $store
    py -3.12 qwen_loop.py run cards\TC-O1 cards\TC-O2 cards\TC-O3 --repo D:\Development\lfmap --experience $store
}
```

Mỗi lần chạy có sổ là một "đợt" và có thể cho bài học nghỉ (`experience.start_batch`), nên dùng bản chụp như W0; sổ thật chỉ đổi ở Q3 sau review. Không chạy chồng với việc GPU khác (hàng đợi GPU của coordinator).

## Rủi ro

- Thuật toán ghi quá chi tiết làm thẻ gần như đọc chính tả: xanh vẫn có ích (có code dùng được), nhưng không chứng minh 14b tự giải được N2. Ghi rõ điều này khi báo kết quả.
- Ba thẻ cùng file đích: khi ghép phải bỏ `split_extension` trùng (O1 và O3) và gộp import.
- Sổ L1b có thể lấy TC-V1 làm ví dụ (cùng kiểu kiểm tra `str` + `repr`): đó là hành vi mong muốn, không phải rò rỉ.
- Flash attention đang tắt trên DIEP-ANH (Hùng 2026-10-28): 14b chạy khoảng 27 tok/s; chỉ ảnh hưởng thời gian.

## Câu hỏi còn mở

Không có câu hỏi chặn. Việc chạy Q2 nằm trong phạm vi đã cấp cho `D:\Development` (qwen-loop đã cài, model đã có), chỉ cần GPU rảnh.

## Cập nhật tài liệu dự án

- 05 Roadmap, dòng 1.7: sau Q3 ghi kết quả đợt O (xanh vòng đầu so với N2 ở W0).
- 03 ADR: không đổi.
- `docs/PROVENANCE.md`: thêm dòng `lfmap_core.naming` ở Q3 (qwen2.5-coder:14b viết, Claude review).

## Prompt khởi động cho Claude Code (Q3)

> Review kết quả qwen của thẻ TC-O1..O3 trong `/mnt/project-files/qwen-loop/runs/2026-10-29-O/` theo `docs/handoff/2026-10-29-qwen-cards-organizer-naming.md`. Chọn lần xanh đầu tiên của mỗi thẻ, ghép thành `packages/lfmap-core/src/lfmap_core/naming.py`, thêm `safe_filename`, thêm `test_naming.py` từ `790748b`, chạy `uv run pytest packages/lfmap-core` và ruff, ghi `claude_fixes` từng thẻ, cập nhật CHANGELOG và `docs/PROVENANCE.md`, đẩy lên nhánh `claude/project-thread-ijq0vh`, bỏ draft PR.
