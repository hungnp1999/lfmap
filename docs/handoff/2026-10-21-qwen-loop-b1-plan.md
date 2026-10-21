# Kế hoạch thực thi B1: `qwen_loop.py`

Đi kèm [`2026-10-21-qwen-loop.md`](2026-10-21-qwen-loop.md). Mọi điểm thiết kế đã chốt ở đây; Claude Code chỉ việc làm theo thứ tự các bước. Nếu code hiện tại không khớp với kế hoạch thì dừng và hỏi.

- **Môi trường:** Local, tức Claude Code trên DIEP-ANH, mở ở `D:\Development\lfmap-tools\qwen-loop\`. Lý do: thư mục đích nằm trên máy này và không phải repo git; test cũng chạy trên Windows luôn, đúng nơi sẽ chạy thật.
- **Python:** 3.12 (`py -3.12`). Chỉ dùng thư viện chuẩn, kể cả test (`unittest`, không dùng pytest).
- **Ruff:** dùng bản trong venv của lfmap: `D:\Development\lfmap\.venv\Scripts\ruff.exe`, với cấu hình như `ruff.toml` của lfmap (line-length 120, rule E F I UP B).

## 1. Bố cục thư mục

```text
D:\Development\lfmap-tools\qwen-loop\
  qwen_loop.py          script, một file
  test_qwen_loop.py     unittest, Ollama giả + repo git giả
  ruff.toml             chép từ lfmap (bỏ phần isort known-first-party)
  README.md             cách chạy (ngắn, tiếng Anh)
  cards\TC-K2\          card.toml + prompt.md (bước 6)
  work\  out\           do script tạo ra; không xoá tự động
