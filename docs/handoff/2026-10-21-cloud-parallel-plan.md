# Kế hoạch thực thi: task chạy song song trên Cloud (21/10 tối)

Đi kèm [`2026-10-20-jobs-j1-j4.md`](2026-10-20-jobs-j1-j4.md) (task 1: J1 + J2) và [`2026-10-20-knowledge-k4-k14.md`](2026-10-20-knowledge-k4-k14.md) (task 4: K8). Spec gốc: [`docs/specs/jobs.md`](../specs/jobs.md) TC-J1, TC-J2 và [`docs/specs/knowledge.md`](../specs/knowledge.md) mục 5.4, TC-K8.

Các điểm API mà spec còn để ngỏ đã được chốt dưới đây. Test viết sẵn nằm trong [`prep/2026-10-21-cloud/`](prep/2026-10-21-cloud/). Nếu code hiện tại không khớp với kế hoạch này, dừng lại và hỏi.

## 1. Chọn task

Điều kiện để chạy trên Cloud: Linux thuần, không cần Windows/Office/GPU/Ollama, và không đụng file mà đợt qwen K4–K7 (B4) và bước review B5 sửa (`extract.py`, `chunker.py`, `fts.py`, `embed.py` cùng test của chúng trên `feature/knowledge-k4-k7`).

| Task | Cloud? | Phụ thuộc | Đụng file của K4–K7? | Kết luận |
|---|---|---|---|---|
| **J1 + J2** (job, `lfmap jobs`) | Có. `schtasks` chỉ xuất hiện trong test qua bản giả; CI Windows kiểm lại | Core 0.2 (đã xong) | Không, chỉ `lfmap-core` | **Khuyến nghị 1** |
| **K8** `vectors.py` | Có. LanceDB chạy trên Linux (K0 đã chạy) | Chỉ Protocol `VectorStore` | Không, file mới | **Khuyến nghị 2** |
| K13 phần `edges.py` | Có | Bảng `edges` (K2) | Không | Dự phòng, chưa chuẩn bị |
| J3 | Có | J2 phải merge trước | Không | Ngày mai, bắt buộc Claude review |
| J4 | Một phần (lệnh hệ thống giả được) | J2 | Không | Ngày mai, Hùng chạy thật trên DIEP-ANH |
| K9, K10, K11 | Có | K4–K8 | Có (gọi các module đó) | Chờ B5 |
| K12 `catalog.py` | Thẻ qwen | Đợt qwen sau | Không | Local (thẻ nằm ở `lfmap-tools`), sau B6 |
| B6, K14 | Không cần code / cần máy thật | B5, J1–J4 | | Không |

Thứ tự trong bàn giao jobs ghi J sau K9. Làm J1 + J2 sớm hơn không trái quyết định nào: quyết định #5 chỉ yêu cầu J1–J4 xong trước K14, và J1–J2 không dùng gì của knowledge.

Xung đột duy nhất có thể xảy ra là `CHANGELOG.md` (mục `[Unreleased]`). PR nào merge sau thì rebase và giữ cả hai dòng.

**Hạn mức Pro.** Ước lượng thô: J1 + J2 cỡ M, khoảng một phần ba cửa sổ 5 giờ. K8 cỡ S–M, khoảng một phần năm. Hạn mức tuần vừa reset (21/10, 18:00 giờ VN), và đêm nay Claude không có việc khác vì B4 chạy bằng qwen. Vì vậy chạy song song cả hai được. Nếu cửa sổ 5 giờ đã dùng nhiều thì làm J1 + J2 trước, vì nó mở đường cho J3 và J4 ngày mai.

## 2. Task A: J1 + J2 (Cloud)

- Nhánh: dùng nhánh mà phiên Cloud tự tạo. Đặt tên PR: `jobs: runner script and lfmap jobs list/run/register (TC-J1, TC-J2)`.
- Bước đầu: chép [`prep/2026-10-21-cloud/test_jobs.py`](prep/2026-10-21-cloud/test_jobs.py) sang `packages/lfmap-core/tests/test_jobs.py` và bỏ 2 dòng chú thích đầu file. Test phải đỏ vì thiếu `lfmap_core.jobs`.
- Không sửa `conftest.py`. Chỉ sửa test khi test sai rõ ràng, và ghi lý do từng chỗ vào PR.

