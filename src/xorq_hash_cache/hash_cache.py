import datetime
import json
import operator
from pathlib import Path
from functools import (
    cache,
    wraps,
)

import cloudpickle
import toolz
from attrs import (
    field,
    frozen,
)
from attrs.validators import (
    instance_of,
    is_callable,
    optional,
)

from xorq_hash_cache.hasher import tokenize
from xorq_hash_cache.utils.inspect_utils import (
    get_arguments,
    get_args_kwargs,
)


def json_dump(obj, path):
    with path.open("wt") as fh:
        json.dump(obj, fh)


def json_load(path):
    with path.open("rt") as fh:
        return json.load(fh)


def cloudpickle_dump(obj, path):
    with path.open("wb") as fh:
        cloudpickle.dump(obj, fh)


def cloudpickle_load(path):
    with path.open("rb") as fh:
        return cloudpickle.load(fh)


def true_stem(path):
    assert path and path.name and path.name[0] != "."
    return Path(path).name.split(".", 1)[0]


def true_suffix(path):
    return "".join(path.suffixes)


@frozen
class Serder:
    serialize = field(validator=is_callable())
    deserialize = field(validator=is_callable())
    suffix = field(validator=instance_of(str))

    def get_path(self, stem_path):
        # "true" stem
        assert not stem_path.suffix
        return stem_path.with_suffix(self.suffix)

    def dump(self, obj, stem_path):
        # "true" stem
        assert not stem_path.suffix
        self.serialize(obj, self.get_path(stem_path))

    def load(self, stem_path):
        # "true" stem
        assert not stem_path.suffix
        return self.deserialize(self.get_path(stem_path))

    def exists(self, stem_path):
        return self.get_path(stem_path).exists()

    @classmethod
    def pkl_serder(cls):
        return cls(
            serialize=cloudpickle_dump, deserialize=cloudpickle_load, suffix=".pkl"
        )

    @classmethod
    def args_kwargs_pkl_serder(cls):
        return cls(
            serialize=cloudpickle_dump, deserialize=cloudpickle_load, suffix=".args.pkl"
        )

    @classmethod
    def json_serder(cls):
        return cls(serialize=json_dump, deserialize=json_load, suffix=".json")

    @classmethod
    def args_kwargs_json_serder(cls):
        return cls(serialize=json_dump, deserialize=json_load, suffix=".args.json")


def get_path_prefix(path, f):
    tokenized_f = tokenize(f)
    path_prefix = Path(path).joinpath(
        ".".join((f.__module__, getattr(f, "__qualname__", f.__name__))),
        tokenized_f,
    )
    return path_prefix


def calc_hash_stem(f, *args, **kwargs):
    arguments = get_arguments(f, *args, **kwargs)
    stem = tokenize(f, arguments)
    return stem


def calc_kwargs_stem(f, *args, **kwargs):
    arguments = get_arguments(f, *args, **kwargs)
    stem = ",".join(f"{k}={v}" for k, v in arguments.items())
    return stem


convert_path = toolz.compose(
    operator.methodcaller("resolve"), operator.methodcaller("expanduser"), Path
)


