# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Geocode prominent New Haven / Yale landmarks with OpenStreetMap Nominatim.

Writes `data/landmarks.json`, which the visualization scripts use to annotate
the labeled figures.
"""

import json
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "landmarks.json"

# (short label, Nominatim query). Science Hill is represented by Kline Tower,
# its tallest building and most recognizable landmark.
LANDMARKS = [
    ("Tweed Airport", "Tweed New Haven Airport, East Haven, Connecticut"),
    ("New Haven Green", "New Haven Green, New Haven"),
    ("Science Hill", "Kline Tower, New Haven"),
    ("Sterling Memorial Library", "Sterling Library, New Haven"),
]

HEADERS = {"User-Agent": "multi-resolution-new-haven (Yale research; geocoding 4 landmarks)"}


def geocode(query: str) -> dict:
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "jsonv2", "limit": 1},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    results = r.json()
    if not results:
        raise RuntimeError(f"No Nominatim result for {query!r}")
    return results[0]


def main():
    out = []
    for label, query in LANDMARKS:
        res = geocode(query)
        out.append(
            {
                "name": label,
                "lat": round(float(res["lat"]), 6),
                "lon": round(float(res["lon"]), 6),
                "osm": f"{res['osm_type']}/{res['osm_id']}",
                "display_name": res["display_name"],
            }
        )
        print(f"{label}: {res['lat']}, {res['lon']}  ({res['display_name']})")
        time.sleep(1.1)  # Nominatim usage policy: max 1 request/second
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