### API đã chốt (`packages/lfmap-core/src/lfmap_core/jobs.py`)

```python
def jobs_path() -> Path: ...  # LFMAP_JOBS, otherwise app_dir() / "jobs.toml"
def load_jobs(path: Path | None = None) -> list[Job]: ...  # missing file -> []; any error -> ToolError invalid_input
def run_job(registry: Registry, job_id: str, path: Path | None = None) -> BaseModel: ...
def task_command(job: Job, repo: Path, uv: Path, script: Path) -> list[str]: ...
def delete_command(job_id: str) -> list[str]: ...  # ["schtasks", "/Delete", "/TN", "\\LFMAP\\<id>", "/F"]
def registered_tasks(query_csv: str) -> set[str]: ...  # ids under \LFMAP\ only
def register_commands(jobs: list[Job], existing: set[str], repo: Path, uv: Path, script: Path) -> list[list[str]]: ...
def _schtasks(args: list[str]) -> str: ...  # the only place that runs a process; tests replace it
```

- **Model:** `Job`, `Schedule` và `JobsFile` là pydantic, `extra="forbid"`.
  - `Job.id` theo `^[a-z][a-z0-9-]*$`, không trùng trong file. `input: dict = {}`, `max_tier: Literal[0, 1] = 0`, `enabled: bool = True`.
  - `Schedule` có đúng một trong ba khoá:
    - `daily = "HH:MM"` (00:00–23:59)
    - `weekly = "MON HH:MM"` (MON..SUN)
    - `every_minutes` (1–1439, giới hạn của `schtasks /MO`)
- **`run_job`:**
  - Job không có → `not_found`. Job tắt → `invalid_input`. Plugin hoặc operation không có → `not_found`.
  - Trước khi chạy, gọi approver với `base_tier(side_effects)`, giống `_operation_command` trong `cli.py`.
  - Gọi `run_operation(entry, op, job.input, channel="job", approver=gate)`. `run_operation` phải được import vào `jobs.py` bằng tên, vì test thay nó.
- **Approver tạm (đến khi có J3):** `Gate(plugin, op, "job", Policy(T1="deny", T2="deny", T3="deny"))`, không có `ask`.
  - Nhờ vậy mọi thứ trên T0 bị từ chối và ghi audit với `channel = "job"`.
  - `max_tier` được đọc nhưng chưa có tác dụng. Ghi rõ điều này trong docstring.
- **`task_command`:**
  - Dạng `["schtasks", "/Create", "/TN", "\\LFMAP\\<id>", "/TR", <action>, "/SC", ..., "/F"]`, với `<action>` = `pwsh -NoProfile -File "<script>" -JobId <id> -RepoPath "<repo>" -UvPath "<uv>"`.
  - Theo kiểu lịch:
    - daily → `/SC DAILY /ST HH:MM`
    - weekly → `/SC WEEKLY /D MON /ST HH:MM`
    - every_minutes → `/SC MINUTE /MO n`
- **`register_commands`:** tạo task cho job bật. Xoá task nếu job tắt mà task đang có, hoặc nếu task có mà job đã bỏ khỏi file. Mọi lệnh xoá đều có tiền tố `\LFMAP\`.
- **Truy vấn task:** `_schtasks(["schtasks", "/Query", "/FO", "CSV", "/NH"])`, lọc theo tiền tố bằng `registered_tasks`. Không dùng `/TN "\LFMAP\"`, vì lệnh đó lỗi khi thư mục chưa tồn tại. Nếu không tìm thấy `schtasks` thì báo `backend_unavailable`.

### CLI (`cli.py`, chỉ thêm nhóm `jobs`)

- `lfmap jobs list [--json]`: mỗi dòng gồm `id`, `operation` (`plugin.op`), `schedule` (`daily 07:30`, `weekly MON 07:30` hoặc `every 60 min`) và `enabled`.
- `lfmap jobs run <id> [--json]`: in output của operation như các lệnh sinh tự động. Không có `--yes`.
- `lfmap jobs register [--dry-run] [--repo PATH] [--uv PATH]`:
  - `--repo` mặc định là gốc repo, tính từ `Path(__file__).parents[4]`.
  - `--uv` mặc định theo luật của J1: `shutil.which("uv")`, rồi tới `%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe`, không có thì báo `not_found`.
  - Script là `<repo>\scripts\Invoke-LfmapJob.ps1`.
  - `--dry-run` chỉ truy vấn rồi in từng lệnh (`subprocess.list2cmdline`). Không có `--dry-run` thì chạy từng lệnh qua `_schtasks`.

