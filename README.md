# xorq-hash-cache

A small Python utility for caching function results to disk, keyed by the
function's identity and the arguments it was called with.

Wrap a function once and every call is transparently memoized to a file on
disk. Cache entries survive across processes, are keyed by a hash of both the
function and its arguments, and can optionally expire after a configurable
time-to-live (TTL).

## Install

```bash
pip install git+https://github.com/xorq-labs/xorq-hash-cache.git
```

Or, with [uv](https://docs.astral.sh/uv/):

```bash
uv add git+https://github.com/xorq-labs/xorq-hash-cache.git
```

## Quickstart

```python
from pathlib import Path

from xorq_hash_cache.hash_cache import HashCached

cache_dir = Path("./cache")


@HashCached.hash_cache(cache_dir)
def expensive(x, y):
    print("computing...")  # only prints on a cache miss
    return x + y


expensive(1, 2)  # computing... -> 3
expensive(1, 2)  # -> 3  (loaded from disk, no recompute)
```

Results are serialized with `cloudpickle` by default, so most Python return
values work out of the box. For JSON-serializable results, use the JSON
variant, which stores human-readable cache files:

```python
from xorq_hash_cache.hash_cache import HashCached, calc_kwargs_stem


@HashCached.json_hash_cache(cache_dir, calc_stem=calc_kwargs_stem)
def fetch(item_id, other):
    return {"item_id": item_id, "other": other}
```

## Features

- **Persistent, cross-process** — cache entries are plain files under a
  directory you choose.
- **Keyed by function + arguments** — the cache path incorporates a hash of the
  function (via [`xorq-dasher`](https://pypi.org/project/xorq-dasher/)
  tokenization) and the call's arguments, so changing either yields a new entry.
- **Pluggable serialization** — pickle (`HashCached.hash_cache`) or JSON
  (`HashCached.json_hash_cache`) out of the box, or supply your own `Serder`.
- **Configurable cache keys** — `calc_hash_stem` (default, opaque hash) or
  `calc_kwargs_stem` (readable `key=value` filenames), or your own.
- **TTL expiry** — pass `ttl=datetime.timedelta(...)`; expired entries are
  recomputed on the next call.

## How it works

For a wrapped function `f`, entries are written under:

```
<path>/<module>.<qualname>/<hash-of-f>/<stem>.pkl
```

- `<stem>` is derived from the call arguments (`calc_stem`). On a call,
  `HashCached` computes the stem path, and returns the stored value if it
  exists and has not expired — otherwise it calls `f`, stores the result, and
  (for the pickle path) also records the arguments alongside it.
- The wrapped function exposes the underlying `HashCached` instance as
  `wrapped.hash_cached`, and `HashCached.gen_hash_cache_paths()` iterates the
  existing entries (each a `HashCachePath` exposing `.retval`, `.arguments`,
  and `.is_expired`).

### TTL example

```python
import datetime
from xorq_hash_cache.hash_cache import HashCached

hc = HashCached(cache_dir, expensive, ttl=datetime.timedelta(hours=1))
hc(1, 2)  # cached for one hour, recomputed thereafter
```

`dated_hash_cache` is also provided, which namespaces the cache under the
current date (`YYYY-MM-DD`).

## Development

This repo uses [uv](https://docs.astral.sh/uv/) and pre-commit.

```bash
uv sync --group dev          # install with dev dependencies
uv run pytest                # run the test suite
uv run pre-commit run --all-files
```

CI runs the test suite (Python 3.10 / 3.12 / 3.13) and linting (ruff +
codespell) on every pull request.

## License

[Apache-2.0](LICENSE).
