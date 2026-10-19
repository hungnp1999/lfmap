"""Time-limited approvals in `%LOCALAPPDATA%\\lfmap\\grants.json` (ADR-017).

Only the interactive CLI creates or revokes grants; no operation and no MCP tool writes this file.
An expired grant counts as no grant.
"""

import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError

MAX_DURATION = {"T1": timedelta(days=7), "T2": timedelta(days=7), "T3": timedelta(hours=24)}
_TIERS = ("T0", "T1", "T2", "T3")
_DURATION = re.compile(r"^(\d+)([mhd])$")


def grants_path() -> Path:
    return app_dir() / "grants.json"


def parse_duration(text: str) -> timedelta:
    match = _DURATION.match(text.strip())
    if not match or int(match.group(1)) == 0:
        raise ToolError("invalid_input", "Duration must look like 30m, 1h or 7d", {"duration": text})
    amount, unit = int(match.group(1)), match.group(2)
    return {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]


def load(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or grants_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as error:
        raise ToolError("invalid_input", f"{path} is not valid JSON", {"error": str(error)}) from error
    if not isinstance(data, list) or not all(isinstance(g, dict) for g in data):
        raise ToolError("invalid_input", f"{path} must hold a list of grants")
    return data


def _save(grants: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(grants, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _expires(grant: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(grant["expires_at"])
    except (KeyError, TypeError, ValueError):
        return None


def active(operation: str, tier: str, path: Path | None = None, now: datetime | None = None) -> bool:
    """True when an unexpired grant for `operation` covers `tier` or a higher one."""
    now = now or datetime.now(UTC)
    for grant in load(path):
        expires = _expires(grant)
        if grant.get("operation") != operation or grant.get("tier") not in _TIERS or expires is None:
            continue
        if expires > now and _TIERS.index(grant["tier"]) >= _TIERS.index(tier):
            return True
    return False


def add(operation: str, tier: str, duration: timedelta, path: Path | None = None) -> dict[str, Any]:
    if tier not in MAX_DURATION:
        raise ToolError("invalid_input", "Tier must be T1, T2 or T3", {"tier": tier})
    if duration > MAX_DURATION[tier]:
        raise ToolError("invalid_input", f"A {tier} grant lasts at most {MAX_DURATION[tier]}", {"tier": tier})
    path = path or grants_path()
    now = datetime.now(UTC)
    grant = {"operation": operation, "tier": tier, "expires_at": (now + duration).isoformat(timespec="seconds")}
    kept = [g for g in load(path) if g.get("operation") != operation and (_expires(g) or now) > now]
    _save([*kept, grant], path)
    return grant


def revoke(operation: str, path: Path | None = None) -> int:
    path = path or grants_path()
    grants = load(path)
    kept = [g for g in grants if g.get("operation") != operation]
    if len(kept) != len(grants):
        _save(kept, path)
    return len(grants) - len(kept)
