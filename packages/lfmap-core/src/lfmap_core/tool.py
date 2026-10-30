"""Tool base class, the @operation marker and operation invocation."""

import inspect
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lfmap_core.errors import ToolError

OPERATION_ATTR = "__lfmap_operation__"

Channel = Literal["sdk", "cli", "mcp", "rest", "job", "event"]


class ToolContext(BaseModel):
    """Injected by the runtime: plugin_id, dry_run, permissions, data_dir, temp_dir, settings, channel, approver
    and, for plugins whose manifest has `[adapters] events = true`, the event publisher behind `events`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    plugin_id: str
    dry_run: bool = False
    permissions: Any = None
    data_dir: Path | None = None
    temp_dir: Path | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    channel: Channel = "sdk"
    approver: Any = None
    event_publisher: Any = None

    @property
    def events(self) -> Any:
        """The plugin's `PluginEvents`; ToolError permission_denied unless the manifest opts in to events."""
        if self.event_publisher is None:
            raise ToolError(
                "permission_denied",
                "This plugin cannot use events; set [adapters] events = true in its manifest",
                {"plugin": self.plugin_id},
            )
        return self.event_publisher

    def require_approval(self, reason: str, detail: str = "", *, destination: str = "", data: str = "normal") -> None:
        """Escalate this call before acting: T3 for reason "external", otherwise T2 (overwrite, rename, delete).

        For data sent out, `destination` (host or service) and `data` (normal, private, secret) let a
        preapproved destination in config.toml cover the call. Raises ToolError permission_denied when refused.
        Without an approver (plain SDK use) the call is the user's own code and runs.
        """
        if self.approver is None:
            return
        tier = "T3" if reason == "external" else "T2"
        if destination:
            self.approver(tier, reason, detail, destination=destination, data=data)
        else:
            self.approver(tier, reason, detail)


class OperationSpec(BaseModel):
    name: str
    method_name: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    description: str


def operation(name: str) -> Callable[[Callable], Callable]:
    """Mark a Tool method as an operation; input and output models come from its type hints."""

    def mark(function: Callable) -> Callable:
        setattr(function, OPERATION_ATTR, name)
        return function

    return mark


def _is_model(value: Any) -> bool:
    return inspect.isclass(value) and issubclass(value, BaseModel)


def _spec(method_name: str, function: Callable) -> OperationSpec:
    hints = typing.get_type_hints(function)
    params = [p for p in inspect.signature(function).parameters if p != "self"]
    output = hints.get("return")
    if len(params) != 1 or not _is_model(hints.get(params[0])) or not _is_model(output):
        raise TypeError(f"Operation method {method_name!r} must take one pydantic model and return one")
    doc = inspect.getdoc(function) or ""
    return OperationSpec(
        name=getattr(function, OPERATION_ATTR),
        method_name=method_name,
        input_model=hints[params[0]],
        output_model=output,
        description=doc.splitlines()[0] if doc else "",
    )


class Tool:
    manifest_path: ClassVar[str] = "lfmap.toml"

    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx

    def health(self) -> dict:
        """Return dependency status (e.g. backend installed, model reachable)."""
        return {"ok": True}

    @classmethod
    def call_tier(cls, operation: str, inp: BaseModel, settings: dict[str, Any]) -> str | None:
        """ADR-020: the tier of one call, read from the user's settings, for operations that declare
        `min_tier`. Core clamps it between `min_tier` and the declared tier; None keeps the declared tier."""
        return None

    @classmethod
    def operations(cls) -> dict[str, OperationSpec]:
        specs: dict[str, OperationSpec] = {}
        for method_name, function in inspect.getmembers(cls, inspect.isfunction):
            if not hasattr(function, OPERATION_ATTR):
                continue
            spec = _spec(method_name, function)
            if spec.name in specs:
                raise TypeError(f"Duplicate operation {spec.name!r} in {cls.__name__}")
            specs[spec.name] = spec
        return specs


def invoke(tool: Tool, name: str, payload: dict[str, Any]) -> BaseModel:
    spec = type(tool).operations().get(name)
    if spec is None:
        raise ToolError("not_found", f"Unknown operation {name!r}", {"operation": name})
    try:
        inp = spec.input_model.model_validate(payload)
    except ValidationError as error:
        raise ToolError(
            "invalid_input", "Input does not match the operation schema", {"errors": error.errors()}
        ) from error
    return getattr(tool, spec.method_name)(inp)
