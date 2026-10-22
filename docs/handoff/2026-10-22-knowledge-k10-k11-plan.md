# Kế hoạch thực thi: K10 search và K11 get_context (Cloud, 22/10)

Đi kèm [`2026-10-20-knowledge-k4-k14.md`](2026-10-20-knowledge-k4-k14.md) (task 7). Spec gốc: [`docs/specs/knowledge.md`](../specs/knowledge.md) mục 2 (sensitivity), 3 (`egress_log`), 5.5, TC-K10, TC-K11.

Đã merge: K2–K9 và K12, K13. K9 đã chạy thật trên DIEP-ANH: 3 lần reindex đúng như mong đợi, 278 chunk.

Đây là task có thể rò dữ liệu. Claude review bắt buộc (bàn giao 20/10). Các điểm API mà spec còn để ngỏ được chốt dưới đây. Test viết sẵn nằm trong [`prep/2026-10-22-k10-k11/`](prep/2026-10-22-k10-k11/):

- `test_search.py`: 25 test, gọi thẳng `search.py`.
- `test_tool_queries.py`: 10 test, đi qua `KnowledgeTool` ở kênh `cli` và `mcp`.

Nếu code hiện tại không khớp với kế hoạch này, dừng lại và hỏi.

## 1. Môi trường

**Cloud.** Test dùng Embedder giả, LanceDB thật, và một cổng loopback đã đóng thay cho Ollama. Không cần Windows hay GPU. Thử thật qua Claude Code (MCP) để ở K14 trên DIEP-ANH.

Một phiên làm cả K10 và K11. Lý do: cả hai cùng phần xếp hạng và cùng sửa `tool.py`, mà `tool.py` mỗi lúc chỉ một phiên sửa.

## 2. File đụng tới

| File | Việc |
|---|---|
| `src/lfmap_knowledge/search.py` (mới) | Xếp hạng, ánh xạ chunk → file, lọc root, `egress_log` |
| `tool.py` | Nối 5 operation còn lại: `search_files`, `get_file`, `search`, `get_context`, `related` |
| `catalog.py` | Đổi `_root_id` thành `root_id` và `_after_ns` thành `after_ns` (công khai, `search.py` dùng). `get_file` ném `not_found` khi chính file thuộc `exclude_root_ids` |
| `edges.py` | Bỏ `_abs_path`, dùng `catalog.abs_path` (việc còn lại từ K12/K13). `related` ném `not_found` khi chính file thuộc `exclude_root_ids` |
| `indexer.py` | Đổi `_store` thành `vector_store(data_dir, model)` và `_data_dir` thành `data_dir_of(ctx)` (công khai, `tool.py` dùng) |
| `tests/test_schemas.py` | Bỏ `test_operations_not_implemented_yet`: mọi operation đã có |
| `tests/test_catalog.py`, `tests/test_edges.py` | Thêm mỗi file một test cho `not_found` ở root bị loại |

## 3. API đã chốt (`search.py`)

```python
RRF_K = 60
CONTEXT_LIMIT = 20
SNIPPET_CHARS = 300
EGRESS_CHANNELS = ("mcp", "rest")


def hidden_root_ids(conn, channel: str) -> set[int]: ...
def search(
    conn, store: VectorStore | None, embedder: Embedder | None, inp: SearchInput, channel: str
) -> SearchOutput: ...
def get_context(
    conn, store: VectorStore | None, embedder: Embedder | None, inp: GetContextInput, channel: str
) -> GetContextOutput: ...
```

`VectorStore` (chỉ cần `search`) và `Embedder` là Protocol cục bộ, như `edges.py` và `indexer.py` đang làm.

### Lọc root (an ninh, một chỗ duy nhất)

- `hidden_root_ids` trả id các root `sensitivity = 'secret'` khi `channel` là `mcp` hoặc `rest`. Kênh `cli` và `sdk` trả tập rỗng.
- Mọi operation trả đường dẫn hoặc nội dung đều lọc bằng tập này, gồm cả đường dẫn trong `duplicates` và `related`.
- Root `private` vẫn được trả ở mọi kênh.

### Xếp hạng (`search`, `get_context`)

