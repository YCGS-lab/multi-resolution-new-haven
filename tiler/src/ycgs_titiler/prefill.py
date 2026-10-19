"""Pre-fill the lookup cache with the CMR granule searches of an area (New
Haven by default), so the first view of a date there doesn't wait on CMR.

For each CMR dataset preset: list the granule times over the area (CMR,
month by month), turn each time into the `datetime` values clients send (the
API's and the website's forms), resolve them as a request would
(`router.resolve`), and store the parent-tile search (`granules.search_parent`)
of every parent tile covering the area under the key a tile request computes.
Entries already stored and unexpired are skipped (`--force` recomputes them).
Times that aren't settled yet are skipped: their entries would expire within
the hour. The weekly prune job then keeps the entries correct like any other.

    uv run python -m ycgs_titiler.prefill --table <nasa lookup_table> [--datasets hls-l30 ...]
        [--start 2024-01-01] [--end 2024-12-31] [--zooms 6-8] [--dry-run]

Run it against the nasa deployment's table (us-west-2; `tofu output
deployments`): the CMR datasets are served there.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import time
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

from httpx2 import Client
from rio_tiler.constants import WEB_MERCATOR_TMS
from titiler.cmr.dependencies import GranuleSearchBackendParams, RasterioGranuleSearchBackendParams
from titiler.cmr.models import GranuleSearch
from titiler.cmr.query import CMR_GRANULE_SEARCH_API

from . import granules, lookups, router, timeres
from .presets import CMR_BACKENDS, Catalog, Dataset, GranuleTime, StaticTime, catalog

logger = logging.getLogger(__name__)

WORKERS = 4
PAGE_SIZE = 2000  # CMR's maximum
RETRIES = 3
# GranuleSearch fields that take a repeated query key
LIST_FIELDS = {"sort_key", "attribute"}


# region times
def granule_times(ds: Dataset, bbox, start: dt.datetime, end: dt.datetime) -> tuple[list[dt.datetime], int]:
    """Start times of the dataset's granules over `bbox` in [start, end], month by
    month, and the number of months whose listing failed (skipped; a later run
    fills them)."""
    out = []
    failed = 0
    t = start
    while t < end:
        t2 = min(timeres.step_range(t, "month")[1], end)
        params = {
            "collection_concept_id": ds.params["collection_concept_id"],
            "temporal": f"{timeres.iso(t)},{timeres.iso(t2)}",
            "bounding_box": ",".join(map(str, bbox)),
            "page_size": PAGE_SIZE,
            "sort_key": "start_date",
        }
        try:
            entries = _retry(lambda p=params: timeres._search_granules(p))
        except Exception:
            logger.warning("%s: listing %s failed; skipped", ds.title, params["temporal"], exc_info=True)
            entries = []
            failed += 1
        if len(entries) >= PAGE_SIZE:
            logger.warning("%s: %d+ granules in %s; times past them are missed", ds.title, PAGE_SIZE, t.date())
        out.extend(timeres.parse_datetime(e["datetime"]) for e in entries)
        t = t2
    return sorted(set(out)), failed


def datetimes(spec: GranuleTime, t: dt.datetime) -> list[str]:
    """`datetime` values a client sends for the time step of a granule starting at `t`:
    the step's start (the API, the website's "instant" form) and the website's
    "interval" form (the step's start to its end minus a second; a minute for
    a dataset without steps)."""
    second = dt.timedelta(seconds=1)
    if spec.align == "instant":
        minute = t.replace(second=0, microsecond=0)
        return [timeres.iso(t), f"{timeres.iso(minute)}/{timeres.iso(minute + 59 * second)}"]
    start, stop = timeres.step_range(t, spec.align)
    return [timeres.iso(start), f"{timeres.iso(start)}/{timeres.iso(stop - second)}"]


# endregion times


# region queries
def granule_search(params: list[tuple[str, str]]) -> GranuleSearch:
    """The GranuleSearch titiler-cmr builds from a request's query parameters."""
    values: dict[str, list[str]] = {}
    for k, v in params:
        values.setdefault(k, []).append(v)
    fields = {}
    for name in GranuleSearch.model_fields:
        if name in values:
            fields[name] = values[name] if name in LIST_FIELDS else values[name][-1]
    return GranuleSearch(**fields)


