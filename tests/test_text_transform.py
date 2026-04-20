from __future__ import annotations

import pytest

from speakup.text_transform import sanitize_text_for_tts, transform_text_for_reading


@pytest.mark.parametrize(
    ("source_text", "expected_text"),
    [
        ("1", "one"),
        ("123", "one hundred twenty-three"),
        ("1980", "nineteen eighty"),
        ("in 1980", "in nineteen eighty"),
        ("1920s", "nineteen twenties"),
        ("1st", "first"),
        ("3:30", "three thirty"),
        ("Room 402", "Room four zero two"),
        ("2 + 2", "two plus two"),
    ],
)
def test_transform_text_for_reading_given_supported_numeric_contexts_returns_spoken_text(
    source_text: str, expected_text: str
) -> None:
    assert transform_text_for_reading(source_text) == expected_text


def test_transform_text_for_reading_given_plain_text_without_numbers_returns_original_text() -> None:
    assert transform_text_for_reading("Please read this aloud.") == "Please read this aloud."


def test_transform_text_for_reading_given_time_with_leading_zero_minutes_spells_oh() -> None:
    assert transform_text_for_reading("3:05") == "three oh five"


def test_transform_text_for_reading_given_multiline_text_inserts_spoken_stops() -> None:
    assert transform_text_for_reading("Room 402\nOpens at 3:30\n\nIn 1980") == "Room four zero two. Opens at three thirty. In nineteen eighty"


def test_transform_text_for_reading_given_existing_terminal_punctuation_before_closers_does_not_add_extra_stop() -> None:
    assert transform_text_for_reading('He said "Done."\nNext step') == 'He said "Done." Next step'
    assert transform_text_for_reading("Summary (done.)\nNext step") == "Summary (done.) Next step"


def test_transform_text_for_reading_given_carriage_return_line_breaks_inserts_spoken_stops() -> None:
    assert transform_text_for_reading("Room 402\rOpens at 3:30\r\rIn 1980") == "Room four zero two. Opens at three thirty. In nineteen eighty"


@pytest.mark.parametrize(
    ("source_text", "expected_text"),
    [
        ("Commit #a1b2c3d", "Commit a one b two"),
        ("Commit a1b2c3d4", "Commit a one b two"),
        ("sha deadbeef", "sha d e a d"),
        ("revision cafebabe", "revision c a f e"),
        ("Fix shipped in #deadbeef yesterday", "Fix shipped in d e a d yesterday"),
    ],
)
def test_transform_text_for_reading_given_commit_like_hashes_preserves_only_first_four_characters(
    source_text: str, expected_text: str
) -> None:
    assert transform_text_for_reading(source_text) == expected_text


@pytest.mark.parametrize(
    ("source_text", "expected_text"),
    [
        ("Version deadbeef is deployed", "Version deadbeef is deployed"),
        ("Error code cafebabe happened", "Error code cafebabe happened"),
    ],
)
def test_transform_text_for_reading_given_non_commit_hex_strings_leaves_them_unchanged(
    source_text: str, expected_text: str
) -> None:
    assert transform_text_for_reading(source_text) == expected_text


@pytest.mark.parametrize(
    ("source_text", "expected_text"),
    [
        (
            "/tmp/audio-1.mp3",
            "slash tmp slash audio dash one dot mp three",
        ),
        (
            "See file /var/log/app-2024.log",
            "See file slash var slash log slash app dash two zero two four dot log",
        ),
        (
            "Open src/v2/api.py before 3:30",
            "Open src slash v two slash api dot py before three thirty",
        ),
        (
            "Config is in /tmp/app_config-2.json",
            "Config is in slash tmp slash app underscore config dash two dot json",
        ),
    ],
)
def test_transform_text_for_reading_given_file_paths_verbalizes_path_structure(
    source_text: str, expected_text: str
) -> None:
    assert transform_text_for_reading(source_text) == expected_text


@pytest.mark.parametrize(
    ("source_text", "expected_text"),
    [
        (
            "# Release Update\n- shipped commit deadbeef\n- []\n",
            "Release Update. shipped commit d e a d",
        ),
        (
            "See [build logs](https://example.com) and `done`",
            "See build logs and done",
        ),
        (
            "hash deadbeef and #cafebabe",
            "hash d e a d and c a f e",
        ),
        (
            "/tmp/.audio-1.mp3",
            "slash tmp slash dot audio dash one dot mp three",
        ),
        (
            "#",
            "",
        ),
    ],
)
def test_sanitize_text_for_tts_removes_non_spoken_markup_and_shortens_hashes(
    source_text: str, expected_text: str
) -> None:
    assert sanitize_text_for_tts(source_text) == expected_text


def test_sanitize_text_for_tts_given_only_empty_collections_returns_empty_string() -> None:
    assert sanitize_text_for_tts("[] {} ()") == ""


def test_sanitize_text_for_tts_given_multiline_text_inserts_spoken_stops() -> None:
    assert sanitize_text_for_tts("Status update\n\n- shipped commit deadbeef\n- ready") == "Status update. shipped commit d e a d. ready"


def test_sanitize_text_for_tts_given_quoted_sentence_before_newline_preserves_existing_stop() -> None:
    assert sanitize_text_for_tts('He said "Done."\nNext step') == 'He said "Done." Next step'


def test_sanitize_text_for_tts_given_carriage_return_line_breaks_inserts_spoken_stops() -> None:
    assert sanitize_text_for_tts("Status update\r\r- shipped commit deadbeef\r- ready") == "Status update. shipped commit d e a d. ready"
