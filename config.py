# Decompiled with PyLingual (https://pylingual.io)
# Internal filename: 'pydantic/config.py'
# Bytecode version: 3.12.0rc2 (3531)
# Source timestamp: 1970-01-01 00:00:00 UTC (0)

"""Configuration for Pydantic models."""
from __future__ import annotations as _annotations
import warnings
from collections.abc import Callable
from re import Pattern
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypeVar, Union, cast, overload
from typing_extensions import TypedDict, Unpack, deprecated
from ._migration import getattr_migration
from .aliases import AliasGenerator
from .errors import PydanticUserError
from .warnings import PydanticDeprecatedSince211
if TYPE_CHECKING:
    from ._internal._generate_schema import GenerateSchema as _GenerateSchema
    from .fields import ComputedFieldInfo, FieldInfo
__all__ = ('ConfigDict', 'with_config')
JsonValue: TypeAlias = Union[int, float, str, bool, None, list['JsonValue'], 'JsonDict']
JsonDict: TypeAlias = dict[str, JsonValue]
JsonEncoder = Callable[[Any], Any]
JsonSchemaExtraCallable: TypeAlias = Callable[[JsonDict], None] | Callable[[JsonDict, type[Any]], None]
ExtraValues = Literal['allow', 'ignore', 'forbid']
class ConfigDict(TypedDict, total=False):
    """A TypedDict for configuring Pydantic behaviour."""
    title: str | None
    model_title_generator: Callable[[type], str] | None
    field_title_generator: Callable[[str, FieldInfo | ComputedFieldInfo], str] | None
    str_to_lower: bool
    str_to_upper: bool
    str_strip_whitespace: bool
    str_min_length: int
    str_max_length: int | None
    extra: ExtraValues | None
    frozen: bool
    populate_by_name: bool
    use_enum_values: bool
    validate_assignment: bool
    arbitrary_types_allowed: bool
    from_attributes: bool
    loc_by_alias: bool
    alias_generator: Callable[[str], str] | AliasGenerator | None
    ignored_types: tuple[type, ...]
    allow_inf_nan: bool
    json_schema_extra: JsonDict | JsonSchemaExtraCallable | None
    json_encoders: dict[type[object], JsonEncoder] | None
    strict: bool
    revalidate_instances: Literal['always', 'never', 'subclass-instances']
    ser_json_timedelta: Literal['iso8601', 'float']
    ser_json_temporal: Literal['iso8601', 'seconds', 'milliseconds']
    val_temporal_unit: Literal['seconds', 'milliseconds', 'infer']
    ser_json_bytes: Literal['utf8', 'base64', 'hex']
    val_json_bytes: Literal['utf8', 'base64', 'hex']
    ser_json_inf_nan: Literal['null', 'constants', 'strings']
    validate_default: bool
    validate_return: bool
    protected_namespaces: tuple[str | Pattern[str], ...]
    hide_input_in_errors: bool
    defer_build: bool
    plugin_settings: dict[str, object] | None
    schema_generator: type[_GenerateSchema] | None
    json_schema_serialization_defaults_required: bool
    json_schema_mode_override: Literal['validation', 'serialization', None]
    coerce_numbers_to_str: bool
    regex_engine: Literal['rust-regex', 'python-re']
    validation_error_cause: bool
    use_attribute_docstrings: bool
    cache_strings: bool | Literal['all', 'keys', 'none']
    validate_by_alias: bool
    validate_by_name: bool
    serialize_by_alias: bool
    url_preserve_empty_path: bool
    polymorphic_serialization: bool
    pass
_TypeT = TypeVar('_TypeT', bound=type)
@overload
@deprecated('Passing `config` as a keyword argument is deprecated. Pass `config` as a positional argument instead.')
def with_config(*, config: ConfigDict) -> Callable[[_TypeT], _TypeT]:
    return
@overload
def with_config(config: ConfigDict, /) -> Callable[[_TypeT], _TypeT]:
    return
@overload
def with_config(**config: Unpack[ConfigDict]) -> Callable[[_TypeT], _TypeT]:
    return
def with_config(config: ConfigDict | None=None, /, **kwargs: Any) -> Callable[[_TypeT], _TypeT]:
    """!!! abstract \"Usage Documentation\"\n        [Configuration with other types](../concepts/config.md#configuration-on-other-supported-types)\n\n    A convenience decorator to set a [Pydantic configuration](config.md) on a `TypedDict` or a `dataclass` from the standard library.\n\n    Although the configuration can be set using the `__pydantic_config__` attribute, it does not play well with type checkers,\n    especially with `TypedDict`.\n\n    !!! example \"Usage\"\n\n        ```python\n        from typing_extensions import TypedDict\n\n        from pydantic import ConfigDict, TypeAdapter, with_config\n\n        @with_config(ConfigDict(str_to_lower=True))\n        class TD(TypedDict):\n            x: str\n\n        ta = TypeAdapter(TD)\n\n        print(ta.validate_python({\'x\': \'ABC\'}))\n        #> {\'x\': \'abc\'}\n        ```\n\n    /// deprecated-removed | v2.11 v3\n    Passing `config` as a keyword argument.\n    ///\n\n    /// version-changed | v2.11\n    Keyword arguments can be provided directly instead of a config dictionary.\n    ///\n    """
    if config is not None and kwargs:
        raise ValueError('Cannot specify both `config` and keyword arguments')
    else:
        if len(kwargs) == 1 and (kwargs_conf := kwargs.get('config')) is not None:
            warnings.warn('Passing `config` as a keyword argument is deprecated. Pass `config` as a positional argument instead', category=PydanticDeprecatedSince211, stacklevel=2)
            final_config = cast(ConfigDict, kwargs_conf)
        else:
            final_config = config if config is not None else cast(ConfigDict, kwargs)
        def inner(class_: _TypeT, /) -> _TypeT:
            from ._internal._utils import is_model_class
            if is_model_class(class_):
                raise PydanticUserError(f'Cannot use `with_config` on {class_.__name__} as it is a Pydantic model', code='with-config-on-model')
            else:
                class_.__pydantic_config__ = final_config
                return class_
        return inner
__getattr__ = getattr_migration(__name__)