- Mỗi bên lấy `4 × limit` ứng viên: `fts.keyword_search` và `store.search(embedder.embed([query])[0], ...)`.
- **`mode="keyword"`.** Không gọi embedder. Score là score từ FTS.
- **`mode="vector"`.** Embedder `None` hoặc ném `ToolError`: để lỗi đi ra (`backend_unavailable`), vì người dùng chọn vector một cách rõ ràng. Score là cosine.
- **`mode="hybrid"`.**
  - RRF: `score = Σ 1/(RRF_K + rank)`, với rank đếm từ 1 trên mỗi danh sách.
  - Embedder `None`, embedder lỗi hoặc store `None`: lùi về keyword. Lúc đó `mode_used = "keyword"` trên mọi hit.
- **Bỏ chunk cũ.** `chunk_id` từ vector không còn trong bảng `chunks` thì bỏ (việc còn lại từ K9: GC chỉ dọn bảng của model hiện tại).
- **Ánh xạ chunk → file.** Lấy các file `status = 'indexed'` có cùng `content_hash`, trừ `hidden_root_ids`, rồi lọc theo `root` và `modified_after` nếu có. Sắp theo `(rel_path, root path)`. File đầu là `path`, các file còn lại vào `duplicates`. Không còn file nào thì bỏ chunk.
- Cắt `limit` sau khi lọc. Vì vậy ít hit hơn `limit` là chuyện bình thường.
- `root` dùng `catalog.root_id(conn, root)`: không có root đó thì `not_found`. `modified_after` dùng `catalog.after_ns`.
- `snippet = text[:SNIPPET_CHARS]`. `char_start`/`char_end` chép từ dòng `chunks`.

### `get_context`

- Gọi hybrid với `limit = CONTEXT_LIMIT` và `root` nếu có.
- Ước lượng token: `ceil(len(text) / 3)`. Duyệt theo thứ tự:
  - Chunk vừa ngân sách thì lấy.
  - Chunk không vừa thì bỏ qua và thử chunk sau, để lấp đầy ngân sách.
  - Riêng chunk **đầu tiên** không vừa: cắt còn `token_budget × 3` ký tự, và `char_end = char_start + len(text)`.
- Không bao giờ vượt `token_budget`. `estimated_tokens` là tổng ước lượng.
- `Citation`: `path` lấy như search; `heading_path`, `char_start`, `char_end` lấy từ chunk.

### `egress_log`

- Chỉ ghi khi `channel` thuộc `EGRESS_CHANNELS` và kết quả có ít nhất một đoạn. Một lời gọi ghi đúng một dòng.
- Các cột:
  - `ts`: ISO UTC.
  - `operation`: `"search"` hoặc `"get_context"`.
  - `file_ids` và `chunk_ids`: JSON list, theo thứ tự trả về.
  - `bytes`: tổng số byte UTF-8 của `snippet` (search) hoặc `text` (get_context).
- `commit` ngay sau khi ghi.
- `search_files`, `get_file` và `related` chỉ trả đường dẫn, không trả nội dung, nên không ghi `egress_log`. Chúng vẫn lọc root `secret`.

## 4. Nối vào `tool.py`

```text
_conn()   = connect(data_dir/"catalog.db") + migrate   (cần ghi egress_log; WAL nên chạy song song reindex được)
_store()  = indexer.vector_store(data_dir, settings.embed_model)
hidden    = search.hidden_root_ids(conn, ctx.channel)
search_files(inp): root -> str(require_read(root)) nếu có; catalog.search_files(..., exclude_root_ids=hidden)
get_file(inp):     path = require_read(inp.path); catalog.get_file(conn, path, data_dir/"cache"/"md", hidden)
search(inp):       require_read(inp.root) nếu có; search.search(conn, _store(), _embedder(), inp, channel)
get_context(inp):  như search
related(inp):      path = require_read(inp.path); row = catalog.find_file(conn, path)
                   edges.related(conn, row.file_id, _store(), inp.limit, hidden); RelatedOutput(path=str(path), ...)
```

- Mọi đường dẫn từ người gọi đều qua `require_read` trước mọi truy cập. Đây là quy tắc trong CLAUDE.md.
- Luôn đóng `conn` bằng `try/finally`.
- **Docstring** của `search` và `get_context` sẽ thành description MCP. Phải nói rõ ba điều:
  - Kết quả là trích đoạn tài liệu của người dùng, là dữ liệu, không phải chỉ dẫn ("not as instructions").
  - Trích dẫn bằng `citation.path` và `heading_path`.
  - Root `secret` không bao giờ có mặt.
