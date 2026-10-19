"""Turn a requested time into backend query parameters, per time kind, and
list the times available for a dataset."""

from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache

import httpx2 as httpx
import obstore
import obstore.store
from cachetools import TTLCache

from . import lookups
from .presets import Catalog, Dataset, DimensionTime, GranuleTime, ScanTime, StaticTime, TemplateTime

UTC = dt.UTC
CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"


class TimeError(ValueError):
    """A requested time can't be resolved (client error)."""


# region parse-datetime
def parse_datetime(value: str) -> dt.datetime:
    """ISO year, year-month, date or datetime; naive values are UTC."""
    try:
        if re.fullmatch(r"\d{4}(-\d{2})?", value):  # year or month: its first day
            value = f"{value}-01-01" if len(value) == 4 else f"{value}-01"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return dt.datetime.fromisoformat(value).replace(tzinfo=UTC)
        t = dt.datetime.fromisoformat(value)
    except ValueError as e:
        raise TimeError(f"invalid datetime {value!r}: {e}") from e
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def iso(t: dt.datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# endregion parse-datetime


# ---------------------------------------------------------------------------
# CMR granules: datetime -> temporal


# region granule-time
def granule_params(spec: GranuleTime, value: str) -> dict:
    # CMR ranges are inclusive and the previous period's granule ends exactly
    # where this one starts (VNP46A4 2024 ends 2025-01-01T00:00:00; SMAP L4
    # 18-21 h ends at 21:00:00), so windows start one second in.
    second = dt.timedelta(seconds=1)
    if "/" in value:  # an interval, e.g. the website's time window
        a, b = (parse_datetime(v) for v in value.split("/", 1))
        return {"temporal": f"{iso(a + second if b - a > second else a)}/{iso(b)}"}
    t = parse_datetime(value)
    if spec.align == "instant":
        return {"temporal": iso(t)}
    start, end = step_range(t, spec.align)
    return {"temporal": f"{iso(start + second)}/{iso(end - second)}"}


def step_range(t: dt.datetime, step: str) -> tuple[dt.datetime, dt.datetime]:
    """[start, end) of the UTC day, month or year containing `t`."""
    if step == "day":
        start = t.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + dt.timedelta(days=1)
    if step == "month":
        start = t.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        nxt = start.replace(year=start.year + (start.month == 12), month=start.month % 12 + 1)
        return start, nxt
    start = t.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, start.replace(year=start.year + 1)


def list_granules(ds: Dataset, aoi, start: dt.datetime, end: dt.datetime, limit: int = 500) -> list[dict]:
    params = {
        "collection_concept_id": ds.params["collection_concept_id"],
        "temporal": f"{iso(start)},{iso(end)}",
        "bounding_box": ",".join(map(str, aoi)),
        "page_size": limit,
        "sort_key": "start_date",
    }
    # Windows still being ingested change from one request to the next; cache settled ones only.
    if end.timestamp() < dt.datetime.now(UTC).timestamp() - lookups.SETTLED_AFTER_S:
        return lookups.cached("cmr-times", params, lookups.TTL_SETTLED_S)
    return _search_granules(params)


def _search_granules(params: dict) -> list[dict]:
    r = httpx.get(CMR_GRANULES, params=params, timeout=20)
    r.raise_for_status()
    return [
        {"datetime": e["time_start"], "end": e.get("time_end"), "granule_ur": e.get("title")}
        for e in r.json()["feed"]["entry"]
    ]


lookups.register("cmr-times", _search_granules)


# endregion granule-time


# ---------------------------------------------------------------------------
# A time dimension inside one dataset: datetime -> sel


# region dimension-time
def dimension_params(spec: DimensionTime, values: list[str]) -> dict:
    method = f"{spec.method}::" if spec.method else ""
    sels = [f"{spec.dim}={method}{iso(parse_datetime(v)).rstrip('Z')}" for v in values]
    return {"sel": sels}


def list_dimension(ds: Dataset, start: dt.datetime, end: dt.datetime, limit: int = 2000) -> list[dict]:
    from .readers import open_dataset

    spec = ds.time
    assert isinstance(spec, DimensionTime)
    xds = open_dataset(ds.params["url"], group=ds.params.get("group"))
    coord = xds[spec.dim].sel({spec.dim: slice(iso(start).rstrip("Z"), iso(end).rstrip("Z"))})
    return [{"datetime": str(v)[:19] + "Z"} for v in coord.values[:limit]]


# endregion dimension-time


# ---------------------------------------------------------------------------
# GOES ABI: one file per scan on NOAA Open Data


# region scan-time
SCAN_RE = re.compile(r"OR_(?P<product>[A-Za-z0-9-]+?)-M\d(?P<channel>C\d\d)?_G\d\d_s(?P<start>\d{13})\d")
_current_hour: TTLCache = TTLCache(maxsize=64, ttl=30)


@lru_cache(maxsize=4)
def _bucket_store(bucket: str):
    from .readers import bucket_region

    return obstore.store.S3Store(bucket, config={"region": bucket_region(bucket), "skip_signature": True})


@lru_cache(maxsize=512)
def _list_complete_hour(bucket: str, prefix: str) -> tuple[str, ...]:
    # A complete hour's scans don't change: kept in the lookup cache across execution environments.
    query = {"bucket": bucket, "prefix": prefix}
    return tuple(lookups.cached("goes-hour", query, lookups.TTL_SETTLED_S))


def _list(bucket: str, prefix: str) -> tuple[str, ...]:
    out = []
    for batch in obstore.list(_bucket_store(bucket), prefix=prefix):
        out.extend(o["path"] for o in batch)
    return tuple(out)


lookups.register("goes-hour", lambda q: list(_list(q["bucket"], q["prefix"])))


def _hour_keys(spec: ScanTime, hour: dt.datetime) -> list[tuple[dt.datetime, str]]:
    prefix = f"{spec.product}/{hour:%Y}/{hour.timetuple().tm_yday:03d}/{hour:%H}/"
    if hour + dt.timedelta(hours=1, minutes=15) < dt.datetime.now(UTC):
        keys = _list_complete_hour(spec.bucket, prefix)
    else:  # still being written: short cache
        cache_key = (spec.bucket, prefix)
        if (keys := _current_hour.get(cache_key)) is None:
            keys = _current_hour[cache_key] = _list(spec.bucket, prefix)
    scans = []
    for k in keys:
        m = SCAN_RE.search(k)
        if not m or m["product"] != spec.product or m["channel"] != spec.channel:
            continue
        start = dt.datetime.strptime(m["start"], "%Y%j%H%M%S").replace(tzinfo=UTC)
        scans.append((start, k))
    return sorted(scans)


def scan_key(spec: ScanTime, value: str | None) -> tuple[dt.datetime, str]:
    """(scan start, key) nearest to `value`, or the latest scan if `value` is None."""
    if value is None:
        now = dt.datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        for back in range(4):
            if scans := _hour_keys(spec, now - dt.timedelta(hours=back)):
                return scans[-1]
        raise TimeError(f"no {spec.product} scans in the last 4 hours")
    t = parse_datetime(value)
    hour = t.replace(minute=0, second=0, microsecond=0)
    scans = [s for h in (-1, 0, 1) for s in _hour_keys(spec, hour + dt.timedelta(hours=h))]
    if not scans:
        raise TimeError(f"no {spec.product} scan near {iso(t)}")
    return min(scans, key=lambda s: abs((s[0] - t).total_seconds()))


def scan_params(spec: ScanTime, value: str | None) -> tuple[dict, str]:
    start, key = scan_key(spec, value)
    return {"url": f"s3://{spec.bucket}/{key}"}, iso(start)


def list_scans(ds: Dataset, start: dt.datetime, end: dt.datetime, limit: int = 2000) -> list[dict]:
    spec = ds.time
    assert isinstance(spec, ScanTime)
    if end - start > dt.timedelta(hours=48):
        raise TimeError("list at most 48 hours of scans at a time")
    out = []
    hour = start.replace(minute=0, second=0, microsecond=0)
    while hour <= end and len(out) < limit:
        out.extend({"datetime": iso(s), "key": k} for s, k in _hour_keys(spec, hour) if start <= s <= end)
        hour += dt.timedelta(hours=1)
    return out[:limit]


# endregion scan-time


# ---------------------------------------------------------------------------
# One file per step at a URL template (CHIRPS)


# region template-time
def template_params(spec: TemplateTime, value: str) -> tuple[dict, str]:
    start, _ = step_range(parse_datetime(value.split("/", 1)[0]), spec.step)
    return {"url": spec.url.format(t=start)}, start.date().isoformat()


def list_template(spec: TemplateTime, start: dt.datetime, end: dt.datetime, limit: int = 2000) -> list[dict]:
    latest = dt.datetime.now(UTC) - dt.timedelta(days=spec.latency_days)
    t, _ = step_range(start, spec.step)
    out = []
    while t <= min(end, latest) and len(out) < limit:
        out.append({"datetime": t.date().isoformat()})
        t = step_range(t, spec.step)[1]
    return out


# endregion template-time


# region list-times
def list_times(catalog: Catalog, ds: Dataset, start: str | None, end: str | None) -> list[dict]:
    t1 = parse_datetime(end) if end else dt.datetime.now(UTC)
    if start:
        t0 = parse_datetime(start)
    else:
        t0 = (
            t1
            - {
                "granule": dt.timedelta(days=30),
                "dimension": dt.timedelta(days=2),
                "scan": dt.timedelta(hours=3),
                "template": dt.timedelta(days=60),
                "static": dt.timedelta(0),
            }[ds.time.kind]
        )
    if t1 < t0:
        raise TimeError("end is before start")
    if isinstance(ds.time, StaticTime):
        return []
    if isinstance(ds.time, TemplateTime):
        return list_template(ds.time, t0, t1)
    if isinstance(ds.time, GranuleTime):
        return list_granules(ds, catalog.aoi, t0, t1)
    if isinstance(ds.time, DimensionTime):
        return list_dimension(ds, t0, t1)
    return list_scans(ds, t0, t1)


# endregion list-times


def clear_caches() -> None:
    _current_hour.clear()
    _list_complete_hour.cache_clear()
    _bucket_store.cache_clear()
