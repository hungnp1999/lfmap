# lfmap-core

Shared runtime and foundational abstractions for LFMAP plugins.

## Purpose

`lfmap-core` provides the shared runtime foundation for LFMAP plugins. It defines the `Tool` base class and `@operation` contract, enforces declarative security boundaries through `PermissionManager` and risk-tiered approval gates (T0–T3), manages plugin discovery, and automatically generates CLI and MCP adapters so plugins remain decoupled from transport protocols.

For the system-wide design, main execution flows, and architecture invariants, see [ARCHITECTURE.md](../../ARCHITECTURE.md).

## Modules

| Module | Role |
| --- | --- |
| `__init__.py` | Top-level exports for `Tool`, `@operation`, `ToolContext`, `ToolError`, `ErrorCode`, `OperationSpec`, `invoke`, and `__version__`. |
| `approval.py` | Evaluates risk tiers (T0–T3), enforces channel policies, and records decisions in `audit.jsonl`. |
| `approvals.py` | Manages the file-based proposal queue for scheduled job approvals (`%LOCALAPPDATA%\lfmap\approvals\`). |
| `cli.py` | Generates Typer CLI commands dynamically from plugin manifests and exposes core commands. |
| `config.py` | Loads `%LOCALAPPDATA%\lfmap\config.toml` and resolves declared folder paths for permissions. |
| `errors.py` | Defines standard `ErrorCode` literals and the shared `ToolError` exception. |
| `grants.py` | Handles time-limited approval grants stored in `%LOCALAPPDATA%\lfmap\grants.json`. |
| `jobs.py` | Parses scheduled job configs (`jobs.toml`) and interfaces with Windows Task Scheduler (`\LFMAP\`). |
| `jobs_doctor.py` | Runs diagnostic health checks on scheduler status, sleep settings, and backend availability. |
| `manifest.py` | Defines the Pydantic schema and parser for `lfmap.toml` plugin manifests. |
| `mcp_adapter.py` | Implements an MCP stdio server that exposes plugin operations as tools. |
| `naming.py` | Pure helper functions for generating safe, unique, and collision-free Windows file names. |
| `permissions.py` | Enforces declarative file-system access boundaries (`require_read`, `require_write`). |
| `registry.py` | Discovers installed plugins and loads manifests via the `lfmap.plugins` entry point group. |
| `runtime.py` | Instantiates plugins, injects `ToolContext`, and executes operations through the gate pipeline. |
| `telemetry.py` | Disables third-party telemetry (such as ONNX Runtime) before plugin dependencies load. |
| `tool.py` | Defines the `Tool` base class, `@operation` decorator, operation metadata, and `ToolContext`. |
| `versions.py` | Parses and compares semantic versions for plugin and core compatibility checks. |

## How plugins use it

1. **Subclass `Tool`**: Define business logic in a `Tool` subclass and decorate methods with `@operation("name")` using typed Pydantic models.
2. **Use `ToolContext`**: Access injected runtime facilities via `self.ctx`, including `permissions` (`require_read`, `require_write`), `data_dir`, and `settings`.
3. **Handle errors**: Raise `ToolError` with a standard `ErrorCode` (`invalid_input`, `permission_denied`, `not_found`, etc.) rather than leaking raw exceptions.
4. **Declare `lfmap.toml`**: Specify plugin metadata, operations, side effect tiers (`none`, `local_write`, `external`), permissions, and adapters.
5. **Register entry point**: Expose the tool class in `pyproject.toml` under the `[project.entry-points."lfmap.plugins"]` group.
6. **Events (optional)**: With `[adapters] events = true` in `lfmap.toml`, publish your own topics with `self.ctx.events.publish("<plugin-id>.<name>", {...})` (a JSON object up to 64 KiB holding references such as paths or ids, never document text or secrets); other plugins get `permission_denied`. Core may then request your operations through `<plugin-id>.<operation>.requested`. Delivery is at least once: a request or event can be handled twice after a crash or a lease over 60 s, so operations and handlers must be **idempotent** (key on `event.id` or the input, check before writing). Long work should be started by an event and tracked as a job.

```python
from lfmap_core import Tool, ToolContext, ToolError, operation
from pydantic import BaseModel


class GreetInput(BaseModel):
    name: str


class GreetOutput(BaseModel):
    greeting: str


class GreetTool(Tool):
    @operation("greet")
    def greet(self, inp: GreetInput) -> GreetOutput:
        if not inp.name.strip():
            raise ToolError("invalid_input", "Name cannot be blank")
        return GreetOutput(greeting=f"Hello, {inp.name}!")
```

## Commands

```powershell
# Sync workspace dependencies
uv sync

# Run the test suite for lfmap-core
uv run pytest packages/lfmap-core
```
