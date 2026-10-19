"""Persistent cache of slow lookups: CMR granule searches and GOES scan
listings, shared by every execution environment of a regional deployment.

A lookup is a `kind` (which function computes it) and a JSON `query` (its
arguments). The first request for a query computes it and stores the
result; later requests, in any execution environment, read it back. Each
entry has an expiry chosen by the caller (long for settled past times,
short for times still being ingested). The weekly prune job
(`ycgs_titiler.prune`) deletes expired entries and recomputes settled ones,
deleting those whose result changed.

Storage is a DynamoDB table (`YCGS_LOOKUP_TABLE`), one item per query; with
no table configured (local runs, tests) every lookup is computed. The cache
fails open: a read or write error is logged and the lookup is computed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import zlib
from collections.abc import Callable, Iterator
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# region policy
# Results for times older than this are settled: data providers have
# finished ingesting them, so they are kept long and revalidated weekly.
SETTLED_AFTER_S = float(os.environ.get("YCGS_LOOKUP_SETTLED_DAYS", "7")) * 86400
TTL_SETTLED_S = float(os.environ.get("YCGS_LOOKUP_TTL_SETTLED_DAYS", "90")) * 86400
TTL_RECENT_S = float(os.environ.get("YCGS_LOOKUP_TTL_RECENT_HOURS", "1")) * 3600
# DynamoDB items are limited to 400 KB; larger results are not stored.
MAX_VALUE_BYTES = 350 * 1024
# endregion policy


def ttl_for(end: float | None, now: float | None = None) -> float:
    """Seconds to keep a result whose data ends at `end` (epoch; None: no time)."""
    now = time.time() if now is None else now
    return TTL_SETTLED_S if end is None or end < now - SETTLED_AFTER_S else TTL_RECENT_S


# region store
class Store(Protocol):
    def get(self, pk: str) -> dict | None: ...
    def put(self, item: dict) -> None: ...
    def delete(self, pk: str) -> None: ...
    def scan(self) -> Iterator[dict]: ...


class DynamoStore:
    """Items {pk, kind, query, value (zlib JSON), digest, created, expires}; `expires`
    is also the table's TTL attribute, so DynamoDB deletes expired items itself."""

    def __init__(self, table: str):
        import boto3
        from botocore.config import Config

        self.table = table
        # Short timeouts: a slow cache must not cost more than the lookup it saves.
        cfg = Config(connect_timeout=1, read_timeout=2, retries={"max_attempts": 2, "mode": "standard"})
        self.client = boto3.client("dynamodb", config=cfg)

    def get(self, pk: str) -> dict | None:
        item = self.client.get_item(TableName=self.table, Key={"pk": {"S": pk}}).get("Item")
        return _from_ddb(item) if item else None

    def put(self, item: dict) -> None:
        self.client.put_item(TableName=self.table, Item=_to_ddb(item))

    def delete(self, pk: str) -> None:
        self.client.delete_item(TableName=self.table, Key={"pk": {"S": pk}})

    def scan(self) -> Iterator[dict]:
        for page in self.client.get_paginator("scan").paginate(TableName=self.table):
            yield from (_from_ddb(i) for i in page["Items"])


def _to_ddb(item: dict) -> dict:
    out = {}
    for k, v in item.items():
        if isinstance(v, bytes):
            out[k] = {"B": v}
        elif isinstance(v, (int, float)):
            out[k] = {"N": str(int(v))}
        else:
            out[k] = {"S": str(v)}
    return out


def _from_ddb(item: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in item.items():
        ((t, x),) = v.items()
        out[k] = int(x) if t == "N" else x
    return out


class MemoryStore:
    """In-process store (tests)."""

    def __init__(self):
        self.items: dict[str, dict] = {}

    def get(self, pk: str) -> dict | None:
        return self.items.get(pk)

    def put(self, item: dict) -> None:
        self.items[item["pk"]] = dict(item)

    def delete(self, pk: str) -> None:
        self.items.pop(pk, None)

    def scan(self) -> Iterator[dict]:
        yield from list(self.items.values())


_store: Store | None = None
_store_ready = False
_store_lock = threading.Lock()


def store() -> Store | None:
    """The configured store (created on first use, i.e. after a SnapStart restore)."""
    global _store, _store_ready
    if not _store_ready:
        with _store_lock:
            if not _store_ready:
                table = os.environ.get("YCGS_LOOKUP_TABLE")
                _store = DynamoStore(table) if table else None
                _store_ready = True
    return _store


def set_store(s: Store | None) -> None:
    """Use `s` (tests; None disables the cache)."""
    global _store, _store_ready
    _store, _store_ready = s, True


def reset() -> None:
    """Forget the store (after a SnapStart restore: no clients from the snapshot)."""
    global _store, _store_ready
    _store, _store_ready = None, False


# endregion store


# region lookup
# kind -> function(query) computing the lookup (registered by the modules
# that use the cache, so the prune job can recompute any entry).
KINDS: dict[str, Callable[[dict], Any]] = {}


def register(kind: str, compute: Callable[[dict], Any]) -> None:
    KINDS[kind] = compute


def key(kind: str, query: dict) -> str:
    return hashlib.sha256(_canonical([kind, query]).encode()).hexdigest()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def encode(value: Any) -> tuple[bytes, str]:
    """(zlib-compressed JSON, digest of the JSON)."""
    raw = _canonical(value).encode()
    return zlib.compress(raw, 6), hashlib.sha256(raw).hexdigest()


def decode(blob: bytes) -> Any:
    return json.loads(zlib.decompress(blob))


def cached(kind: str, query: dict, ttl: float, compute: Callable[[], Any] | None = None) -> Any:
    """The stored result of `kind(query)` if present and unexpired, else compute and store it.

    `compute` defaults to the registered function for `kind`. A result that
    is None (e.g. a truncated search) is returned but not stored."""
    compute = compute or (lambda: KINDS[kind](query))
    s = store()
    if s is None:
        return compute()
    pk = key(kind, query)
    now = time.time()
    try:
        item = s.get(pk)
        if item and item["expires"] > now:
            return decode(item["value"])
    except Exception:
        logger.warning("lookup cache read failed (%s)", kind, exc_info=True)
    value = compute()
    if value is not None:
        put(s, kind, query, value, ttl, now)
    return value


def put(s: Store, kind: str, query: dict, value: Any, ttl: float, now: float | None = None) -> None:
    now = time.time() if now is None else now
    blob, digest = encode(value)
    if len(blob) > MAX_VALUE_BYTES:
        logger.info("lookup %s: %d bytes compressed, not stored", kind, len(blob))
        return
    item = {
        "pk": key(kind, query),
        "kind": kind,
        "query": _canonical(query),
        "value": blob,
        "digest": digest,
        "created": now,
        "expires": now + ttl,
    }
    try:
        s.put(item)
    except Exception:
        logger.warning("lookup cache write failed (%s)", kind, exc_info=True)


# endregion lookup
