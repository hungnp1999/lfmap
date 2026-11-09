<!-- Copy of the project file 02_Plugin_Contract.md (v0.1.1), kept in the repo so Cloud sessions can read it. The project file stays the source; update both when the contract changes (Plugin Contract v0.2 is #192). -->

# LFMAP Plugin Contract v0.1.1

_2026-10-18: cập nhật theo lfmap-core 0.1.0 (Phase 0) và ADR-014. Thay đổi xem §8._

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
min_core_version = "0.1.0"

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
rest = true                       # adapter REST có từ Roadmap 1.3; lfmap-core mặc định false
events = false

[dependencies.licenses]           # kiểm tra tự động bởi CI
allowed = ["MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC", "PSF-2.0"]
```

## 3. Interface trong lfmap-core

```python
# packages/lfmap-core/src/lfmap_core/tool.py
from typing import Any, ClassVar
from pydantic import BaseModel

class ToolContext(BaseModel):
    """Injected by the runtime: permissions, logger, config, cancellation."""
    plugin_id: str
    dry_run: bool = False
    permissions: Any = None   # PermissionManager; logger, settings… later

class Tool:
    manifest_path: ClassVar[str] = "lfmap.toml"

    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx

    def health(self) -> dict:
        """Return dependency status (e.g. backend installed, model reachable)."""
        return {"ok": True}
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
| REST | operations → FastAPI routes | `POST /tools/<plugin>/<operation>`, OpenAPI tự sinh |
| Events (Phase 2) | operations → subscriber | nhận `<plugin>.<operation>.requested`, phát `.completed` / `.failed` |

Lệnh khởi chạy:

```powershell
lfmap markitdown convert --path .\a.pdf     # CLI
lfmap serve mcp --plugins markitdown         # MCP server (stdio)
lfmap serve rest --port 8765                 # REST server cho mọi plugin (Roadmap 1.3, chưa có)
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
- [ ] Chạy được qua cả CLI, MCP (thử bằng một MCP client thật), REST
- [ ] `health()` báo đúng khi thiếu dependency
- [ ] CI kiểm tra giấy phép dependency pass
- [ ] README dạng trang sản phẩm: dùng để làm gì, cài đặt, 3 ví dụ (CLI/SDK/MCP), giới hạn
- [ ] CHANGELOG và version SemVer

## 8. Thay đổi v0.1 → v0.1.1 (2026-10-18)

1. `lfmap.toml` nằm trong `src/lfmap_<name>/` (lfmap-core đọc bằng `importlib.resources`, nên manifest phải đi kèm package).
2. Tên tool MCP `<plugin>_<operation>` (ADR-014).
3. `ToolContext` có trường `permissions`; `default_context` import từ `lfmap_core.runtime`.
4. Entry point phải trùng plugin id; mọi `[[operations]]` phải khớp các method `@operation` (lệch thì plugin bị bỏ qua, có warning).
5. Chưa quy định: adapter lấy giá trị `${input_dir}` / `${output_dir}` từ đâu. lfmap-core 0.1.0 chưa truyền biến nào từ CLI/MCP, nên manifest có biến sẽ báo `invalid_input`. Cần chốt trong Module Spec của plugin `markitdown` (Roadmap 1.1).

## 9. Thay đổi 2026-10-22 (ADR-020)

1. `[[operations]]` có thể khai `min_tier` (T0–T2, phải thấp hơn tầng của `side_effects`). Khi đó Tool cài classmethod `call_tier(operation, inp, settings)` trả tầng của lời gọi, chỉ đọc từ settings người dùng. lfmap-core kẹp kết quả trong [`min_tier`, tầng gốc]; lỗi hoặc giá trị lạ thì dùng tầng gốc. Hiện chỉ `powershell.run` dùng (`min_tier = "T1"`).
