# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Scan daily CHIRPS v3 over New Haven to pick a rainy day for the figures.

For every day in a date range, reads the small window covering the greater
view and prints precipitation at New Haven Green and the min / max over the
greater view's land pixels, then lists the wettest days. Reads only a few KB
per day; nothing is saved.

    uv run scripts/chirps/find_rainy_days.py [START] [END]   # YYYY-MM-DD
"""

import datetime as dt
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import chirps
import numpy as np
from common.views import VIEWS, load_landmarks

LAST_FINAL = dt.date(2026, 8, 31)  # last day with final daily COGs (as of 2026-10-02)


def stats(date: dt.date):
    stream = "final" if date <= LAST_FINAL else "prelim"
    try:
        arr, transform, _ = chirps.read_window(chirps.url(date, stream), VIEWS["greater"].bounds_lonlat(chirps.RES * 111e3))
    except Exception as e:  # missing file
        return date, stream, None, None, None, str(e).splitlines()[0]
    green = next(lm for lm in load_landmarks() if lm["name"] == "New Haven Green")
    col, row = ~transform * (green["lon"], green["lat"])
    nh = arr[int(row), int(col)]
    return date, stream, nh, np.nanmin(arr), np.nanmax(arr), ""


def main():
    start = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date(2026, 1, 1)
    end = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else dt.date(2026, 9, 30)
    days = [start + dt.timedelta(d) for d in range((end - start).days + 1)]
    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(stats, days))
    print("date        stream  NH Green  view min  view max  (mm/day)")
    for date, stream, nh, lo, hi, err in rows:
        if err:
            print(f"{date}  {stream:6s}  missing ({err})")
        elif nh >= 1:
            print(f"{date}  {stream:6s}  {nh:8.1f}  {lo:8.1f}  {hi:8.1f}")
    ok = [r for r in rows if not r[5]]
    print("\nWettest days at New Haven Green:")
    for date, stream, nh, lo, hi, _ in sorted(ok, key=lambda r: -r[2])[:15]:
        print(f"{date}  {stream:6s}  {nh:8.1f}  {lo:8.1f}  {hi:8.1f}  range {hi - lo:5.1f}")


if __name__ == "__main__":
    main()
