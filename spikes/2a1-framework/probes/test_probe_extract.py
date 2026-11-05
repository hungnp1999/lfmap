"""F7 probes for packages/lfmap-knowledge/src/lfmap_knowledge/extract.py (card TC-K4).

Each probe checks one rule the card or the repo security rules state but the frozen tests do not exercise.
Uses the fixtures of packages/lfmap-knowledge/tests/conftest.py (root, data_dir, perms).
"""

import contextlib
import os
from pathlib import Path

import pytest
from lfmap_core import ToolContext, ToolError
from lfmap_knowledge.extract import cache_path, extract

HASH = "cd" + "0" * 62


@pytest.fixture
def ctx(perms) -> ToolContext:
    return ToolContext(plugin_id="knowledge", permissions=perms)


@pytest.fixture
def cache_dir(data_dir: Path) -> Path:
    return data_dir / "cache" / "md"


@pytest.fixture
def note(root: Path) -> Path:
    path = root / "probe.md"
    path.write_text("# Probe\n\nNội dung.\n", encoding="utf-8")
    return path


def _failing_replace(monkeypatch: pytest.MonkeyPatch, suffix: str) -> list[str]:
    """os.replace raises OSError when the destination ends with suffix; returns the destinations it refused."""
    real = os.replace
    refused: list[str] = []

    def replace(src, dst, *args, **kwargs):
        if str(dst).endswith(suffix):
            refused.append(str(dst))
            raise OSError("probe: disk full")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    return refused


def test_probe_permission_before_existence(ctx: ToolContext, tmp_path: Path, cache_dir: Path):
    """A missing file outside the allowed roots answers permission_denied, never not_found (no existence oracle)."""
    outside = tmp_path / "outside" / "missing.md"
    with pytest.raises(ToolError) as caught:
        extract(ctx, outside, HASH, cache_dir, False, config={})
    assert caught.value.code == "permission_denied"


def test_probe_sidecar_written_last(ctx: ToolContext, note: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """When writing the .md fails, no .json sidecar exists: a sidecar means the extraction is complete."""
    refused = _failing_replace(monkeypatch, ".md")
    with contextlib.suppress(OSError, ToolError):
        extract(ctx, note, HASH, cache_dir, False, config={})
    if not refused:
        pytest.skip("the .md is not written through os.replace; probe inconclusive")
    assert not cache_path(cache_dir, HASH).with_suffix(".json").exists()


def test_probe_write_error_is_raised(ctx: ToolContext, note: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """An OSError while writing the sidecar reaches the caller; it is not swallowed."""
    refused = _failing_replace(monkeypatch, ".json")
    raised = False
    try:
        extract(ctx, note, HASH, cache_dir, False, config={})
    except (OSError, ToolError):
        raised = True
    if not refused:
        pytest.skip("the .json is not written through os.replace; probe inconclusive")
    assert raised


def test_probe_no_temp_files_after_failed_write(
    ctx: ToolContext, note: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """A failed write leaves no temp file in the cache folder."""
    refused = _failing_replace(monkeypatch, "")
    with contextlib.suppress(OSError, ToolError):
        extract(ctx, note, HASH, cache_dir, False, config={})
    if not refused:
        pytest.skip("no write goes through os.replace; probe inconclusive")
    folder = cache_path(cache_dir, HASH).parent
    left = sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []
    assert left == []
