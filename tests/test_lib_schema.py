from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Union

import pytest

from speakup.lib.schema import Gt, from_dict, SchemaValidationError


# ---------------------------------------------------------------------------
# Test fixture dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SimpleRequired:
    name: str
    count: int


@dataclass
class WithDefaults:
    label: str = "default_label"
    enabled: bool = True
    score: float = 0.5


@dataclass
class WithLiterals:
    mode: Literal["auto", "manual"] = "auto"
    level: Literal["low", "medium", "high"] = "medium"


@dataclass
class WithOptional:
    tag: Union[str, None] = None
    value: Union[int, None] = None


@dataclass
class NestedInner:
    x: int
    y: int = 0


@dataclass
class WithNested:
    inner: NestedInner = field(default_factory=lambda: NestedInner(x=1))
    name: str = "root"


@dataclass
class WithList:
    items: list[str] = field(default_factory=list)
    nums: list[int] = field(default_factory=list)


@dataclass
class WithDict:
    mapping: dict[str, int] = field(default_factory=dict)


@dataclass
class WithNestedList:
    children: list[NestedInner] = field(default_factory=list)


@dataclass
class WithLiteralList:
    providers: list[Literal["a", "b", "c"]] = field(default_factory=lambda: ["a"])


@dataclass
class WithLiteralDict:
    files: dict[Literal["x", "y"], str] = field(default_factory=dict)


@dataclass
class DeepNested:
    inner: WithNested = field(default_factory=lambda: WithNested())


# ---------------------------------------------------------------------------
# Primitive types
# ---------------------------------------------------------------------------

class TestPrimitiveValidation:
    def test_string_valid(self):
        result = from_dict(SimpleRequired, {"name": "hello", "count": 5})
        assert result.name == "hello"

    def test_string_invalid(self):
        with pytest.raises(SchemaValidationError, match="name must be a string"):
            from_dict(SimpleRequired, {"name": 123, "count": 5})

    def test_int_valid(self):
        result = from_dict(SimpleRequired, {"name": "x", "count": 42})
        assert result.count == 42

    def test_int_rejects_string(self):
        with pytest.raises(SchemaValidationError, match="count must be an integer"):
            from_dict(SimpleRequired, {"name": "x", "count": "42"})

    def test_int_rejects_bool(self):
        """bool is a subclass of int in Python, but we should reject it."""
        with pytest.raises(SchemaValidationError, match="count must be an integer"):
            from_dict(SimpleRequired, {"name": "x", "count": True})

    def test_int_rejects_float(self):
        with pytest.raises(SchemaValidationError, match="count must be an integer"):
            from_dict(SimpleRequired, {"name": "x", "count": 3.14})

    def test_bool_valid(self):
        result = from_dict(WithDefaults, {"enabled": False})
        assert result.enabled is False

    def test_bool_rejects_string(self):
        with pytest.raises(SchemaValidationError, match="enabled must be a boolean"):
            from_dict(WithDefaults, {"enabled": "yes"})

    def test_float_valid(self):
        result = from_dict(WithDefaults, {"score": 9.5})
        assert result.score == 9.5

    def test_float_coerces_int(self):
        """An int value should be coerced to float when float is expected."""
        result = from_dict(WithDefaults, {"score": 3})
        assert isinstance(result.score, float)
        assert result.score == 3.0

    def test_float_rejects_string(self):
        with pytest.raises(SchemaValidationError, match="score must be of type float"):
            from_dict(WithDefaults, {"score": "high"})


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_all_defaults_applied(self):
        result = from_dict(WithDefaults, {})
        assert result.label == "default_label"
        assert result.enabled is True
        assert result.score == 0.5

    def test_partial_override(self):
        result = from_dict(WithDefaults, {"label": "custom"})
        assert result.label == "custom"
        assert result.enabled is True

    def test_missing_required_field(self):
        with pytest.raises(SchemaValidationError, match="Missing required field: name"):
            from_dict(SimpleRequired, {"count": 1})

    def test_missing_all_required_fields(self):
        with pytest.raises(SchemaValidationError, match="Missing required field"):
            from_dict(SimpleRequired, {})


# ---------------------------------------------------------------------------
# Literal
# ---------------------------------------------------------------------------

