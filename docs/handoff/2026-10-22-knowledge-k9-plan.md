# Kế hoạch thực thi: K9 reindex và status (Cloud, 22/10)

Đi kèm [`2026-10-20-knowledge-k4-k14.md`](2026-10-20-knowledge-k4-k14.md) (task 5). Spec gốc: [`docs/specs/knowledge.md`](../specs/knowledge.md) mục 3, 4, TC-K9.

Đã merge trước kế hoạch này: K2–K7, K8 `vectors.py` (#31), K13 `edges.py` (#33). K12 `catalog.py` (#32) đang merge; K9 không dùng nó.

Các điểm API mà spec còn để ngỏ được chốt dưới đây. Test viết sẵn: [`prep/2026-10-22-k9/test_indexer.py`](prep/2026-10-22-k9/test_indexer.py) (23 test). Nếu code hiện tại không khớp với kế hoạch này, dừng lại và hỏi.

## 1. Môi trường

**Cloud.** Test chỉ dùng file `.md`, `.txt`, `.rtf` (markitdown chuyển `.md`/`.txt` trên Linux; `.rtf` bị từ chối với `office_gui_only`), Embedder giả và LanceDB thật. Không cần Ollama, Office hay GPU.

Bước "chạy thật trên một thư mục nhỏ của Hùng" (tiêu chí xong của task 5) làm **Local** trên DIEP-ANH sau khi PR merge. Xem mục 6.

## 2. File đụng tới

- Mới: `src/lfmap_knowledge/indexer.py`, `tests/test_indexer.py`.
- Sửa: `tool.py`, chỉ hai operation `status` và `reindex`. Năm operation còn lại giữ `not implemented` cho phiên K10 + K11.
- Không sửa module K2–K8, K13. Nếu thấy lỗi ở đó, sửa tối thiểu và ghi lý do trong PR.

## 3. API đã chốt (`indexer.py`)

```python
DEFAULT_EMBED_MODEL = "bge-m3"
MAX_ATTEMPTS = 3
Progress = Callable[[str, int, int], None]  # stage ("scan" | "extract" | "embed"), done, total


def knowledge_roots(ctx: ToolContext) -> list[Path]: ...
def reindex(
    ctx: ToolContext,
    embedder: Embedder | None,
    root: str = "",
    full: bool = False,
    progress: Progress | None = None,
    config: dict | None = None,  # passed to extract(); tests pass {}
) -> ReindexOutput: ...
def status(ctx: ToolContext, ollama_available: bool) -> StatusOutput: ...
```

`Embedder` là Protocol ở spec mục 5.4 (`model`, `embed`). Khai báo trong `indexer.py`, không import `OllamaEmbedder` ở đây. Vector store luôn là `LanceVectorStore(data_dir / "vectors", f"chunks_{model_slug(embedder.model)}")`.

### `knowledge_roots`

`ctx.permissions.read_roots`, bỏ `data_dir` và mọi thứ nằm dưới nó (so sánh sau `realpath` + `normcase`), giữ thứ tự, bỏ trùng.

### `reindex`, theo đúng thứ tự spec mục 4

1. **Root.** `root` rỗng nghĩa là quét mọi knowledge root. Có `root`: `require_read(root)`, rồi phải trùng một knowledge root, không thì `invalid_input` (ví dụ thư mục con của root).
2. **Khoá.** `data_dir.mkdir(parents=True, exist_ok=True)`, rồi toàn bộ phần còn lại chạy trong `writer_lock(data_dir)`. Khoá bận thì để nguyên `ToolError` `indexer_busy` của `store.py` đi ra.
3. **Mở catalog.** `connect` + `migrate`.
4. **Đồng bộ bảng `roots`** với mọi knowledge root, kể cả khi có `root`:
   - Thêm root mới. Mỗi lần chạy, đặt lại `sensitivity` từ `settings["sensitivity"]` (khoá so sánh sau `normcase(normpath)`, mặc định `normal`).
   - Root không còn trong cấu hình: mọi file của nó thành `deleted` và được cộng vào `deleted`.
5. **`full=True`.**
   - Xoá mọi `contents` cùng `chunks`, FTS của chúng, và `store.drop()`.
   - File `indexed` chuyển về `pending`. Cache md vẫn giữ, nên bước trích chỉ đọc cache, không gọi markitdown.
6. **Quét.** Với mỗi root đích:
   - Thư mục không tồn tại (ổ rút ra, OneDrive chưa mount): `errors += 1` và **không** gọi `reconcile`. Lý do: `reconcile` sẽ đánh dấu xoá mọi file của root.
   - Còn lại: `reconcile(conn, root_id, root, perms, settings, extractor_version())`, cộng `ScanStats` vào output (`scanned = seen`).
   - `progress("scan", i, n_roots)` sau mỗi root.
7. **Trích.** Mỗi file `pending` (cả root không quét lần này), theo `file_id`:
   - `content_hash` đã có trong `contents` với `extractor_version` hiện tại (file trùng vừa trích): chỉ đổi thành `indexed`.
   - `extract(...)` trả `SkipResult`: `skipped` + `reason_code`, `skipped += 1`.
   - Bất kỳ `Exception` nào: `attempts += 1`; tới `MAX_ATTEMPTS` thì `error`, không thì vẫn `pending`; `errors += 1`. File `error` không được thử lại cho tới khi file đổi (scanner reset `attempts`).
   - `ExtractResult`:
     - Có `contents` cũ của hash này (khác version): xoá FTS, chunks, contents và vector của nó trước.
     - Sau đó `chunk_markdown`, ghi `contents`, `chunks`, `fts.index_chunks`, file thành `indexed` (`reason_code` rỗng).
     - `edges.link_references(file_id, markdown)`. `extracted += 1`.
   - `commit` sau mỗi file, để crash giữa chừng không mất phần đã làm. `progress("extract", i, n_pending)`.
   - `extracted` đếm số content hash được chunk, không phải số file. Hai file giống nhau là `extracted == 1`.
8. **Cạnh.**
   - `edges.link_generated_from` cho mỗi file vừa thành `indexed` ở bước 7. Không chạy cho cả catalog, để giữ mục tiêu 10k file dưới 60 giây.
   - Xoá cạnh có `src` hoặc `dst` là file `deleted`.
9. **GC.** `contents` không còn file nào khác `deleted` trỏ tới: xoá FTS, chunks, contents và vector (nếu có store). Cache md giữ nguyên (rẻ, file có thể quay lại).
10. **Embed.**
    - `embedder is None`: `embed_skipped_reason = "no_embedder"`.
    - Bảng vector của model chưa có (`not store.exists()`, ví dụ người dùng xoá `vectors/`): coi mọi `contents` là chưa embed.
    - Mỗi content có `embedded_at IS NULL` hoặc `embed_model` khác `embedder.model`:
      - Embed các chunk theo `ordinal`, `store.upsert`, cập nhật `embed_model` và `embedded_at`, rồi commit.
      - `embedded += 1`, `progress("embed", i, n)`.
    - `ToolError` từ embedder: dừng embed. `embed_skipped_reason = details.get("reason", code)`, ví dụ `ollama_unreachable`. Không tính vào `errors`: index vẫn tìm được bằng từ khoá.
    - Cuối cùng `store.optimize()`.
11. **Output.** `duration_s` dùng `time.monotonic()`.

### `status`

- Không lấy khoá. Đọc bằng `connect(..., readonly=True)`.
- `catalog.db` chưa có: `roots=[]`, `files_by_status={}`, `chunks=0`, và không tạo file nào trừ có thể `indexer.lock`.
- `roots`: sắp theo `path`. `files` đếm file khác `deleted`. `last_scan` rỗng khi NULL.
- `files_by_status`: đếm mọi trạng thái có mặt.
- `embed_model = settings.get("embed_model", DEFAULT_EMBED_MODEL)`.
- `indexer_busy`: thử `writer_lock(data_dir)` rồi nhả ngay. Bận thì True.
  - Cửa sổ thử rất ngắn. Một `reindex` bắt đầu đúng lúc đó sẽ nhận `indexer_busy` và người dùng chạy lại. Chấp nhận được, đơn giản hơn file pid.

## 4. Nối vào `tool.py` (chỉ `status`, `reindex`)

```text
_embedder(ctx) = OllamaEmbedder(settings.get("ollama_url", "http://127.0.0.1:11434"),
                                settings.get("embed_model", "bge-m3"), ctx.permissions)
status(inp)  -> indexer.status(ctx, ollama_available=_embedder(ctx).ping())
reindex(inp) -> indexer.reindex(ctx, _embedder(ctx), inp.root, inp.full, progress=<cli: stderr>, config=None)
```

- `ollama_url` không phải loopback: `check_loopback` ném `invalid_input` ngay. Đúng ý, vì đó là lỗi cấu hình.
- **Tiến độ.** Core chưa có API tiến độ. Khi `ctx.channel == "cli"`, ghi một dòng `"{stage} {done}/{total}"` ra **stderr**, để stdout `--json` vẫn sạch. Kênh khác không ghi gì.
  - Đây là quyết định tạm, mức thấp. Khi core có hook tiến độ thì chuyển sang hook đó.
- Docstring của hai operation (thành description MCP) nói rõ: `reindex` chỉ đọc file của người dùng và chỉ ghi vào `data_dir`.
- Thêm ít nhất 2 test cho tool, đặt cùng `test_indexer.py` hoặc trong `test_tool.py`:
  - `status` với `ollama_url` trỏ vào một cổng loopback đang đóng: `ollama_available is False`.
  - `reindex` qua `KnowledgeTool` với cùng cấu hình đó: `embed_skipped_reason == "ollama_unreachable"`, `extracted > 0`.
  - Cô lập cấu hình bằng `monkeypatch.setenv("LFMAP_CONFIG", str(tmp_path / "config.toml"))`, như `packages/lfmap-core/tests/conftest.py`. Context cần có `network=True` trong `PermissionManager`.

## 5. Xong khi

- 23 test chuẩn bị và các test tool mới đều xanh. `uv run pytest` toàn bộ xanh. Ruff sạch.
- Không thêm dependency.
- CHANGELOG có mục cho K9, nêu cách báo tiến độ tạm qua stderr.
- PR `knowledge: incremental reindex and status (TC-K9)` không phải draft, CI Windows và CodeQL xanh.

## 6. Chuẩn bị sẵn

- Test đã chạy xanh (23/23, khoảng 28 giây) trên một bản cài thử theo đúng API trên, trên `main` 538f709 (Linux, Python 3.12). Bản cài thử không commit, Claude Code tự viết code.
- Nhánh: phiên Cloud tự tạo, tách từ `main`.
- Không đụng file của K12 (`catalog.py`). Nếu #32 merge trước thì chỉ cần rebase `CHANGELOG.md`.

**Chạy thật trên DIEP-ANH sau khi PR merge (Local, khoảng 10 phút, Hùng tự chạy hoặc qua Remote Control):**

```powershell
cd D:\Development\lfmap
git switch main; git pull
uv sync                                   # đóng app Claude trước nếu lfmap.exe bị khoá
# config.toml: [paths] knowledge = ['D:\Tmp\kb-test'] (thư mục nhỏ, 5–20 file PDF/DOCX, không nhạy cảm)
uv run lfmap knowledge status --json
uv run lfmap knowledge reindex --json     # lần 1: extracted > 0, embedded > 0 nếu Ollama chạy
uv run lfmap knowledge reindex --json     # lần 2: extracted = 0, embedded = 0
Remove-Item -Recurse "$env:LOCALAPPDATA\lfmap\knowledge\vectors"
uv run lfmap knowledge reindex --json     # embedded = số content, extracted = 0
```

Dán ba output JSON vào thread để Claude kiểm.

## 7. Prompt cho Claude Code (Cloud, repo lfmap)

```text
/plan Đọc docs/handoff/2026-10-22-knowledge-k9-plan.md và docs/specs/knowledge.md (mục 3, 4, TC-K9), rồi đọc packages/lfmap-knowledge/src/lfmap_knowledge/{store,scanner,extract,chunker,fts,vectors,edges,tool,schemas}.py. Chép docs/handoff/prep/2026-10-22-k9/test_indexer.py sang packages/lfmap-knowledge/tests/test_indexer.py, xác nhận nó đỏ vì thiếu module, rồi lập kế hoạch cài src/lfmap_knowledge/indexer.py và nối status/reindex vào tool.py theo đúng API đã chốt (không thêm dependency, không đụng 5 operation còn lại). Chỉ sửa test khi sai rõ ràng và ghi lý do vào PR. Hỏi lại nếu có điểm không khớp với codebase.
```

## 8. Sau K9

- **K10 + K11 (Cloud, Claude review bắt buộc).** `search.py`, nối `search`, `get_context`, `search_files`, `get_file`, `related` vào `tool.py`, lọc root `secret` ở kênh `mcp`/`rest`, ghi `egress_log`.
- **K14 (Local).** Dùng lại thư mục thử ở mục 6.

## 9. Cập nhật tài liệu dự án

- `05_Roadmap.md`, Phase 1, dòng 1.4: "22/10: K8, K13 merge; K9 theo `docs/handoff/2026-10-22-knowledge-k9-plan.md` (Cloud), chạy thật trên DIEP-ANH sau merge."
- Không có ADR mới. Báo tiến độ qua stderr ở kênh `cli` là quyết định tạm mức thấp (Claude), ghi trong CHANGELOG.
