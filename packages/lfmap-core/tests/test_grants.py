from datetime import UTC, datetime, timedelta

import pytest

from lfmap_core import grants
from lfmap_core.errors import ToolError


def test_parse_duration():
    assert grants.parse_duration("30m") == timedelta(minutes=30)
    assert grants.parse_duration("1h") == timedelta(hours=1)
    assert grants.parse_duration("7d") == timedelta(days=7)
    for bad in ["0h", "1w", "h", "-1h", ""]:
        with pytest.raises(ToolError):
            grants.parse_duration(bad)


def test_maximum_duration(user_dirs):
    with pytest.raises(ToolError):
        grants.add("p.op", "T3", timedelta(hours=25))
    with pytest.raises(ToolError):
        grants.add("p.op", "T2", timedelta(days=8))
    with pytest.raises(ToolError):
        grants.add("p.op", "T0", timedelta(hours=1))


def test_active_covers_lower_tiers_until_expiry(user_dirs):
    grants.add("p.op", "T2", timedelta(hours=1))
    assert grants.active("p.op", "T1") and grants.active("p.op", "T2")
    assert not grants.active("p.op", "T3")
    assert not grants.active("p.other", "T1")
    later = datetime.now(UTC) + timedelta(hours=2)
    assert not grants.active("p.op", "T1", now=later)


def test_add_replaces_and_drops_expired(user_dirs):
    grants.grants_path().parent.mkdir(parents=True, exist_ok=True)
    grants.grants_path().write_text(
        '[{"operation": "old.op", "tier": "T1", "expires_at": "2020-01-01T00:00:00+00:00"},'
        ' {"operation": "p.op", "tier": "T1", "expires_at": "2999-01-01T00:00:00+00:00"}]',
        encoding="utf-8",
    )
    grants.add("p.op", "T3", timedelta(hours=1))
    assert [(g["operation"], g["tier"]) for g in grants.load()] == [("p.op", "T3")]


def test_malformed_entries_grant_nothing(user_dirs):
    grants.grants_path().parent.mkdir(parents=True, exist_ok=True)
    grants.grants_path().write_text('[{"operation": "p.op", "tier": "T3", "expires_at": "soon"}]', encoding="utf-8")
    assert not grants.active("p.op", "T1")
    grants.grants_path().write_text("{not json", encoding="utf-8")
    with pytest.raises(ToolError):
        grants.load()


def test_revoke(user_dirs):
    grants.add("p.op", "T1", timedelta(hours=1))
    assert grants.revoke("p.op") == 1
    assert grants.revoke("p.op") == 0
    assert grants.load() == []
