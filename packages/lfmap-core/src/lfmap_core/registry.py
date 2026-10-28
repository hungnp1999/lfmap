"""Plugin discovery through the `lfmap.plugins` entry point group."""

import importlib.resources
import logging
from dataclasses import dataclass
from importlib.metadata import entry_points

from lfmap_core import __version__
from lfmap_core.errors import ToolError
from lfmap_core.manifest import Manifest, parse_manifest
from lfmap_core.tool import Tool
from lfmap_core.versions import require_core_version

ENTRY_POINT_GROUP = "lfmap.plugins"
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginEntry:
    id: str
    tool_class: type[Tool]
    manifest: Manifest


def load_entry(tool_class: type[Tool]) -> PluginEntry:
    """Read the manifest shipped next to the tool's module and check it against the class and the core version."""
    package = tool_class.__module__.rpartition(".")[0] or tool_class.__module__
    resource = importlib.resources.files(package) / tool_class.manifest_path
    try:
        text = resource.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ToolError("not_found", "Manifest not found", {"package": package}) from error
    manifest = parse_manifest(text, f"{package}/{tool_class.manifest_path}")
    require_core_version(manifest.plugin.id, manifest.plugin.min_core_version, __version__)
    declared = {op.name for op in manifest.operations}
    implemented = set(tool_class.operations())
    if declared != implemented:
        raise ToolError(
            "invalid_input",
            "Manifest operations do not match the tool class",
            {"plugin": manifest.plugin.id, "declared": sorted(declared), "implemented": sorted(implemented)},
        )
    return PluginEntry(manifest.plugin.id, tool_class, manifest)


class Registry:
    def __init__(self) -> None:
        self._plugins: dict[str, PluginEntry] = {}

    def register(self, entry: PluginEntry) -> None:
        if entry.id in self._plugins:
            raise ToolError("invalid_input", f"Plugin {entry.id!r} is registered twice", {"plugin": entry.id})
        self._plugins[entry.id] = entry

    def discover(self) -> None:
        """Load every installed plugin; a broken plugin is skipped with a warning."""
        for point in entry_points(group=ENTRY_POINT_GROUP):
            try:
                tool_class = point.load()
                if not (isinstance(tool_class, type) and issubclass(tool_class, Tool)):
                    raise TypeError(f"{point.value} is not a Tool subclass")
                entry = load_entry(tool_class)
                if entry.id != point.name:
                    raise ToolError("invalid_input", "Entry point name differs from plugin id", {"plugin": entry.id})
                self.register(entry)
            except (ImportError, TypeError, ToolError) as error:
                log.warning("Skipping plugin %s: %s", point.name, error)

    def get(self, plugin_id: str) -> PluginEntry:
        try:
            return self._plugins[plugin_id]
        except KeyError:
            raise ToolError("not_found", f"Unknown plugin {plugin_id!r}", {"plugin": plugin_id}) from None

    def all(self) -> list[PluginEntry]:
        return sorted(self._plugins.values(), key=lambda entry: entry.id)