class TestLiterals:
    def test_literal_valid(self):
        result = from_dict(WithLiterals, {"mode": "manual"})
        assert result.mode == "manual"

    def test_literal_default(self):
        result = from_dict(WithLiterals, {})
        assert result.mode == "auto"
        assert result.level == "medium"

    def test_literal_invalid_value(self):
        with pytest.raises(SchemaValidationError, match="mode must be one of"):
            from_dict(WithLiterals, {"mode": "turbo"})

    def test_literal_wrong_type(self):
        with pytest.raises(SchemaValidationError, match="level must be one of"):
            from_dict(WithLiterals, {"level": 42})


# ---------------------------------------------------------------------------
# Optional / Union
# ---------------------------------------------------------------------------

class TestOptional:
    def test_optional_none_explicit(self):
        result = from_dict(WithOptional, {"tag": None})
        assert result.tag is None

    def test_optional_none_default(self):
        result = from_dict(WithOptional, {})
        assert result.tag is None

    def test_optional_with_value(self):
        result = from_dict(WithOptional, {"tag": "important", "value": 42})
        assert result.tag == "important"
        assert result.value == 42

    def test_optional_wrong_type(self):
        with pytest.raises(SchemaValidationError):
            from_dict(WithOptional, {"tag": 123})


# ---------------------------------------------------------------------------
# Nested dataclasses
# ---------------------------------------------------------------------------

class TestNested:
    def test_nested_valid(self):
        result = from_dict(WithNested, {"inner": {"x": 10, "y": 20}, "name": "parent"})
        assert isinstance(result.inner, NestedInner)
        assert result.inner.x == 10
        assert result.inner.y == 20

    def test_nested_default(self):
        result = from_dict(WithNested, {})
        assert result.inner.x == 1
        assert result.inner.y == 0

    def test_nested_partial(self):
        result = from_dict(WithNested, {"inner": {"x": 5}})
        assert result.inner.x == 5
        assert result.inner.y == 0  # default

    def test_nested_invalid_not_dict(self):
        with pytest.raises(SchemaValidationError, match="inner must be an object"):
            from_dict(WithNested, {"inner": "not_a_dict"})

    def test_nested_invalid_field_type(self):
        with pytest.raises(SchemaValidationError, match="inner.x must be an integer"):
            from_dict(WithNested, {"inner": {"x": "bad"}})

    def test_deep_nested(self):
        data = {"inner": {"inner": {"x": 99}, "name": "mid"}}
        result = from_dict(DeepNested, data)
        assert result.inner.inner.x == 99
        assert result.inner.name == "mid"

    def test_deep_nested_path_in_error(self):
        with pytest.raises(SchemaValidationError, match="inner.inner.x must be an integer"):
            from_dict(DeepNested, {"inner": {"inner": {"x": "bad"}}})


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------

class TestLists:
    def test_list_of_strings(self):
        result = from_dict(WithList, {"items": ["a", "b", "c"]})
        assert result.items == ["a", "b", "c"]

    def test_list_of_ints(self):
        result = from_dict(WithList, {"nums": [1, 2, 3]})
        assert result.nums == [1, 2, 3]

    def test_list_empty(self):
        result = from_dict(WithList, {"items": []})
        assert result.items == []

    def test_list_not_an_array(self):
        with pytest.raises(SchemaValidationError, match="items must be an array"):
            from_dict(WithList, {"items": "not_a_list"})

    def test_list_wrong_element_type(self):
        with pytest.raises(SchemaValidationError, match=r"items\[1\] must be a string"):
            from_dict(WithList, {"items": ["ok", 42, "also_ok"]})

    def test_list_of_nested(self):
        data = {"children": [{"x": 1}, {"x": 2, "y": 3}]}
        result = from_dict(WithNestedList, data)
        assert len(result.children) == 2
        assert result.children[0].x == 1
        assert result.children[1].y == 3

    def test_list_of_nested_invalid(self):
        with pytest.raises(SchemaValidationError, match=r"children\[0\] must be an object"):
            from_dict(WithNestedList, {"children": ["not_a_dict"]})

    def test_list_of_literals(self):
        result = from_dict(WithLiteralList, {"providers": ["a", "c"]})
        assert result.providers == ["a", "c"]

    def test_list_of_literals_invalid(self):
        with pytest.raises(SchemaValidationError, match=r"providers\[1\] must be one of"):
            from_dict(WithLiteralList, {"providers": ["a", "z"]})


# ---------------------------------------------------------------------------
# Dicts
# ---------------------------------------------------------------------------

