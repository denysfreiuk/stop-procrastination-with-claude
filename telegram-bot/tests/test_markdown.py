from __future__ import annotations

from discipline_bot.markdown import (
    append_line,
    list_items,
    properties,
    remove_line,
    render_value,
    section_lines,
    set_property,
)

NOTE = """---
date: 2026-10-30
focus_minutes: 50
screen_time_min:
aliases:
  - день
mood: "добрий: дуже"
---
## Фокус

## Лог

"""


def test_properties_read_scalars_and_skip_lists() -> None:
    values = properties(NOTE)
    assert values["date"] == "2026-10-30"
    assert values["focus_minutes"] == "50"
    assert values["screen_time_min"] == ""
    assert values["mood"] == "добрий: дуже"
    assert "  - день" not in values


def test_set_property_changes_only_its_own_line() -> None:
    updated = set_property(NOTE, "screen_time_min", "95")
    assert "screen_time_min: 95\n" in updated
    assert updated.replace("screen_time_min: 95", "screen_time_min:") == NOTE


def test_set_property_adds_a_missing_key_inside_the_frontmatter() -> None:
    updated = set_property(NOTE, "energy", "4")
    assert 'mood: "добрий: дуже"\nenergy: 4\n---\n' in updated


def test_set_property_empty_value_has_no_trailing_space() -> None:
    assert "focus_minutes:\n" in set_property(NOTE, "focus_minutes", "")


def test_note_without_frontmatter_gets_one() -> None:
    updated = set_property("просто текст\n", "gym", "true")
    assert updated == "---\ngym: true\n---\nпросто текст\n"
    assert properties(updated) == {"gym": "true"}


def test_unclosed_frontmatter_is_left_as_text() -> None:
    assert properties("---\ngym: true\n") == {}


def test_render_value() -> None:
    assert render_value(True) == "true"
    assert render_value(False) == "false"
    assert render_value(7.5) == "7.5"
    assert render_value(7.0) == "7"
    assert render_value(50) == "50"


def test_append_goes_right_under_the_heading_of_an_empty_section() -> None:
    updated = append_line(NOTE, "Фокус", "- 14:32 · 50 хв · ML")
    assert "## Фокус\n- 14:32 · 50 хв · ML\n\n## Лог\n" in updated


def test_append_keeps_the_order_inside_a_section() -> None:
    updated = append_line(append_line(NOTE, "Лог", "- перше"), "Лог", "- друге")
    assert section_lines(updated, "Лог") == ["- перше", "- друге"]
    assert updated.endswith("- перше\n- друге\n\n")


def test_user_text_in_a_section_stays_above_new_entries() -> None:
    note = "## Лог\nмій запис\n\nще абзац\n\n## Інше\n"
    assert append_line(note, "Лог", "- бот") == "## Лог\nмій запис\n\nще абзац\n- бот\n\n## Інше\n"


def test_a_removed_section_comes_back_at_the_end() -> None:
    updated = append_line("---\na: 1\n---\n## Фокус\n", "Лог", "- 10:00 текст")
    assert updated == "---\na: 1\n---\n## Фокус\n\n## Лог\n- 10:00 текст\n"


def test_deeper_headings_belong_to_the_section() -> None:
    note = "## Лог\n### Ранок\n- рання\n\n## Інше\n"
    assert append_line(note, "Лог", "- нова") == "## Лог\n### Ранок\n- рання\n- нова\n\n## Інше\n"


def test_headings_inside_code_blocks_do_not_count() -> None:
    note = "```\n## Лог\n```\n\n## Лог\n- справжня\n\n## Інше\n```\n## Лог\n```\n"
    assert section_lines(note, "Лог") == ["- справжня"]
    assert append_line(note, "Лог", "- нова").count("- нова") == 1
    assert section_lines(append_line(note, "Лог", "- нова"), "Лог") == ["- справжня", "- нова"]


def test_a_similar_heading_is_not_the_section() -> None:
    assert section_lines("## Лог дня\n- ні\n", "Лог") == []


def test_section_at_the_end_of_a_file_without_newline() -> None:
    assert append_line("## Лог", "Лог", "- запис") == "## Лог\n- запис"


def test_remove_line_takes_the_last_copy_in_its_section_only() -> None:
    note = "## Лог\n- так\n- ні\n- так\n\n## Інше\n- так\n"
    assert remove_line(note, "Лог", "- так") == "## Лог\n- так\n- ні\n\n## Інше\n- так\n"
    assert remove_line(note, "Немає", "- так") == note


def test_list_items_ignore_plain_text() -> None:
    assert list_items("## Лог\n- один\n* два\n1. три\nтекст\n", "Лог") == ["- один", "* два", "1. три"]
