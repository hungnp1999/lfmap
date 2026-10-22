"""The allow-list in `[plugins.powershell.settings.scripts.<id>]` and typed script arguments."""

import hashlib
import re
import unicodedata
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from lfmap_core import ToolError

SCRIPT_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
PARAM_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,39}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
# PowerShell also reads en dash, em dash and horizontal bar as the start of a parameter name.
_DASHES = ("-", "–", "—", "―")
_TYPE_OPTIONS = {"string": {"pattern", "max_length"}, "int": {"min", "max"}, "choice": {"choices"}, "switch": set()}
_ALL_OPTIONS = set().union(*_TYPE_OPTIONS.values())

ParamType = Literal["string", "int", "switch", "choice"]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unsafe_reason(value: str) -> str:
    """Why `value` cannot be passed as an argument value, or "" when it can."""
    if not value:
        return "empty"
    if value.startswith(_DASHES):
        return "starts with a dash"
    if '"' in value:
        return 'contains "'
    if any(unicodedata.category(char) == "Cc" for char in value):
        return "contains a control character"
    return ""


class ParamSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    type: ParamType = "string"
    required: bool = False
    pattern: str = ""
    max_length: int = Field(256, ge=1, le=4096)
    min: int = Field(0, ge=0)
    max: int = Field(2_147_483_647, ge=0)
    choices: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Self:
        misplaced = self.model_fields_set & _ALL_OPTIONS - _TYPE_OPTIONS[self.type]
        if misplaced:
            raise ValueError(f"{', '.join(sorted(misplaced))} not allowed for type {self.type}")
        if self.pattern:
            try:
                re.compile(self.pattern)
            except re.error as error:
                raise ValueError(f"pattern does not compile: {error}") from error
        if self.min > self.max:
            raise ValueError("min is greater than max")
        if self.type == "choice":
            if not self.choices:
                raise ValueError("choice needs choices")
            for choice in self.choices:
                if unsafe_reason(choice):
                    raise ValueError(f"unsafe choice {choice!r}: {unsafe_reason(choice)}")
        if self.type == "switch" and self.required:
            raise ValueError("a switch cannot be required")
        return self


class ScriptEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    path: str = Field(min_length=1)
    sha256: str
    description: str = ""
    timeout_s: int = Field(60, ge=1, le=3600)
    max_output_chars: int = Field(20_000, ge=1000, le=200_000)
    params: dict[str, ParamSpec] = Field(default_factory=dict)

    @field_validator("sha256")
    @classmethod
    def _hash(cls, value: str) -> str:
        if not _SHA256.match(value):
            raise ValueError("sha256 must be 64 hex characters")
        return value.lower()

    @field_validator("params")
    @classmethod
    def _names(cls, value: dict[str, ParamSpec]) -> dict[str, ParamSpec]:
        seen: set[str] = set()
        for name in value:
            if not PARAM_NAME.match(name):
                raise ValueError(f"invalid parameter name {name!r}")
            if name.lower() in seen:
                raise ValueError(f"parameter names differ only in case: {name!r}")
            seen.add(name.lower())
        return value


def _error_text(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        where = ".".join(str(part) for part in item["loc"])
        parts.append(f"{where}: {item['msg']}" if where else item["msg"])
    return "; ".join(parts)


def load_allowlist(settings: dict[str, Any]) -> tuple[dict[str, ScriptEntry], dict[str, str]]:
    """Valid entries by id, and the reason each invalid entry was left out."""
    scripts = settings.get("scripts", {})
    if not isinstance(scripts, dict):
        raise ToolError("invalid_input", "[plugins.powershell.settings.scripts] must be a table")
    entries: dict[str, ScriptEntry] = {}
    problems: dict[str, str] = {}
    for script_id, raw in scripts.items():
        if not SCRIPT_ID.match(script_id):
            problems[script_id] = f"invalid id: must match {SCRIPT_ID.pattern}"
        elif not isinstance(raw, dict):
            problems[script_id] = "invalid entry: must be a table"
        else:
            try:
                entries[script_id] = ScriptEntry.model_validate(raw)
            except ValidationError as error:
                problems[script_id] = f"invalid entry: {_error_text(error)}"
    return entries, problems


def _invalid(message: str, name: str) -> ToolError:
    return ToolError("invalid_input", message, {"param": name})


def _value_args(name: str, spec: ParamSpec, value: str | int | bool) -> list[str]:
    if spec.type == "switch":
        if not isinstance(value, bool):
            raise _invalid(f"Parameter {name} must be true or false", name)
        return [f"-{name}"] if value else []
    if spec.type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid(f"Parameter {name} must be an integer", name)
        if not spec.min <= value <= spec.max:
            raise _invalid(f"Parameter {name} must be between {spec.min} and {spec.max}", name)
        return [f"-{name}", str(value)]
    if not isinstance(value, str):
        raise _invalid(f"Parameter {name} must be a string", name)
    if spec.type == "choice":
        if value not in spec.choices:
            raise _invalid(f"Parameter {name} must be one of {', '.join(spec.choices)}", name)
        return [f"-{name}", value]
    reason = unsafe_reason(value)
    if reason:
        raise _invalid(f"Parameter {name} is not allowed: {reason}", name)
    if len(value) > spec.max_length:
        raise _invalid(f"Parameter {name} is longer than {spec.max_length} characters", name)
    if spec.pattern and not re.fullmatch(spec.pattern, value):
        raise _invalid(f"Parameter {name} does not match {spec.pattern}", name)
    return [f"-{name}", value]


def build_args(params: dict[str, ParamSpec], values: dict[str, str | int | bool]) -> list[str]:
    """Check `values` against the allow-list and return the arguments, in allow-list order."""
    unknown = sorted(set(values) - set(params))
    if unknown:
        raise ToolError("invalid_input", "Unknown parameters", {"unknown": unknown, "allowed": list(params)})
    args: list[str] = []
    for name, spec in params.items():
        if name not in values:
            if spec.required:
                raise _invalid(f"Parameter {name} is required", name)
            continue
        args += _value_args(name, spec, values[name])
    return args
