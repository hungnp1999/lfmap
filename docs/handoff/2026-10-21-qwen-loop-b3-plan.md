# Kế hoạch thực thi B3: test và card K4–K7 cho qwen-loop

File này đi kèm [`2026-10-21-qwen-loop.md`](2026-10-21-qwen-loop.md) (task B3) và [`2026-10-20-knowledge-k4-k14.md`](2026-10-20-knowledge-k4-k14.md) (task 1, phần K4–K7). Spec gốc: [`docs/specs/knowledge.md`](../specs/knowledge.md), mục 5 và mục 8.

Các điểm API spec còn để ngỏ đã được chốt dưới đây. Claude Code chỉ việc viết test và prompt theo đúng các điểm đó. Nếu code hiện tại không khớp với kế hoạch này, dừng lại và hỏi.

- **Môi trường: Local**, tức Claude Code trên DIEP-ANH, mở ở `D:\Development\lfmap`. Kế hoạch ban đầu ghi Cloud, nhưng đã đổi vì hai lý do:
  - Card phải nằm ở `D:\Development\lfmap-tools\qwen-loop\cards\`, mà phiên Cloud không ghi được vào đó.
  - Test K4 cần markitdown thật, chạy trên Windows sẽ khớp với lúc chạy thật.
- **Điều kiện trước:** B1 xong, tức đã có định dạng card và `qwen_loop.py`.
- **Không viết module đích.** qwen sẽ viết các module này ở B4. Ở B3 chỉ có test và prompt.

## 1. Nhánh

```text
git fetch origin
git switch -c feature/knowledge-k4-k7 origin/main
```

- Commit 4 file test, mỗi card một commit, message `test(knowledge): add TC-Kn tests for <module>`.
- Push nhánh nhưng **không mở PR**. CI sẽ đỏ vì thiếu module, và PR sẽ mở ở B5.
- Không sửa `conftest.py`. Nếu cần fixture mới thì định nghĩa trong chính file test (fixture riêng của file), rồi dán nguyên văn vào prompt.

## 2. API đã chốt và danh sách test

Mọi đường dẫn tính từ `packages/lfmap-knowledge/`. Mỗi test dùng fixture có sẵn trong `tests/conftest.py`: `data_dir`, `root`, `perms`, `db`.

### TC-K4 `src/lfmap_knowledge/extract.py`, test `tests/test_extract.py`

```python
@dataclass(frozen=True)
class ExtractResult:
    markdown: str
    extractor_version: str
    text_quality: float | None
    from_cache: bool


@dataclass(frozen=True)
class SkipResult:
    reason_code: str


# f"markitdown/{version('markitdown')}/{version('lfmap-markitdown')}"; missing package -> "0"
def extractor_version() -> str: ...
def cache_path(cache_dir: Path, content_hash: str) -> Path: ...  # cache_dir / hash[:2] / f"{hash}.md"
def extract(
    tool_ctx: ToolContext, path: Path, content_hash: str, cache_dir: Path, ocr: bool, config: dict | None = None
) -> ExtractResult | SkipResult: ...
```

Các quyết định đã chốt:

- **Cache:**
  - Mỗi bản trích có hai file: `<hash>.md` và file kèm `<hash>.json`, chứa `{"extractor_version": ..., "text_quality": ...}`.
  - Cache hợp lệ khi có đủ hai file và `extractor_version` trong JSON khớp với giá trị hiện tại.
  - Lý do dùng file JSON kèm: chữ ký hàm trong spec không mang version, và không được ghi version vào chính file `.md`, vì `char_start` của chunk tính trên văn bản đó.
- **Ghi nguyên tử:** ghi ra file tạm cùng thư mục rồi `os.replace`. Ghi `.md` trước, `.json` sau. Có `.json` nghĩa là bản trích đã hoàn chỉnh.
- **Gọi markitdown:** `MarkitdownTool(context_for("markitdown", parent=tool_ctx, config=config)).convert(ConvertInput(path=str(path), ocr=ocr))`.
  - Tham số `config` được thêm so với spec. Lý do: test truyền `{}`, để không đọc file cấu hình thật của máy.
- **Xử lý lỗi:**
  - `ToolError` có `details["reason_code"]` → trả `SkipResult(reason_code)`.
  - `ToolError` khác → raise lại.

Test (dùng `ToolContext(plugin_id="knowledge", permissions=perms)`, tham số `config={}`):

| # | Ca | Kỳ vọng |
|---|---|---|
| 1 | File `.md` thật trong `root`, gọi lần đầu | `ExtractResult`, `from_cache=False`. Có cả `cache_path(...)` lẫn `.json`, nội dung `.md` bằng `markdown` |
| 2 | Gọi lần hai với cùng hash | `from_cache=True`. Markitdown không được gọi: monkeypatch `MarkitdownTool.convert` bằng hàm bọc đếm số lần gọi |
| 3 | Sửa `extractor_version` trong `.json` thành giá trị khác | Trích lại, `from_cache=False` |
| 4 | File `.doc` (vài byte giả) | `SkipResult("office_gui_only")`. Nếu markitdown không báo đúng mã này thì dừng và hỏi |
| 5 | Monkeypatch `convert` raise `ToolError("internal", "x")` | raise `ToolError` |
| 6 | Không còn file tạm nào trong thư mục cache sau ca 1 | chỉ có `.md` và `.json` |
| 7 | `cache_path(Path("c"), "abcdef")` | `Path("c/ab/abcdef.md")` |

### TC-K5 `src/lfmap_knowledge/chunker.py`, test `tests/test_chunker.py`

```python
@dataclass(frozen=True)
class Chunk:
    ordinal: int
    heading_path: str
    char_start: int
    char_end: int
    text: str


