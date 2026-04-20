from __future__ import annotations

import re

_ONES = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
}

_TENS = {
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}

_ORDINAL_BASE = {
    0: "zeroth",
    1: "first",
    2: "second",
    3: "third",
    4: "fourth",
    5: "fifth",
    6: "sixth",
    7: "seventh",
    8: "eighth",
    9: "ninth",
    10: "tenth",
    11: "eleventh",
    12: "twelfth",
    13: "thirteenth",
    14: "fourteenth",
    15: "fifteenth",
    16: "sixteenth",
    17: "seventeenth",
    18: "eighteenth",
    19: "nineteenth",
}

_ORDINAL_TENS = {
    20: "twentieth",
    30: "thirtieth",
    40: "fortieth",
    50: "fiftieth",
    60: "sixtieth",
    70: "seventieth",
    80: "eightieth",
    90: "ninetieth",
}

_SCALES = (
    (1_000_000_000, "billion"),
    (1_000_000, "million"),
    (1_000, "thousand"),
    (100, "hundred"),
)

_MATH_OPERATORS = {
    "+": "plus",
    "-": "minus",
    "*": "times",
    "/": "divided by",
    "=": "equals",
}

_IDENTIFIER_LABELS = (
    "room",
    "suite",
    "unit",
    "apt",
    "apartment",
    "gate",
)

_DECADE_WORDS = {
    0: "hundreds",
    1: "tens",
    2: "twenties",
    3: "thirties",
    4: "forties",
    5: "fifties",
    6: "sixties",
    7: "seventies",
    8: "eighties",
    9: "nineties",
}

_COMMIT_REFERENCE_PATTERN = re.compile(
    r"(?P<prefix>\b(?:commit|sha|rev|revision|hash)\s+)(?P<hash>#?[0-9a-fA-F]{7,40})\b",
    re.IGNORECASE,
)
_HASH_REFERENCE_PATTERN = re.compile(r"(?<!\w)#(?P<hash>[0-9a-fA-F]{7,40})\b")
_FENCED_CODE_BLOCK_PATTERN = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((?:[^()\\]|\\.)*?\)")
_MARKDOWN_PREFIX_PATTERN = re.compile(r"(?m)^\s*(?:#{1,6}\s+|>\s*|(?:[-*+]|\d+[.)])\s+)")
_STANDALONE_MARKDOWN_HASH_PATTERN = re.compile(r"(?<!\w)#+(?!\w)")
_EMPTY_COLLECTION_PATTERN = re.compile(r"(?<!\w)(?:\[\s*\]|\{\s*\}|\(\s*\))(?!\w)")
_STANDALONE_BRACKETS_PATTERN = re.compile(r"(?<!\w)[\[\]{}()<>]+(?!\w)")
_MARKDOWN_DECORATION_PATTERN = re.compile(r"[*_~`|]+")
_HEX_HASH_TOKEN_PATTERN = re.compile(r"\b(?P<hash>(?=[0-9a-fA-F]{7,40}\b)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]+)\b")
_SENTENCE_ENDING_PATTERN = re.compile(r'[.!?]["\')\]}”’]*$')
_TRAILING_CLAUSE_PUNCTUATION_PATTERN = re.compile(r'[,;:](["\')\]}”’]*)$')


def transform_text_for_reading(text: str) -> str:
    transformed = _replace_file_paths(_normalize_line_breaks(text))

    if re.fullmatch(r"\d{4}", transformed.strip()):
        return _year_to_words(int(transformed.strip()))

    transformed = _replace_commit_like_hashes(transformed)
    transformed = _replace_math_operators(transformed)
    transformed = _replace_times(transformed)
    transformed = _replace_identifiers(transformed)
    transformed = _replace_decades(transformed)
    transformed = _replace_ordinals(transformed)
    transformed = _replace_contextual_years(transformed)
    transformed = _replace_cardinals(transformed)
    transformed = _replace_newlines_with_stops(transformed)

    return re.sub(r" {2,}", " ", transformed)


