from __future__ import annotations

import dataclasses
import sys
import types
from typing import Annotated, Any, Literal, TypeVar, Union, get_args, get_origin, get_type_hints

T = TypeVar("T")


class SchemaValidationError(ValueError):
    """Raised when data fails to validate against a schema."""
    pass


# ---------------------------------------------------------------------------
# Annotation metadata markers for field-level constraints.
# Use with ``typing.Annotated``, e.g. ``Annotated[int, Gt(0)]``.
# ---------------------------------------------------------------------------

class Gt:
    """Marks a numeric field as requiring ``value > bound``."""
    def __init__(self, bound: int | float) -> None:
        self.bound = bound

    def validate(self, value: int | float, path: str) -> None:
        if value <= self.bound:
            raise SchemaValidationError(f"{path} must be greater than {self.bound}")


class Ge:
    """Marks a numeric field as requiring ``value >= bound``."""
    def __init__(self, bound: int | float) -> None:
        self.bound = bound

    def validate(self, value: int | float, path: str) -> None:
        if value < self.bound:
            raise SchemaValidationError(f"{path} must be at least {self.bound}")


def _resolve_type(type_hint: Any, value: Any, path: str) -> Any:
    origin = get_origin(type_hint)

    # Handle Annotated[X, ...metadata...]
    if origin is Annotated:
        args = get_args(type_hint)
        base_type = args[0]
        metadata = args[1:]
        result = _resolve_type(base_type, value, path)
        for meta in metadata:
            if hasattr(meta, "validate"):
                meta.validate(result, path)
        return result

    if origin is Literal:
        allowed = get_args(type_hint)
        if value not in allowed:
            raise SchemaValidationError(f"{path} must be one of {set(allowed)}")
        return value

    if type_hint is Any:
        return value

    if origin is list:
        if not isinstance(value, list):
            raise SchemaValidationError(f"{path} must be an array")
        arg_type = get_args(type_hint)[0]
        return [_resolve_type(arg_type, v, f"{path}[{i}]") for i, v in enumerate(value)]

    if origin is dict:
        if not isinstance(value, dict):
            raise SchemaValidationError(f"{path} must be an object")
        k_type, v_type = get_args(type_hint)
        return {
            _resolve_type(k_type, k, f"{path} key '{k}'"): _resolve_type(v_type, v, f"{path}.{k}")
            for k, v in value.items()
        }

    if dataclasses.is_dataclass(type_hint) and isinstance(type_hint, type):
        if not isinstance(value, dict):
            raise SchemaValidationError(f"{path} must be an object")
        return from_dict(type_hint, value, _prefix=f"{path}.")

    # Deal with Union types (e.g. str | None, int | float)
    _union_type = getattr(types, "UnionType", None)
    is_union = (
        origin is Union
        or (_union_type is not None and isinstance(type_hint, _union_type))
    )
    if is_union:
        args = get_args(type_hint)
        type_None = type(None)
        if type_None in args and value is None:
            return None

        last_err = None
        for arg in args:
            if arg is type_None:
                continue
            try:
                return _resolve_type(arg, value, path)
            except SchemaValidationError as e:
                last_err = e
                continue
        if last_err is not None:
            raise last_err
        raise SchemaValidationError(f"{path} has invalid type")

    # For primitive types
    if isinstance(type_hint, type):
        if type_hint is float and isinstance(value, int):
            return float(value)
        if type_hint is int and isinstance(value, bool):
            raise SchemaValidationError(f"{path} must be an integer")
        if not isinstance(value, type_hint):
            if type_hint is int:
                raise SchemaValidationError(f"{path} must be an integer")
            if type_hint is str:
                raise SchemaValidationError(f"{path} must be a string")
            if type_hint is bool:
                raise SchemaValidationError(f"{path} must be a boolean")
            raise SchemaValidationError(f"{path} must be of type {type_hint.__name__}")

    return value


def from_dict(cls: type[T], data: dict[str, Any], _prefix: str = "") -> T:
    """
    Parses and validates a dictionary into a specified dataclass type.

    Recursively resolves nested dataclasses, validates primitive types,
    ``typing.Literal`` constraints, ``list``/``dict`` generics,
    ``Union`` (including ``Optional``), and ``Annotated`` metadata
    constraints. Raises ``SchemaValidationError`` with a dot-path
    on failure.
    """
    if not isinstance(data, dict):
        path_label = _prefix.rstrip(".") or "root"
        raise SchemaValidationError(f"{path_label} must be an object")

    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"Class {cls.__name__} is not a dataclass")

    # Resolve string annotations to real types via get_type_hints.
    # This is necessary when modules use `from __future__ import annotations`.
    resolved_hints = get_type_hints(cls, include_extras=True)

    init_kwargs: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        field_name = field.name
        path = f"{_prefix}{field_name}"
        field_type = resolved_hints[field_name]

        if field_name not in data:
            if field.default is not dataclasses.MISSING:
                init_kwargs[field_name] = field.default
            elif field.default_factory is not dataclasses.MISSING:
                init_kwargs[field_name] = field.default_factory()
            else:
                raise SchemaValidationError(f"Missing required field: {path}")
            continue

        value = data[field_name]
        init_kwargs[field_name] = _resolve_type(field_type, value, path)

    return cls(**init_kwargs)
