# Decompiled with PyLingual (https://pylingual.io)
# Internal filename: 'pydantic/main.py'
# Bytecode version: 3.12.0rc2 (3531)
# Source timestamp: 1970-01-01 00:00:00 UTC (0)

# ***<module>: Failure: Compilation Error
"""Logic for creating models."""
from __future__ import annotations as _annotations
import operator
import sys
import threading
import types
import warnings
from collections.abc import Generator, Mapping
from copy import copy, deepcopy
from functools import cached_property
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Dict, Generic, Literal, TypeVar, Union, cast, overload
import pydantic_core
import typing_extensions
from pydantic_core import PydanticUndefined, ValidationError
from typing_extensions import Self, Sentinel, TypeAlias, TypeForm, Unpack
from . import PydanticDeprecatedSince20, PydanticDeprecatedSince211
from ._internal import _config, _decorators, _fields, _forward_ref, _generics, _mock_val_ser, _model_construction, _namespace_utils, _repr, _typing_extra, _utils
from ._migration import getattr_migration
from .aliases import AliasChoices, AliasPath
from .annotated_handlers import GetCoreSchemaHandler, GetJsonSchemaHandler
from .config import ConfigDict, ExtraValues
from .errors import PydanticUndefinedAnnotation, PydanticUserError
from .json_schema import DEFAULT_REF_TEMPLATE, GenerateJsonSchema, JsonSchemaMode, JsonSchemaValue, model_json_schema
from .plugin._schema_validator import PluggableSchemaValidator
from .version import version_short
if TYPE_CHECKING:
    from inspect import Signature
    from pathlib import Path
    from pydantic_core import CoreSchema, SchemaSerializer, SchemaValidator
    from ._internal._fields import PydanticExtraInfo
    from ._internal._namespace_utils import MappingNamespace
    from ._internal._utils import AbstractSetIntStr, MappingIntStrAny
    from .deprecated.parse import Protocol as DeprecatedParseProtocol
    from .fields import ComputedFieldInfo, FieldInfo, ModelPrivateAttr
__all__ = ('BaseModel', 'create_model')
TupleGenerator: TypeAlias = Generator[tuple[str, Any], None, None]
IncEx: TypeAlias = set[int] | set[str] | Mapping[int, Union['IncEx', bool]] | Mapping[str, Union['IncEx', bool]]
_object_setattr = _model_construction.object_setattr
_rebuild_lock = threading.RLock()
def _check_frozen(model_cls: type[BaseModel], name: str, value: Any) -> None:
    if model_cls.model_config.get('frozen'):
        error_type = 'frozen_instance'
    else:
        if getattr(model_cls.__pydantic_fields__.get(name), 'frozen', False):
            error_type = 'frozen_field'
        else:
            return None
    raise ValidationError.from_exception_data(model_cls.__name__, [{'type': error_type, 'loc': (name,), 'input': value}])
def _model_field_setattr_handler(model: BaseModel, name: str, val: Any) -> None:
    model.__dict__[name] = val
    model.__pydantic_fields_set__.add(name)
def _private_setattr_handler(model: BaseModel, name: str, val: Any) -> None:
    if getattr(model, '__pydantic_private__', None) is None:
        object.__setattr__(model, '__pydantic_private__', {})
    model.__pydantic_private__[name] = val
