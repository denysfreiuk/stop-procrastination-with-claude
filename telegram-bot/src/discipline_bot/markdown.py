"""Edits of a note's text, line by line.

Frontmatter is never parsed and written back as YAML: only the lines of our own keys
change, so the user's other properties keep their exact form. Text uses \\n here;
journal.py restores the file's own line endings.
"""

from __future__ import annotations

import re

KEY_LINE = re.compile(r"^([A-Za-z_][\w-]*):[ \t]*(.*?)[ \t]*$")
TOP_HEADING = re.compile(r"^#{1,2}\s")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\S")
FENCE = "```"


def _frontmatter_end(lines: list[str]) -> int | None:
    """Index of the closing `---`, or None when the note has no frontmatter."""
    if not lines or lines[0].lstrip("﻿").rstrip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            return index
    return None


def properties(text: str) -> dict[str, str]:
    lines = text.split("\n")
    end = _frontmatter_end(lines)
    values: dict[str, str] = {}
    if end is None:
        return values
    for line in lines[1:end]:
        match = KEY_LINE.match(line)
        if match:
            values[match[1]] = match[2].strip("\"'")
    return values


def render_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def set_property(text: str, key: str, value: str) -> str:
    lines = text.split("\n")
    line = f"{key}: {value}" if value else f"{key}:"
    end = _frontmatter_end(lines)
    if end is None:
        return "\n".join(["---", line, "---", *lines])
    for index in range(1, end):
        match = KEY_LINE.match(lines[index])
        if match and match[1] == key:
            lines[index] = line
            return "\n".join(lines)
    lines.insert(end, line)
    return "\n".join(lines)


def _section_span(lines: list[str], heading: str) -> tuple[int, int] | None:
    """Index of the heading and of the line right after the section."""
    title = f"## {heading}"
    start = None
    fenced = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith(FENCE):
            fenced = not fenced
        elif fenced:
            continue
        elif start is None:
            if line.rstrip() == title:
                start = index
        elif TOP_HEADING.match(line):
            return start, index
    return None if start is None else (start, len(lines))


def append_line(text: str, heading: str, line: str) -> str:
    """Add to the end of a section; a section the user removed comes back at the end of the note."""
    lines = text.split("\n")
    span = _section_span(lines, heading)
    if span is None:
        return f"{text.rstrip()}\n\n## {heading}\n{line}\n"
    start, end = span
    position = end
    while position > start + 1 and not lines[position - 1].strip():
        position -= 1
    lines.insert(position, line)
    return "\n".join(lines)


def section_lines(text: str, heading: str) -> list[str]:
    lines = text.split("\n")
    span = _section_span(lines, heading)
    if span is None:
        return []
    return [line for line in lines[span[0] + 1 : span[1]] if line.strip()]


def remove_line(text: str, heading: str, line: str) -> str:
    """Remove the last copy of a line from a section."""
    lines = text.split("\n")
    span = _section_span(lines, heading)
    if span is None:
        return text
    for index in range(span[1] - 1, span[0], -1):
        if lines[index] == line:
            del lines[index]
            break
    return "\n".join(lines)


def list_items(text: str, heading: str) -> list[str]:
    return [line for line in section_lines(text, heading) if LIST_ITEM.match(line)]
