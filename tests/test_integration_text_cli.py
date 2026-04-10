from __future__ import annotations

from pathlib import Path

from .conftest import run_cli


def test_verbalize_command_given_inline_text_returns_transformed_output() -> None:
    result = run_cli(["verbalize", "--text", "Room 402 opens at 3:30 in 1980."])

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Room four zero two opens at three thirty in nineteen eighty.\n"


def test_verbalize_command_given_input_file_returns_transformed_output(tmp_path: Path) -> None:
    input_file = tmp_path / "input.txt"
    input_file.write_text("2 + 2 = 4")

    result = run_cli(["verbalize", "--input-file", str(input_file)])

    assert result.returncode == 0, result.stderr
    assert result.stdout == "two plus two equals four\n"


def test_verbalize_command_given_stdin_returns_transformed_output() -> None:
    result = run_cli(["verbalize"], stdin="1st prize in 1920s")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "first prize in nineteen twenties\n"