class TestDicts:
    def test_dict_valid(self):
        result = from_dict(WithDict, {"mapping": {"a": 1, "b": 2}})
        assert result.mapping == {"a": 1, "b": 2}

    def test_dict_empty(self):
        result = from_dict(WithDict, {"mapping": {}})
        assert result.mapping == {}

    def test_dict_not_an_object(self):
        with pytest.raises(SchemaValidationError, match="mapping must be an object"):
            from_dict(WithDict, {"mapping": [1, 2]})

    def test_dict_wrong_value_type(self):
        with pytest.raises(SchemaValidationError, match=r"mapping\.bad must be an integer"):
            from_dict(WithDict, {"mapping": {"ok": 1, "bad": "nope"}})

    def test_dict_literal_keys_valid(self):
        result = from_dict(WithLiteralDict, {"files": {"x": "path_x"}})
        assert result.files == {"x": "path_x"}

    def test_dict_literal_keys_invalid(self):
        with pytest.raises(SchemaValidationError, match="must be one of"):
            from_dict(WithLiteralDict, {"files": {"unknown_key": "path"}})


# ---------------------------------------------------------------------------
# Root validation
# ---------------------------------------------------------------------------

class TestRootValidation:
    def test_root_not_a_dict(self):
        with pytest.raises(SchemaValidationError, match="must be an object"):
            from_dict(SimpleRequired, "not_a_dict")

    def test_root_is_list(self):
        with pytest.raises(SchemaValidationError, match="must be an object"):
            from_dict(SimpleRequired, [1, 2, 3])

    def test_root_is_none(self):
        with pytest.raises(SchemaValidationError, match="must be an object"):
            from_dict(SimpleRequired, None)

    def test_not_a_dataclass(self):
        with pytest.raises(TypeError, match="is not a dataclass"):
            from_dict(str, {"x": 1})


# ---------------------------------------------------------------------------
# Extra keys (should be silently ignored)
# ---------------------------------------------------------------------------

class TestExtraKeys:
    def test_extra_keys_ignored(self):
        result = from_dict(WithDefaults, {"label": "custom", "unknown_field": 42})
        assert result.label == "custom"


# ---------------------------------------------------------------------------
# Integration: speakup AppConfig
# ---------------------------------------------------------------------------

