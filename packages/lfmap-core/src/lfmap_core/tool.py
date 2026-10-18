"""Tool base class, the @operation marker and operation invocation."""

import inspect
import typing
from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError

from lfmap_core.errors import ToolError

OPERATION_ATTR = "__lfmap_operation__"


class ToolContext(BaseModel):
    """Injected by the runtime: permissions, logger, config, cancellation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    plugin_id: str
    dry_run: bool = False
    permissions: Any = None


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