def coverage_tolerance(ds: Dataset) -> float:
    """titiler-cmr's default for the dataset's backend (presets don't let clients set it)."""
    params = RasterioGranuleSearchBackendParams if ds.backend == "cmr-rasterio" else GranuleSearchBackendParams
    return params.coverage_tolerance


def parent_tiles(ds: Dataset, bbox, zooms: list[int]) -> list[list[int]]:
    """Parent tiles ([x, y, z]) of the tile requests over `bbox` at `zooms`."""
    out = []
    for z in zooms:
        if not ds.minzoom <= z <= ds.maxzoom:
            continue
        for tile in WEB_MERCATOR_TMS.tiles(*bbox, zooms=[z]):
            p = granules.parent_tile(WEB_MERCATOR_TMS.bounds(tile))
            if [p.x, p.y, p.z] not in out:
                out.append([p.x, p.y, p.z])
    return out


def queries(cat: Catalog, ds_id: str, values: list[str | None], tiles: list[list[int]]) -> Iterator[dict]:
    """Lookup queries of tile requests for `ds_id` at each `datetime` value, as
    `CachedCMRBackend.get_assets` builds them."""
    ds = cat.datasets[ds_id]
    render = next(iter(ds.renders))
    tolerance = coverage_tolerance(ds)
    for value in values:
        resolved = router.resolve(cat, ds_id, render, "info", {"datetime": [value]} if value else {})
        search = granule_search(resolved.params).model_dump(mode="json", exclude_none=True)
        for tile in tiles:
            yield {"search": search, "tile": tile, "tolerance": tolerance}


# endregion queries


# region fill
def _retry(fn):
    for attempt in range(RETRIES):
        try:
            return fn()
        except Exception:
            if attempt == RETRIES - 1:
                raise
            time.sleep(2 * 2**attempt)


def fill(s: lookups.Store, query: dict, client: Client, force: bool = False) -> str:
    """Search and store one parent tile's granules; the outcome."""
    pk = lookups.key(granules.KIND, query)
    if not force:
        try:
            item = s.get(pk)
        except Exception:
            logger.warning("lookup cache read failed", exc_info=True)
            item = None
        if item and item["expires"] > time.time():
            return "cached"
    search = GranuleSearch.model_validate(query["search"])
    try:
        value = _retry(lambda: granules.search_parent(query, client))
    except Exception:
        logger.warning("search failed: %s", query, exc_info=True)
        return "error"
    lookups.put(s, granules.KIND, query, value, lookups.ttl_for(granules.data_end(search)))
    return "stored" if value["complete"] else "stored_truncated"


def plan(
    cat: Catalog, ds_ids: list[str], bbox, start: dt.datetime, end: dt.datetime, zooms: list[int] | None
) -> Iterator[tuple[str, dict | str]]:
    """(dataset id, query) of every entry to fill, unique, or (dataset id,
    outcome) for one skipped: "recent" (not settled yet), "listing_error" (a
    month whose times couldn't be listed)."""
    seen = set()
    for ds_id in ds_ids:
        ds = cat.datasets[ds_id]
        tiles = parent_tiles(ds, bbox, zooms or [min(granules.CACHE_ZOOM, ds.maxzoom)])
        if isinstance(ds.time, StaticTime):
            values: list[str | None] = [None]
        else:
            assert isinstance(ds.time, GranuleTime)
            times, failed = granule_times(ds, bbox, start, end)
            for _ in range(failed):
                yield ds_id, "listing_error"
            logger.info("%s: %d granule times, %d parent tiles", ds_id, len(times), len(tiles))
            values = [v for t in times for v in datetimes(ds.time, t)]
        for query in queries(cat, ds_id, values, tiles):
            pk = lookups.key(granules.KIND, query)
            if pk in seen:
                continue
            seen.add(pk)
            search = GranuleSearch.model_validate(query["search"])
            settled = lookups.ttl_for(granules.data_end(search)) == lookups.TTL_SETTLED_S
            yield ds_id, query if settled else "recent"


