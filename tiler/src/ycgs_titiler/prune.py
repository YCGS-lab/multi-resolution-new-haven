"""Weekly pruning of the lookup cache (Lambda entry point `ycgs_titiler.prune.handler`,
run by an EventBridge schedule; same image as the tiler).

For each entry: expired entries are deleted (DynamoDB's TTL deletes them
too, but only within a day or two); settled entries are recomputed and
deleted if the result changed (a granule reprocessed, replaced or
withdrawn), so the next request stores the new result; entries of a kind
this version doesn't know are deleted. Short-lived entries (recent times)
are left to expire. A recompute that fails keeps the entry. Recomputing
stops a minute before the invocation's time limit; the rest wait a week.

    uv run python -m ycgs_titiler.prune   # with YCGS_LOOKUP_TABLE and AWS credentials
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import granules, lookups, timeres  # noqa: F401  (register their lookup kinds)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

WORKERS = 8
# Stop recomputing this long before Lambda's time limit.
MARGIN_S = 60


def check(s: lookups.Store, item: dict, now: float, deadline: float = float("inf")) -> str:
    if item["expires"] <= now:
        s.delete(item["pk"])
        return "expired"
    compute = lookups.KINDS.get(item["kind"])
    if compute is None:
        s.delete(item["pk"])
        return "unknown_kind"
    if item["expires"] - item["created"] < lookups.TTL_SETTLED_S / 2:
        return "recent"
    if time.monotonic() > deadline:
        return "deferred"
    try:
        value = compute(json.loads(item["query"]))
    except Exception:
        logger.warning("recompute failed for %s %s", item["kind"], item["query"], exc_info=True)
        return "error"
    if value is None or lookups.encode(value)[1] != item["digest"]:
        s.delete(item["pk"])
        return "changed"
    return "valid"


def prune(s: lookups.Store, now: float | None = None, deadline: float = float("inf")) -> dict[str, int]:
    """Counts of entries by outcome; `deadline` is a time.monotonic() value."""
    now = time.time() if now is None else now
    with ThreadPoolExecutor(WORKERS) as pool:
        counts = Counter(pool.map(lambda item: check(s, item, now, deadline), s.scan()))
    return dict(counts)


def handler(event=None, context=None) -> dict[str, int]:
    s = lookups.store()
    if s is None:
        raise RuntimeError("YCGS_LOOKUP_TABLE is not set")
    deadline = float("inf")
    if context is not None:
        deadline = time.monotonic() + context.get_remaining_time_in_millis() / 1000 - MARGIN_S
    counts = prune(s, deadline=deadline)
    logger.info("pruned lookup cache: %s", counts)
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(handler())