@frozen
class HashCached:
    path = field(validator=instance_of(Path), converter=convert_path)
    f = field(validator=is_callable())
    serder = field(validator=instance_of(Serder), factory=Serder.pkl_serder)
    args_kwargs_serder = field(
        validator=optional(instance_of(Serder)), factory=Serder.args_kwargs_pkl_serder
    )
    f_serder = field(validator=instance_of(Serder), factory=Serder.pkl_serder)
    calc_stem = field(validator=is_callable(), default=calc_hash_stem)
    ttl = field(validator=optional(instance_of(datetime.timedelta)), default=None)

    def __attrs_post_init__(self):
        if (
            self.args_kwargs_serder
            and self.serder.suffix == self.args_kwargs_serder.suffix
        ):
            raise ValueError
        if not self.f_serder.exists(self.f_stem_path):
            self.path_prefix.mkdir(exist_ok=True, parents=True)
            self.f_serder.dump(self.f, self.f_stem_path)

    def is_expired(self, stem_path):
        path = self.serder.get_path(stem_path)
        assert path.is_relative_to(self.path_prefix)
        if self.ttl is not None:
            delta_seconds = datetime.datetime.now().timestamp() - path.stat().st_mtime
            return delta_seconds >= self.ttl.total_seconds()
        else:
            return False

    def __call__(self, *args, **kwargs):
        stem_path = self.calc_stem_path(*args, **kwargs)
        if self.serder.exists(stem_path) and not self.is_expired(stem_path):
            value = self.serder.load(stem_path)
        else:
            value = self.f(*args, **kwargs)
            self.serder.dump(value, stem_path)
            if self.args_kwargs_serder:
                self.args_kwargs_serder.dump(
                    get_args_kwargs(self.f, *args, **kwargs),
                    stem_path,
                )
        return value

    @property
    @cache
    def path_prefix(self):
        return get_path_prefix(self.path, self.f)

    @property
    def f_stem_path(self):
        return self.path_prefix.parent.joinpath(self.path_prefix.name)

    def calc_stem_path(self, *args, **kwargs):
        stem = self.calc_stem(self.f, *args, **kwargs)
        return self.path_prefix.joinpath(stem)

    def get_hash_cache_path(self, *args, **kwargs):
        stem_path = self.calc_stem_path(*args, **kwargs)
        return HashCachePath(stem_path, hash_cached=self, require_exists=False)

    def gen_hash_cache_paths(self):
        stem_paths = (
            p.with_name(true_stem(p))
            for p in self.path_prefix.iterdir()
            if true_suffix(p) == self.serder.suffix
        )
        yield from (HashCachePath(p, hash_cached=self) for p in stem_paths)

    @classmethod
    @toolz.curry
    def hash_cache(cls, path, f, **kwargs):
        typ = toolz.curry(cls, **kwargs)
        return hash_cache(path, f, typ=typ)

    @classmethod
    @toolz.curry
    def json_hash_cache(
        cls,
        path,
        f,
        serder=Serder.json_serder(),
        args_kwargs_serder=Serder.args_kwargs_json_serder(),
        **kwargs,
    ):
        return cls.hash_cache(
            path=path,
            f=f,
            serder=serder,
            args_kwargs_serder=args_kwargs_serder,
            **kwargs,
        )


@toolz.curry
def hash_cache(path, f, *, typ=HashCached, **kwargs):
    hc = typ(path, f, **kwargs)

    @wraps(f)
    def wrapper(*args, **kwargs):
        return hc(*args, **kwargs)

    wrapper.hash_cached = hc
    wrapper.__wrapped__ = f
    return wrapper


@toolz.curry
def dated_hash_cache(path, f, name="dated_hash_cache", **kwargs):
    return hash_cache(
        path=path.joinpath(name, datetime.datetime.now().strftime("%Y-%m-%d")),
        f=f,
        **kwargs,
    )


@frozen
class HashCachePath:
    stem_path = field(validator=instance_of(Path), converter=convert_path)
    hash_cached = field(validator=instance_of(HashCached))
    require_exists = field(validator=instance_of(bool), default=True)

    def __attrs_post_init__(self):
        assert not self.stem_path.suffix
        hash_cached = self.hash_cached
        if self.require_exists:
            if not hash_cached.serder.exists(self.stem_path):
                raise ValueError
            if (
                hash_cached.args_kwargs_serder
                and not hash_cached.args_kwargs_serder.exists(self.stem_path)
            ):
                raise ValueError

    @property
    def is_expired(self):
        return self.hash_cached.is_expired(self.stem_path)

    def pipe(self, func, *args, **kwargs):
        return func(self, *args, **kwargs)

    @property
    def args_kwargs(self):
        (args, kwargs) = self.hash_cached.args_kwargs_serder.load(self.stem_path)
        return (args, kwargs)

    @property
    def arguments(self):
        (args, kwargs) = self.args_kwargs
        arguments = get_arguments(
            self.hash_cached.f,
            *args,
            **kwargs,
        )
        return arguments

    @property
    def retval(self):
        return self.hash_cached.serder.load(self.stem_path)
