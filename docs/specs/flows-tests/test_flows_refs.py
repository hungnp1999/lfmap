"""Reference grammar of docs/specs/flows.md section 4 (`lfmap_core.flows_refs`)."""

import pytest

from lfmap_core import ToolError
from lfmap_core.flows_refs import find_refs, resolve, truthy

SCOPE = {
    "trigger": {"payload": {"path": "D:/in/a.docx", "count": 3, "tags": ["x", "y"], "empty": None, "ok": True}},
    "steps": {
        "export": {"output": {"path": "D:/out/a.md", "succeeded": True, "files": [{"name": "a"}, {"name": "b"}]}},
        "my-step": {"output": {"n": 0, "text": "", "ratio": 1.5}},
    },
}


# find_refs


def test_find_refs_returns_paths_in_order():
    value = {"a": "${trigger.payload.path}", "b": ["x ${steps.export.output.path} y", 5, None]}
    assert find_refs(value) == [
        ("trigger", "payload", "path"),
        ("steps", "export", "output", "path"),
    ]


def test_find_refs_walks_nested_dicts_and_lists():
    value = {"a": {"b": [{"c": "${trigger.payload.count}"}]}}
    assert find_refs(value) == [("trigger", "payload", "count")]


def test_find_refs_two_in_one_string():
    assert find_refs("${trigger.payload.count}-${trigger.payload.path}") == [
        ("trigger", "payload", "count"),
        ("trigger", "payload", "path"),
    ]


@pytest.mark.parametrize("value", ["plain", "", "$5", "cost $ {x}", "{trigger.payload}", 5, 1.5, True, None, [], {}])
def test_find_refs_none(value):
    assert find_refs(value) == []


def test_find_refs_list_index_stays_a_string_key():
    assert find_refs("${trigger.payload.tags.0}") == [("trigger", "payload", "tags", "0")]


def test_find_refs_root_only():
    assert find_refs("${trigger}") == [("trigger",)]


def test_find_refs_dict_keys_are_not_scanned():
    assert find_refs({"${trigger.payload}": 1}) == []


@pytest.mark.parametrize(
    "text",
    [
        "${}",
        "${ trigger.payload }",
        "${trigger.}",
        "${trigger..payload}",
        "${trigger.payload-x}",
        "${trigger.payload.a b}",
        "${trigger.1a}",
        "${trigger.payload[0]}",
        "${triggerx.payload}",
        "${env.HOME}",
        "${steps}",
        "${steps.}",
        "${steps.Export.output}",
        "${steps.1x.output}",
        "${trigger.payload + 1}",
        "${len(trigger.payload)}",
        "${trigger.payload.${trigger.payload.path}}",
        "${trigger.payload",
        "prefix ${bad} suffix",
        "${trigger.payload} and ${nope}",
    ],
)
def test_find_refs_refuses_anything_outside_the_grammar(text):
    with pytest.raises(ToolError) as error:
        find_refs(text)
    assert error.value.code == "invalid_input"


def test_find_refs_refuses_bad_reference_deep_inside():
    with pytest.raises(ToolError) as error:
        find_refs({"a": [{"b": "${nope}"}]})
    assert error.value.code == "invalid_input"


# resolve: exact reference keeps its type


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("${trigger.payload.path}", "D:/in/a.docx"),
        ("${trigger.payload.count}", 3),
        ("${trigger.payload.ok}", True),
        ("${trigger.payload.tags}", ["x", "y"]),
        ("${trigger.payload.empty}", None),
        ("${steps.export.output.succeeded}", True),
        ("${steps.export.output.files}", [{"name": "a"}, {"name": "b"}]),
        ("${steps.my-step.output.n}", 0),
        ("${steps.my-step.output.text}", ""),
        ("${steps.my-step.output.ratio}", 1.5),
    ],
)
def test_exact_reference_keeps_json_type(text, expected):
    result = resolve(text, SCOPE)
    assert result == expected
    assert type(result) is type(expected)


def test_list_index():
    assert resolve("${trigger.payload.tags.1}", SCOPE) == "y"
    assert resolve("${steps.export.output.files.1.name}", SCOPE) == "b"


def test_root_only_returns_the_whole_object():
    assert resolve("${trigger}", SCOPE) == SCOPE["trigger"]


