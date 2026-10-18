import os

import pytest

from lfmap_core import ToolError
from lfmap_core.manifest import Permissions
from lfmap_core.permissions import PermissionManager


@pytest.fixture
def dirs(tmp_path):
    data = tmp_path / "data"
    out = tmp_path / "out"
    sibling = tmp_path / "data2"
    for folder in (data, out, sibling):
        folder.mkdir()
    return data, out, sibling


@pytest.fixture
def perms(dirs):
    data, out, _ = dirs
    declared = Permissions(fs_read=["${input_dir}"], fs_write=["${output_dir}"])
    return PermissionManager.from_manifest(declared, {"input_dir": str(data), "output_dir": str(out)})


def denied(call, *args):
    with pytest.raises(ToolError) as caught:
        call(*args)
    assert caught.value.code == "permission_denied"


def test_read_inside(perms, dirs):
    data = dirs[0]
    assert perms.require_read(data / "a.pdf") == (data / "a.pdf").resolve()
    assert perms.require_read(data) == data.resolve()


def test_write_root_is_also_readable(perms, dirs):
    assert perms.require_read(dirs[1] / "a.md")


def test_read_root_is_not_writable(perms, dirs):
    denied(perms.require_write, dirs[0] / "a.md")


def test_outside_and_dotdot(perms, dirs, tmp_path):
    denied(perms.require_read, tmp_path / "other.txt")
    denied(perms.require_read, dirs[0] / ".." / "secret.txt")


def test_sibling_prefix(perms, dirs):
    denied(perms.require_read, dirs[2] / "a.pdf")


@pytest.mark.parametrize("path", [r"\\host\share\a.pdf", "//host/share/a.pdf", r"\\?\C:\a.pdf", r"\\.\pipe\x"])
def test_remote_paths(perms, path):
    denied(perms.require_read, path)


def test_remote_root_refused():
    with pytest.raises(ToolError) as caught:
        PermissionManager.from_manifest(Permissions(fs_read=["${d}"]), {"d": r"\\host\share"})
    assert caught.value.code == "permission_denied"


def test_undefined_variable():
    with pytest.raises(ToolError) as caught:
        PermissionManager.from_manifest(Permissions(fs_read=["${input_dir}"]), {})
    assert caught.value.code == "invalid_input"


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive paths are Windows only")
def test_case_insensitive(perms, dirs):
    assert perms.require_read(str(dirs[0] / "A.pdf").upper())


def test_symlink_escape(perms, dirs, tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    link = dirs[0] / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("cannot create symlinks here")
    denied(perms.require_read, link / "a.pdf")


def test_network(perms):
    denied(perms.require_network)
    assert PermissionManager([], [], network=True).require_network() is None
