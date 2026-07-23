import datetime
import os
from pathlib import Path

import pytest

from xorq_hash_cache.hash_cache import (
    HashCached,
)
from xorq_hash_cache.utils.inspect_utils import (
    get_args_kwargs,
)


def f(x, *args, y=1, z, **kwargs):
    return (x, args, y, z, kwargs)


def test_initialization_files(tmpdir):
    tmpdir = Path(tmpdir)
    assert not tuple(tmpdir.iterdir())

    g = HashCached(tmpdir, f)
    assert tuple(tmpdir.iterdir())
    assert tuple(g.path.iterdir())
    # we are writing inside the path that was passed
    assert g.path.relative_to(tmpdir)
    # we have written f to disk
    assert g.f_serder.exists(g.f_stem_path)
    assert f == g.f_serder.load(g.f_stem_path)

    assert not tuple(g.path_prefix.iterdir())


def test_hash_cache_path(tmpdir):
    g = HashCached(tmpdir, f)
    args = (1, 2, 3)
    kwargs = {"z": "a"}
    assert not tuple(g.path_prefix.iterdir())
    retval = g(*args, **kwargs)
    assert tuple(g.path_prefix.iterdir())
    (hcp,) = g.gen_hash_cache_paths()
    assert retval == hcp.retval
    assert get_args_kwargs(f, *args, **kwargs) == hcp.args_kwargs


@pytest.mark.parametrize(
    "ttl,should_be_expired",
    (
        (datetime.timedelta(milliseconds=1), True),
        (datetime.timedelta(days=1), False),
    ),
)
def test_ttl(tmpdir, ttl, should_be_expired):
    g = HashCached(tmpdir, f, ttl=ttl)
    args = (1, 2, 3)
    kwargs = {"z": "a"}
    assert not tuple(g.path_prefix.iterdir())
    retval = g(*args, **kwargs)
    assert tuple(g.path_prefix.iterdir())
    (hcp,) = g.gen_hash_cache_paths()
    assert retval == hcp.retval
    assert get_args_kwargs(f, *args, **kwargs) == hcp.args_kwargs

    if should_be_expired:
        # Backdate the mtime well past the ttl; comparing a freshly-written
        # mtime against now() is racy for a millisecond ttl.
        path = hcp.hash_cached.serder.get_path(hcp.stem_path)
        past = datetime.datetime.now().timestamp() - 3600
        os.utime(path, (past, past))
        assert hcp.is_expired
        assert g.is_expired(hcp.stem_path)
    else:
        assert not hcp.is_expired
        assert not g.is_expired(hcp.stem_path)