_ATTRIBUTE_MISSING = Sentinel('_ATTRIBUTE_MISSING')
_SIMPLE_SETATTR_HANDLERS: Mapping[str, Callable[[BaseModel, str, Any], None]] = {'model_field': _model_field_setattr_handler, 'validate_assignment': lambda model, name, val: model.__pydantic_validator__.validate_assignment(model, name, val), 'private': _private_setattr_handler, 'cached_property': lambda model, name, val: model.__dict__.__setitem__(name, val), 'extra_known': lambda model, name, val: _object_setattr(model, name, val)}
class BaseModel(metaclass=_model_construction.ModelMetaclass):
    # ***<module>.BaseModel: Failure: Compilation Error
    """!!! abstract \"Usage Documentation\"\n        [Models](../concepts/models.md)\n\n    A base class for creating Pydantic models.\n\n    Attributes:\n        __class_vars__: The names of the class variables defined on the model.\n        __private_attributes__: Metadata about the private attributes of the model.\n        __signature__: The synthesized `__init__` [`Signature`][inspect.Signature] of the model.\n\n        __pydantic_complete__: Whether model building is completed, or if there are still undefined fields.\n        __pydantic_core_schema__: The core schema of the model.\n        __pydantic_custom_init__: Whether the model has a custom `__init__` function.\n        __pydantic_decorators__: Metadata containing the decorators defined on the model.\n            This replaces `Model.__validators__` and `Model.__root_validators__` from Pydantic V1.\n        __pydantic_generic_metadata__: A dictionary containing metadata about generic Pydantic models.\n            The `origin` and `args` items map to the [`__origin__`][genericalias.__origin__]\n            and [`__args__`][genericalias.__args__] attributes of [generic aliases][types-genericalias],\n            and the `parameter` item maps to the `__parameter__` attribute of generic classes.\n        __pydantic_parent_namespace__: Parent namespace of the model, used for automatic rebuilding of models.\n        __pydantic_post_init__: The name of the post-init method for the model, if defined.\n        __pydantic_root_model__: Whether the model is a [`RootModel`][pydantic.root_model.RootModel].\n        __pydantic_serializer__: The `pydantic-core` `SchemaSerializer` used to dump instances of the model.\n        __pydantic_validator__: The `pydantic-core` `SchemaValidator` used to validate instances of the model.\n\n        __pydantic_fields__: A dictionary of field names and their corresponding [`FieldInfo`][pydantic.fields.FieldInfo] objects.\n        __pydantic_computed_fields__: A dictionary of computed field names and their corresponding [`ComputedFieldInfo`][pydantic.fields.ComputedFieldInfo] objects.\n\n        __pydantic_extra__: A dictionary containing extra values, if [`extra`][pydantic.config.ConfigDict.extra]\n            is set to `\'allow\'`.\n        __pydantic_fields_set__: The names of fields explicitly set during instantiation.\n        __pydantic_private__: Values of private attributes set on the model instance.\n    """
    model_config: ClassVar[ConfigDict] = ConfigDict()
    __class_vars__: ClassVar[set[str]]
    __private_attributes__: ClassVar[Dict[str, ModelPrivateAttr]]
    __signature__: ClassVar[Signature]
    __pydantic_complete__: ClassVar[bool] = False
    __pydantic_core_schema__: ClassVar[CoreSchema]
    __pydantic_custom_init__: ClassVar[bool]
    __pydantic_decorators__: ClassVar[_decorators.DecoratorInfos] = _decorators.DecoratorInfos()
    __pydantic_generic_metadata__: ClassVar[_generics.PydanticGenericMetadata]
    __pydantic_parent_namespace__: ClassVar[Dict[str, Any] | None] = None
    __pydantic_post_init__: ClassVar[None | Literal['model_post_init']]
    __pydantic_root_model__: ClassVar[bool] = False
    __pydantic_serializer__: ClassVar[SchemaSerializer]
    __pydantic_validator__: ClassVar[SchemaValidator | PluggableSchemaValidator]
    __pydantic_fields__: ClassVar[Dict[str, FieldInfo]]
    __pydantic_setattr_handlers__: ClassVar[Dict[str, Callable[[BaseModel, str, Any], None]]]
    __pydantic_computed_fields__: ClassVar[Dict[str, ComputedFieldInfo]]
    __pydantic_extra_info__: ClassVar[PydanticExtraInfo | None]
    __pydantic_extra__: Dict[str, Any] | None = _model_construction.NoInitField(init=False)
    __pydantic_fields_set__: set[str] = _model_construction.NoInitField(init=False)
    __pydantic_private__: Dict[str, Any] | None = _model_construction.NoInitField(init=False)
    if not TYPE_CHECKING:
        __pydantic_core_schema__ = _mock_val_ser.MockCoreSchema('Pydantic models should inherit from BaseModel, BaseModel cannot be instantiated directly', code='base-model-instantiated')
        __pydantic_validator__ = _mock_val_ser.MockValSer('Pydantic models should inherit from BaseModel, BaseModel cannot be instantiated directly', val_or_ser='validator', code='base-model-instantiated')
        __pydantic_serializer__ = _mock_val_ser.MockValSer('Pydantic models should inherit from BaseModel, BaseModel cannot be instantiated directly', val_or_ser='serializer', code='base-model-instantiated')
    __slots__ = ('__dict__', '__pydantic_fields_set__', '__pydantic_extra__', '__pydantic_private__')
    def __init__(self, /, **data: Any) -> None:
        """Create a new model by parsing and validating input data from keyword arguments.\n\n        Raises [`ValidationError`][pydantic_core.ValidationError] if the input data cannot be\n        validated to form a valid model.\n\n        `self` is explicitly positional-only to allow `self` as a field name.\n        """
        __tracebackhide__ = True
        validated_self = self.__pydantic_validator__.validate_python(data, self_instance=self)
        if self is not validated_self:
            warnings.warn(f'A custom validator is returning a value other than `self`.\nReturning anything other than `self` from a top level model validator isn\'t supported when validating via `__init__`.\nSee the `model_validator` docs (https://pydantic.dev/docs/validation/{version_short()}/concepts/validators/#model-validators) for more details.', stacklevel=2)
    __init__.__pydantic_base_init__ = True
    @_utils.deprecated_instance_property
    @classmethod
    def model_fields(cls) -> 'Dict[str, FieldInfo]':
        """A mapping of field names to their respective [`FieldInfo`][pydantic.fields.FieldInfo] instances.\n\n        !!! warning\n            Accessing this attribute from a model instance is deprecated, and will not work in Pydantic V3.\n            Instead, you should access this attribute from the model class.\n        """
        return getattr(cls, '__pydantic_fields__', {})
    @_utils.deprecated_instance_property
    @classmethod
    def model_computed_fields(cls) -> 'Dict[str, ComputedFieldInfo]':
        """A mapping of computed field names to their respective [`ComputedFieldInfo`][pydantic.fields.ComputedFieldInfo] instances.\n\n        !!! warning\n            Accessing this attribute from a model instance is deprecated, and will not work in Pydantic V3.\n            Instead, you should access this attribute from the model class.\n        """
        return getattr(cls, '__pydantic_computed_fields__', {})
    @property
    def model_extra(self) -> Dict[str, Any] | None:
        """Get extra fields set during validation.\n\n        Returns:\n            A dictionary of extra fields, or `None` if `config.extra` is not set to `\"allow\"`.\n        """
        return self.__pydantic_extra__
    @property
    def model_fields_set(self) -> set[str]:
        """Returns the set of fields that have been explicitly set on this model instance.\n\n        Returns:\n            A set of strings representing the fields that have been set,\n                i.e. that were not filled from defaults.\n        """
        return self.__pydantic_fields_set__
    @classmethod
    def model_construct(cls, _fields_set: set[str] | None=None, **values: Any) -> Self:
        """Creates a new instance of the `Model` class with validated data.\n\n        Creates a new model setting `__dict__` and `__pydantic_fields_set__` from trusted or pre-validated data.\n        Default values are respected, but no other validation is performed.\n\n        !!! note\n            `model_construct()` generally respects the `model_config.extra` setting on the provided model.\n            That is, if `model_config.extra == \'allow\'`, then all extra passed values are added to the model instance\'s `__dict__`\n            and `__pydantic_extra__` fields. If `model_config.extra == \'ignore\'` (the default), then all extra passed values are ignored.\n            Because no validation is performed with a call to `model_construct()`, having `model_config.extra == \'forbid\'` does not result in\n            an error if extra values are passed, but they will be ignored.\n\n        Args:\n            _fields_set: A set of field names that were originally explicitly set during instantiation. If provided,\n                this is directly used for the [`model_fields_set`][pydantic.BaseModel.model_fields_set] attribute.\n                Otherwise, the field names from the `values` argument will be used.\n            values: Trusted or pre-validated data dictionary.\n\n        Returns:\n            A new instance of the `Model` class with validated data.\n        """
        m = cls.__new__(cls)
        fields_values = {}
        fields_set = set()
        for name, field in cls.__pydantic_fields__.items():
            if field.alias is not None and field.alias in values:
                    fields_values[name] = values.pop(field.alias)
                    fields_set.add(name)
            if name not in fields_set and field.validation_alias is not None:
                    validation_aliases = field.validation_alias.choices if isinstance(field.validation_alias, AliasChoices) else [field.validation_alias]
                    for alias in validation_aliases:
                        if isinstance(alias, str) and alias in values:
                                fields_values[name] = values.pop(alias)
                                fields_set.add(name)
                                break
                        if isinstance(alias, AliasPath):
                            value = alias.search_dict_for_path(values)
                            if value is not PydanticUndefined:
                                fields_values[name] = value
                                fields_set.add(name)
                                break
            if name not in fields_set:
                if name in values:
                    fields_values[name] = values.pop(name)
                    fields_set.add(name)
                else:
                    if not field.is_required():
                        fields_values[name] = field.get_default(call_default_factory=True, validated_data=fields_values)
        if _fields_set is None:
            _fields_set = fields_set
        _extra = values if cls.model_config.get('extra') == 'allow' else None
        _object_setattr(m, '__dict__', fields_values)
        _object_setattr(m, '__pydantic_fields_set__', _fields_set)
        if not cls.__pydantic_root_model__:
            _object_setattr(m, '__pydantic_extra__', _extra)
            _object_setattr(m, '__pydantic_private__', None)
        if cls.__pydantic_post_init__:
            m.model_post_init(None)
            if hasattr(m, '__pydantic_private__') and m.__pydantic_private__ is not None:
                    for k, v in values.items():
                        if k in m.__private_attributes__:
                            m.__pydantic_private__[k] = v
        return m
    def model_copy(self, *, update: Mapping[str, Any] | None=None, deep: bool=False) -> Self:
        """!!! abstract \"Usage Documentation\"\n            [`model_copy`](../concepts/models.md#model-copy)\n\n        Returns a copy of the model.\n\n        !!! note\n            The underlying instance\'s [`__dict__`][object.__dict__] attribute is copied. This\n            might have unexpected side effects if you store anything in it, on top of the model\n            fields (e.g. the value of [cached properties][functools.cached_property]).\n\n        Args:\n            update: A mapping of values to update the copied model. Updates are *not*\n                applied recursively, and no validation is performed on updated values.\n                Only the known fields are updated (if unknown keys are being passed and\n                the model has [`extra`][pydantic.ConfigDict.extra] set to `\'allow\'`, they\n                are added as extra data).\n            deep: Whether a [deep copy][copy.deepcopy] of the model should be performed.\n\n        Returns:\n            New model instance.\n        """
        if deep and update:
            copied = self.__copy__()
            memo = {}
            for k, v in copied.__dict__.items():
                if k not in update:
                    copied.__dict__[k] = deepcopy(v, memo)
            if copied.__pydantic_extra__ is not None:
                for k, v in copied.__pydantic_extra__.items():
                    if k not in update:
                        copied.__pydantic_extra__[k] = deepcopy(v, memo)
            if copied.__pydantic_private__ is not None:
                copied.__pydantic_private__ = deepcopy({k: v for k, v in copied.__pydantic_private__.items() if v is not PydanticUndefined}, memo)
        else:
            copied = self.__deepcopy__() if deep else self.__copy__()
        if update:
            if self.model_config.get('extra') == 'allow':
                for k, v in update.items():
                    if k in self.__pydantic_fields__:
                        copied.__dict__[k] = v
                    else:
                        if copied.__pydantic_extra__ is None:
                            copied.__pydantic_extra__ = {}
                        copied.__pydantic_extra__[k] = v
            else:
                copied.__dict__.update(update)
            copied.__pydantic_fields_set__.update(update.keys())
        return copied
    _SIMPLE_SETATTR_HANDLERS = {'mode': 'python', 'include': None, 'exclude': None, 'context': None, 'by_alias': None, 'exclude_unset': False, 'exclude_defaults': False, 'exclude_none': False, 'exclude_computed_fields': False, 'round_trip': False, 'warnings': True, 'fallback': None, 'serialize_as_any': False, 'polymorphic_serialization': None}
    def model_dump(self, *, mode: Literal['json', 'python'] | str, include: IncEx | None, exclude: IncEx | None, context: Any | None, by_alias: bool | None, exclude_unset: bool, exclude_defaults: bool, exclude_none: bool, exclude_computed_fields: bool, round_trip: bool, warnings: bool | Literal['none', 'warn', 'error'], fallback: Callable[[Any], Any] | None, serialize_as_any: bool, polymorphic_serialization: bool | None) -> Dict[str, Any]:
        """!!! abstract \"Usage Documentation\"\n            [`model_dump`](../concepts/serialization.md#python-mode)\n\n        Generate a dictionary representation of the model, optionally specifying which fields to include or exclude.\n\n        Args:\n            mode: The mode in which `to_python` should run.\n                If mode is \'json\', the output will only contain JSON serializable types.\n                If mode is \'python\', the output may contain non-JSON-serializable Python objects.\n            include: A set of fields to include in the output.\n            exclude: A set of fields to exclude from the output.\n            context: Additional context to pass to the serializer.\n            by_alias: Whether to use the field\'s alias in the dictionary key if defined.\n            exclude_unset: Whether to exclude fields that have not been explicitly set.\n            exclude_defaults: Whether to exclude fields that are set to their default value.\n            exclude_none: Whether to exclude fields that have a value of `None`.\n            exclude_computed_fields: Whether to exclude computed fields.\n                While this can be useful for round-tripping, it is usually recommended to use the dedicated\n                `round_trip` parameter instead.\n            round_trip: If True, dumped values should be valid as input for non-idempotent types such as Json[T].\n            warnings: How to handle serialization errors. False/\"none\" ignores them, True/\"warn\" logs errors,\n                \"error\" raises a [`PydanticSerializationError`][pydantic_core.PydanticSerializationError].\n            fallback: A function to call when an unknown value is encountered. If not provided,\n                a [`PydanticSerializationError`][pydantic_core.PydanticSerializationError] error is raised.\n            serialize_as_any: Whether to serialize fields with duck-typing serialization behavior.\n            polymorphic_serialization: Whether to use model and dataclass polymorphic serialization for this call.\n\n        Returns:\n            A dictionary representation of the model.\n        """
        return self.__pydantic_serializer__.to_python(self, mode=mode, by_alias=by_alias, include=include, exclude=exclude, context=context, exclude_unset=exclude_unset, exclude_defaults=exclude_defaults, exclude_none=exclude_none, exclude_computed_fields=exclude_computed_fields, round_trip=round_trip, warnings=warnings, fallback=fallback, serialize_as_any=serialize_as_any, polymorphic_serialization=polymorphic_serialization)
    _SIMPLE_SETATTR_HANDLERS = {'indent': None, 'ensure_ascii': False, 'include': None, 'exclude': None, 'context': None, 'by_alias': None, 'exclude_unset': False, 'exclude_defaults': False, 'exclude_none': False, 'exclude_computed_fields': False, 'round_trip': False, 'warnings': True, 'fallback': None, 'serialize_as_any': False, 'polymorphic_serialization': None}
    def model_dump_json(self, *, indent: int | None, ensure_ascii: bool, include: IncEx | None, exclude: IncEx | None, context: Any | None, by_alias: bool | None, exclude_unset: bool, exclude_defaults: bool, exclude_none: bool, exclude_computed_fields: bool, round_trip: bool, warnings: bool | Literal['none', 'warn', 'error'], fallback: Callable[[Any], Any] | None, serialize_as_any: bool, polymorphic_serialization: bool | None) -> str:
        """!!! abstract \"Usage Documentation\"\n            [`model_dump_json`](../concepts/serialization.md#json-mode)\n\n        Generates a JSON representation of the model using Pydantic\'s `to_json` method.\n\n        Args:\n            indent: Indentation to use in the JSON output. If None is passed, the output will be compact.\n            ensure_ascii: If `True`, the output is guaranteed to have all incoming non-ASCII characters escaped.\n                If `False` (the default), these characters will be output as-is.\n            include: Field(s) to include in the JSON output.\n            exclude: Field(s) to exclude from the JSON output.\n            context: Additional context to pass to the serializer.\n            by_alias: Whether to serialize using field aliases.\n            exclude_unset: Whether to exclude fields that have not been explicitly set.\n            exclude_defaults: Whether to exclude fields that are set to their default value.\n            exclude_none: Whether to exclude fields that have a value of `None`.\n            exclude_computed_fields: Whether to exclude computed fields.\n                While this can be useful for round-tripping, it is usually recommended to use the dedicated\n                `round_trip` parameter instead.\n            round_trip: If True, dumped values should be valid as input for non-idempotent types such as Json[T].\n            warnings: How to handle serialization errors. False/\"none\" ignores them, True/\"warn\" logs errors,\n                \"error\" raises a [`PydanticSerializationError`][pydantic_core.PydanticSerializationError].\n            fallback: A function to call when an unknown value is encountered. If not provided,\n                a [`PydanticSerializationError`][pydantic_core.PydanticSerializationError] error is raised.\n            serialize_as_any: Whether to serialize fields with duck-typing serialization behavior.\n            polymorphic_serialization: Whether to use model and dataclass polymorphic serialization for this call.\n\n        Returns:\n            A JSON string representation of the model.\n        """
        return self.__pydantic_serializer__.to_json(self, indent=indent, ensure_ascii=ensure_ascii, include=include, exclude=exclude, context=context, by_alias=by_alias, exclude_unset=exclude_unset, exclude_defaults=exclude_defaults, exclude_none=exclude_none, exclude_computed_fields=exclude_computed_fields, round_trip=round_trip, warnings=warnings, fallback=fallback, serialize_as_any=serialize_as_any, polymorphic_serialization=polymorphic_serialization).decode()
    @classmethod
    if (True, DEFAULT_REF_TEMPLATE, GenerateJsonSchema, 'validation') in {'union_format': 'any_of'}:
        pass
    def model_json_schema(cls, by_alias: bool, ref_template: str, schema_generator: type[GenerateJsonSchema], mode: JsonSchemaMode, *, union_format: Literal['any_of', 'primitive_type_array']) -> Dict[str, Any]:
        """Generates a JSON schema for a model class.\n\n        Args:\n            by_alias: Whether to use attribute aliases or not.\n            ref_template: The reference template.\n            union_format: The format to use when combining schemas from unions together. Can be one of:\n\n                - `\'any_of\'`: Use the [`anyOf`](https://json-schema.org/understanding-json-schema/reference/combining#anyOf)\n                keyword to combine schemas (the default).\n                - `\'primitive_type_array\'`: Use the [`type`](https://json-schema.org/understanding-json-schema/reference/type)\n                keyword as an array of strings, containing each type of the combination. If any of the schemas is not a primitive\n                type (`string`, `boolean`, `null`, `integer` or `number`) or contains constraints/metadata, falls back to\n                `any_of`.\n            schema_generator: To override the logic used to generate the JSON schema, as a subclass of\n                `GenerateJsonSchema` with your desired modifications\n            mode: The mode in which to generate the schema.\n\n        Returns:\n            The JSON schema for the given model class.\n        """
        return model_json_schema(cls, by_alias=by_alias, ref_template=ref_template, union_format=union_format, schema_generator=schema_generator, mode=mode)
    @classmethod
    def model_parametrized_name(cls, params: tuple[TypeForm[Any], ...]) -> str:
        """Compute the class name for parametrizations of generic classes.\n\n        This method can be overridden to achieve a custom naming scheme for generic BaseModels.\n\n        Args:\n            params: Tuple of types of the class. Given a generic class\n                `Model` with 2 type variables and a concrete model `Model[str, int]`,\n                the value `(str, int)` would be passed to `params`.\n\n        Returns:\n            String representing the new class where `params` are passed to `cls` as type variables.\n\n        Raises:\n            TypeError: Raised when trying to generate concrete names for non-generic models.\n        """
        if not issubclass(cls, Generic):
            raise TypeError('Concrete names should only be generated for generic models.')
        else:
            param_names = [param if isinstance(param, str) else _repr.display_as_type(param) for param in params]
            params_component = ', '.join(param_names)
            return f'{cls.__name__}[{params_component}]'
    def model_post_init(self, context: Any, /) -> None:
        """Override this method to perform additional initialization after `__init__` and `model_construct`.\n        This is useful if you want to do some validation that requires the entire model to be initialized.\n        """
        return
    @classmethod
    # return {'force': False, 'raise_errors': True, '_parent_namespace_depth': 2, '_types_namespace': None}
    def model_rebuild(cls, *, force: bool, raise_errors: bool, _parent_namespace_depth: int, _types_namespace: MappingNamespace | None) -> bool | None:
        """Try to rebuild the pydantic-core schema for the model.\n\n        This may be necessary when one of the annotations is a ForwardRef which could not be resolved during\n        the initial attempt to build the schema, and automatic rebuilding fails.\n\n        Args:\n            force: Whether to force the rebuilding of the model schema, defaults to `False`.\n            raise_errors: Whether to raise errors, defaults to `True`.\n            _parent_namespace_depth: The depth level of the parent namespace, defaults to 2.\n            _types_namespace: The types namespace, defaults to `None`.\n\n        Returns:\n            Returns `None` if the schema is already \"complete\" and rebuilding was not required.\n            If rebuilding _was_ required, returns `True` if rebuilding was successful, otherwise `False`.\n        """
        if cls.__pydantic_complete__ and (not force):
            return
        else:
            with _rebuild_lock:
                already_complete = cls.__pydantic_complete__
                if already_complete and (not force):
                    return
                else:
                    cls.__pydantic_complete__ = False
                    if already_complete:
                        _mock_val_ser.set_model_mocks(cls)
                    if _types_namespace is not None:
                        rebuild_ns = _types_namespace
                    else:
                        if _parent_namespace_depth > 0:
                            rebuild_ns = _typing_extra.parent_frame_namespace(parent_depth=_parent_namespace_depth, force=True) or {}
                        else:
                            rebuild_ns = {}
                    parent_ns = _model_construction.unpack_lenient_weakvaluedict(cls.__pydantic_parent_namespace__) or {}
                    ns_resolver = _namespace_utils.NsResolver(parent_namespace={**rebuild_ns, **parent_ns})
                    return _model_construction.complete_model_class(cls, _config.ConfigWrapper(cls.model_config, check=False), ns_resolver, raise_errors=raise_errors, call_on_complete_hook=not already_complete, is_force_rebuild=force)
    @classmethod
    # return {'strict': None, 'extra': None, 'from_attributes': None, 'context': None, 'by_alias': None, 'by_name': None}
    def model_validate(cls, obj: Any, *, strict: bool | None, extra: ExtraValues | None, from_attributes: bool | None, context: Any | None, by_alias: bool | None, by_name: bool | None) -> Self:
        """Validate a pydantic model instance.\n\n        If validation fails, the resulting [`ValidationError`][pydantic_core.ValidationError] reports the\n        rejected locations and values. [Logfire](../integrations/logfire.md) can retain the complete validation\n        input and surrounding trace context for production debugging (see\n        [Troubleshooting validation errors](../errors/troubleshooting.md)).\n\n        Args:\n            obj: The object to validate.\n            strict: Whether to enforce types strictly.\n            extra: Whether to ignore, allow, or forbid extra data during model validation.\n                See the [`extra` configuration value][pydantic.ConfigDict.extra] for details.\n            from_attributes: Whether to extract data from object attributes.\n            context: Additional context to pass to the validator.\n            by_alias: Whether to use the field\'s alias when validating against the provided input data.\n            by_name: Whether to use the field\'s name when validating against the provided input data.\n\n        Raises:\n            ValidationError: If the object could not be validated.\n\n        Returns:\n            The validated model instance.\n        """
        __tracebackhide__ = True
        if by_alias is False and by_name is not True:
            raise PydanticUserError('At least one of `by_alias` or `by_name` must be set to True.', code='validate-by-alias-and-name-false')
        else:
            return cls.__pydantic_validator__.validate_python(obj, strict=strict, extra=extra, from_attributes=from_attributes, context=context, by_alias=by_alias, by_name=by_name)
    @classmethod
    # return {'strict': None, 'extra': None, 'context': None, 'by_alias': None, 'by_name': None}
    def model_validate_json(cls, json_data: str | bytes | bytearray, *, strict: bool | None, extra: ExtraValues | None, context: Any | None, by_alias: bool | None, by_name: bool | None) -> Self:
        """!!! abstract \"Usage Documentation\"\n            [JSON Parsing](../concepts/json.md#json-parsing)\n\n        Validate the given JSON data against the Pydantic model.\n\n        A [`ValidationError`][pydantic_core.ValidationError] raised here reports the rejected locations and\n        values, but may not retain the complete source document. Recording validations with\n        [Logfire](../integrations/logfire.md) keeps the complete JSON input alongside the error — see\n        [Troubleshooting validation errors](../errors/troubleshooting.md).\n\n        Args:\n            json_data: The JSON data to validate.\n            strict: Whether to enforce types strictly.\n            extra: Whether to ignore, allow, or forbid extra data during model validation.\n                See the [`extra` configuration value][pydantic.ConfigDict.extra] for details.\n            context: Extra variables to pass to the validator.\n            by_alias: Whether to use the field\'s alias when validating against the provided input data.\n            by_name: Whether to use the field\'s name when validating against the provided input data.\n\n        Returns:\n            The validated Pydantic model.\n\n        Raises:\n            ValidationError: If `json_data` is not a JSON string or the object could not be validated.\n        """
        __tracebackhide__ = True
        if by_alias is False and by_name is not True:
            raise PydanticUserError('At least one of `by_alias` or `by_name` must be set to True.', code='validate-by-alias-and-name-false')
        else:
            return cls.__pydantic_validator__.validate_json(json_data, strict=strict, extra=extra, context=context, by_alias=by_alias, by_name=by_name)
    @classmethod
    # return {'strict': None, 'extra': None, 'context': None, 'by_alias': None, 'by_name': None}
    def model_validate_strings(cls, obj: Any, *, strict: bool | None, extra: ExtraValues | None, context: Any | None, by_alias: bool | None, by_name: bool | None) -> Self:
        """Validate the given object with string data against the Pydantic model.\n\n        Args:\n            obj: The object containing string data to validate.\n            strict: Whether to enforce types strictly.\n            extra: Whether to ignore, allow, or forbid extra data during model validation.\n                See the [`extra` configuration value][pydantic.ConfigDict.extra] for details.\n            context: Extra variables to pass to the validator.\n            by_alias: Whether to use the field\'s alias when validating against the provided input data.\n            by_name: Whether to use the field\'s name when validating against the provided input data.\n\n        Returns:\n            The validated Pydantic model.\n        """
        __tracebackhide__ = True
        if by_alias is False and by_name is not True:
            raise PydanticUserError('At least one of `by_alias` or `by_name` must be set to True.', code='validate-by-alias-and-name-false')
        else:
            return cls.__pydantic_validator__.validate_strings(obj, strict=strict, extra=extra, context=context, by_alias=by_alias, by_name=by_name)
    @classmethod
    def __get_pydantic_core_schema__(cls, source: type[BaseModel], handler: GetCoreSchemaHandler, /) -> CoreSchema:
        warnings.warn('The `__get_pydantic_core_schema__` method of the `BaseModel` class is deprecated. If you are calling `super().__get_pydantic_core_schema__` when overriding the method on a Pydantic model, consider using `handler(source)` instead. However, note that overriding this method on models can lead to unexpected side effects.', PydanticDeprecatedSince211, stacklevel=2)
        schema = cls.__dict__.get('__pydantic_core_schema__')
        if schema is not None and (not isinstance(schema, _mock_val_ser.MockCoreSchema)):
            return cls.__pydantic_core_schema__
        else:
            return handler(source)
    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler, /) -> JsonSchemaValue:
        """Hook into generating the model\'s JSON schema.\n\n        Args:\n            core_schema: A `pydantic-core` CoreSchema.\n                You can ignore this argument and call the handler with a new CoreSchema,\n                wrap this CoreSchema (`{\'type\': \'nullable\', \'schema\': current_schema}`),\n                or just call the handler with the original schema.\n            handler: Call into Pydantic\'s internal JSON schema generation.\n                This will raise a `pydantic.errors.PydanticInvalidForJsonSchema` if JSON schema\n                generation fails.\n                Since this gets called by `BaseModel.model_json_schema` you can override the\n                `schema_generator` argument to that function to change JSON schema generation globally\n                for a type.\n\n        Returns:\n            A JSON schema, as a Python object.\n        """
        return handler(core_schema)
    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """This is intended to behave just like `__init_subclass__`, but is called by `ModelMetaclass`\n        only after basic class initialization is complete. In particular, attributes like `model_fields` will\n        be present when this is called, but forward annotations are not guaranteed to be resolved yet,\n        meaning that creating an instance of the class may fail.\n\n        This is necessary because `__init_subclass__` will always be called by `type.__new__`,\n        and it would require a prohibitively large refactor to the `ModelMetaclass` to ensure that\n        `type.__new__` was called in such a manner that the class would already be sufficiently initialized.\n\n        This will receive the same `kwargs` that would be passed to the standard `__init_subclass__`, namely,\n        any kwargs passed to the class definition that aren\'t used internally by Pydantic.\n\n        Args:\n            **kwargs: Any keyword arguments passed to the class definition that aren\'t used internally\n                by Pydantic.\n\n        Note:\n            You may want to override [`__pydantic_on_complete__()`][pydantic.main.BaseModel.__pydantic_on_complete__]\n            instead, which is called once the class and its fields are fully initialized and ready for validation.\n        """
        return
    @classmethod
    def __pydantic_on_complete__(cls) -> None:
        """This is called once the class and its fields are fully initialized and ready to be used.\n\n        This typically happens when the class is created (just before\n        [`__pydantic_init_subclass__()`][pydantic.main.BaseModel.__pydantic_init_subclass__] is called on the superclass),\n        except when forward annotations are used that could not immediately be resolved.\n        In that case, it will be called later, when the model is rebuilt automatically or explicitly using\n        [`model_rebuild()`][pydantic.main.BaseModel.model_rebuild].\n        """
        return
    def __class_getitem__(cls, typevar_values: TypeForm[Any] | tuple[TypeForm[Any], ...]) -> type[BaseModel] | _forward_ref.PydanticRecursiveRef:
        cached = _generics.get_cached_generic_type_early(cls, typevar_values)
        if cached is not None:
            return cached
        else:
            if cls is BaseModel:
                raise TypeError('Type parameters should be placed on typing.Generic, not BaseModel')
            else:
                if not hasattr(cls, '__parameters__'):
                    raise TypeError(f'{cls} cannot be parametrized because it does not inherit from typing.Generic')
                else:
                    if not cls.__pydantic_generic_metadata__['parameters'] and Generic not in cls.__bases__:
                        raise TypeError(f'{cls} is not a generic class')
                    else:
                        if not isinstance(typevar_values, tuple):
                            typevar_values = (typevar_values,)
                        typevars_map = _generics.map_generic_model_arguments(cls, typevar_values)
                        typevar_values = tuple((v for v in typevars_map.values()))
                        if _utils.all_identical(typevars_map.keys(), typevars_map.values()) and typevars_map:
                            submodel = cls
                            _generics.set_cached_generic_type(cls, typevar_values, submodel)
                            return submodel
                        else:
                            parent_args = cls.__pydantic_generic_metadata__['args']
                            if not parent_args:
                                args = typevar_values
                            else:
                                args = tuple((_generics.replace_types(arg, typevars_map) for arg in parent_args))
                            origin = cls.__pydantic_generic_metadata__['origin'] or cls
                            model_name = origin.model_parametrized_name(args)
                            params = tuple(dict.fromkeys(_generics.iter_contained_typevars(typevars_map.values())))
                            with _generics.generic_recursion_self_type(origin, args) as maybe_self_type:
                                cached = _generics.get_cached_generic_type_late(cls, typevar_values, origin, args)
                                if cached is not None:
                                    return cached
                                else:
                                    if maybe_self_type is not None:
                                        return maybe_self_type
                                    else:
                                        try:
                                            parent_ns = _typing_extra.parent_frame_namespace(parent_depth=2) or {}
                                            origin.model_rebuild(_types_namespace=parent_ns)
                                        except PydanticUndefinedAnnotation:
                                            pass
                                        submodel = _generics.create_generic_submodel(model_name, origin, args, params)
                                        _generics.set_cached_generic_type(cls, typevar_values, submodel, origin, args)
                            return submodel
    def __copy__(self) -> Self:
        """Returns a shallow copy of the model."""
        # ***<module>.BaseModel.__copy__: Failure: Different control flow
        cls = type(self)
        m = cls.__new__(cls)
        _object_setattr(m, '__dict__', copy(self.__dict__))
        _object_setattr(m, '__pydantic_extra__', copy(self.__pydantic_extra__))
        _object_setattr(m, '__pydantic_fields_set__', copy(self.__pydantic_fields_set__))
        if hasattr(self, '__pydantic_private__') and self.__pydantic_private__ is None:
            _object_setattr(m, '__pydantic_private__', None)
            return m
        else:
            _object_setattr(m, '__pydantic_private__', {k: v for k, v in self.__pydantic_private__.items() if v is not PydanticUndefined})
            return m
    def __deepcopy__(self, memo: Dict[int, Any] | None=None) -> Self:
        """Returns a deep copy of the model."""
        # ***<module>.BaseModel.__deepcopy__: Failure: Different control flow
        cls = type(self)
        m = cls.__new__(cls)
        _object_setattr(m, '__dict__', deepcopy(self.__dict__, memo=memo))
        _object_setattr(m, '__pydantic_extra__', deepcopy(self.__pydantic_extra__, memo=memo))
        _object_setattr(m, '__pydantic_fields_set__', copy(self.__pydantic_fields_set__))
        if hasattr(self, '__pydantic_private__') and self.__pydantic_private__ is None:
            _object_setattr(m, '__pydantic_private__', None)
            return m
        else:
            _object_setattr(m, '__pydantic_private__', deepcopy({k: v for k, v in self.__pydantic_private__.items() if v is not PydanticUndefined}, memo=memo))
            return m
    if not TYPE_CHECKING:
        def __getattr__(self, item: str) -> Any:
            # ***<module>.BaseModel.__getattr__, None: Failure: Missing bytecode
            private_attributes = object.__getattribute__(self, '__private_attributes__')
            if item in private_attributes:
                attribute = private_attributes[item]
                if hasattr(attribute, '__get__'):
                    return attribute.__get__(self, type(self))
                else:
                    try:
                        return self.__pydantic_private__[item]
                    except KeyError as exc:
                        raise AttributeError(f'{type(self).__name__!r} object has no attribute {item!r}') from exc
            else:
                try:
                    pydantic_extra = object.__getattribute__(self, '__pydantic_extra__')
                except AttributeError:
                    pydantic_extra = None
                if pydantic_extra and item in pydantic_extra:
                    return pydantic_extra[item]
                else:
                    if hasattr(self.__class__, item):
                        return super().__getattribute__(item)
                    else:
                        raise AttributeError('%r object has no attribute %r' % (type(self).__name__, item))
        def __setattr__(self, name: str, value: Any) -> None:
            # ***<module>.BaseModel.__setattr__, None: Failure: Missing bytecode
            if (setattr_handler := self.__pydantic_setattr_handlers__.get(name)) is not None:
                setattr_handler(self, name, value)
            else:
                if (setattr_handler := self._setattr_handler(name, value)) is not None:
                    setattr_handler(self, name, value)
                    self.__pydantic_setattr_handlers__[name] = setattr_handler
        def _setattr_handler(self, name: str, value: Any) -> Callable[[BaseModel, str, Any], None] | None:
            """Get a handler for setting an attribute on the model instance.\n\n            Returns:\n                A handler for setting an attribute on the model instance. Used for memoization of the handler.\n                Memoizing the handlers leads to a dramatic performance improvement in `__setattr__`\n                Returns `None` when memoization is not safe, then the attribute is set directly.\n            """
            # ***<module>.BaseModel._setattr_handler, None: Failure: Missing bytecode
            cls = self.__class__
            if name in cls.__class_vars__:
                raise AttributeError(f'{name!r} is a ClassVar of `{cls.__name__}` and cannot be set on an instance. If you want to set a value on the class, use `{cls.__name__}.{name} = value`.')
            else:
                if not _fields.is_valid_field_name(name):
                    if (attribute := cls.__private_attributes__.get(name)) is not None:
                        if hasattr(attribute, '__set__'):
                            return lambda model, _name, val: attribute.__set__(model, val)
                        else:
                            return _SIMPLE_SETATTR_HANDLERS['private']
                    else:
                        _object_setattr(self, name, value)
                        return
                else:
                    attr = getattr(cls, name, _ATTRIBUTE_MISSING)
                    if isinstance(attr, cached_property):
                        return _SIMPLE_SETATTR_HANDLERS['cached_property']
                    else:
                        _check_frozen(cls, name, value)
                        if isinstance(attr, property):
                            return lambda model, _name, val: attr.__set__(model, val)
                        else:
                            if cls.model_config.get('validate_assignment'):
                                return _SIMPLE_SETATTR_HANDLERS['validate_assignment']
                            else:
                                if name not in cls.__pydantic_fields__:
                                    if cls.model_config.get('extra') != 'allow':
                                        raise ValueError(f'\"{cls.__name__}\" object has no field \"{name}\"')
                                    else:
                                        if attr is _ATTRIBUTE_MISSING:
                                            self.__pydantic_extra__[name] = value
                                            self.__pydantic_fields_set__.add(name)
                                            return
                                        else:
                                            return _SIMPLE_SETATTR_HANDLERS['extra_known']
                                else:
                                    return _SIMPLE_SETATTR_HANDLERS['model_field']
        def __delattr__(self, item: str) -> Any:
            # ***<module>.BaseModel.__delattr__, None: Failure: Missing bytecode
            cls = self.__class__
            if item in self.__private_attributes__:
                attribute = self.__private_attributes__[item]
                if hasattr(attribute, '__delete__'):
                    attribute.__delete__(self)
                    return
                else:
                    try:
                        del self.__pydantic_private__[item]
                    except KeyError as exc:
                        raise AttributeError(f'{cls.__name__!r} object has no attribute {item!r}') from exc
                    return
            else:
                attr = getattr(cls, item, None)
                if isinstance(attr, cached_property):
                    return object.__delattr__(self, item)
                else:
                    _check_frozen(cls, name=item, value=None)
                    if item in self.__pydantic_fields__:
                        object.__delattr__(self, item)
                        return
                    else:
                        if self.__pydantic_extra__ is not None and item in self.__pydantic_extra__:
                            del self.__pydantic_extra__[item]
                            return
                        else:
                            try:
                                object.__delattr__(self, item)
                            except AttributeError:
                                raise AttributeError(f'{type(self).__name__!r} object has no attribute {item!r}')
        def __replace__(self, **changes: Any) -> Self:
            # ***<module>.BaseModel.__replace__, None: Failure: Missing bytecode
            return self.model_copy(update=changes)
    def __getstate__(self) -> Dict[Any, Any]:
        private = self.__pydantic_private__
        if private:
            private = {k: v for k, v in private.items() if v is not PydanticUndefined}
        return {'__dict__': self.__dict__, '__pydantic_extra__': self.__pydantic_extra__, '__pydantic_fields_set__': self.__pydantic_fields_set__, '__pydantic_private__': private}
    def __setstate__(self, state: Dict[Any, Any]) -> None:
        # ***<module>.BaseModel.__setstate__: Failure: Different bytecode
        _object_setattr(self, '__pydantic_fields_set__', state.get('__pydantic_fields_set__', {}))
        _object_setattr(self, '__pydantic_extra__', state.get('__pydantic_extra__', {}))
        _object_setattr(self, '__pydantic_private__', state.get('__pydantic_private__', {}))
        _object_setattr(self, '__dict__', state.get('__dict__', {}))
    if not TYPE_CHECKING:
        def __eq__(self, other: Any) -> bool:
            # ***<module>.BaseModel.__eq__, None: Failure: Missing bytecode
            if isinstance(other, BaseModel):
                self_type = self.__pydantic_generic_metadata__['origin'] or self.__class__
                other_type = other.__pydantic_generic_metadata__['origin'] or other.__class__
                if not (self_type is other_type and getattr(self, '__pydantic_private__', None) == getattr(other, '__pydantic_private__', None) and (self.__pydantic_extra__ or {}) == (other.__pydantic_extra__ or {})):
                    return False
                else:
                    if self.__dict__ == other.__dict__:
                        return True
                    else:
                        model_fields = type(self).__pydantic_fields__.keys()
                        if self.__dict__.keys() <= model_fields and other.__dict__.keys() <= model_fields:
                            return False
                        else:
                            getter = operator.itemgetter(*model_fields) if model_fields else lambda _: _utils._SENTINEL
                            try:
                                return getter(self.__dict__) == getter(other.__dict__)
                            except KeyError:
                                self_fields_proxy = _utils.SafeGetItemProxy(self.__dict__)
                                other_fields_proxy = _utils.SafeGetItemProxy(other.__dict__)
                                return getter(self_fields_proxy) == getter(other_fields_proxy)
            else:
                return NotImplemented
    if TYPE_CHECKING:
        def __init_subclass__(cls, **kwargs: Unpack[ConfigDict]):
            """This signature is included purely to help type-checkers check arguments to class declaration, which\n            provides a way to conveniently set model_config key/value pairs.\n\n            ```python\n            from pydantic import BaseModel\n\n            class MyModel(BaseModel, extra=\'allow\'): ...\n            ```\n\n            However, this may be deceiving, since the _actual_ calls to `__init_subclass__` will not receive any\n            of the config arguments, and will only receive any keyword arguments passed during class initialization\n            that are _not_ expected keys in ConfigDict. (This is due to the way `ModelMetaclass.__new__` works.)\n\n            Args:\n                **kwargs: Keyword arguments passed to the class definition, which set model_config\n\n            Note:\n                You may want to override `__pydantic_init_subclass__` instead, which behaves similarly but is called\n                *after* the class is fully initialized.\n            """
            # ***<module>.BaseModel.__init_subclass__, None: Failure: Missing bytecode
            return
    def __iter__(self) -> TupleGenerator:
        """So `dict(model)` works."""
        yield from [(k, v) for k, v in self.__dict__.items() if not k.startswith('_')]
        extra = self.__pydantic_extra__
        if extra:
            yield from extra.items()
    def __repr__(self) -> str:
        return f"{self.__repr_name__()}({self.__repr_str__(', ')})"
    def __repr_args__(self) -> _repr.ReprArgs:
        computed_fields_repr_args = [(k, getattr(self, k)) for k, v in self.__pydantic_computed_fields__.items() if v.repr]
        for k, v in self.__dict__.items():
            field = self.__pydantic_fields__.get(k)
            if field and field.repr:
                    if v is not self:
                        yield (k, v)
                    else:
                        yield (k, self.__repr_recursion__(v))
        try:
            pydantic_extra = object.__getattribute__(self, '__pydantic_extra__')
        except AttributeError:
            pydantic_extra = None
        if pydantic_extra is not None:
            yield from ((k, v) for k, v in pydantic_extra.items())
        yield from computed_fields_repr_args
    __repr_name__ = _repr.Representation.__repr_name__
    __repr_recursion__ = _repr.Representation.__repr_recursion__
    __repr_str__ = _repr.Representation.__repr_str__
    __pretty__ = _repr.Representation.__pretty__
    __rich_repr__ = _repr.Representation.__rich_repr__
    def __str__(self) -> str:
        return self.__repr_str__(' ')
    @property
    @typing_extensions.deprecated('The `__fields__` attribute is deprecated, use the `model_fields` class property instead.', category=None)
    def __fields__(self) -> 'Dict[str, FieldInfo]':
        warnings.warn('The `__fields__` attribute is deprecated, use the `model_fields` class property instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        return getattr(type(self), '__pydantic_fields__', {})
    @property
    @typing_extensions.deprecated('The `__fields_set__` attribute is deprecated, use `model_fields_set` instead.', category=None)
    def __fields_set__(self) -> 'set[str]':
        warnings.warn('The `__fields_set__` attribute is deprecated, use `model_fields_set` instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        return self.__pydantic_fields_set__
    @typing_extensions.deprecated('The `dict` method is deprecated; use `model_dump` instead.', category=None)
    # return {'include': None, 'exclude': None, 'by_alias': False, 'exclude_unset': False, 'exclude_defaults': False, 'exclude_none': False}
    def dict(self, *, include: IncEx | None, exclude: IncEx | None, by_alias: bool, exclude_unset: bool, exclude_defaults: bool, exclude_none: bool) -> Dict[str, Any]:
        warnings.warn('The `dict` method is deprecated; use `model_dump` instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        return self.model_dump(include=include, exclude=exclude, by_alias=by_alias, exclude_unset=exclude_unset, exclude_defaults=exclude_defaults, exclude_none=exclude_none)
    @typing_extensions.deprecated('The `json` method is deprecated; use `model_dump_json` instead.', category=None)
    @{'include': None, 'exclude': None, 'by_alias': False, 'exclude_unset': False, 'exclude_defaults': False, 'exclude_none': False, 'encoder': PydanticUndefined, 'models_as_dict': PydanticUndefined}
    def json(self, *, include: IncEx | None, exclude: IncEx | None, by_alias: bool, exclude_unset: bool, exclude_defaults: bool, exclude_none: bool, encoder: Callable[[Any], Any] | None, models_as_dict: bool, **dumps_kwargs: Any) -> str:
        warnings.warn('The `json` method is deprecated; use `model_dump_json` instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        if encoder is not PydanticUndefined:
            raise TypeError('The `encoder` argument is no longer supported; use field serializers instead.')
        else:
            if models_as_dict is not PydanticUndefined:
                raise TypeError('The `models_as_dict` argument is no longer supported; use a model serializer instead.')
            else:
                if dumps_kwargs:
                    raise TypeError('`dumps_kwargs` keyword arguments are no longer supported.')
                else:
                    return self.model_dump_json(include=include, exclude=exclude, by_alias=by_alias, exclude_unset=exclude_unset, exclude_defaults=exclude_defaults, exclude_none=exclude_none)
    @classmethod
    @typing_extensions.deprecated('The `parse_obj` method is deprecated; use `model_validate` instead.', category=None)
    def parse_obj(cls, obj: Any) -> Self:
        warnings.warn('The `parse_obj` method is deprecated; use `model_validate` instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        return cls.model_validate(obj)
    @classmethod
    @typing_extensions.deprecated('The `parse_raw` method is deprecated; if your data is JSON use `model_validate_json`, otherwise load the data then use `model_validate` instead.', category=None)
    # return {'content_type': None, 'encoding': 'utf8', 'proto': None, 'allow_pickle': False}
    def parse_raw(cls, b: str | bytes, *, content_type: str | None, encoding: str, proto: DeprecatedParseProtocol | None, allow_pickle: bool) -> Self:
        warnings.warn('The `parse_raw` method is deprecated; if your data is JSON use `model_validate_json`, otherwise load the data then use `model_validate` instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        from .deprecated import parse
        try:
            obj = parse.load_str_bytes(b, proto=proto, content_type=content_type, encoding=encoding, allow_pickle=allow_pickle)
        except (ValueError, TypeError) as exc:
            import json
            if isinstance(exc, UnicodeDecodeError):
                type_str = 'value_error.unicodedecode'
            else:
                if isinstance(exc, json.JSONDecodeError):
                    type_str = 'value_error.jsondecode'
                else:
                    if isinstance(exc, ValueError):
                        type_str = 'value_error'
                    else:
                        type_str = 'type_error'
            error = {'type': pydantic_core.PydanticCustomError(type_str, str(exc)), 'loc': ('__root__',), 'input': b}
            raise pydantic_core.ValidationError.from_exception_data(cls.__name__, [error])
        return cls.model_validate(obj)
    @classmethod
    @typing_extensions.deprecated('The `parse_file` method is deprecated; load the data from file, then if your data is JSON use `model_validate_json`, otherwise `model_validate` instead.', category=None)
    # return {'content_type': None, 'encoding': 'utf8', 'proto': None, 'allow_pickle': False}
    def parse_file(cls, path: str | Path, *, content_type: str | None, encoding: str, proto: DeprecatedParseProtocol | None, allow_pickle: bool) -> Self:
        warnings.warn('The `parse_file` method is deprecated; load the data from file, then if your data is JSON use `model_validate_json`, otherwise `model_validate` instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        from .deprecated import parse
        obj = parse.load_file(path, proto=proto, content_type=content_type, encoding=encoding, allow_pickle=allow_pickle)
        return cls.parse_obj(obj)
    @classmethod
    @typing_extensions.deprecated('The `from_orm` method is deprecated; set `model_config[\'from_attributes\']=True` and use `model_validate` instead.', category=None)
    def from_orm(cls, obj: Any) -> Self:
        warnings.warn('The `from_orm` method is deprecated; set `model_config[\'from_attributes\']=True` and use `model_validate` instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        if not cls.model_config.get('from_attributes', None):
            raise PydanticUserError('You must set the config attribute `from_attributes=True` to use from_orm', code=None)
        else:
            return cls.model_validate(obj)
    @classmethod
    @typing_extensions.deprecated('The `construct` method is deprecated; use `model_construct` instead.', category=None)
    def construct(cls, _fields_set: set[str] | None=None, **values: Any) -> Self:
        warnings.warn('The `construct` method is deprecated; use `model_construct` instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        return cls.model_construct(_fields_set=_fields_set, **values)
    @typing_extensions.deprecated('The `copy` method is deprecated; use `model_copy` instead. See the docstring of `BaseModel.copy` for details about how to handle `include` and `exclude`.', category=None)
    # return {'include': None, 'exclude': None, 'update': None, 'deep': False}
    def copy(self, *, include: AbstractSetIntStr | MappingIntStrAny | None, exclude: AbstractSetIntStr | MappingIntStrAny | None, update: Dict[str, Any] | None, deep: bool) -> Self:
        """Returns a copy of the model.\n\n        !!! warning \"Deprecated\"\n            This method is now deprecated; use `model_copy` instead.\n\n        If you need `include` or `exclude`, use:\n\n        ```python {test=\"skip\" lint=\"skip\"}\n        data = self.model_dump(include=include, exclude=exclude, round_trip=True)\n        data = {**data, **(update or {})}\n        copied = self.model_validate(data)\n        ```\n\n        Args:\n            include: Optional set or mapping specifying which fields to include in the copied model.\n            exclude: Optional set or mapping specifying which fields to exclude in the copied model.\n            update: Optional dictionary of field-value pairs to override field values in the copied model.\n            deep: If True, the values of fields that are Pydantic models will be deep-copied.\n\n        Returns:\n            A copy of the model with included, excluded and updated fields as specified.\n        """
        warnings.warn('The `copy` method is deprecated; use `model_copy` instead. See the docstring of `BaseModel.copy` for details about how to handle `include` and `exclude`.', category=PydanticDeprecatedSince20, stacklevel=2)
        from .deprecated import copy_internals
        values = dict(copy_internals._iter(self, to_dict=False, by_alias=False, include=include, exclude=exclude, exclude_unset=False), **update or {})
        if self.__pydantic_private__ is None:
            private = None
        else:
            private = {k: v for k, v in self.__pydantic_private__.items() if v is not PydanticUndefined}
        if self.__pydantic_extra__ is None:
            extra = None
        else:
            extra = self.__pydantic_extra__.copy()
            for k in list(self.__pydantic_extra__):
                if k not in values:
                    extra.pop(k)
            for k in list(values):
                if k in self.__pydantic_extra__:
                    extra[k] = values.pop(k)
        if update:
            fields_set = self.__pydantic_fields_set__ | update.keys()
        else:
            fields_set = set(self.__pydantic_fields_set__)
        if exclude:
            fields_set -= set(exclude)
        return copy_internals._copy_and_set_values(self, values, fields_set, extra, private, deep=deep)
    @classmethod
    @typing_extensions.deprecated('The `schema` method is deprecated; use `model_json_schema` instead.', category=None)
    @(True, DEFAULT_REF_TEMPLATE)
    def schema(cls, by_alias: bool, ref_template: str) -> Dict[str, Any]:
        warnings.warn('The `schema` method is deprecated; use `model_json_schema` instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        return cls.model_json_schema(by_alias=by_alias, ref_template=ref_template)
    @classmethod
    @typing_extensions.deprecated('The `schema_json` method is deprecated; use `model_json_schema` and json.dumps instead.', category=None)
    @{'by_alias': True, 'ref_template': DEFAULT_REF_TEMPLATE}
    def schema_json(cls, *, by_alias: bool, ref_template: str, **dumps_kwargs: Any) -> str:
        warnings.warn('The `schema_json` method is deprecated; use `model_json_schema` and json.dumps instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        import json
        from .deprecated.json import pydantic_encoder
        return json.dumps(cls.model_json_schema(by_alias=by_alias, ref_template=ref_template), default=pydantic_encoder, **dumps_kwargs)
    @classmethod
    @typing_extensions.deprecated('The `validate` method is deprecated; use `model_validate` instead.', category=None)
    def validate(cls, value: Any) -> Self:
        warnings.warn('The `validate` method is deprecated; use `model_validate` instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        return cls.model_validate(value)
    @classmethod
    @typing_extensions.deprecated('The `update_forward_refs` method is deprecated; use `model_rebuild` instead.', category=None)
    def update_forward_refs(cls, **localns: Any) -> None:
        warnings.warn('The `update_forward_refs` method is deprecated; use `model_rebuild` instead.', category=PydanticDeprecatedSince20, stacklevel=2)
        if localns:
            raise TypeError('`localns` arguments are not longer accepted.')
        else:
            cls.model_rebuild(force=True)
    @typing_extensions.deprecated('The private method `_iter` will be removed and should no longer be used.', category=None)
    def _iter(self, *args: Any, **kwargs: Any) -> Any:
        warnings.warn('The private method `_iter` will be removed and should no longer be used.', category=PydanticDeprecatedSince20, stacklevel=2)
        from .deprecated import copy_internals
        return copy_internals._iter(self, *args, **kwargs)
    @typing_extensions.deprecated('The private method `_copy_and_set_values` will be removed and should no longer be used.', category=None)
    def _copy_and_set_values(self, *args: Any, **kwargs: Any) -> Any:
        warnings.warn('The private method `_copy_and_set_values` will be removed and should no longer be used.', category=PydanticDeprecatedSince20, stacklevel=2)
        from .deprecated import copy_internals
        return copy_internals._copy_and_set_values(self, *args, **kwargs)
    @classmethod
    @typing_extensions.deprecated('The private method `_get_value` will be removed and should no longer be used.', category=None)
    def _get_value(cls, *args: Any, **kwargs: Any) -> Any:
        warnings.warn('The private method `_get_value` will be removed and should no longer be used.', category=PydanticDeprecatedSince20, stacklevel=2)
        from .deprecated import copy_internals
        return copy_internals._get_value(cls, *args, **kwargs)
    @typing_extensions.deprecated('The private method `_calculate_keys` will be removed and should no longer be used.', category=None)
    def _calculate_keys(self, *args: Any, **kwargs: Any) -> Any:
        warnings.warn('The private method `_calculate_keys` will be removed and should no longer be used.', category=PydanticDeprecatedSince20, stacklevel=2)
        from .deprecated import copy_internals
        return copy_internals._calculate_keys(self, *args, **kwargs)
ModelT = TypeVar('ModelT', bound=BaseModel)
_CREATE_MODEL_RESERVED_NAMESPACE_KEYS: dict[str, str] = {'__annotations__': 'field definitions', '__module__': 'the `__module__` argument', '__qualname__': 'the `__qualname__` argument', '__doc__': 'the `__doc__` argument', 'model_config': 'the `__config__` argument'}
@overload, '__doc__': {'__config__': None, '__doc__': None, '__base__': None, '__module__': __name__, '__validators__': None, '__namespace__': None, '__cls_kwargs__': None, '__qualname__': None}
def create_model(model_name: str, /, *, __config__: ConfigDict | None, __doc__: str | None, __base__: None, __module__: str, __validators__: dict[str, Callable[..., Any]] | None, __namespace__: dict[str, Any] | None, __cls_kwargs__: dict[str, Any] | None, __qualname__: str | None, **field_definitions: TypeForm[Any] | tuple[TypeForm[Any], Any]) -> type[BaseModel]:
    return
@overload
@{'__config__': None, '__doc__': None, '__module__': __name__, '__validators__': None, '__namespace__': None, '__cls_kwargs__': None, '__qualname__': None}
def create_model(model_name: str, /, *, __config__: ConfigDict | None, __doc__: str | None, __base__: type[ModelT] | tuple[type[ModelT], ...], __module__: str, __validators__: dict[str, Callable[..., Any]] | None, __namespace__: dict[str, Any] | None, __cls_kwargs__: dict[str, Any] | None, __qualname__: str | None, **field_definitions: TypeForm[Any] | tuple[TypeForm[Any], Any]) -> type[ModelT]:
    return
# return {'__config__': None, '__doc__': None, '__base__': None, '__module__': None, '__validators__': None, '__namespace__': None, '__cls_kwargs__': None, '__qualname__': None}
def create_model(model_name: str, /, *, __config__: ConfigDict | None, __doc__: str | None, __base__: type[ModelT] | tuple[type[ModelT], ...] | None, __module__: str | None, __validators__: dict[str, Callable[..., Any]] | None, __namespace__: dict[str, Any] | None, __cls_kwargs__: dict[str, Any] | None, __qualname__, **field_definitions: TypeForm[Any] | tuple[TypeForm[Any], Any]) -> type[ModelT]:
    """!!! abstract \"Usage Documentation\"\n        [Dynamic Model Creation](../concepts/models.md#dynamic-model-creation)\n\n    Dynamically creates and returns a new Pydantic model. In other words, `create_model()` dynamically creates a\n    subclass of [`BaseModel`][pydantic.BaseModel].\n\n    !!! warning\n        This function may execute arbitrary code contained in field annotations, if string references need to be evaluated.\n\n        See [Security implications of introspecting annotations](https://docs.python.org/3/library/annotationlib.html#annotationlib-security) for more information.\n\n    Args:\n        model_name: The name of the newly created model.\n        __config__: The configuration of the new model.\n        __doc__: The docstring of the new model.\n        __base__: The base class or classes for the new model.\n        __module__: The name of the module that the model belongs to;\n            if `None`, the value is taken from `sys._getframe(1)`\n        __validators__: A dictionary of methods that validate fields. The keys are the names of the validation methods to\n            be added to the model, and the values are the validation methods themselves. You can read more about functional\n            validators [here](../concepts/validators.md#field-validators).\n\n            /// version-changed | v2.14\n            It is now recommended to use the `__namespace__` argument, which isn\'t restricted to validators.\n            `__validators__` will be deprecated in v3.\n            ///\n        __namespace__: A dictionary of attributes to add to the class namespace of the new model, such as\n            [validators](../concepts/validators.md), methods or [computed fields][pydantic.computed_field].\n            Keys take precedence over the ones from `__validators__`, and must not clash with any of the field names\n            or with the attributes that have a dedicated argument (`__annotations__`, `__module__`, `__qualname__`,\n            `__doc__` and `model_config`).\n\n            /// version-added | v2.14\n            This argument replaces `__validators__`, which will be deprecated in v3.\n            ///\n        __cls_kwargs__: A dictionary of keyword arguments for class creation, such as `metaclass`.\n        __qualname__: The qualified name of the newly created model.\n        **field_definitions: Field definitions of the new model. Either:\n\n            - a single element, representing the type annotation of the field.\n            - a two-tuple, the first element being the type and the second element the assigned value\n              (either a default or the [`Field()`][pydantic.Field] function).\n\n    Returns:\n        The new [model][pydantic.BaseModel].\n\n    Raises:\n        PydanticUserError: If `__base__` and `__config__` are both passed,\n            or if a key of `__namespace__` clashes with a field name or with an attribute that has a dedicated argument.\n    """
    if __base__ is None:
        __base__ = (cast('type[ModelT]', BaseModel),)
    else:
        if not isinstance(__base__, tuple):
            __base__ = (__base__,)
    __cls_kwargs__ = __cls_kwargs__ or {}
    fields = {}
    annotations = {}
    for f_name, f_def in field_definitions.items():
        if isinstance(f_def, tuple):
            if len(f_def) != 2:
                raise PydanticUserError(f'Field definition for {f_name!r} should a single element representing the type or a two-tuple, the first element being the type and the second element the assigned value (either a default or the `Field()` function).', code='create-model-field-definitions')
            else:
                annotations[f_name] = f_def[0]
                fields[f_name] = f_def[1]
        else:
            annotations[f_name] = f_def
    if __namespace__:
        if (clashing_names := (field_definitions.keys() & __namespace__.keys())):
            raise PydanticUserError(f"Field name(s) {', '.join(map(repr, sorted(clashing_names)))} clash with keys of the `__namespace__` argument.", code='create-model-namespace')
        else:
            for key, argument in _CREATE_MODEL_RESERVED_NAMESPACE_KEYS.items():
                if key in __namespace__:
                    raise PydanticUserError(f'{key!r} is not allowed as a key of the `__namespace__` argument, use {argument} instead.', code='create-model-namespace')
    if __module__ is None:
        f = sys._getframe(1)
        __module__ = f.f_globals['__name__']
    namespace = {'__annotations__': annotations, '__module__': __module__}
    if __doc__:
        namespace['__doc__'] = __doc__
    if __qualname__ is not None:
        namespace['__qualname__'] = __qualname__
    if __validators__:
        namespace.update(__validators__)
    if __namespace__:
        namespace.update(__namespace__)
    namespace.update(fields)
    if __config__:
        namespace['model_config'] = __config__
    resolved_bases = types.resolve_bases(__base__)
    meta, ns, kwds = types.prepare_class(model_name, resolved_bases, kwds=__cls_kwargs__)
    if resolved_bases is not __base__:
        ns['__orig_bases__'] = __base__
    namespace.update(ns)
    return meta(model_name, resolved_bases, namespace, __pydantic_reset_parent_namespace__=False, _create_model_module=__module__, **kwds)
__getattr__ = getattr_migration(__name__)