import ast
import os
from pathlib import Path

import pytest

from lfmap_core import ToolError
from lfmap_core import data_classes as dc
from lfmap_core.data_classes import (
    CLASSES,
    TIER_NAMES,
    ClassMap,
    adjust,
    egress_level,
    highest,
    load_class_map,
)

TIERS = ("T0", "T1", "T2", "T3")


def _expected(tier: str, access: str, cls: str) -> str:
    if cls == "scratch" and access == "write" and tier == "T2":
        return "T1"
    if cls == "secret":
        floor = 1 if access == "read" else 2
        return TIER_NAMES[max(TIER_NAMES.index(tier), floor)]
    return tier


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    return tmp_path / "appdata" / "lfmap"


def make(tmp_path: Path, **names: str) -> ClassMap:
    table = {str(tmp_path / name.replace("__", "/")): cls for name, cls in names.items()}
    return load_class_map({"data": {"classes": table}})


def test_adjust_table():
    rows = [(c, a, t) for c in CLASSES for a in ("read", "write") for t in TIERS]
    assert len(rows) == 32
    for cls, access, tier in rows:
        assert adjust(tier, access, cls) == _expected(tier, access, cls), (cls, access, tier)


def test_adjust_never_lowers_t3():
    for cls in CLASSES:
        for access in ("read", "write"):
            assert adjust("T3", access, cls) == "T3"


def test_adjust_clamp():
    for cls in CLASSES:
        for access in ("read", "write"):
            for tier in TIERS:
                result = TIER_NAMES.index(adjust(tier, access, cls))
                assert max(TIER_NAMES.index(tier) - 1, 0) <= result <= 3
                if access == "write" and tier != "T0":
                    assert result >= 1
    for bad in (("T9", "read", "normal"), ("T1", "exec", "normal"), ("T1", "read", "top")):
        with pytest.raises(ValueError):
            adjust(*bad)  # type: ignore[arg-type]


def test_class_of_most_specific(tmp_path, monkeypatch):
    class_map = make(tmp_path, Work="normal", Work__Contracts="secret", Tmp="scratch")
    assert class_map.class_of(tmp_path / "Work" / "notes.md") == "normal"
    assert class_map.class_of(tmp_path / "Work" / "Contracts" / "a.pdf") == "secret"
    assert class_map.class_of(tmp_path / "Work" / "Contracts") == "secret"
    assert class_map.class_of(tmp_path / "Tmp" / "x") == "scratch"
    assert class_map.lookup(tmp_path / "Work" / "notes.md") == ("normal", os.path.realpath(tmp_path / "Work"))
    assert class_map.class_of(tmp_path / "Workshop" / "x") == "private"
    monkeypatch.setattr(os.path, "normcase", str.lower)
    insensitive = make(tmp_path, Work="normal")
    assert insensitive.class_of(str(tmp_path / "WORK" / "x").upper()) == "normal"


def test_class_default_private(tmp_path):
    assert make(tmp_path, Work="normal").class_of(tmp_path / "Other" / "x.txt") == "private"
    empty = load_class_map({})
    assert not empty
    assert load_class_map({"data": {"classes": {}}}).entries == ()
    assert empty.class_of(tmp_path) == "private"


def test_class_under_takes_nested_highest(tmp_path):
    class_map = make(tmp_path, Work="normal", Work__Contracts="secret", Tmp="scratch")
    assert class_map.class_under(tmp_path / "Work") == "secret"
    assert class_map.class_under(tmp_path / "Work" / "notes.md") == "normal"
    assert class_map.class_under(tmp_path / "Work" / "Contracts" / "a.pdf") == "secret"
    assert class_map.class_under(tmp_path / "Tmp") == "scratch"
    assert class_map.class_under(tmp_path) == "secret"
    assert class_map.class_under(tmp_path / "Work2") == "private"
    assert highest(["scratch", "secret", "normal"]) == "secret"
    assert highest([]) == "scratch"
    assert [egress_level(c) for c in CLASSES] == ["normal", "normal", "private", "secret"]


@pytest.mark.parametrize("key", ["\\\\server\\share\\x", "\\\\?\\C:\\x", "\\\\.\\pipe\\x", "//host/share"])
def test_class_map_refuses_remote_before_io(key, monkeypatch, app):
    def forbidden(*args, **kwargs):
        raise AssertionError("realpath called")

    monkeypatch.setattr(os.path, "realpath", forbidden)
    with pytest.raises(ToolError) as caught:
        load_class_map({"data": {"classes": {key: "secret"}}})
    assert caught.value.code in ("invalid_input", "permission_denied")
    with pytest.raises(ToolError):
        ClassMap(()).class_of(key)


def test_class_map_invalid(tmp_path, app):
    def invalid(table):
        with pytest.raises(ToolError) as caught:
            load_class_map({"data": {"classes": table}})
        assert caught.value.code == "invalid_input"
        assert "[data.classes]" in caught.value.message

    invalid({"relative/path": "normal"})
    invalid({str(tmp_path / "a"): "top-secret"})
    invalid({str(tmp_path / "a"): 3})
    invalid({str(app / "data"): "scratch"})
    invalid({str(app): "scratch"})
    target = tmp_path / "real"
    target.mkdir()
    (tmp_path / "link").symlink_to(target)
    invalid({str(target): "normal", str(tmp_path / "link"): "secret"})
    invalid({str(tmp_path / "a"): "normal", str(tmp_path / "a") + os.sep: "secret"})
    for broken in ("nope", ["x"]):
        with pytest.raises(ToolError) as caught:
            load_class_map({"data": {"classes": broken}})
        assert caught.value.code == "invalid_input"
    with pytest.raises(ToolError):
        load_class_map({"data": "nope"})


def test_module_is_a_leaf():
    tree = ast.parse(Path(dc.__file__).read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "lfmap_core.approval" not in modules