def chunk_markdown(text: str, target_chars: int = 1500, max_chars: int = 3000) -> list[Chunk]: ...
```

Quy tắc theo spec mục 5.2. Chỉ dùng thư viện chuẩn. Các điểm chốt thêm:

- `heading_path` nối các heading bằng `" > "`. Văn bản trước heading đầu tiên có `heading_path = ""`.
- Dòng heading nằm trong chunk đầu tiên của mục đó.
- `ordinal` chạy từ 0 và liên tục.
- Chunk chỉ có khoảng trắng thì bỏ.

Test:

| # | Ca | Kỳ vọng |
|---|---|---|
| 1 | Văn bản trộn: heading, đoạn, bảng, tiếng Việt | Với mọi chunk `c`: `text[c.char_start:c.char_end] == c.text` |
| 2 | `# A` / `## B` / đoạn | chunk của đoạn có `heading_path == "A > B"` |
| 3 | `# A` / `## B` / `## C` | chunk dưới C có `"A > C"` (B không còn trong path) |
| 4 | Một đoạn 10.000 ký tự gồm nhiều câu | mọi chunk ≤ `max_chars`, nối lại phủ đủ đoạn |
| 5 | Một "câu" 10.000 ký tự không có dấu câu | cắt cứng, mọi chunk ≤ `max_chars` |
| 6 | Bảng 5 dòng giữa hai đoạn dài | bảng nằm trọn trong một chunk |
| 7 | Bảng 200 dòng (> `max_chars`) | mọi chunk ≤ `max_chars`; mọi chunk chứa dòng bảng đều bắt đầu bằng dòng tiêu đề bảng; mọi dòng dữ liệu xuất hiện đúng một lần |
| 8 | `""` và `"   \n\n"` | `[]` |
| 9 | Nhiều đoạn ngắn | được gộp: số chunk < số đoạn, mỗi chunk ≤ `max_chars` |
| 10 | `ordinal` | `[c.ordinal for c in chunks] == list(range(len(chunks)))` |

Lưu ý cho ca 7: với chunk bảng có lặp dòng tiêu đề, `c.text` không còn là một lát cắt của văn bản gốc. Chốt như sau:

- Chunk bảng lặp tiêu đề vẫn giữ `char_start`/`char_end` của phần dữ liệu.
- Ca 1 chỉ áp dụng cho văn bản không có bảng dài.
- Ghi rõ điều này trong prompt và docstring.

### TC-K6 `src/lfmap_knowledge/fts.py`, test `tests/test_fts.py`

```python
def fold(s: str) -> str: ...  # s.casefold().replace("đ", "d")
def fts_query(user_text: str) -> str: ...  # '"hop" "dong"'; rỗng -> ToolError("invalid_input", ...)
def index_chunks(conn: sqlite3.Connection, rows: Iterable[tuple[int, str]]) -> None: ...  # (chunk_id, text)
def delete_content(conn: sqlite3.Connection, content_hash: str) -> None: ...
def keyword_search(conn: sqlite3.Connection, query: str, limit: int) -> list[tuple[int, float]]: ...
```