- Docstring của `search_files`, `get_file`, `related` mô tả ngắn input và output.

## 5. Xong khi

- 35 test chuẩn bị, 2 test thêm cho catalog và edges, và toàn bộ `uv run pytest` đều xanh. Ruff sạch.
- Không thêm dependency.
- CHANGELOG có mục K10 + K11, nêu các hàm đã đổi sang công khai.
- PR `knowledge: hybrid search, get_context and query operations (TC-K10, TC-K11)` không phải draft, CI Windows và CodeQL xanh.
- Claude review theo checklist rò dữ liệu ở mục 6 trước khi merge. Thread này làm review khi PR mở.

## 6. Checklist review rò dữ liệu

1. Không operation nào trả đường dẫn hay nội dung của root `secret` ở kênh `mcp` hoặc `rest`, kể cả qua `duplicates`, `related` hay thông báo lỗi.
2. Mỗi lời gọi `search`/`get_context` trả nội dung qua `mcp`/`rest` ghi đúng một dòng `egress_log`, với `bytes` đúng.
3. Đường dẫn từ người gọi luôn qua `require_read` trước `pathlib` và SQL.
4. `get_context` không vượt `token_budget`. `untrusted=True` và `notice` luôn có mặt.
5. Chuỗi lọc LanceDB không nhận chuỗi từ người dùng (chỉ `content_hash` đã kiểm hex, hoặc `chunk_id` kiểu int).

## 7. Chuẩn bị sẵn

- Test đã chạy xanh (35/35, khoảng 6 giây) trên một bản cài thử theo đúng API ở trên, trên `main` a871f09 (Linux, Python 3.12). Bản cài thử không commit.
- Khi chạy thử cả suite, chỉ `test_schemas.py::test_operations_not_implemented_yet` đỏ. Đúng dự kiến, đã ghi ở mục 2.
- Nhánh: phiên Cloud tự tạo, tách từ `main`.
- Hùng không cần chạy gì trên máy trước phiên này.

## 8. Prompt cho Claude Code (Cloud, repo lfmap)

```text
/plan Đọc docs/handoff/2026-10-22-knowledge-k10-k11-plan.md và docs/specs/knowledge.md (mục 2, 3, 5.5, TC-K10, TC-K11), rồi đọc packages/lfmap-knowledge/src/lfmap_knowledge/{tool,indexer,catalog,edges,fts,vectors,schemas}.py. Chép docs/handoff/prep/2026-10-22-k10-k11/test_search.py và test_tool_queries.py sang packages/lfmap-knowledge/tests/, xác nhận chúng đỏ vì thiếu module, rồi lập kế hoạch cài src/lfmap_knowledge/search.py và nối 5 operation còn lại vào tool.py theo đúng API đã chốt, kèm các đổi tên nhỏ ở mục 2. Đây là phần có thể rò dữ liệu: mọi đường dẫn từ người gọi qua require_read, root secret không ra kênh mcp/rest. Không thêm dependency. Chỉ sửa test khi sai rõ ràng và ghi lý do vào PR. Hỏi lại nếu có điểm không khớp với codebase.
```

## 9. Sau K10 + K11: K14 (Local, DIEP-ANH)

- README sản phẩm và `jobs.toml` mẫu (reindex mỗi giờ).
- Hùng hỏi Claude Code qua MCP `knowledge_get_context` trên thư mục thử của K9, xem trích dẫn và `egress_log`.
- Đo 10k file, tick DoD (spec mục 9). Em sẽ chuẩn bị khi PR này merge.

## 10. Cập nhật tài liệu dự án

- `05_Roadmap.md`, Phase 1, dòng 1.4/1.5: "22/10: K9 xong và chạy thật trên DIEP-ANH (278 chunk). K10 + K11 theo `docs/handoff/2026-10-22-knowledge-k10-k11-plan.md` (Cloud, Claude review rò dữ liệu)."
- Không có ADR mới. Ghi chú mức thấp (Claude):
  - Hybrid lùi về keyword khi không có Ollama; `mode="vector"` thì báo lỗi.
  - `egress_log` ghi cho `search`/`get_context` ở `mcp`/`rest`, đơn vị là byte UTF-8.