def prefill(
    s: lookups.Store | None,
    ds_ids: list[str],
    bbox=None,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    zooms: list[int] | None = None,
    workers: int = WORKERS,
    force: bool = False,
    cat: Catalog | None = None,
) -> dict[str, Counter]:
    """Counts of entries by outcome, per dataset; with no store, only plans (dry run)."""
    cat = cat or catalog()
    settled = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=lookups.SETTLED_AFTER_S)
    end = min(end or settled, settled)
    start = start or timeres.step_range(end - dt.timedelta(days=365), "day")[0]
    bbox = bbox or cat.aoi
    counts: dict[str, Counter] = {ds_id: Counter() for ds_id in ds_ids}
    with Client(base_url=CMR_GRANULE_SEARCH_API, timeout=30) as client, ThreadPoolExecutor(workers) as pool:

        def one(entry: tuple[str, dict | str]) -> tuple[str, str]:
            ds_id, query = entry
            if isinstance(query, str):
                return ds_id, query
            if s is None:
                return ds_id, "planned"
            return ds_id, fill(s, query, client, force)

        for n, (ds_id, outcome) in enumerate(pool.map(one, plan(cat, ds_ids, bbox, start, end, zooms)), 1):
            counts[ds_id][outcome] += 1
            if n % 100 == 0:
                logger.info("%d entries: %s", n, {k: dict(v) for k, v in counts.items()})
    return counts


# endregion fill


def _zooms(value: str) -> list[int]:
    a, _, b = value.partition("-")
    zooms = list(range(int(a), int(b or a) + 1))
    if max(zooms) > granules.CACHE_ZOOM:
        raise argparse.ArgumentTypeError(
            f"tiles above zoom {granules.CACHE_ZOOM} share their zoom-{granules.CACHE_ZOOM} parent's entry"
        )
    return zooms


def main(argv: list[str] | None = None) -> None:
    cmr_ids = [k for k, ds in catalog().datasets.items() if ds.backend in CMR_BACKENDS]
    p = argparse.ArgumentParser(prog="python -m ycgs_titiler.prefill", description=__doc__.split("\n\n")[0])
    p.add_argument("--table", help="DynamoDB lookup table (default: $YCGS_LOOKUP_TABLE)")
    p.add_argument(
        "--datasets", nargs="+", choices=cmr_ids, default=cmr_ids, metavar="ID", help=f"default: {' '.join(cmr_ids)}"
    )
    p.add_argument("--start", type=timeres.parse_datetime, help="default: a year before --end")
    p.add_argument("--end", type=timeres.parse_datetime, help="default (and latest): the settled cutoff (7 days ago)")
    p.add_argument(
        "--bbox",
        type=lambda v: tuple(map(float, v.split(","))),
        help="lon/lat minx,miny,maxx,maxy (default: the catalog's aoi)",
    )
    p.add_argument(
        "--zooms",
        type=_zooms,
        help=f"request zooms, e.g. 6-8 (default: {granules.CACHE_ZOOM}, or the dataset's maxzoom if lower)",
    )
    p.add_argument("--workers", type=int, default=WORKERS, help="concurrent CMR searches")
    p.add_argument("--force", action="store_true", help="recompute entries already stored")
    p.add_argument("--dry-run", action="store_true", help="list times and count entries; search and store nothing")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logger.setLevel(logging.INFO)
    if args.table:
        lookups.set_store(lookups.DynamoStore(args.table))
    s = None if args.dry_run else lookups.store()
    if s is None and not args.dry_run:
        p.error("no lookup table: pass --table or set YCGS_LOOKUP_TABLE (or use --dry-run)")
    counts = prefill(s, args.datasets, args.bbox, args.start, args.end, args.zooms, args.workers, args.force)
    for ds_id, c in counts.items():
        print(f"{ds_id}: {dict(c) or 'nothing to fill'}")


if __name__ == "__main__":
    main()