def sanitize_text_for_tts(text: str) -> str:
    cleaned = _normalize_line_breaks(text).strip()
    if not cleaned:
        return ""

    cleaned = _replace_file_paths(cleaned)
    cleaned = _FENCED_CODE_BLOCK_PATTERN.sub(" ", cleaned)
    cleaned = _MARKDOWN_LINK_PATTERN.sub(r"\1", cleaned)
    cleaned = _MARKDOWN_PREFIX_PATTERN.sub("", cleaned)
    cleaned = _STANDALONE_MARKDOWN_HASH_PATTERN.sub(" ", cleaned)
    cleaned = _MARKDOWN_DECORATION_PATTERN.sub(" ", cleaned)
    cleaned = _EMPTY_COLLECTION_PATTERN.sub(" ", cleaned)
    cleaned = _STANDALONE_BRACKETS_PATTERN.sub(" ", cleaned)
    cleaned = _replace_commit_like_hashes(cleaned)
    cleaned = _HEX_HASH_TOKEN_PATTERN.sub(_hash_reference_replacement, cleaned)
    cleaned = _replace_newlines_with_stops(cleaned)
    cleaned = re.sub(r"\s+([?!.,])", r"\1", cleaned)
    cleaned = re.sub(r"([,:;])(?=\S)", r"\1 ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" \t\r\n,;:-")


def _replace_file_paths(text: str) -> str:
    path_pattern = re.compile(
        r"(?<!\w)(?:/(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+|(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+)"
    )
    return path_pattern.sub(lambda match: _verbalize_path(match.group(0)), text)


def _normalize_line_breaks(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _replace_newlines_with_stops(text: str) -> str:
    if "\n" not in text and "\r" not in text:
        return text

    segments = [segment.strip() for segment in re.split(r"(?:\r\n|\r|\n)+", text)]
    spoken_segments = [segment for segment in segments if segment]
    if not spoken_segments:
        return ""

    combined = spoken_segments[0]
    for segment in spoken_segments[1:]:
        if _SENTENCE_ENDING_PATTERN.search(combined):
            combined = f"{combined} {segment}"
            continue
        combined = _TRAILING_CLAUSE_PUNCTUATION_PATTERN.sub(r"\1", combined)
        combined = f"{combined}. {segment}"
    return combined


def _verbalize_path(path: str) -> str:
    spoken_parts: list[str] = []
    current = []

    for char in path:
        if char == "/":
            if current:
                spoken_parts.append(_verbalize_path_segment("".join(current)))
                current = []
            spoken_parts.append("slash")
            continue

        if char in ".-_":
            if current:
                spoken_parts.append(_verbalize_path_segment("".join(current)))
                current = []
            if char == ".":
                spoken_parts.append("dot")
            elif char == "-":
                spoken_parts.append("dash")
            else:
                spoken_parts.append("underscore")
            continue

        current.append(char)

    if current:
        spoken_parts.append(_verbalize_path_segment("".join(current)))

    return " ".join(spoken_parts)


def _verbalize_path_segment(segment: str) -> str:
    parts = re.findall(r"[A-Za-z]+|\d+", segment)
    if not parts:
        return segment

    spoken_parts: list[str] = []
    for part in parts:
        if part.isdigit():
            spoken_parts.append(" ".join(_ONES[int(digit)] for digit in part))
        else:
            spoken_parts.append(part.lower())
    return " ".join(spoken_parts)


def _replace_math_operators(text: str) -> str:
    return re.sub(
        r"(?<=\d)\s*([+\-*/=])\s*(?=\d)",
        lambda match: f" {_MATH_OPERATORS[match.group(1)]} ",
        text,
    )


def _replace_commit_like_hashes(text: str) -> str:
    transformed = _COMMIT_REFERENCE_PATTERN.sub(_commit_reference_replacement, text)
    return _HASH_REFERENCE_PATTERN.sub(_hash_reference_replacement, transformed)


def _commit_reference_replacement(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}{_verbalize_commit_hash(match.group('hash'))}"


def _hash_reference_replacement(match: re.Match[str]) -> str:
    return _verbalize_commit_hash(match.group("hash"))


def _verbalize_commit_hash(value: str) -> str:
    hash_value = value[1:] if value.startswith("#") else value
    return " ".join(hash_value[:4])


def _replace_times(text: str) -> str:
    return re.sub(r"\b(\d{1,2}):(\d{2})\b", _time_replacement, text)


def _time_replacement(match: re.Match[str]) -> str:
    hour = int(match.group(1))
    minute = int(match.group(2))

    if minute == 0:
        return f"{_cardinal_to_words(hour)} o'clock"
    if minute < 10:
        return f"{_cardinal_to_words(hour)} oh {_cardinal_to_words(minute)}"
    return f"{_cardinal_to_words(hour)} {_cardinal_to_words(minute)}"


def _replace_identifiers(text: str) -> str:
    labels = "|".join(_IDENTIFIER_LABELS)
    pattern = re.compile(rf"\b(?P<label>{labels})\s+(?P<number>\d+)\b", re.IGNORECASE)
    return pattern.sub(_identifier_replacement, text)


def _identifier_replacement(match: re.Match[str]) -> str:
    label = match.group("label")
    digits = " ".join(_ONES[int(digit)] for digit in match.group("number"))
    return f"{label} {digits}"


def _replace_decades(text: str) -> str:
    return re.sub(r"\b(\d{4})s\b", lambda match: _decade_to_words(int(match.group(1))), text)


def _replace_ordinals(text: str) -> str:
    return re.sub(
        r"\b(\d+)(st|nd|rd|th)\b",
        lambda match: _ordinal_to_words(int(match.group(1))),
        text,
    )


def _replace_contextual_years(text: str) -> str:
    pattern = re.compile(
        r"\b(?P<prefix>in|since|from|during|around)\s+(?P<year>\d{4})\b",
        re.IGNORECASE,
    )
    return pattern.sub(
        lambda match: f"{match.group('prefix')} {_year_to_words(int(match.group('year')))}",
        text,
    )


def _replace_cardinals(text: str) -> str:
    return re.sub(r"\b\d+\b", lambda match: _cardinal_to_words(int(match.group(0))), text)


def _cardinal_to_words(number: int) -> str:
    if number < 0:
        return f"minus {_cardinal_to_words(abs(number))}"
    if number < 20:
        return _ONES[number]
    if number < 100:
        tens = (number // 10) * 10
        remainder = number % 10
        if remainder == 0:
            return _TENS[tens]
        return f"{_TENS[tens]}-{_ONES[remainder]}"

    for scale_value, scale_name in _SCALES:
        if number >= scale_value:
            quotient, remainder = divmod(number, scale_value)
            head = f"{_cardinal_to_words(quotient)} {scale_name}"
            if remainder == 0:
                return head
            return f"{head} {_cardinal_to_words(remainder)}"

    raise ValueError(f"Unsupported number: {number}")


def _ordinal_to_words(number: int) -> str:
    if number < 20:
        return _ORDINAL_BASE[number]
    if number < 100:
        tens = (number // 10) * 10
        remainder = number % 10
        if remainder == 0:
            return _ORDINAL_TENS[tens]
        return f"{_TENS[tens]}-{_ordinal_to_words(remainder)}"
    if number < 1_000:
        hundreds, remainder = divmod(number, 100)
        if remainder == 0:
            return f"{_cardinal_to_words(hundreds)} hundredth"
        return f"{_cardinal_to_words(hundreds)} hundred {_ordinal_to_words(remainder)}"

    thousands, remainder = divmod(number, 1_000)
    if remainder == 0:
        return f"{_cardinal_to_words(thousands)} thousandth"
    return f"{_cardinal_to_words(thousands)} thousand {_ordinal_to_words(remainder)}"


def _year_to_words(year: int) -> str:
    if 2000 <= year <= 2009:
        remainder = year % 100
        if remainder == 0:
            return "two thousand"
        return f"two thousand {_cardinal_to_words(remainder)}"

    if 1000 <= year <= 2099:
        first_pair = year // 100
        second_pair = year % 100
        if second_pair == 0:
            return f"{_cardinal_to_words(first_pair)} hundred"
        if second_pair < 10:
            return f"{_cardinal_to_words(first_pair)} oh {_cardinal_to_words(second_pair)}"
        return f"{_cardinal_to_words(first_pair)} {_cardinal_to_words(second_pair)}"

    return _cardinal_to_words(year)


def _decade_to_words(year: int) -> str:
    if 1900 <= year <= 1999:
        prefix = _cardinal_to_words(year // 100)
    elif 2000 <= year <= 2009:
        prefix = "two thousand"
    elif 2010 <= year <= 2099:
        prefix = "twenty"
    else:
        return _cardinal_to_words(year)

    decade = (year % 100) // 10
    return f"{prefix} {_DECADE_WORDS[decade]}"