### J1: script và tài liệu

- `scripts/Invoke-LfmapJob.ps1` theo đúng TC-J1 trong spec. Thêm hai tham số `-RepoPath` và `-UvPath`, vì `task_command` truyền chúng.
- Container Cloud không có `pwsh`, nên không chạy thử script ở đây. Hùng chạy thử trên DIEP-ANH (mục 4).
- `docs/jobs.md`:
  - Mẫu `jobs.toml`.
  - Cách chạy tay script.
  - `register --dry-run`.
  - Cách bật "Run whether user is logged on" trong Task Scheduler. CLI không nhận mật khẩu.
  - Ghi chú rằng job trên T0 bị từ chối cho tới khi có J3.

### Xong khi

- `uv run pytest` xanh, gồm 32 test mới. Không test nào chạy `schtasks` thật. Ruff sạch.
- `uv run lfmap jobs register --dry-run --uv /usr/bin/true` in đúng lệnh cho cả 3 kiểu lịch, với một `jobs.toml` mẫu đặt qua `LFMAP_JOBS`.
- CHANGELOG có mục cho J1 và J2.
- PR không phải draft, CI Windows và CodeQL xanh. Đây là PR code, nên merge theo quy tắc repo, không áp quy tắc tự merge của PR tài liệu.

### Prompt cho Claude Code (Cloud, repo lfmap)

```text
/plan Đọc docs/handoff/2026-10-21-cloud-parallel-plan.md mục 2, docs/handoff/2026-10-20-jobs-j1-j4.md và docs/specs/jobs.md (TC-J1, TC-J2), cùng cli.py, runtime.py, approval.py của lfmap-core. Chép docs/handoff/prep/2026-10-21-cloud/test_jobs.py sang packages/lfmap-core/tests/test_jobs.py, xác nhận nó đỏ vì thiếu module, rồi lập kế hoạch cài jobs.py, nhóm lệnh `lfmap jobs`, scripts/Invoke-LfmapJob.ps1 và docs/jobs.md theo đúng API đã chốt. Không sửa conftest.py; chỉ sửa test khi sai rõ ràng và ghi lý do vào PR. Hỏi lại nếu có điểm không khớp với codebase.
```

## 3. Task B: K8 `vectors.py` (Cloud)

- Nhánh: dùng nhánh mà phiên Cloud tự tạo, tách từ `main` (không tách từ `feature/knowledge-k4-k7`). Đặt tên PR: `knowledge: LanceDB vector store (TC-K8)`.
- Bước đầu: chép [`prep/2026-10-21-cloud/test_vectors.py`](prep/2026-10-21-cloud/test_vectors.py) sang `packages/lfmap-knowledge/tests/test_vectors.py` và bỏ 2 dòng chú thích đầu file. Test phải đỏ vì thiếu module.

### API đã chốt (`packages/lfmap-knowledge/src/lfmap_knowledge/vectors.py`)

```python
ANN_INDEX_MIN_ROWS = 50_000  # K0 result: build the ANN index from about 50k vectors


def model_slug(model: str) -> str: ...  # lower case, every run of non [a-z0-9] -> "_", stripped


class LanceVectorStore:  # implements VectorStore (spec 5.4)
    def __init__(self, path: Path, table: str) -> None: ...  # opens nothing yet
    def exists(self) -> bool: ...
    def count(self) -> int: ...
    def has_index(self) -> bool: ...
    def upsert(self, chunk_ids: list[int], content_hashes: list[str], vectors: list[list[float]]) -> None: ...
    def delete_content(self, content_hash: str) -> None: ...
    def search(self, vector: list[float], limit: int) -> list[tuple[int, float]]: ...  # best first
    def vector_of(self, chunk_ids: list[int]) -> list[list[float]]: ...  # input order
    def drop(self) -> None: ...
    def optimize(self) -> None: ...
```

- **Mở lười.** Hàm khởi tạo không tạo thư mục. Thư mục và kết nối chỉ được tạo ở lần `upsert` đầu tiên. Khi chưa có bảng:
  - `exists()` trả False, `search` trả `[]`, `vector_of([])` trả `[]`.
  - `delete_content` và `drop` không làm gì.
