# Prepared for Roadmap 1.2 (docs/handoff/2026-10-23-docling-backend.md).
# Copy to plugins/lfmap-markitdown/tests/test_headings.py and delete these two lines.
import pytest

from lfmap_markitdown.headings import fix_heading_levels


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("## 1. Scope", "## 1. Scope"),
        ("## 1 Scope", "## 1 Scope"),
        ("## 1.1 Responsibilities", "### 1.1 Responsibilities"),
        ("## 1.1. Responsibilities", "### 1.1. Responsibilities"),
        ("## 2.3.4 Records of calibration", "#### 2.3.4 Records of calibration"),
        ("## 1.2.3.4.5 Deep", "###### 1.2.3.4.5 Deep"),
        ("## 1.2.3.4.5.6 Deeper", "###### 1.2.3.4.5.6 Deeper"),
        ("## 4\\.1 Escaped dot", "### 4\\.1 Escaped dot"),
        ("## Quality Manual", "## Quality Manual"),
        ("## Điều 3. Phạm vi", "## Điều 3. Phạm vi"),
        ("## II. Purpose", "## II. Purpose"),
        ("## 1.1", "## 1.1"),
        ("## 1234.5 Not a section number", "## 1234.5 Not a section number"),
    ],
)
def test_level_follows_section_number(line: str, expected: str) -> None:
    assert fix_heading_levels(line) == expected


def test_only_level_two_headings_change() -> None:
    markdown = "# 1.1 Title kept\n### 1.1 Already deeper\n## 1.1 Changed"
    assert fix_heading_levels(markdown) == "# 1.1 Title kept\n### 1.1 Already deeper\n### 1.1 Changed"


def test_body_lines_and_lists_are_untouched() -> None:
    markdown = "1.1 Responsibilities in body text\n- ## 1.1 inside a list item\nText ## 1.1 inline"
    assert fix_heading_levels(markdown) == markdown


def test_fenced_code_is_untouched() -> None:
    markdown = "```\n## 1.1 in code\n```\n~~~\n## 2.1 in code\n~~~\n## 3.1 Real"
    expected = "```\n## 1.1 in code\n```\n~~~\n## 2.1 in code\n~~~\n### 3.1 Real"
    assert fix_heading_levels(markdown) == expected


def test_document_keeps_line_endings_and_other_text() -> None:
    markdown = "## Quality Manual\n\n## 1. Scope\n\nBody.\n\n## 1.1 Responsibilities\n\n| a | b |\n|---|---|\n"
    expected = "## Quality Manual\n\n## 1. Scope\n\nBody.\n\n### 1.1 Responsibilities\n\n| a | b |\n|---|---|\n"
    assert fix_heading_levels(markdown) == expected


def test_empty_text() -> None:
    assert fix_heading_levels("") == ""
