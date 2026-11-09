import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "changelog_fragments", Path(__file__).parents[1] / "changelog_fragments.py"
)
cf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cf)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- old entry\n", encoding="utf-8"
    )
    return tmp_path


def write(root: Path, name: str, text: str) -> None:
    (root / "changelog.d" / name).write_text(text, encoding="utf-8")


def test_check_accepts_good_and_flags_bad_fragments(root: Path) -> None:
    write(root, "a-one.added.md", "Entry one.")
    write(root, "bad.md", "x")
    write(root, "b.unknown.md", "x")
    write(root, "c.fixed.md", "- has bullet")
    write(root, "d.fixed.md", "  ")
    groups, problems = cf.read_fragments(root / "changelog.d")
    assert [t for _, t in groups["added"]] == ["Entry one."]
    assert len(problems) == 4


def test_release_groups_fragments_keeps_legacy_and_deletes_files(root: Path) -> None:
    write(root, "1-b.added.md", "Second\nline.")
    write(root, "0-a.fixed.md", "A fix.")
    used = cf.release(root, "1.2.3", "2026-12-01")
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert len(used) == 2 and not list((root / "changelog.d").glob("*.md"))
    assert text.index("## [Unreleased]") < text.index("## [1.2.3] - 2026-12-01")
    assert "### Added\n\n- Second line." in text
    assert "### Fixed\n\n- A fix." in text
    assert "### Earlier entries" in text and "- old entry" in text


def test_release_rejects_bad_version_and_bad_fragments(root: Path) -> None:
    with pytest.raises(SystemExit):
        cf.release(root, "v1", "2026-12-01")
    write(root, "x.bogus.md", "x")
    with pytest.raises(SystemExit):
        cf.release(root, "1.0.0", "2026-12-01")
    assert (root / "changelog.d" / "x.bogus.md").exists()