def test_resolve_does_not_alias_the_scope():
    result = resolve("${trigger.payload.tags}", SCOPE)
    result.append("z")
    assert SCOPE["trigger"]["payload"]["tags"] == ["x", "y"]


# resolve: embedded reference uses str()


def test_embedded_reference_is_inserted_as_text():
    assert resolve("file ${trigger.payload.path} n=${trigger.payload.count}", SCOPE) == "file D:/in/a.docx n=3"


def test_embedded_scalar_types():
    assert resolve("${trigger.payload.ok}!", SCOPE) == "True!"
    assert resolve("r=${steps.my-step.output.ratio}", SCOPE) == "r=1.5"
    assert resolve("n=${steps.my-step.output.n}", SCOPE) == "n=0"


@pytest.mark.parametrize(
    "text", ["x ${trigger.payload.tags}", "x ${steps.export.output}", "x ${trigger.payload.empty}"]
)
def test_embedded_reference_refuses_list_dict_and_null(text):
    with pytest.raises(ToolError) as error:
        resolve(text, SCOPE)
    assert error.value.code == "invalid_input"


def test_embedded_missing_key_raises_even_when_not_strict():
    with pytest.raises(ToolError):
        resolve("x ${trigger.payload.nope}", SCOPE)


# resolve: structures


def test_resolve_walks_dicts_and_lists_and_keeps_literals():
    value = {
        "path": "${steps.export.output.path}",
        "n": 7,
        "flag": False,
        "none": None,
        "items": ["${trigger.payload.count}", "lit"],
    }
    assert resolve(value, SCOPE) == {
        "path": "D:/out/a.md",
        "n": 7,
        "flag": False,
        "none": None,
        "items": [3, "lit"],
    }


def test_resolve_does_not_change_its_input():
    value = {"a": ["${trigger.payload.count}"]}
    resolve(value, SCOPE)
    assert value == {"a": ["${trigger.payload.count}"]}


def test_resolve_does_not_resolve_inside_resolved_values():
    scope = {"trigger": {"payload": {"text": "${trigger.payload.text}"}}, "steps": {}}
    assert resolve("${trigger.payload.text}", scope) == "${trigger.payload.text}"
    assert resolve("a ${trigger.payload.text}", scope) == "a ${trigger.payload.text}"


def test_resolve_without_references_returns_equal_value():
    assert resolve("plain", SCOPE) == "plain"
    assert resolve({"a": [1, 2]}, SCOPE) == {"a": [1, 2]}


# resolve: missing keys


@pytest.mark.parametrize(
    "text",
    [
        "${trigger.payload.nope}",
        "${trigger.payload.tags.5}",
        "${trigger.payload.count.x}",
        "${trigger.payload.path.0}",
        "${steps.nope.output.path}",
        "${steps.export.output.nope.deeper}",
    ],
)
def test_missing_key_is_none_when_not_strict(text):
    assert resolve(text, SCOPE) is None


def test_missing_trigger_is_none_when_not_strict():
    assert resolve("${trigger.payload.x}", {"steps": {}}) is None


def test_missing_key_in_strict_mode_names_step_and_reference():
    with pytest.raises(ToolError) as error:
        resolve({"a": "${steps.export.output.nope}"}, SCOPE, step="index", strict=True)
    assert error.value.code == "invalid_input"
    assert "index" in error.value.message
    assert "${steps.export.output.nope}" in error.value.message
    assert error.value.details["step"] == "index"
    assert error.value.details["reference"] == "${steps.export.output.nope}"


def test_present_null_is_not_missing_in_strict_mode():
    assert resolve("${trigger.payload.empty}", SCOPE, step="s", strict=True) is None


def test_strict_mode_keeps_good_references():
    assert resolve({"a": "${trigger.payload.count}"}, SCOPE, step="s", strict=True) == {"a": 3}


def test_resolve_refuses_grammar_errors_in_both_modes():
    for strict in (False, True):
        with pytest.raises(ToolError) as error:
            resolve("${bad}", SCOPE, step="s", strict=strict)
        assert error.value.code == "invalid_input"


# truthy


@pytest.mark.parametrize("value", [None, False, 0, 0.0, "", [], {}])
def test_falsy(value):
    assert truthy(value) is False


@pytest.mark.parametrize("value", [True, 1, -1, 0.5, "0", "false", " ", [0], [None], {"a": None}])
def test_truthy(value):
    assert truthy(value) is True
