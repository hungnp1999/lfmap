"""Heading levels from section numbers: Docling writes every section heading as `##`."""

import re

MAX_LEVEL = 6
# "1", "1.1", "2.3.4." or Docling's escaped "4\.1": one to three digits per part, at most six parts,
# then whitespace and a letter.
_NUMBERED = re.compile(r"## (\d{1,3}(?:\\?\.\d{1,3}){0,5})(?:\\?\.)?\s+[^\W\d_]")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")


def _level(number: str) -> int:
    return min(number.replace("\\", "").count(".") + 2, MAX_LEVEL)


def fix_heading_levels(markdown: str) -> str:
    """Turn `## 1.1 X` into `### 1.1 X` and so on; other lines and fenced code stay as they are."""
    lines = markdown.split("\n")
    fence = ""
    for index, line in enumerate(lines):
        opening = _FENCE.match(line)
        if fence:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence):
                fence = ""
            continue
        if opening:
            fence = opening.group(1)
            continue
        numbered = _NUMBERED.match(line)
        if numbered:
            lines[index] = "#" * _level(numbered.group(1)) + line[2:]
    return "\n".join(lines)