Các quyết định đã chốt:

- **`fts_query`:** fold, tách theo khoảng trắng, bỏ mọi `"` trong từ, bỏ từ rỗng, rồi bọc từng từ trong nháy kép và nối bằng dấu cách (nghĩa là AND).
- **`index_chunks`:** `INSERT INTO chunks_fts(rowid, folded) VALUES (?, fold(text))`.
- **`delete_content`:** đọc `chunk_id, text` từ bảng `chunks` theo `content_hash`, rồi với mỗi dòng chạy `INSERT INTO chunks_fts(chunks_fts, rowid, folded) VALUES('delete', ?, ?)`. Hàm không xoá dòng trong `chunks`, vì bên gọi tự xoá.
- **`keyword_search`:** `SELECT rowid, bm25(chunks_fts) ... MATCH fts_query(query) ORDER BY bm25 LIMIT ?`. Trả `(chunk_id, -bm25)`, nghĩa là điểm càng cao càng khớp.
- Không hàm nào gọi `commit`; bên gọi quản lý transaction.

Test (dùng fixture `db`; ca 6 cần thêm dòng `contents` và `chunks` thật):

| # | Ca | Kỳ vọng |
|---|---|---|
| 1 | `fold("Đường ĐI")` | `== "dường di"` (dấu thanh để tokenizer lo) |
| 2 | index "Đường Nguyễn Trãi", tìm `duong` | trả chunk đó |
| 3 | index "Hợp đồng thuê nhà", tìm `hop dong` | khớp; tìm `hop xe` không khớp |
| 4 | `NEAR(a b)`, `"`, `a OR b -c*`, `hợp "đồng` | không raise lỗi cú pháp FTS5 (kết quả có thể rỗng) |
| 5 | `fts_query("   ")` và `fts_query('""')` | `ToolError`, `.code == "invalid_input"` |
| 6 | `delete_content` | chunk của hash đó không còn được tìm thấy, chunk của hash khác vẫn còn |
| 7 | 3 chunk, `limit=2` | 2 kết quả, sắp điểm giảm dần |

### TC-K7 `src/lfmap_knowledge/embed.py`, test `tests/test_embed.py`

```python
BATCH_SIZE = 32


def check_loopback(
    url: str,
) -> str: ...  # trả url bỏ "/" cuối; không phải loopback -> ToolError("invalid_input", ..., {"url": url})


class OllamaEmbedder:
    def __init__(self, url: str, model: str, perms: PermissionManager, timeout: float = 120) -> None: ...

    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def ping(self) -> bool: ...
```

Các quyết định đã chốt:

- **`check_loopback`:**
  - Chỉ nhận scheme `http` hoặc `https`.
  - Không được có user hoặc password.
  - Host phải là `localhost` hoặc một IP có `ipaddress.ip_address(host).is_loopback`.
  - Hàm được gọi trong `__init__`.
- **`embed`:**
  - Gọi `perms.require_network()` trước tiên.
  - Gửi `POST {url}/api/embed` theo lô 32, body `{"model", "input"}`, rồi đọc `embeddings`.
  - Danh sách rỗng → trả `[]` và không gọi mạng.
- **Bỏ qua proxy:** `urllib.request.build_opener(urllib.request.ProxyHandler({}))`. Bắt buộc, vì máy có biến proxy thì dữ liệu sẽ đi ra ngoài.
- **Lỗi:** `URLError`, `OSError` hay timeout → `ToolError("backend_unavailable", ..., {"reason": "ollama_unreachable"})`.
- **`ping`:** `GET /api/tags`, trả `True` khi nhận HTTP 200 và `False` với mọi lỗi.

Test (server giả dùng `http.server.ThreadingHTTPServer` trên `127.0.0.1:0` trong một thread, định nghĩa trong file test; `PermissionManager([], [], network=True)`):

