import json

import pytest

from lfmap_core.approval import Policy, audit, audit_path, base_tier, decide, raise_tier
from lfmap_core.errors import ToolError

DEFAULT = Policy()


def test_base_tier():
    assert base_tier("none") == "T0"
    assert base_tier("local_write") == "T1"
    assert base_tier("external") == "T3"


def test_raise_tier_never_lowers():
    assert raise_tier("T1", "T2") == "T2"
    assert raise_tier("T3", "T2") == "T3"


@pytest.mark.parametrize(
    ("tier", "channel", "preapproved", "can_elicit", "expected"),
    [
        # T0 and T1 run on every channel with the default policy.
        ("T0", "mcp", False, False, "allow"),
        ("T1", "mcp", False, False, "allow"),
        ("T1", "job", False, False, "allow"),
        # T2 asks: a pre-approval or an interactive person is needed.
        ("T2", "mcp", True, False, "allow"),
        ("T2", "mcp", False, True, "ask"),
        ("T2", "mcp", False, False, "deny"),
        ("T2", "cli", False, True, "ask"),
        ("T2", "cli", True, False, "allow"),
        ("T2", "cli", False, False, "deny"),
        ("T2", "job", False, False, "deny"),
        ("T2", "sdk", False, False, "deny"),
        # T3: pre-approval and MCP elicitation never count; only the interactive CLI may ask.
        ("T3", "mcp", True, True, "deny"),
        ("T3", "mcp", False, False, "deny"),
        ("T3", "cli", True, False, "deny"),
        ("T3", "cli", False, True, "ask"),
        ("T3", "rest", True, True, "deny"),
        ("T3", "job", True, False, "deny"),
    ],
)
def test_decision_table(tier, channel, preapproved, can_elicit, expected):
    approved = {"p.op"} if preapproved else set()
    assert decide(DEFAULT, "p", "op", tier, channel, approved, can_elicit) == expected


def test_preapproval_is_per_operation():
    assert decide(DEFAULT, "p", "op", "T2", "mcp", {"p.other"}, False) == "deny"


@pytest.mark.parametrize("tier", ["T2", "T3"])
def test_grant_allows(tier):
    assert decide(DEFAULT, "p", "op", tier, "mcp", set(), False, granted=True) == "allow"


def test_policy_deny_beats_everything():
    policy = Policy.from_config({"approval": {"T2": "deny"}})
    assert decide(policy, "p", "op", "T2", "cli", {"p.op"}, True, granted=True) == "deny"


def test_policy_can_relax_t1_and_t2():
    policy = Policy.from_config({"approval": {"T1": "ask", "operations": {"p.op": "audit"}}})
    assert decide(policy, "p", "op", "T2", "mcp", set(), False) == "allow"
    assert decide(policy, "p", "other", "T1", "mcp", set(), False) == "deny"


@pytest.mark.parametrize("approval", [{"T3": "allow"}, {"T3": "audit"}, {"operations": {"p.op": "allow"}}])
def test_policy_cannot_relax_t3(approval):
    policy = Policy.from_config({"approval": approval})
    assert decide(policy, "p", "op", "T3", "mcp", {"p.op"}, True) == "deny"
    assert decide(policy, "p", "op", "T3", "cli", set(), True) == "ask"


def test_t0_ignores_policy():
    policy = Policy.from_config({"approval": {"operations": {"p.op": "deny"}}})
    assert decide(policy, "p", "op", "T0", "mcp", set(), False) == "allow"


@pytest.mark.parametrize("approval", [{"T2": "maybe"}, {"T4": "ask"}, {"operations": {"p.op": "yes"}}, "ask"])
def test_invalid_policy(approval):
    with pytest.raises(ToolError) as excinfo:
        Policy.from_config({"approval": approval})
    assert excinfo.value.code == "invalid_input"


def test_audit_appends_json_lines(user_dirs):
    audit({"channel": "mcp", "plugin": "p", "operation": "op", "tier": "T1", "decision": "allow"})
    audit(
        {"channel": "cli", "plugin": "p", "operation": "op", "tier": "T2", "decision": "deny", "target": "D:\\Tài liệu"}
    )
    lines = audit_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert first["decision"] == "allow" and first["time"].endswith("+00:00")
    assert second["target"] == "D:\\Tài liệu"


def test_audit_refuses_unknown_fields(user_dirs):
    with pytest.raises(ValueError):
        audit({"plugin": "p", "content": "secret text"})
    assert not audit_path().exists()
