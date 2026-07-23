"""Deterministic hashing for hash-cache, built on xorq_dasher.

``DEFAULT_HASHER`` from xorq_dasher already covers Python callables
(FunctionType/MethodType/CodeType/CellType/classmethod/staticmethod), the
common builtins (dict, type, module), numpy (RandomState) and pandas
(Interval, Timestamp) types, and an ``object`` fallback that probes
``__dasher_tokenize__``.

This module adds the stdlib/toolz gap rules that hash-cache relies on and
exposes the canonical ``HASHER`` instance plus a ``tokenize`` helper.
"""

from __future__ import annotations

import functools
import operator
import types

import toolz
from xorq_dasher import DEFAULT_HASHER, Hasher, fqn
from xorq_dasher.rules.functions import normalize_function

from xorq_hash_cache.utils.inspect_utils import get_partial_arguments


def _extract_methodcaller_fields(
    mc: operator.methodcaller,
) -> tuple[str, tuple, dict]:
    """Extract (name, args, kwargs) via the pickle protocol (``__reduce__``).

    Works on any Python implementation (no ctypes / CPython internals).
    """
    constructor, constructor_args = mc.__reduce__()[:2]
    if isinstance(constructor, functools.partial):
        return constructor.args[0], constructor_args, constructor.keywords
    return constructor_args[0], constructor_args[1:], {}


def normalize_lru_cache(func: functools._lru_cache_wrapper) -> tuple:
    """Covers ``functools.lru_cache`` and ``functools.cache`` wrappers."""
    inner = func
    while hasattr(inner, "__wrapped__"):
        inner = inner.__wrapped__
    return normalize_function(inner)


def normalize_functools_partial(p: functools.partial) -> tuple:
    return (
        "functools.partial",
        p.func,
        tuple(p.args),
        tuple(sorted(p.keywords.items())),
    )


def normalize_builtin_callable(
    func: types.BuiltinFunctionType | types.BuiltinMethodType,
) -> tuple:
    """Builtin C functions / methods (e.g. ``json.dumps``)."""
    return (
        "builtins.builtin",
        getattr(func, "__module__", None),
        getattr(func, "__qualname__", getattr(func, "__name__", repr(func))),
    )


def normalize_slice(s: slice) -> tuple:
    return ("slice", s.start, s.stop, s.step)


def normalize_property(prop: property) -> tuple:
    return ("property", prop.fget, prop.fset, prop.fdel)


def normalize_toolz_compose(composed: toolz.functoolz.Compose) -> tuple:
    return ("toolz.Compose", composed.first, composed.funcs)


def normalize_toolz_curry(curried: toolz.curry) -> tuple:
    partial_arguments = get_partial_arguments(
        curried.func, *curried.args, **curried.keywords
    )
    return ("toolz.curry", curried.func, tuple(sorted(partial_arguments.items())))


def normalize_toolz_excepts(f: toolz.functoolz.excepts) -> tuple:
    return ("toolz.excepts", f.exc, f.func)


def normalize_methodcaller(obj: operator.methodcaller) -> tuple:
    return ("operator.methodcaller", *_extract_methodcaller_fields(obj))


RULES: tuple = (
    (fqn(functools._lru_cache_wrapper), normalize_lru_cache),
    (fqn(functools.partial), normalize_functools_partial),
    ("builtins.builtin_function_or_method", normalize_builtin_callable),
    (fqn(slice), normalize_slice),
    (fqn(property), normalize_property),
    (fqn(toolz.functoolz.Compose), normalize_toolz_compose),
    (fqn(toolz.curry), normalize_toolz_curry),
    (fqn(toolz.functoolz.excepts), normalize_toolz_excepts),
    (fqn(operator.methodcaller), normalize_methodcaller),
)


HASHER: Hasher = DEFAULT_HASHER.override(*RULES)


def tokenize(*objs) -> str:
    """Return a deterministic hex digest for one or more objects."""
    return HASHER.tokenize(*objs)