| # | Ca | Kỳ vọng |
|---|---|---|
| 1 | `http://10.0.0.5:11434`, `http://example.com`, `ftp://127.0.0.1`, `http://u:p@127.0.0.1` | `ToolError` `invalid_input` |
| 2 | `http://127.0.0.1:11434/`, `http://localhost:1`, `http://[::1]:1` | chấp nhận |
| 3 | 70 câu | 70 vector theo đúng thứ tự; server nhận 3 request (32 + 32 + 6) với đúng `model` |
| 4 | `[]` | `[]`, 0 request |
| 5 | Server đã tắt (cổng đóng) | `ToolError` `backend_unavailable`, `details["reason"] == "ollama_unreachable"` |
| 6 | `perms` không có quyền network | `ToolError` `permission_denied`, 0 request |
| 7 | `ping()` khi server chạy và khi đã tắt | `True`, rồi `False` |
| 8 | Đặt biến môi trường `HTTP_PROXY=http://203.0.113.1:9` (monkeypatch) | vẫn gọi tới server giả và thành công |

## 3. Kiểm tra trước khi push

- `uv run pytest packages/lfmap-knowledge/tests/test_<x>.py -q`: mỗi file đỏ **chỉ** vì `ModuleNotFoundError: lfmap_knowledge.<x>`. Không được có lỗi nào khác.
- Các test cũ vẫn xanh: `uv run pytest -q` với `--ignore=` cho từng file trong 4 file mới.
- `uv run ruff check .` và `uv run ruff format --check .` sạch.

## 4. Card cho qwen

Bốn thư mục `D:\Development\lfmap-tools\qwen-loop\cards\TC-K4` … `TC-K7`. Mỗi thư mục có:

`card.toml`:

```toml
id = "TC-K4"
base_ref = "feature/knowledge-k4-k7"
targets = ["packages/lfmap-knowledge/src/lfmap_knowledge/extract.py"]
tests = ["packages/lfmap-knowledge/tests/test_extract.py"]
max_rounds = 3
```

`prompt.md` theo khuôn của `cards\TC-K2\prompt.md` (bản gốc TC-K2_qwen.md), theo đúng thứ tự:

1. Một câu vai trò: "You are a careful Python 3.12 developer. Write ONE new module …". Kèm quy định: chỉ thư viện chuẩn (riêng K4 được dùng `lfmap_core`, `lfmap_markitdown`), small functions, type hints, docstring tiếng Anh cho mỗi hàm public.
2. `RULES`:
   - Do NOT edit the tests or conftest.py, do NOT define pytest fixtures.
   - Reply with `FILE: <path>` then ONE python block with the COMPLETE module.
   - Never answer with an empty block.
3. `API`: chữ ký ở mục 2, nguyên văn.
4. Mô tả hành vi: các gạch đầu dòng "Các quyết định đã chốt" ở mục 2, dịch sang tiếng Anh, ngắn.
5. `Imports available`: chỉ những import cần (ví dụ `from lfmap_core import ToolError`, chữ ký `ToolError(code, message, details=None)`).
6. `CONFTEST`: dán nguyên văn `tests/conftest.py`.
7. `TESTS`: dán nguyên văn file test của card.
8. Câu cuối: ``NOW WRITE THE COMPLETE `<module>.py`. Start with the FILE line, then the code block containing the whole module.``

Giới hạn: mỗi prompt dưới khoảng 4k token, tức khoảng 14.000 ký tự. Kiểm bằng số ký tự.

Nếu prompt vượt giới hạn, cắt theo thứ tự:
1. Rút gọn mô tả hành vi.
2. Bỏ những phần không dùng tới trong conftest.

Không được cắt test.

## 5. Tiêu chí xong B3

- Nhánh `feature/knowledge-k4-k7` trên origin có 4 file test. Mỗi file đỏ đúng vì thiếu module, test cũ vẫn xanh, ruff sạch.
- Có 4 thư mục card, `card.toml` hợp lệ.
  - Kiểm bằng `py -3.12 -c "import qwen_loop, pathlib; [qwen_loop.load_card(pathlib.Path(p)) for p in ['cards/TC-K4','cards/TC-K5','cards/TC-K6','cards/TC-K7']]"`, hoặc tên hàm nạp card tương ứng trong B1.
  - Mỗi `prompt.md` dưới 14.000 ký tự.
- Báo lại cho Hùng: số ký tự từng prompt, và lệnh B4:
  ```powershell
  cd D:\Development\lfmap-tools\qwen-loop
  py -3.12 qwen_loop.py run cards\TC-K4 cards\TC-K5 cards\TC-K6 cards\TC-K7 --repo D:\Development\lfmap
  ```