class TestAppConfigIntegration:
    """Tests that the full AppConfig schema parses and validates correctly."""

    def test_default_config_round_trips(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        result = from_dict(AppConfig, raw)
        assert result.privacy.mode == "prefer_local"
        assert result.tts.voice == "default"
        assert result.providers.lmstudio.base_url == "http://localhost:1234/v1"
        assert result.droid.events.notification is True

    def test_invalid_privacy_mode(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["privacy"]["mode"] = "remote_only"
        with pytest.raises(SchemaValidationError, match="privacy.mode must be one of"):
            from_dict(AppConfig, raw)

    def test_invalid_tts_audio_format(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["tts"]["audio_format"] = "flac"
        with pytest.raises(SchemaValidationError, match="tts.audio_format must be one of"):
            from_dict(AppConfig, raw)

    def test_invalid_tts_play_audio(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["tts"]["play_audio"] = "yes"
        with pytest.raises(SchemaValidationError, match="tts.play_audio must be a boolean"):
            from_dict(AppConfig, raw)

    def test_invalid_logging_level(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["logging"]["level"] = "TRACE"
        with pytest.raises(SchemaValidationError, match="logging.level must be one of"):
            from_dict(AppConfig, raw)

    def test_invalid_logging_destination(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["logging"]["destination"] = "console"
        with pytest.raises(SchemaValidationError, match="logging.destination must be one of"):
            from_dict(AppConfig, raw)

    def test_invalid_fallback_fail_fast(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["fallback"]["fail_fast"] = "yes"
        with pytest.raises(SchemaValidationError, match="fallback.fail_fast must be a boolean"):
            from_dict(AppConfig, raw)

    def test_invalid_lmstudio_tts_mode(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["providers"]["lmstudio"]["tts_mode"] = "bad"
        with pytest.raises(SchemaValidationError, match="providers.lmstudio.tts_mode must be one of"):
            from_dict(AppConfig, raw)

    def test_invalid_summarizer_provider_order(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["summarization"]["provider_order"] = ["rule_based", "unknown"]
        with pytest.raises(SchemaValidationError, match=r"summarization.provider_order\[1\] must be one of"):
            from_dict(AppConfig, raw)

    def test_invalid_dedup_window_seconds_zero(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["dedup"]["window_seconds"] = "thirty"
        with pytest.raises(SchemaValidationError, match="dedup.window_seconds must be an integer"):
            from_dict(AppConfig, raw)

    def test_invalid_playback_queue_enabled(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["playback"]["queue_enabled"] = "yes"
        with pytest.raises(SchemaValidationError, match="playback.queue_enabled must be a boolean"):
            from_dict(AppConfig, raw)

    def test_invalid_event_sounds_unknown_key(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["event_sounds"]["files"]["unknown"] = "some_path"
        with pytest.raises(SchemaValidationError, match="must be one of"):
            from_dict(AppConfig, raw)

    def test_partial_config_uses_defaults(self):
        from speakup.config import AppConfig
        result = from_dict(AppConfig, {})
        assert result.playback.queue_enabled is True
        assert result.tts.speed == 1.0
        assert len(result.providers.kokoro_cli.args) > 0

    def test_valid_overrides(self):
        from speakup.config import AppConfig
        raw = {"tts": {"voice": "custom_voice", "speed": 1.5}}
        result = from_dict(AppConfig, raw)
        assert result.tts.voice == "custom_voice"
        assert result.tts.speed == 1.5
        # other sections get defaults
        assert result.privacy.mode == "prefer_local"

    def test_dedup_window_seconds_rejects_zero(self):
        """window_seconds uses Annotated[int, Gt(0)], so 0 should be rejected."""
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["dedup"]["window_seconds"] = 0
        with pytest.raises(SchemaValidationError, match="dedup.window_seconds must be greater than 0"):
            from_dict(AppConfig, raw)

    def test_dedup_window_seconds_rejects_negative(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["dedup"]["window_seconds"] = -5
        with pytest.raises(SchemaValidationError, match="dedup.window_seconds must be greater than 0"):
            from_dict(AppConfig, raw)

    def test_rotate_max_bytes_rejects_zero(self):
        from speakup.config import default_config, AppConfig
        raw = default_config()
        raw["logging"]["rotate_max_bytes"] = 0
        with pytest.raises(SchemaValidationError, match="logging.rotate_max_bytes must be greater than 0"):
            from_dict(AppConfig, raw)


# ---------------------------------------------------------------------------
# Annotated constraints (Gt, Ge)
# ---------------------------------------------------------------------------

class TestAnnotatedConstraints:
    """Tests for Annotated[type, Gt/Ge] constraint metadata."""

    def test_gt_accepts_value_above_bound(self):
        from typing import Annotated

        @dataclass
        class PositiveOnly:
            count: Annotated[int, Gt(0)] = 1

        result = from_dict(PositiveOnly, {"count": 5})
        assert result.count == 5

    def test_gt_rejects_value_at_bound(self):
        from typing import Annotated

        @dataclass
        class PositiveOnly:
            count: Annotated[int, Gt(0)] = 1

        with pytest.raises(SchemaValidationError, match="count must be greater than 0"):
            from_dict(PositiveOnly, {"count": 0})

    def test_gt_rejects_value_below_bound(self):
        from typing import Annotated

        @dataclass
        class PositiveOnly:
            count: Annotated[int, Gt(0)] = 1

        with pytest.raises(SchemaValidationError, match="count must be greater than 0"):
            from_dict(PositiveOnly, {"count": -3})

    def test_gt_still_validates_base_type(self):
        from typing import Annotated

        @dataclass
        class PositiveOnly:
            count: Annotated[int, Gt(0)] = 1

        with pytest.raises(SchemaValidationError, match="count must be an integer"):
            from_dict(PositiveOnly, {"count": "five"})

    def test_gt_uses_default_when_missing(self):
        from typing import Annotated

        @dataclass
        class PositiveOnly:
            count: Annotated[int, Gt(0)] = 10

        result = from_dict(PositiveOnly, {})
        assert result.count == 10

    def test_gt_works_with_float(self):
        from typing import Annotated

        @dataclass
        class Threshold:
            value: Annotated[float, Gt(0.0)] = 1.0

        result = from_dict(Threshold, {"value": 0.5})
        assert result.value == 0.5

        with pytest.raises(SchemaValidationError, match="value must be greater than"):
            from_dict(Threshold, {"value": 0.0})