```

## 2. Định dạng card

`card.toml`:

| Khoá | Bắt buộc | Ý nghĩa |
|---|---|---|
| `id` | không (mặc định = tên thư mục) | chỉ gồm chữ, số, `.`, `_`, `-` |
| `base_ref` | có | nhánh/commit trong repo lfmap để tạo worktree |
| `targets` | có | danh sách đường dẫn tương đối trong repo; qwen chỉ được ghi các file này |
| `tests` | có | file test của card; bị khoá bằng hash |
| `locked` | không | file khoá thêm (ngoài test và `conftest.py`) |
| `max_rounds` | không (mặc định 3) | |
| `checks` | không | danh sách lệnh (mỗi lệnh là list chuỗi). Phần tử `"{tests}"` và `"{targets}"` được thay bằng danh sách tương ứng |

`checks` mặc định:

```toml
checks = [
  ["uv", "run", "--frozen", "pytest", "-q", "--tb=short", "{tests}"],
  ["uv", "run", "--frozen", "ruff", "check", "{targets}"],
  ["uv", "run", "--frozen", "ruff", "format", "--check", "{targets}"],
]
```

Cách kiểm tra đường dẫn (cả `targets`, `tests`, `locked`): đổi `\` thành `/`, bỏ `./` ở đầu. Từ chối đường dẫn tuyệt đối, có ổ đĩa (`C:`), chứa `..` hoặc đoạn rỗng. Nếu `targets` giao với `tests` thì card lỗi.

`prompt.md`: prompt vòng 1, gửi nguyên văn.

## 3. Dòng lệnh

```text
py -3.12 qwen_loop.py run <card-dir> [<card-dir> ...] --repo D:\Development\lfmap
    [--work DIR] [--out DIR] [--url http://127.0.0.1:11434] [--model qwen2.5-coder:14b] [--num-ctx 16384]
```

- `--work` mặc định là `work\<YYYYmmdd-HHMMSS>`, `--out` mặc định là `out\<YYYYmmdd-HHMMSS>`. Mỗi lần chạy dùng thư mục mới, nên không ghi đè và không phải xoá gì.
- Mã thoát: 0 khi mọi card xanh, 1 khi có card không xanh, 2 khi lỗi tham số (gồm URL không phải loopback).
- Mỗi card in một dòng tiến độ ra stdout.

## 4. Thuật toán cho mỗi card

1. Nạp card. Card lỗi thì ghi `error` vào summary và chạy card tiếp theo.
2. Nếu `<work>\<id>` đã tồn tại thì báo `error`. Ngược lại chạy `git -C <repo> worktree add --detach <work>\<id> <base_ref>`.
3. Danh sách khoá = `tests` + `locked` + mọi `conftest.py` cùng thư mục với từng test (nếu có). Ghi sha256 của từng file.
4. Lặp `round = 1..max_rounds`:
   1. Gọi Ollama với prompt hiện tại. Lưu `round-N.prompt.md` và `round-N.answer.md`, ghi một dòng `hw-log.csv`.
   2. **Câu trả lời rỗng** (không có code block nào có nội dung): gửi lại một lần prompt cũ cộng dòng `NOW WRITE THE COMPLETE <tên các target>.` Lưu `round-N.retry.*`. Lần này vẫn ghi `hw-log.csv` với cùng số Round, nhưng không tính là một vòng.
   3. **Tách code block** theo mục 5. Mỗi đường dẫn bị từ chối được ghi vào Notes của report. Không có file hợp lệ nào thì đây là vòng hỏng: ghi `round-N.test.log` = lý do, prompt sửa = "YOUR ANSWER COULD NOT BE USED: <lý do>", rồi sang vòng sau.
   4. Ghi các file target (UTF-8, xuống dòng `\n`, thêm `\n` cuối nếu thiếu). Trước khi ghi phải kiểm tra `realpath` nằm trong worktree, với guard `startswith` viết inline.
   5. Chạy lần lượt mọi `checks` với `cwd` = worktree, timeout 900 s mỗi lệnh. Lưu toàn bộ output vào `round-N.test.log`, mỗi lệnh có dòng `$ <lệnh>` và `[exit N]`.
   6. Tính lại hash các file khoá. Khác hash lúc đầu → `tests_changed`, dừng (ghi tên file vào detail).
   7. Mọi lệnh exit 0 → `green`, dừng.
   8. Tính chữ ký lỗi (mục 6). Trùng với vòng trước → `no_progress`, dừng.
   9. Prompt sửa = prompt gốc + `---` + "YOUR PREVIOUS ANSWER DID NOT PASS." + lỗi rút gọn + nội dung hiện tại của các target (`FILE:` + block) + yêu cầu trả nguyên file, không sửa test, không định nghĩa fixture + dòng `NOW WRITE THE COMPLETE <targets>.`
5. Hết vòng → `max_rounds`.
6. Lỗi git, lỗi Ollama hay lỗi I/O → `error`, kèm thông báo trong detail.
7. Luôn kết thúc card bằng: `final.diff` (chạy `git add --intent-to-add` cho các target đang có trên đĩa, rồi `git diff -- <targets>`), `report.md`, và một dòng `summary.csv`.

Script không commit, không push, không xoá worktree hay file nào.

## 5. Tách code block

- Block: rào ```` ``` ```` có ngôn ngữ rỗng, `python`, `py` hoặc `python3`. Bỏ qua block rỗng.
- Tiêu đề đường dẫn: dòng không rỗng cuối cùng trước block, dạng `FILE: path`, `` `path` ``, `**path**`, `# path` hoặc `path:`. Nếu không có, chấp nhận dòng đầu trong block dạng comment `# path.py`.
- Khớp target: đúng đường dẫn, hoặc là đuôi duy nhất của một target (ví dụ `store.py`). Không khớp target nào → từ chối và ghi chú.
- Card có một target: không có block nào khớp target mà có đúng một block không tiêu đề → nhận block đó. Có nhiều block không tiêu đề → vòng hỏng.
- Card có nhiều target: bắt buộc có tiêu đề.

## 6. Lỗi rút gọn và chữ ký lỗi

- Dòng "tín hiệu" là dòng bắt đầu bằng `FAILED `, `ERROR `, `E `, `___ `, `path.py:line:`, `Would reformat`, `XxxError`/`XxxException`, hoặc dòng tổng kết `=== ... failed`.
- Rút gọn: giữ hai dòng đầu của mỗi lệnh hỏng (lệnh và exit), các dòng tín hiệu, và 12 dòng cuối. Tổng tối đa 6000 ký tự (khoảng 1,5k token), chia đều cho các lệnh hỏng.
- Chữ ký: sha256 của các dòng tín hiệu (không có thì lấy 20 dòng cuối), sau khi bỏ địa chỉ `0x...` và thời gian `in 0.12s`.

## 7. Gọi Ollama

- `POST <url>/api/generate`, body `{"model", "prompt", "stream": false, "options": {"num_ctx": 16384, "temperature": 0.2}}`, timeout 1800 s.
- **Chỉ loopback:** URL phải là `http`/`https`, không có user/password, host là `localhost` hoặc IP loopback (dùng `ipaddress`). Kiểm ở `main`, ở `run_cards` và ngay trong hàm gọi.
- **Bỏ qua proxy:** dùng `urllib.request.build_opener(urllib.request.ProxyHandler({}))`. Nếu không, biến `HTTP(S)_PROXY` sẽ đẩy prompt ra ngoài máy.
- VRAM: nếu có `nvidia-smi` thì một thread lấy mẫu mỗi giây (`--query-gpu=memory.used --format=csv,noheader,nounits`) và giữ giá trị đỉnh.

## 8. File kết quả

`<out>\hw-log.csv`: cùng cột và thứ tự với `Ask-Qwen.ps1`, mọi ô trong ngoặc kép (giống `Export-Csv`), UTF-8 không BOM:

`Time, Card, Round, PromptFile, PromptTokens, AnswerTokens, TokPerSec, LoadSec, WallSec, PeakVramMiB, ContextTokens`

- `Time` là giờ máy, dạng `2026-10-21T22:05:31`.
- `Round` là số vòng của loop (lần hỏi lại vẫn mang cùng số).
- `PromptFile` có dạng `TC-K2/round-1.prompt.md`.
- `TokPerSec` = `eval_count / (eval_duration/1e9)`, làm tròn 1 chữ số.
- `LoadSec` = `load_duration/1e9`.
- `PeakVramMiB` để trống nếu không có `nvidia-smi`.

`<out>\summary.csv` (thêm một dòng mỗi card): `time, card, status, rounds, tok_s, wall_s, peak_vram_mb, claude_fixes`. `claude_fixes` để trống. `status` ∈ `green | max_rounds | no_progress | tests_changed | error`.

`<out>\<id>\`:
- `round-N.prompt.md`, `round-N.answer.md`, `round-N.test.log`, `round-N.retry.*`
- `final.diff`
- `report.md`, gồm:
  - status, base_ref, đường dẫn worktree, targets
  - số vòng, số lần gọi model, tổng token trả lời, tok/s, thời gian
  - Notes: write bị từ chối, lần hỏi lại, prompt chạm trần context, docstring bị mất so với base (so tên hàm/lớp có docstring bằng `ast` giữa `git show <base_ref>:<target>` và file cuối), thay đổi khác trong `git status`

## 9. Test bắt buộc (`test_qwen_loop.py`)

Hạ tầng:
- Ollama giả là `http.server.ThreadingHTTPServer` trên `127.0.0.1:0`. Nó trả lần lượt các câu trả lời dựng sẵn, ghi lại prompt nhận được, và trả `prompt_eval_count=100`, `eval_count=40`, `eval_duration=1e9`, `load_duration=5e8`.
- Repo giả: `git init` trong thư mục tạm, gồm:
  - `pkg/mod.py`: hàm `add` trả 0, có docstring.
  - `tests/check_mod.py`: script `assert mod.add(2, 3) == 5, 'add is wrong'`.
  - Một commit.
- Card dùng `checks = [['<sys.executable>', '{tests}']]` (chuỗi literal TOML), nên không cần uv hay pytest.

Ca test (mỗi dòng một test):

| # | Ca | Kỳ vọng |
|---|---|---|
| 1 | Trả code đúng ngay vòng 1 | `green`, 1 vòng. Có `final.diff`, report ghi docstring bị mất, header `hw-log.csv` đúng `HW_COLUMNS`, `summary.csv` có `claude_fixes` rỗng. Repo gốc không đổi |
| 2 | Sai rồi đúng | `green`, 2 vòng. Prompt vòng 2 chứa `add is wrong`, code cũ và `NOW WRITE THE COMPLETE mod.py` |
| 3 | Câu trả lời có block `FILE: tests/check_mod.py` cùng block target đúng | Test không đổi, report ghi "refused", vẫn `green` |
| 4 | Chỉ có block cho `../escape.py` rồi cho file test (`max_rounds=2`) | `max_rounds`, không có file nào ngoài worktree, test không đổi |
| 5 | Code target ghi đè file test lúc import | `tests_changed` sau vòng 1, không gọi model lần 2 |
| 6 | Sai giống hệt hai lần | `no_progress` sau 2 vòng, chỉ 2 lần gọi model |
| 7 | Block rỗng rồi code đúng | `green`, 1 vòng. Prompt lần 2 kết thúc bằng `NOW WRITE THE COMPLETE mod.py.`; `hw-log.csv` có hai dòng Round 1 |
| 8 | Hai câu trả lời sai khác nhau, `max_rounds=2` | `max_rounds` |
| 9 | Hai card | Chạy đúng thứ tự, `summary.csv` có 2 dòng |
| 10 | Thư mục worktree đã tồn tại | `error` "already exists", không gọi model |
| 11 | URL `example.com`, `10.0.0.5`, `file://`, có `user:pass@` | `ValueError`. `127.0.0.1`, `localhost`, `[::1]` thì được |
| 12 | Hàm gọi Ollama với URL LAN | `ValueError` trước khi có kết nối |
| 13 | `main(["run", "x", "--url", "http://example.com"])` | `SystemExit(2)` |
| 14 | Đường dẫn card `/etc/passwd`, `C:/x.py`, `../x.py`, `a//b.py` | bị từ chối. `.\pkg\mod.py` → `pkg/mod.py` |
| 15 | Tách block: một target không tiêu đề; nhiều target thiếu tiêu đề; tiêu đề `` `two.py`: `` khớp đuôi; comment `# pkg/mod.py` trong block | như mục 5 |
| 16 | So docstring | phát hiện mất `<module>`, `A`, `A.f` |

Dọn dẹp test: `git worktree prune` rồi xoá thư mục tạm (chỉ trong `TemporaryDirectory`).

## 10. Các bước

1. Tạo `ruff.toml` và `qwen_loop.py` theo mục 2–8.
2. Viết `test_qwen_loop.py` theo mục 9. Chạy `py -3.12 -m unittest -v test_qwen_loop`: xanh hết.
3. `ruff check .` và `ruff format --check .`: sạch.
4. Viết `README.md` (tiếng Anh, khoảng 30 dòng): lệnh chạy, định dạng card, ý nghĩa status, nhắc dọn worktree bằng tay (`git -C D:\Development\lfmap worktree remove <path>`).
5. Tạo nhánh base cho B2 trong `D:\Development\lfmap`, không đụng nhánh đang làm:
   ```text
   git fetch origin
   git worktree add ..\lfmap-k2base origin/main -b scratch/k2-rerun
   cd ..\lfmap-k2base ; git rm packages/lfmap-knowledge/src/lfmap_knowledge/store.py
   git commit -m "scratch: remove store.py to rerun TC-K2 with qwen-loop"
   git push -u origin scratch/k2-rerun
   ```
   Không mở PR. Nhánh chỉ để chạy lại K2. Chạy `uv run pytest packages/lfmap-knowledge -q` trong worktree đó: test store và scanner phải đỏ vì thiếu module (đúng như mong đợi), các test khác xanh.
6. Card TC-K2:
   - Hùng đặt sẵn `cards\TC-K2\card.toml` và `prompt.md` (tải từ project files `qwen-loop/cards/TC-K2/`; `prompt.md` = nguyên văn `TC-K2_qwen.md`). Nếu chưa có thì dừng và nhắc Hùng.
   - `card.toml` phải có nội dung:
   ```toml
   id = "TC-K2"
   base_ref = "scratch/k2-rerun"
   targets = ["packages/lfmap-knowledge/src/lfmap_knowledge/store.py"]
   tests = ["packages/lfmap-knowledge/tests/test_store.py"]
   max_rounds = 3
   ```
   - Lưu ý: `test_scanner.py` cũng đỏ trên nhánh này, nhưng card chỉ chạy `test_store.py`, nên không ảnh hưởng.
7. Chạy thử khô, chưa cần qwen: `py -3.12 qwen_loop.py run cards\TC-K2 --repo D:\Development\lfmap --url http://127.0.0.1:9`. Kỳ vọng: worktree được tạo, card `error` vì không kết nối được Ollama, có `report.md` và một dòng `summary.csv`. Sau đó `git worktree remove` worktree vừa tạo.
8. Báo lại cho Hùng: kết quả test, lệnh B2 cần chạy (mục 11), và những điểm lệch khỏi kế hoạch (nếu có).

## 11. Lệnh B2 cho Hùng (sau B1)

```powershell
cd D:\Development\lfmap-tools\qwen-loop
py -3.12 qwen_loop.py run cards\TC-K2 --repo D:\Development\lfmap
```

So `out\<thời điểm>\hw-log.csv` với số chạy tay: khoảng 35–40 tok/s, VRAM ≤ 13 GB.

## 12. Tiêu chí xong B1

- 16 ca test ở mục 9 xanh trên Windows, ruff sạch.
- Có nhánh `scratch/k2-rerun` trên origin, và có `cards\TC-K2\` (`card.toml` + `prompt.md`).
- Bước 7 chạy đúng như kỳ vọng.
