"""The lfmap.toml plugin manifest: schema and loader."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lfmap_core.errors import ToolError

SideEffects = Literal["none", "local_write", "external"]
MinTier = Literal["T0", "T1", "T2", "T3"]
_BASE_TIER_INDEX = {"none": 0, "local_write": 1, "external": 3}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Entrypoint(_Strict):
    module: str
    class_: str = Field(alias="class")


class PluginInfo(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str
    license: str
    authors: list[str] = []
    min_core_version: str = "0.1.0"
    entrypoint: Entrypoint


class OperationDecl(_Strict):
    name: str
    input: str
    output: str
    side_effects: SideEffects = "none"
    # ADR-020: the plugin may lower a call's tier from the user's config, never below this.
    min_tier: MinTier | None = None

    @model_validator(mode="after")
    def _min_tier_below_base(self) -> "OperationDecl":
        if self.min_tier is not None and int(self.min_tier[1]) >= _BASE_TIER_INDEX[self.side_effects]:
            raise ValueError(f"min_tier {self.min_tier} must be below the tier of side_effects {self.side_effects!r}")
        return self


class Permissions(_Strict):
    fs_read: list[str] = []
    fs_write: list[str] = []
    network: bool = False
    exec: list[str] = []
    cloud_ai: bool = False


class Adapters(_Strict):
    cli: bool = True
    mcp: bool = True
    rest: bool = False
    events: bool = False


class LicensePolicy(_Strict):
    allowed: list[str] = []


class Dependencies(_Strict):
    licenses: LicensePolicy = LicensePolicy()


class Manifest(_Strict):
    plugin: PluginInfo
    operations: list[OperationDecl] = []
    permissions: Permissions = Permissions()
    adapters: Adapters = Adapters()
    dependencies: Dependencies = Dependencies()

    def operation(self, name: str) -> OperationDecl | None:
        return next((op for op in self.operations if op.name == name), None)


def parse_manifest(text: str, source: str = "lfmap.toml") -> Manifest:
    try:
        return Manifest.model_validate(tomllib.loads(text))
    except tomllib.TOMLDecodeError as error:
        raise ToolError("invalid_input", f"{source} is not valid TOML", {"error": str(error)}) from error
    except ValidationError as error:
        raise ToolError(
            "invalid_input", f"{source} does not match the manifest schema", {"errors": error.errors()}
        ) from error


def load_manifest(path: Path) -> Manifest:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ToolError("not_found", "Manifest not found", {"path": str(path)}) from error
    return parse_manifest(text, str(path))
