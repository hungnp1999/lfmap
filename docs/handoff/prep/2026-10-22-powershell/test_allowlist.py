# Prepared for Roadmap 1.6 (docs/handoff/2026-10-22-powershell-plan.md).
# Copy to plugins/lfmap-powershell/tests/test_allowlist.py and delete these two lines.
import pytest

from lfmap_core import ToolError
from lfmap_powershell.allowlist import ParamSpec, build_args, load_allowlist, sha256_hex, unsafe_reason

HASH = "a" * 64


def _entry(**extra) -> dict:
    return {"path": "C:/scripts/a.ps1", "sha256": HASH, **extra}


def test_valid_entry_loads_with_defaults_and_lower_case_hash():
    entries, problems = load_allowlist({"scripts": {"disk-report": _entry(sha256="A" * 64)}})
    assert problems == {}
    entry = entries["disk-report"]
    assert entry.sha256 == "a" * 64
    assert entry.timeout_s == 60
    assert entry.max_output_chars == 20_000
    assert entry.params == {}


def test_no_scripts_section_is_empty():
    assert load_allowlist({}) == ({}, {})


def test_scripts_not_a_table_is_invalid_input():
    with pytest.raises(ToolError) as error:
        load_allowlist({"scripts": ["a"]})
    assert error.value.code == "invalid_input"


@pytest.mark.parametrize(
    ("script_id", "raw"),
    [
        ("Disk", _entry()),
        ("1disk", _entry()),
        ("disk_report", _entry()),
        ("x" * 41, _entry()),
        ("disk", "not a table"),
        ("disk", {"path": "C:/a.ps1"}),
        ("disk", _entry(sha256="xyz")),
        ("disk", _entry(unknown=1)),
        ("disk", _entry(timeout_s=0)),
        ("disk", _entry(timeout_s=3601)),
        ("disk", _entry(max_output_chars=10)),
        ("disk", _entry(params={"bad-name": {}})),
        ("disk", _entry(params={"Name": {}, "name": {}})),
        ("disk", _entry(params={"P": {"type": "float"}})),
        ("disk", _entry(params={"P": {"pattern": "("}})),
        ("disk", _entry(params={"P": {"type": "choice"}})),
        ("disk", _entry(params={"P": {"type": "choice", "choices": ["-x"]}})),
        ("disk", _entry(params={"P": {"type": "switch", "required": True}})),
        ("disk", _entry(params={"P": {"type": "int", "min": 5, "max": 1}})),
        ("disk", _entry(params={"P": {"type": "int", "min": -1}})),
    ],
)
def test_invalid_entries_are_reported_not_loaded(script_id, raw):
    entries, problems = load_allowlist({"scripts": {script_id: raw, "good": _entry()}})
    assert script_id not in entries
    assert problems[script_id].startswith(("invalid id", "invalid entry"))
    assert "good" in entries


PARAMS = {
    "Drive": ParamSpec(type="string", required=True, pattern="[A-Z]"),
    "Days": ParamSpec(type="int", min=1, max=30),
    "Verbose": ParamSpec(type="switch"),
    "Mode": ParamSpec(type="choice", choices=["fast", "full"]),
}


def test_args_follow_allow_list_order_not_caller_order():
    args = build_args(PARAMS, {"Mode": "full", "Verbose": True, "Days": 7, "Drive": "C"})
    assert args == ["-Drive", "C", "-Days", "7", "-Verbose", "-Mode", "full"]


def test_optional_params_may_be_left_out_and_false_switch_adds_nothing():
    assert build_args(PARAMS, {"Drive": "D", "Verbose": False}) == ["-Drive", "D"]


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"Drive": "C", "Other": "x"},
        {"Drive": "CD"},
        {"Drive": "c"},
        {"Drive": 1},
        {"Drive": "C", "Days": 0},
        {"Drive": "C", "Days": 31},
        {"Drive": "C", "Days": "7"},
        {"Drive": "C", "Days": True},
        {"Drive": "C", "Verbose": "true"},
        {"Drive": "C", "Mode": "slow"},
        {"Drive": "C", "Mode": 1},
    ],
)
def test_bad_values_are_invalid_input(values):
    with pytest.raises(ToolError) as error:
        build_args(PARAMS, values)
    assert error.value.code == "invalid_input"


@pytest.mark.parametrize("value", ["", "-Command", "--x", 'a"b', "a\nb", "a\rb", "a\x00b", "a\tb", "x" * 257])
def test_unsafe_strings_are_refused(value):
    with pytest.raises(ToolError) as error:
        build_args({"Text": ParamSpec()}, {"Text": value})
    assert error.value.code == "invalid_input"


@pytest.mark.parametrize("value", ["C:\\Data\\báo cáo.xlsx", "a-b", "x" * 256, "a b; c", "$env:PATH"])
def test_safe_strings_pass_unchanged(value):
    assert build_args({"Text": ParamSpec()}, {"Text": value}) == ["-Text", value]


def test_unsafe_reason():
    assert unsafe_reason("ok") == ""
    assert unsafe_reason("-x")
    assert unsafe_reason('"')


def test_sha256_hex():
    assert sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
