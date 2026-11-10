<!-- Copy of the project file 02_Plugin_Contract.md, kept in the repo so Cloud sessions can read it. The project file stays the source; update both when the contract changes. v0.2 (#192) was written in this repo and describes lfmap-core 0.2.0; the owner copies it to the project file. -->

# LFMAP Plugin Contract v0.2

_2026-11-10: khớp lfmap-core 0.2.0 (events, flows, jobs đọc như flow, `principal`). Chỉ mô tả cái đã có trong code; phần chưa có code ghi rõ là "dự kiến". Thay đổi xem §8, §9, §14._

**Cam kết tương thích.** Plugin viết theo v0.1.1 vẫn nạp và chạy trên lfmap-core 0.2.0 mà không sửa gì. Bài kiểm tra `packages/lfmap-core/tests/test_plugin_compat.py` chạy một plugin đóng băng (`tests/fixtures/frozen_plugin_v011/`) qua nạp, SDK, CLI, MCP, flow và quyền ghi. Test đỏ nghĩa là sửa lfmap-core, không sửa fixture.

Mọi Tool trong LFMAP là một plugin tuân thủ hợp đồng này. Mục tiêu: viết logic **một lần**, có CLI + SDK + MCP + REST **miễn phí**, và có thể đóng gói như một sản phẩm độc lập.

## 1. Cấu trúc thư mục một plugin

```text
plugins/lfmap-markitdown/
├── pyproject.toml             # package Python, khai báo entry point
├── README.md                  # dùng như trang sản phẩm
├── LICENSE                    # Apache-2.0
├── CHANGELOG.md
├── src/lfmap_markitdown/
│   ├── lfmap.toml             # manifest (nằm trong package để đi kèm wheel)
│   ├── __init__.py            # export public SDK
│   ├── schemas.py             # Pydantic Input/Output
│   ├── tool.py                # class Tool — logic nghiệp vụ
│   └── backends/              # markitdown, docling…
└── tests/
    ├── test_tool.py
    └── fixtures/
```

## 2. Manifest — `lfmap.toml`

```toml
[plugin]
id = "markitdown"                 # duy nhất, kebab-case; trùng tên entry point
name = "MarkitdownTool"
version = "0.1.0"                 # SemVer
description = "Convert documents (PDF, DOCX, PPTX, XLSX, HTML) to Markdown."
license = "Apache-2.0"
authors = ["<tên bạn>"]
min_core_version = "0.1.0"        # đặt "0.2.0" nếu dùng events hoặc call_tier (§10, §3)

[plugin.entrypoint]
module = "lfmap_markitdown.tool"
class = "MarkitdownTool"

[[operations]]
name = "convert"                  # → CLI: lfmap markitdown convert
                                  # → MCP: markitdown_convert (ADR-014)
                                  # → REST: POST /tools/markitdown/convert
input = "lfmap_markitdown.schemas:ConvertInput"
output = "lfmap_markitdown.schemas:ConvertOutput"
side_effects = "none"             # none | local_write | external
# min_tier = "T1"                 # tùy chọn (ADR-020): plugin hạ tầng từng lời gọi theo config người dùng, không thấp hơn giá trị này

[permissions]
fs_read = ["${input_dir}"]
fs_write = ["${output_dir}"]
network = false
exec = []
cloud_ai = false

[adapters]
cli = true
mcp = true
rest = true                       # cờ có trong schema; lfmap-core 0.2.0 chưa có adapter REST (mặc định false)
events = false                    # true: plugin được dùng ctx.events và nhận <plugin>.<op>.requested (§10)

[dependencies.licenses]           # kiểm tra tự động bởi CI
allowed = ["MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC", "PSF-2.0"]
```

## 3. Interface trong lfmap-core

```python
# packages/lfmap-core/src/lfmap_core/tool.py
from typing import Any, ClassVar
from pydantic import BaseModel


class ToolContext(BaseModel):
    """Injected by the runtime."""

    plugin_id: str
    dry_run: bool = False
    permissions: Any = None  # PermissionManager
    data_dir: Path | None = None  # thư mục riêng của plugin; ghi vào đây không phải side effect (ADR-016)
    temp_dir: Path | None = None
    settings: dict[str, Any] = {}  # [plugins.<id>.settings] trong config.toml của người dùng
    channel: Channel = "sdk"  # sdk | cli | mcp | rest | job | event | flow
    approver: Any = None  # cổng phê duyệt; None khi dùng SDK thuần
    event_publisher: Any = None  # chỉ có khi manifest [adapters] events = true

    @property
    def events(self) -> Any: ...  # PluginEvents; permission_denied nếu plugin chưa bật events

    def require_approval(self, reason: str, detail: str = "", *, destination: str = "", data: str = "normal") -> None:
        """Nâng cấp lời gọi trước khi làm: T3 nếu reason == "external", ngược lại T2 (ghi đè, đổi tên, xóa)."""


class Tool:
    manifest_path: ClassVar[str] = "lfmap.toml"

    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx

    def health(self) -> dict:
        """Return dependency status (e.g. backend installed, model reachable)."""
        return {"ok": True}

    @classmethod
    def call_tier(cls, operation: str, inp: BaseModel, settings: dict[str, Any]) -> str | None:
        """ADR-020: chỉ cần khi operation khai min_tier. None giữ tầng đã khai."""
        return None
```

Mỗi operation là một method nhận đúng một Pydantic Input và trả về một Pydantic Output:

```python
# plugins/lfmap-markitdown/src/lfmap_markitdown/tool.py
from lfmap_core import Tool, operation
from .schemas import ConvertInput, ConvertOutput


class MarkitdownTool(Tool):
    @operation("convert")
    def convert(self, inp: ConvertInput) -> ConvertOutput:
        self.ctx.permissions.require_read(inp.path)
        ...
```

Plugin gọi plugin khác trong cùng tiến trình bằng SDK, với quyền của bên gọi: `lfmap_core.runtime.context_for(plugin_id, parent_ctx)`. Không gọi nhau qua CLI hay MCP.

Hàm tiện lợi cho dùng như SDK thuần:

```python
# src/lfmap_markitdown/__init__.py
from lfmap_core.runtime import default_context
from .tool import MarkitdownTool
from .schemas import ConvertInput, ConvertOutput


def convert(inp: ConvertInput) -> ConvertOutput:
    return MarkitdownTool(default_context("markitdown")).convert(inp)
```

## 4. Discovery

Plugin đăng ký qua Python entry point; lfmap-core quét entry point khi khởi động:

```toml
# pyproject.toml của plugin
[project.entry-points."lfmap.plugins"]
markitdown = "lfmap_markitdown.tool:MarkitdownTool"
```

## 5. Adapter sinh tự động

| Adapter | Sinh từ | Quy ước |
|---|---|---|
| CLI | operations + Input schema → Typer options | `lfmap <plugin> <operation> [--field value]`, `--json` để in Output dạng JSON |
| MCP | operations → MCP tools, Input schema → JSON Schema | tên `<plugin>_<operation>` (`-` trong plugin id đổi thành `_`, ≤ 64 ký tự, ADR-014), description lấy từ docstring |
| REST | operations → FastAPI routes | **chưa có trong lfmap-core 0.2.0** (chỉ cờ `rest` trong manifest); dự kiến `POST /tools/<plugin>/<operation>` |
| Events | operations → subscriber, chỉ khi `[adapters] events = true` | nhận `<plugin>.<operation>.requested`, phát `.completed` / `.failed` (§10) |
| Flows | operations → bước `call = "<plugin>.<operation>"` | không cần cờ nào; xem §11 |

Lệnh khởi chạy:

```powershell
lfmap markitdown convert --path .\a.pdf     # CLI
lfmap serve mcp --plugins markitdown         # MCP server (stdio)
lfmap events run --until-idle                # chạy handler sự kiện (không có daemon)
lfmap flows start <id>                       # chạy một flow
lfmap serve rest --port 8765                 # chưa có trong lfmap-core 0.2.0
```

## 6. Quy ước lỗi

Mọi lỗi nghiệp vụ là `ToolError(code, message, details)`; adapter tự ánh xạ:
- CLI → exit code ≠ 0, thông báo tiếng Anh ngắn
- MCP → tool result `isError: true`
- REST → HTTP 4xx/5xx với body JSON `{code, message, details}`

Mã lỗi chuẩn: `invalid_input`, `permission_denied`, `not_found`, `backend_unavailable`, `timeout`, `internal`.

## 7. Definition of Done cho một plugin

- [ ] `lfmap.toml` hợp lệ, khai báo đủ quyền
- [ ] Input/Output là Pydantic, có docstring và ví dụ
- [ ] Test unit cho mọi operation, chạy được trên Windows
- [ ] Chạy được qua CLI và MCP (thử bằng một MCP client thật); REST khi adapter có
- [ ] `health()` báo đúng khi thiếu dependency
- [ ] CI kiểm tra giấy phép dependency pass
- [ ] README dạng trang sản phẩm: dùng để làm gì, cài đặt, 3 ví dụ (CLI/SDK/MCP), giới hạn
- [ ] CHANGELOG và version SemVer; đổi tên hay bỏ trường Output là thay đổi phá vỡ (§11)
- [ ] Dùng events: operation idempotent, chỉ phát topic `<plugin-id>.…`, payload là tham chiếu (§10)
- [ ] Output nhỏ (dưới 64 KiB), ưu tiên đường dẫn và id hơn văn bản tài liệu (§11)
- [ ] Khai `min_core_version` đúng khi dùng tính năng mới (§12)

## 8. Thay đổi v0.1 → v0.1.1 (2026-10-18)

1. `lfmap.toml` nằm trong `src/lfmap_<name>/` (lfmap-core đọc bằng `importlib.resources`, nên manifest phải đi kèm package).
2. Tên tool MCP `<plugin>_<operation>` (ADR-014).
3. `ToolContext` có trường `permissions`; `default_context` import từ `lfmap_core.runtime`.
4. Entry point phải trùng plugin id; mọi `[[operations]]` phải khớp các method `@operation` (lệch thì plugin bị bỏ qua, có warning).
5. (Đã giải quyết, xem §12.) Khi viết v0.1.1 chưa quy định adapter lấy `${input_dir}` / `${output_dir}` từ đâu.

## 9. Thay đổi 2026-10-22 (ADR-020)

1. `[[operations]]` có thể khai `min_tier` (T0–T2, phải thấp hơn tầng của `side_effects`). Khi đó Tool cài classmethod `call_tier(operation, inp, settings)` trả tầng của lời gọi, chỉ đọc từ settings người dùng. lfmap-core kẹp kết quả trong [`min_tier`, tầng gốc]; lỗi hoặc giá trị lạ thì dùng tầng gốc. Hiện chỉ `powershell.run` dùng (`min_tier = "T1"`).

## 10. Sự kiện (`ctx.events`), nguồn: `docs/specs/events.md`

Chỉ plugin có `[adapters] events = true` được dùng. Không bật thì `ctx.events` ném `permission_denied`.

**Phát.** `ctx.events.publish(topic, payload)`; `source` luôn là id plugin, plugin không tự đặt.
- Topic: 2 đến 8 token nối bằng dấu chấm, bắt đầu bằng `<plugin-id>.`, token gồm `a-z 0-9 _ -`, tối đa 200 ký tự. Ví dụ `email.message.received`.
- Không được phát `<plugin>.<operation>.requested|completed|failed`. Ba topic này chỉ core phát. Vi phạm là `permission_denied`.
- Payload: object JSON, khóa chuỗi, không NaN/Infinity, tối đa 65 536 byte UTF-8. Mang tham chiếu (đường dẫn, id, số đếm), không mang nội dung tài liệu hay bí mật.
- Trong lúc adapter chạy một lời gọi, sự kiện plugin phát tiếp nối chuỗi (`correlation_id`, `causation_id`) của request.
- `publish` không chạy handler. Plugin không tự đăng ký handler; plugin nhận việc bằng cách có operation được gọi qua `.requested`.

**Nhận.** Core giữ subscription bền `adapter-<plugin-id>` với pattern `<plugin-id>.*.requested`. Request do core phát, payload `{"input": {...}}`, thêm `"job": "<id>"` nếu có. Adapter kiểm tra Input, chạy operation trên kênh `event` rồi phát:
- `.completed` với `{"request_id", "output"}`, hoặc `{"request_id", "output": null, "output_too_large": true}` khi Output vượt giới hạn payload.
- `.failed` với `{"request_id", "error": {code, message, details}}` khi operation ném `ToolError`. Lỗi nghiệp vụ không được thử lại.

**Ngữ nghĩa giao nhận.** Ít nhất một lần (at-least-once): sau khi crash hoặc lease hết hạn (60 giây) cùng một request có thể chạy hai lần, `event.id` giữ nguyên. **Operation của plugin bật events phải idempotent** (chạy lại không gây hại: ghi cùng đường dẫn đích, bỏ qua việc đã làm). Ngoại lệ không phải `ToolError` thoát khỏi adapter được thử lại với chờ 2, 4, 8… giây (tối đa 300), tối đa 5 lần, rồi thành dead letter (`lfmap events dead`, `lfmap events retry` ở TTY).

**Tầng.** Lời gọi trên kênh `event` không bao giờ hỏi ai. Tầng của nó bị chặn bởi `[events] max_tier` trong config.toml (0 hoặc 1, mặc định 0). Vượt trần thì lời gọi thành một proposal trong hàng đợi phê duyệt để người duyệt ở TTY. Plugin không thể kích hoạt operation của plugin khác bằng sự kiện.

**Không có daemon.** Handler chỉ chạy khi một tiến trình drain: `lfmap events run` hoặc cuối `lfmap jobs run`. Độ trễ là "lần drain kế tiếp".

## 11. Flows và jobs, nguồn: `docs/specs/flows.md` (gồm §13)

Mọi operation đều dùng được làm bước flow, không cần khai gì thêm: `call = "<plugin>.<operation>"` trong `flows.toml`.

**Output là giao diện công khai.** Bước sau tham chiếu Output của bước trước bằng `${steps.<id>.output.<khóa>}`, và trigger sự kiện bằng `${trigger.payload.<khóa>}` (payload của sự kiện, ví dụ `output.path` của một `.completed`). Hệ quả cho tác giả plugin:
- Đổi tên hay bỏ một trường Output làm hỏng flow của người dùng. Coi đó là thay đổi phá vỡ (tăng MAJOR, hoặc MINOR khi còn ở 0.x, và ghi trong CHANGELOG).
- Output đã lưu bằng `model_dump(mode="json")`, tối đa 64 KiB, vượt thì bước lỗi `internal` với `reason: output_too_large`. Ưu tiên operation ghi file và trả đường dẫn (như `markitdown.export`) hơn operation trả nguyên văn bản (như `markitdown.convert`).
- Giá trị tham chiếu được thay vào Input rồi kiểm tra bằng Input model của operation lúc chạy. Input không có tham chiếu được kiểm tra sớm bởi `lfmap flows check`.
- Đường dẫn trong Input vẫn phải qua `PermissionManager.require_read/require_write` trong plugin; Flows không đụng file.

**Kênh và tầng.** Bước chạy trên kênh `flow`, không bao giờ hỏi ai. Trần là `max_tier` của flow (0 hoặc 1, không cao hơn). Tầng của lời gọi gồm cả `call_tier` (§3, ADR-020). Vượt trần, hoặc bước `approve`, thì run dừng sau một proposal `flows.resume` (T2) mà người duyệt ở TTY bằng `lfmap approvals approve`; run lưu ở `%LOCALAPPDATA%\lfmap\flows\runs\` và tiếp tục ở tiến trình mới. Flow không tự duyệt, không nâng trần, không khởi động flow khác. Bước lỗi `ToolError` thì run `failed`, không tự thử lại.

**Jobs.** `jobs.toml` vẫn hợp lệ và không bị ghi lại; mỗi job được đọc như một flow một bước (id bước `run`) và chạy bằng cùng bộ chạy flow trên kênh `flow` (kênh `job` chỉ còn trong dòng audit và proposal cũ). Tác giả plugin không phải đổi gì: tầng, `max_tier`, hàng đợi phê duyệt và tên task `\LFMAP\<id>` giữ nguyên. Job `via = "event"` đi qua request/answer của §10 và đòi `[adapters] events = true`.

## 12. Danh tính (`principal`), biến đường dẫn, phát hiện

**`principal`** (PR #209). Mỗi dòng `audit.jsonl`, mỗi grant và mỗi proposal ghi `principal`, hiện luôn là `owner` (`lfmap_core.config.PRINCIPAL`). Bản ghi cũ không có trường này được đọc là `owner`. Core ghi trường này; `ToolContext` chưa có trường `principal` và plugin không đặt nó. Mã mới không được giả định chỉ có một người dùng khi lưu dữ liệu: thêm người dùng sau này chỉ thêm giá trị, không đổi cấu trúc.

**Biến trong `[permissions]`.** Adapter lấy `${...}` từ config.toml của người dùng: mục `[paths]` (giá trị là một đường dẫn hoặc danh sách), cộng hai biến có sẵn `${data_dir}` (`%LOCALAPPDATA%\lfmap\<plugin-id>`) và `${temp_dir}` (`<data_dir>\tmp`). Biến không có trong `[paths]` thì không cấp quyền nào. Thư mục chỉ đến từ config.toml; không operation nào ghi file này.

**Nạp và tương thích.** `registry.load_entry` đọc manifest cạnh module của Tool, kiểm `min_core_version` (`invalid_input`, details `{plugin, min_core_version, core_version}`) và kiểm tập `[[operations]]` bằng tập method `@operation`; lệch thì plugin bị bỏ qua kèm cảnh báo. Manifest chặt (`extra = "forbid"`): khóa mà core không biết làm manifest bị từ chối với lỗi schema, không phải lỗi phiên bản. Vì vậy khi dùng tính năng mới, hãy đặt `min_core_version` và cập nhật lfmap-core trước.

## 13. Truy cập model: dự kiến, chưa có trong code

Spec: `docs/specs/model-client.md` (PR #216, chỉ tài liệu). lfmap-core 0.2.0 **chưa có** `ctx.models`, khóa manifest `[adapters] models` (manifest có khóa này hiện bị từ chối), `ModelClient`, `[models]` trong config.toml hay plugin `llm`. Mục này không thuộc điều kiện phù hợp của v0.2 và sẽ vào v0.3 khi MC-2 hoàn tất. Hướng đã chốt, để tác giả plugin không đi ngược:
- Plugin gọi model qua `ctx.models` (`chat`, `embed`, luôn kèm tên tác vụ); không tự đặt URL hay endpoint. Mặc định loopback; endpoint cloud chỉ khi chủ máy khai tuyến trong config.toml, và mỗi lời gọi là T3, bị từ chối trên `mcp`, `rest`, `job`, `event`, `flow`.
- Plugin cloud cần `[permissions] cloud_ai = true` và `network = true`; `secret` không bao giờ ra ngoài; mỗi lời gọi cloud ghi một dòng `model_call` vào `audit.jsonl`, không có nội dung.
- Cho đến lúc đó, plugin cần model tự nói chuyện với loopback (như `knowledge` với Ollama). Không thêm client thứ ba.

## 14. Thay đổi v0.1.1 → v0.2 (2026-11-10)

1. `ToolContext` có thêm `data_dir`, `temp_dir`, `settings`, `channel`, `approver`, `event_publisher`, thuộc tính `events` và phương thức `require_approval` (§3). Đây là mô tả lại code hiện tại của lfmap-core 0.2.0, không phải thay đổi hành vi của plugin cũ.
2. `Tool.call_tier` và `min_tier` (đã có ở §9 từ 2026-10-22) được đưa vào §3.
3. §10 sự kiện: `ctx.events`, quy tắc phát, request/answer, at-least-once và yêu cầu idempotent, kênh `event`, trần `[events] max_tier`.
4. §11 flows và jobs: Output là giao diện công khai, kênh `flow`, trần tầng, jobs đọc như flow một bước (#190, PR #215).
5. §12 `principal` (#192, PR #209); nguồn của biến `${...}`; luật nạp và `min_core_version`.
6. §13 truy cập model ghi là dự kiến; không có code.
7. Adapter REST ghi đúng hiện trạng: chưa có trong lfmap-core 0.2.0.
8. Kiểm chứng tương thích: `test_plugin_compat.py` với fixture đóng băng.