- **Schema:** `chunk_id: int64`, `content_hash: string`, `vector: fixed_size_list<float32>[dim]`.
  - `dim` lấy từ lần `upsert` đầu. Sai chiều hoặc ba danh sách khác độ dài → `invalid_input`.
- **`upsert`:** thay thế theo `chunk_id` (`merge_insert("chunk_id")`).
- **Khoảng cách:** cosine, score = `1 - _distance`.
  - Khi chưa có index, tìm vét cạn: score của chính vector đó ≈ 1.
  - Khi có index, test chỉ yêu cầu đúng thứ hạng.
- **`delete_content`:** kiểm `content_hash` khớp `^[0-9a-f]{64}$` trước khi đưa vào chuỗi lọc `where`, không thì `invalid_input`. Lý do: chuỗi lọc của LanceDB là biểu thức SQL.
- **`vector_of`:** id không có → `not_found`.
- **`drop`:** chỉ xoá bảng của model này, không xoá cả thư mục `vectors/`.
- **`optimize`:**
  - Nếu `count() >= ANN_INDEX_MIN_ROWS` và chưa có index: tạo index vector `IVF_HNSW_SQ`, cosine, bằng API mới (`config=...`), vì cách gọi cũ với `metric=` đã bị đánh dấu deprecated ở 0.40.0.
  - Sau đó luôn gọi `table.optimize()`.
  - Test đặt ngưỡng 600, vì đã thử: LanceDB 0.40.0 dựng được cả 3 loại index với 600 vector 16 chiều.
  - Nếu Claude Code thấy `IVF_PQ` hợp hơn thì được đổi, kèm lý do trong PR.

### Xong khi

- 14 test mới xanh. `uv run pytest` toàn bộ xanh. Ruff sạch.
- Không đổi dependency (`lancedb==0.40.0` đã có).
- Không sửa `tool.py`. K9 sẽ dùng store này.
- CHANGELOG có mục cho K8.
- PR không phải draft, CI Windows và CodeQL xanh.

### Prompt cho Claude Code (Cloud, repo lfmap)

```text
/plan Đọc docs/handoff/2026-10-21-cloud-parallel-plan.md mục 3 và docs/specs/knowledge.md (mục 5.4, TC-K8). Chép docs/handoff/prep/2026-10-21-cloud/test_vectors.py sang packages/lfmap-knowledge/tests/test_vectors.py, xác nhận nó đỏ vì thiếu module, rồi lập kế hoạch cài src/lfmap_knowledge/vectors.py theo đúng API đã chốt (lancedb==0.40.0, không thêm dependency, không sửa tool.py). Chỉ sửa test khi sai rõ ràng và ghi lý do vào PR. Hỏi lại nếu có điểm không khớp với codebase.
```

## 4. Việc Hùng làm trên DIEP-ANH sau khi PR J1 + J2 merge (pwsh)

```powershell
cd D:\Development\lfmap
git switch main; git pull
uv sync                     # close the Claude app first if lfmap.exe is locked
@'
[[jobs]]
id = "echo-hello"
plugin = "echo"
operation = "say"
input = { text = "xin chào" }
schedule = { daily = "07:30" }
'@ | Set-Content "$env:LOCALAPPDATA\lfmap\jobs.toml" -Encoding utf8
pwsh -NoProfile -File .\scripts\Invoke-LfmapJob.ps1 -JobId echo-hello; $LASTEXITCODE   # expect 0
pwsh -NoProfile -File .\scripts\Invoke-LfmapJob.ps1 -JobId khong-co;   $LASTEXITCODE   # expect 1
Get-Content "$env:LOCALAPPDATA\lfmap\logs\jobs-$(Get-Date -Format yyyy-MM-dd).jsonl" -Tail 2
uv run lfmap jobs register --dry-run
```

Chưa chạy `register` thật cho tới khi xong J4 (doctor).

## 5. Đã chốt cho J3

- Hàng đợi đề xuất của job dùng lệnh `lfmap approvals pending` (Hùng đồng ý 2026-10-21). Lệnh `lfmap approvals list` giữ nguyên, tiếp tục liệt kê grants như hiện nay.
