# Kế hoạch thực thi: K8, K12, K13 chạy song song trên Cloud (22/10 sáng)

Đi kèm [`2026-10-20-knowledge-k4-k14.md`](2026-10-20-knowledge-k4-k14.md) (task 4 và task 8) và [`2026-10-21-cloud-parallel-plan.md`](2026-10-21-cloud-parallel-plan.md) (mục 3: K8). Spec gốc: [`docs/specs/knowledge.md`](../specs/knowledge.md) mục 5.6, TC-K8, TC-K12, TC-K13.

Các điểm API mà spec còn để ngỏ được chốt dưới đây. Test viết sẵn nằm trong [`prep/2026-10-22-k12-k13/`](prep/2026-10-22-k12-k13/). Nếu code hiện tại không khớp với kế hoạch này, dừng lại và hỏi.

## 1. Chọn task

Bối cảnh sáng 22/10: J4 task A đã merge (PR #29). J4 task B đang chạy trên DIEP-ANH. Hùng ở văn phòng, chỉ có trình duyệt, nên chỉ chọn việc chạy được trên Cloud.

| Task | Môi trường | Phụ thuộc | File đụng tới | Kết luận |
|---|---|---|---|---|
| **K8** `vectors.py` | Cloud. LanceDB chạy trên Linux; CI Windows kiểm lại | Không | File mới | **Chạy ngay**, đã chuẩn bị từ 21/10 |
| **K12** `catalog.py` | Cloud (không dùng qwen, xem dưới) | Bảng `files`/`roots`/`contents` (K2), `cache_path` (K4) | File mới | **Chạy ngay** |
| **K13** `edges.py` | Cloud | Bảng `edges` (K2). Phần vector chỉ dùng Protocol `VectorStore`, test dùng store giả | File mới | **Chạy ngay** |
| K9 reindex | Cloud | K8 (gọi store), K13 (gọi `link_*`) | `indexer.py`, `tool.py` | Sau khi K8 và K13 merge |
| K10 + K11 | Cloud, Claude review bắt buộc | K8, K9 | `search.py`, `tool.py` | Sau K9 |
| K14 | Local (DIEP-ANH, thư mục thật, Ollama) | Tất cả | README | Cuối |

**Vì sao K12 không giao qwen.** B6 (21/10) chốt qwen chỉ nhận card cỡ S có test chặt. Spec ghi K12 cỡ M. Thêm nữa, DIEP-ANH đang chạy J4 task B. Đợi tối chạy qwen sẽ chậm một ngày mà không tiết kiệm nhiều.

**Không đụng `tool.py`.** Cả ba task chỉ thêm module thuần và test. Việc nối `search_files`, `get_file`, `related` vào `tool.py` thuộc phiên K10 + K11, vì phiên đó đã xử lý `channel` và root `secret`. Quy tắc này giữ nguyên từ bàn giao 20/10: mỗi lúc chỉ một phiên sửa `tool.py`.

**Xung đột duy nhất là `CHANGELOG.md`** (mục `[Unreleased]`). PR nào merge sau thì rebase và giữ mọi dòng.

**Hạn mức Pro.** Ước lượng thô: K8 khoảng 1/5 cửa sổ 5 giờ; K12 và K13 mỗi task khoảng 1/5 đến 1/4. Ba phiên song song dùng khoảng 2/3 cửa sổ. Nếu cửa sổ đã dùng nhiều thì chạy K8 và K13 trước, vì K9 cần cả hai. K12 chạy sau cũng không chặn gì.

## 2. Task K8: `vectors.py`

Giữ nguyên [`2026-10-21-cloud-parallel-plan.md`](2026-10-21-cloud-parallel-plan.md) mục 3: API, test (`prep/2026-10-21-cloud/test_vectors.py`, 14 test) và prompt. Không có gì thay đổi.

## 3. Task K12: `catalog.py`

- Nhánh: nhánh phiên Cloud tự tạo, tách từ `main`. Tên PR: `knowledge: file catalog queries (TC-K12)`.
- Bước đầu: chép [`prep/2026-10-22-k12-k13/test_catalog.py`](prep/2026-10-22-k12-k13/test_catalog.py) sang `packages/lfmap-knowledge/tests/test_catalog.py`, bỏ 2 dòng chú thích đầu. Test phải đỏ vì thiếu module.

### Khác spec (schemas K1 đã merge thắng spec)

- `SearchFilesInput` không có trường `glob`. Glob đi qua `query`: nếu `query` chứa `*`, `?` hoặc `[` thì đó là mẫu glob trên `rel_path`. Ngược lại là tìm theo tên.
- `GetFileOutput` không có trường `edges`. Cạnh trả qua operation `related` (K13).

### API đã chốt (`packages/lfmap-knowledge/src/lfmap_knowledge/catalog.py`)

```python
def strip_accents(s: str) -> str: ...  # casefold, đ→d, NFD, drop combining marks
def abs_path(root_path: str, rel_path: str) -> str: ...  # normpath(join(root, *rel.split("/")))
def search_files(
    conn,
    query="",
    root="",
    ext="",
    status="",
    modified_after="",
    limit=10,
    exclude_root_ids: Collection[int] = frozenset(),
) -> SearchFilesOutput: ...
def find_file(conn, path: Path) -> sqlite3.Row: ...  # files row joined with roots.path AS root_path
def get_file(conn, path: Path, cache_dir: Path) -> GetFileOutput: ...
```

- **Tên.** Mỗi từ của `query` (sau `strip_accents`) phải là chuỗi con của `strip_accents(name_folded)`. Lọc bằng Python sau khi lọc SQL. Không dùng `LIKE`, để `%` và `_` trong `query` là ký tự thường.
  - Lý do: `name_folded` do scanner ghi còn dấu ("báo cáo"). Lọc Python trên tập đã lọc SQL đủ nhanh cho 10k file.
- **Glob.** `fnmatch.fnmatchcase(strip_accents(rel_path), strip_accents(query))`. Lưu ý `*` của `fnmatch` khớp cả `/`, nên `*.pdf` khớp mọi PDF ở mọi thư mục, còn `**/*.pdf` chỉ khớp PDF trong thư mục con.
- **`status`.**
  - Rỗng: mọi trạng thái trừ `deleted`.
  - Một trong 5 trạng thái của bảng `files` (kể cả `deleted`): đúng trạng thái đó.
  - Giá trị khác: `invalid_input`.
- **`ext`.** Chấp nhận `pdf`, `.pdf`, `.PDF`; so với `files.ext` (luôn chữ thường, có dấu chấm).
- **`root`.** So với `roots.path` sau `normcase(normpath(...))`. Không có root đó: `not_found`.
  - Catalog không kiểm quyền. `tool.py` gọi `require_read(root)` trước.
- **`modified_after`.** `datetime.fromisoformat`. Thiếu múi giờ thì hiểu là giờ máy, vì người dùng gõ ngày theo giờ VN. Sai định dạng: `invalid_input`. Điều kiện `mtime_ns > ts`.
- **`exclude_root_ids`.** Bỏ file của các root này. `tool.py` truyền id các root `secret` khi `channel` là `mcp` hoặc `rest` (spec mục 2).
  - Tên file trong root `secret` cũng là dữ liệu nhạy cảm, nên lọc ở mọi operation trả đường dẫn.
- **Thứ tự và đếm.** `ORDER BY mtime_ns DESC, file_id`. `total` đếm trước khi cắt `limit`.
- **`FileInfo`.**
  - `path = abs_path(root.path, rel_path)`, `root = roots.path`.
  - `mtime` = ISO UTC đến giây, ví dụ `2026-01-01T00:00:00+00:00`.
  - `content_hash` rỗng khi NULL.
- **`find_file`.** Chọn root dài nhất chứa `path` (bằng `Path.relative_to`; root lồng nhau được phép). `rel_path = relative.as_posix()`.
  - Không có root chứa `path`, không có dòng, hoặc dòng `deleted`: `not_found`.
  - `path` nhận vào đã qua `require_read` ở `tool.py`, nên đây là đường dẫn đã resolve.
- **`get_file`.**
  - `chunk_count` lấy từ `contents`; không có dòng `contents` thì 0.
  - `duplicates` là đường dẫn tuyệt đối của file khác cùng `content_hash`, không tính file `deleted`, sắp theo chữ.
  - `markdown_cached = cache_path(cache_dir, hash).exists()` (dùng `extract.cache_path`).

### Xong khi

- 24 test mới xanh. `uv run pytest` toàn bộ xanh. Ruff sạch.
- Không sửa `tool.py`, không thêm dependency.
- CHANGELOG có mục cho K12, nêu hai điểm khác spec ở trên.
- PR không phải draft, CI Windows và CodeQL xanh.

### Prompt cho Claude Code (Cloud, repo lfmap)

```text
/plan Đọc docs/handoff/2026-10-22-knowledge-k12-k13-plan.md mục 1 và 3, docs/specs/knowledge.md (mục 3, TC-K12), và packages/lfmap-knowledge/src/lfmap_knowledge/{schemas,store,scanner,extract}.py. Chép docs/handoff/prep/2026-10-22-k12-k13/test_catalog.py sang packages/lfmap-knowledge/tests/test_catalog.py, xác nhận nó đỏ vì thiếu module, rồi lập kế hoạch cài src/lfmap_knowledge/catalog.py theo đúng API đã chốt (không thêm dependency, không sửa tool.py). Chỉ sửa test khi sai rõ ràng và ghi lý do vào PR. Hỏi lại nếu có điểm không khớp với codebase.
```

## 4. Task K13: `edges.py`

- Nhánh: nhánh phiên Cloud tự tạo, tách từ `main`. Tên PR: `knowledge: file edges and related files (TC-K13)`.
- Bước đầu: chép [`prep/2026-10-22-k12-k13/test_edges.py`](prep/2026-10-22-k12-k13/test_edges.py) sang `packages/lfmap-knowledge/tests/test_edges.py`, bỏ 2 dòng chú thích đầu. Test phải đỏ vì thiếu module.

### API đã chốt (`packages/lfmap-knowledge/src/lfmap_knowledge/edges.py`)

```python
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def link_targets(markdown: str) -> list[str]: ...  # safe relative targets, in order
def link_generated_from(conn, file_id: int) -> int: ...  # edges newly written
def link_references(conn, file_id: int, markdown: str) -> int: ...
def related(
    conn,
    file_id: int,
    store: VectorStore | None = None,
    limit: int = 10,
    exclude_root_ids: Collection[int] = frozenset(),
) -> list[RelatedFile]: ...
```

`VectorStore` là Protocol ở spec mục 5.4. K8 chạy song song, nên K13 tự khai báo một Protocol nhỏ (chỉ `vector_of` và `search`) trong `edges.py`, hoặc dùng `typing.Protocol` cục bộ. Không import `vectors.py`. Các hàm không `commit`; người gọi (K9) commit.

- **`link_targets`.** Chỉ xử lý chuỗi, không bao giờ mở đường dẫn trong link. Lần lượt:
  - Bỏ link bắt đầu bằng `\` hoặc `/` (UNC, `//server`, đường dẫn tuyệt đối).
  - Bỏ link có scheme, kiểm bằng `^[a-zA-Z][a-zA-Z0-9+.-]*:`. Luật này bắt được `http:`, `https:`, `file:`, `mailto:` và cả ổ đĩa `C:`.
  - Cắt `#...` và `?...`.
  - `urllib.parse.unquote`.
  - Đổi `\` thành `/`.
  - Bỏ chuỗi rỗng (link `#top`).
- **`link_references`.**
  - Xoá cạnh `REFERENCES` cũ của `file_id`, để reindex thay thế chứ không cộng dồn.
  - Mỗi target: `posixpath.normpath(posixpath.join(dirname(src.rel_path), target))`. Kết quả là `..` hoặc bắt đầu bằng `../` (ra ngoài root) thì bỏ.
  - Tra file cùng root, không `deleted`. Không tự trỏ về chính nó.
  - `INSERT OR IGNORE`, `detail` = target sau `link_targets`.
- **`link_generated_from`.** Cạnh luôn có chiều `md → nguồn` (`src_file_id` là file `.md`). Chỉ xét file cùng thư mục, cùng root, không `deleted`.
  - Với `X.md`: nguồn là `X` (`a.pdf.md → a.pdf`), hoặc `X.<ext khác .md>` (`a.md → a.docx`).
  - Gọi được từ cả hai phía: gọi với `a.pdf` cũng tìm `a.pdf.md` và `a.md`.
  - Idempotent.
- **`related`.** File không tồn tại: `not_found`. Gom ứng viên, mỗi file giữ lý do mạnh nhất theo thứ tự sau:

  | Thứ tự | `reason` | Nguồn | `score` |
  |---|---|---|---|
  | 1 | `duplicate` | cùng `content_hash` | 1.0 |
  | 2 | `generated_from` | cạnh `GENERATED_FROM` theo cả hai chiều | 0.9 |
  | 3 | `references` | cạnh `REFERENCES` đi ra | 0.8 |
  | 4 | `referenced_by` | cạnh `REFERENCES` đi vào | 0.7 |
  | 5 | `similar_content` | vector, xem dưới | điểm từ store, lấy max theo file |
  | 6 | `same_folder` | cùng root, cùng thư mục cha | 0.1 |

  - **`similar_content`:**
    - Lấy `chunk_id` của content đó theo `ordinal`, rồi `store.vector_of(ids)`. Lấy trung bình các vector, rồi `store.search(mean, limit * 3)`.
    - Chunk cùng `content_hash` với file gốc thì bỏ.
    - `vector_of` ném `ToolError` (chưa embed) hoặc `store is None`: bỏ qua nguồn này, không lỗi.
  - Bỏ chính nó, file `deleted` và file thuộc `exclude_root_ids`.
  - Sắp theo (thứ tự lý do, `-score`, `rel_path`), cắt `limit`. `path` là đường dẫn tuyệt đối như `catalog.abs_path`.
    - Không import `catalog.py` vì K12 chạy song song. Viết một helper riêng 1 dòng; gộp sau khi cả hai merge.

### Xong khi

- 18 test mới xanh (tính cả tham số hoá). `uv run pytest` toàn bộ xanh. Ruff sạch.
- Không sửa `tool.py`, không thêm dependency.
- CHANGELOG có mục cho K13.
- PR không phải draft, CI Windows và CodeQL xanh.

### Prompt cho Claude Code (Cloud, repo lfmap)

```text
/plan Đọc docs/handoff/2026-10-22-knowledge-k12-k13-plan.md mục 1 và 4, docs/specs/knowledge.md (mục 5.4, 5.6, TC-K13), và packages/lfmap-knowledge/src/lfmap_knowledge/{schemas,store}.py. Chép docs/handoff/prep/2026-10-22-k12-k13/test_edges.py sang packages/lfmap-knowledge/tests/test_edges.py, xác nhận nó đỏ vì thiếu module, rồi lập kế hoạch cài src/lfmap_knowledge/edges.py theo đúng API đã chốt (không mở đường dẫn trong link, không thêm dependency, không sửa tool.py, không import vectors.py hay catalog.py). Chỉ sửa test khi sai rõ ràng và ghi lý do vào PR. Hỏi lại nếu có điểm không khớp với codebase.
```

## 5. Chuẩn bị sẵn

- Test K12 (24 test) và K13 (18 test) đã chạy xanh trên một bản cài thử dùng xong bỏ, theo đúng API trên (Linux, Python 3.12, `uv sync` từ `main` 0914ac3). Bản cài thử không commit. Vì vậy test không mâu thuẫn nhau, nhưng Claude Code vẫn tự viết code.
- Cả ba task không cần bước nào trên máy Hùng. CI Windows kiểm phần khác hệ điều hành.
- Thứ tự merge gợi ý: K8, K13, K12, theo thứ tự xong. PR nào sau thì rebase `CHANGELOG.md`.

## 6. Việc tiếp theo sau khi ba PR merge

- **K9 reindex (Cloud).** Gọi `vectors`, `edges.link_generated_from`/`link_references`, nối `status`/`reindex` vào `tool.py`. Chuẩn bị test và kế hoạch khi K8 và K13 đã merge.
- **K10 + K11 (Cloud, Claude review).** Nối `search`, `get_context`, `search_files`, `get_file`, `related` vào `tool.py`. Truyền `exclude_root_ids` cho kênh `mcp`/`rest`.
- **K14 (Local, DIEP-ANH).** Chạy trên thư mục thật.

## 7. Cập nhật tài liệu dự án

- `05_Roadmap.md`, Phase 1, dòng 1.4: "22/10: K8, K12, K13 chạy song song trên Cloud. K12 chuyển từ qwen sang Claude Code vì là card M (theo B6)."
- `03_Decisions_ADR.md`, ghi chú dưới ADR-004 (quyết định mức thấp, Claude): "K12 không giao qwen: card M, B6 chỉ cho qwen card S."
- Không có ADR mới. Hai điểm khác spec ở K12 (glob qua `query`, `get_file` không trả cạnh) đi theo schema K1 đã merge.
