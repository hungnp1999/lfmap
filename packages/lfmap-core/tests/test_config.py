import json

import pytest

from lfmap_core import ToolError
from lfmap_core.config import config_path, load_config, plugin_variables
from lfmap_core.manifest import Permissions
from lfmap_core.permissions import PermissionManager


def test_missing_config_is_empty(user_dirs):
    assert config_path() == user_dirs / "config.toml"
    assert load_config() == {}


def test_invalid_toml(user_dirs):
    (user_dirs / "config.toml").write_text("[paths\n", encoding="utf-8")
    with pytest.raises(ToolError) as caught:
        load_config()
    assert caught.value.code == "invalid_input"


def test_plugin_variables(user_dirs):
    docs = user_dirs / "docs"
    quoted = json.dumps(str(docs))  # a TOML basic string, also on Windows
    (user_dirs / "config.toml").write_text(f"[paths]\ndocuments = [{quoted}]\nexports = {quoted}\n", encoding="utf-8")
    variables = plugin_variables(load_config(), "fake-plugin")
    assert variables["documents"] == [str(docs)]
    assert variables["exports"] == [str(docs)]
    data_dir = user_dirs / "localappdata" / "lfmap" / "fake-plugin"
    assert variables["data_dir"] == [str(data_dir)]
    assert (data_dir / "tmp").is_dir()


def test_paths_must_be_strings():
    with pytest.raises(ToolError) as caught:
        plugin_variables({"paths": {"documents": [1]}}, "x")
    assert caught.value.code == "invalid_input"


def test_network_path_in_config_refused():
    variables = plugin_variables({"paths": {"documents": [r"\\server\share"]}}, "x")
    with pytest.raises(ToolError) as caught:
        PermissionManager.from_manifest(Permissions(fs_read=["${documents}"]), variables)
    assert caught.value.code == "permission_denied"
