# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pandas", "geopandas", "pyarrow", "shapely", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""ICESat-2 canopy height (ATL08) and classified photon profiles (ATL03 + ATL08),
from the files written by download.py.

Map products (per view, on a lightened OpenStreetMap basemap):
  canopy_height           ATL08 20 m canopy heights, growing seasons 2025 + 2026
  canopy_height_allyears  same, all growing seasons 2019-2026 (the central view
                          has no 2025-2026 segments)
  tracks                  the numbered sample lines used for the photon profiles
Profiles (not maps): figures/icesat2/profile_<n>.png and profile_<n>_labeled.png
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geopandas as gpd
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from PIL import Image

from common import config, remote, render
from common.views import VIEWS

DATASET = "icesat2"
DATA = config.data_dir(DATASET)
RECENT = (2025, 2026)
ALL_YEARS = tuple(range(2019, 2027))
SOURCE = "NASA ICESat-2 ATL08/ATL03 release 007 via SlideRule Earth (slideruleearth.io). " + remote.OSM_ATTRIBUTION

CANOPY_CMAP = "viridis"
CANOPY_NORM = Normalize(0, 35)
NO_CANOPY = "#7a7a7a"
LINE_COLORS = ["#d62728", "#1f77b4", "#ff7f0e"]  # validated categorical order
# ATL08 photon classes: (label, color, draw order); palette checked with the dataviz validator
CLASSES = {
    0: ("Noise", "#bdbdbd", 0),
    4: ("Unclassified", "#3a87c8", 1),
    1: ("Ground", "#a6611a", 2),
    2: ("Canopy", "#7fbc41", 3),
    3: ("Top of canopy", "#1b7837", 4),
}


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


def load_20m(years) -> gpd.GeoDataFrame:
    """ATL08 20 m sub-segments with a valid canopy and/or ground height."""
    gdf = pd.concat([gpd.read_parquet(DATA / f"atl08_20m_{y}.parquet") for y in years]).sort_index()
    return gdf[gdf["h_canopy_20m"].notna() | gdf["h_te_best_fit_20m"].notna()]


def in_view(gdf, view, pad_px=20):
    x, y = view.to_xy(gdf.geometry.x.values, gdf.geometry.y.values)
    xmin, ymin, xmax, ymax = view.bounds
    p = pad_px * view.pixel_size_m * view.merc_scale
    m = (x >= xmin - p) & (x <= xmax + p) & (y >= ymin - p) & (y <= ymax + p)
    return gdf[m], x[m], y[m]


def pass_summary(gdf, view) -> tuple[str, list[str]]:
    """'n passes: dates' for the passes with data inside the view."""
    sub, _, _ = in_view(gdf, view, pad_px=0)
    dates = sorted({str(sub.index[sub["granule"] == g].min())[:10] for g in sub["granule"].unique()})
    return f"{len(dates)} pass{'es' if len(dates) != 1 else ''}", dates


# --------------------------------------------------------------------------
# Basemap
# --------------------------------------------------------------------------


def basemap(view) -> np.ndarray:
    """OSM tiles one zoom level coarser than auto (legible labels), desaturated
    and lightened so the data points stand out. Cached in data/icesat2/."""
    z = remote.auto_zoom(view) - 1
    path = DATA / f"osm_{view.name}_z{z}.png"
    if path.exists():
        rgba = np.asarray(Image.open(path))
    else:
        rgba = remote.fetch_osm(view, zoom=z)
        render.save_png(rgba, path)
    rgb = rgba[..., :3].astype("float32") / 255
    gray = rgb @ np.array([0.299, 0.587, 0.114], dtype="float32")
    rgb = 0.45 * rgb + 0.55 * gray[..., None]  # desaturate
    rgb = 1 - 0.65 * (1 - rgb)  # lighten
    return render.to_rgba(rgb)


def marker_size(view, ground_m=20.0, min_px=12.0) -> float:
    """Scatter size (pt^2): ~ the 20 m segment length, but at least min_px wide."""
    d_px = max(min_px, ground_m / view.pixel_size_m)
    return (d_px * 72 / render.DPI) ** 2


def save_map(fig_fn, view, product, **label_kwargs):
    """Draw with fig_fn(ax) on the basemap; write data-only and labeled PNGs."""
    plain, labeled = config.figure_paths(DATASET, view.name, product)
    base = basemap(view)
    for path, labels in ((plain, False), (labeled, True)):
        fig, ax = render.map_figure(view, base)
        fig_fn(ax)
        if labels:
            render.add_labels(ax, view, **label_kwargs)
        render.save_figure(fig, path)
    assert Image.open(plain).size == (view.width_px, view.height_px)
    print(f"  wrote {plain.relative_to(config.REPO)} and {labeled.name}")


# --------------------------------------------------------------------------
# Canopy height maps
# --------------------------------------------------------------------------


def canopy_map(view, years, product, period):
    gdf = load_20m(years)
    sub, x, y = in_view(gdf, view)
    has = sub["h_canopy_20m"].notna().values
    s = marker_size(view)
    print(f"  {product}: {has.sum()} canopy + {(~has).sum()} ground-only 20 m segments")

    def draw(ax):
        ax.scatter(x[~has], y[~has], s=s * 0.35, c=NO_CANOPY, linewidths=0, zorder=2)
        # time-sorted, so the most recent pass is drawn on top where tracks repeat
        ax.scatter(
            x[has], y[has], s=s, c=sub["h_canopy_20m"].values[has], cmap=CANOPY_CMAP, norm=CANOPY_NORM,
            edgecolors="black", linewidths=0.25, zorder=3,
        )  # fmt: skip

    n, dates = pass_summary(gdf, view)
    when = ", ".join(dates) if len(dates) <= 6 else f"{dates[0]} to {dates[-1]}"
    subtitle = (
        f"{period}: {n} with data in view ({when})\n"
        f"ATL08 h_canopy_20m (98th percentile canopy relief), 20 m along-track segments, ~11 m footprints; "
        f"gray = ground only (no canopy height)"
    )
    if not len(dates):
        subtitle = f"{period}: no ICESat-2 ATL08 segments in this view\nATL08 h_canopy_20m, 20 m along-track segments"
    save_map(
        draw, view, product,
        title="ICESat-2 ATL08 canopy height",
        subtitle=subtitle,
        colorbar=dict(cmap=CANOPY_CMAP, norm=CANOPY_NORM, label="Canopy height (m)", extend="max"),
        source=SOURCE,
    )  # fmt: skip


# --------------------------------------------------------------------------
# Sample lines
# --------------------------------------------------------------------------


def load_lines():
    lines = json.loads((DATA / "lines.json").read_text())
    for line in lines:
        ph = gpd.read_parquet(DATA / f"atl03_line{line['n']}.parquet").sort_values("x_atc")
        lat = ph.geometry.y.values
        # along-track distance from the southern edge of the view
        ascending = np.corrcoef(ph["x_atc"].values, lat)[0, 1] > 0
        x = ph["x_atc"].values
        ph["dist_km"] = ((x - x.min()) if ascending else (x.max() - x)) / 1000
        line["photons"] = ph
        line["label"] = f"{line['date'][:10]}, RGT {line['rgt']}, beam {line['beam']}"
    return lines


def tracks_map(view, lines):
    lw_px = 9

    def draw(ax):
        halo = [pe.Stroke(linewidth=(lw_px + 6) * 72 / render.DPI, foreground="white"), pe.Normal()]
        xmin, ymin, xmax, ymax = view.bounds
        for line, color in zip(lines, LINE_COLORS):
            ph = line["photons"].iloc[::25].sort_values("dist_km")
            x, y = view.to_xy(ph.geometry.x.values, ph.geometry.y.values)
            ax.plot(x, y, color=color, lw=lw_px * 72 / render.DPI, solid_capstyle="round", path_effects=halo, zorder=5)
            inside = (x >= xmin) & (x <= xmax) & (y >= ymin) & (y <= ymax)
            if not inside.any():
                continue
            # number near the northern end of the visible part of the line
            yt = min(y[inside].max(), ymax - 0.24 * (ymax - ymin))  # below the title block
            i = np.argmin(np.abs(np.where(inside, y, np.inf) - yt))
            ax.annotate(
                str(line["n"]), (x[i], y[i]), xytext=(0, 0), textcoords="offset points",
                ha="center", va="center", fontsize=20, fontweight="bold", color="white", zorder=7,
                bbox=dict(boxstyle="circle,pad=0.35", fc=color, ec="white", lw=2.5),
            )  # fmt: skip

    visible = [len(in_view(l["photons"], view, pad_px=0)[0]) > 0 for l in lines]
    entries = [(c, f"{l['n']}: {l['label']}") for l, c, v in zip(lines, LINE_COLORS, visible) if v]
    save_map(
        draw, view, "tracks",
        title="ICESat-2 photon profile sample lines",
        subtitle="Strong-beam ATL03 ground tracks with ATL08 photon classes (see profile_<n>.png)",
        legend=dict(entries=entries, title="Sample line: date (UTC), track, beam"),
        source=SOURCE,
    )  # fmt: skip


def central_span(line):
    """Along-track distance range (km) of the line inside the central view, if any."""
    ph = line["photons"]
    sub, _, _ = in_view(ph, VIEWS["central"], pad_px=0)
    return (sub["dist_km"].min(), sub["dist_km"].max()) if len(sub) else None


def profile(line):
    ph = line["photons"]
    d, h, cls = ph["dist_km"].values, ph["height"].values, ph["atl08_class"].values
    signal = np.isin(cls, (1, 2, 3))
    ground = h[cls == 1]
    lo = np.percentile(ground, 0.5) - 15
    hi = np.percentile(h[signal], 99.9) + 25
    w, hpx = 3840, 2160
    out = config.figure_dir(DATASET)
    order = sorted(CLASSES, key=lambda c: CLASSES[c][2])

    def scatter(ax, s):
        for c in order:
            m = cls == c
            size = s * 0.6 if c in (0, 4) else s  # recessive noise / unclassified
            ax.scatter(d[m], h[m], s=size, c=CLASSES[c][1], linewidths=0, rasterized=True, zorder=2 + CLASSES[c][2])
        ax.set_xlim(0, d.max())
        ax.set_ylim(lo, hi)

    # data only: the axes fill the figure
    fig = plt.figure(figsize=(w / render.DPI, hpx / render.DPI), dpi=render.DPI, facecolor="white")
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_axis_off()
    scatter(ax, s=2.5)
    render.save_figure(fig, out / f"profile_{line['n']}.png")

    # labeled
    fig, ax = plt.subplots(figsize=(w / render.DPI, hpx / render.DPI), dpi=render.DPI, facecolor="white")
    fig.subplots_adjust(left=0.06, right=0.985, bottom=0.09, top=0.85)
    scatter(ax, s=2.5)
    span = central_span(line)
    if span:
        ax.axvspan(*span, color="#000000", alpha=0.06, lw=0, zorder=1)
        ax.text(np.mean(span), hi - 0.02 * (hi - lo), "central view", ha="center", va="top", fontsize=14, color="#444")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(color="#e6e6e6", lw=0.8, zorder=0)
    ax.tick_params(labelsize=15)
    ax.set_xlabel("Distance along track from the southern edge of the Greater New Haven view (km)", fontsize=18)
    ax.set_ylabel("Elevation (m above EGM2008 geoid)", fontsize=18)
    t = pd.Timestamp(ph.index.min())
    strength = "strong" if line["spot"] in (1, 3, 5) else "weak"
    fig.suptitle(
        f"ICESat-2 photons with ATL08 classification: sample line {line['n']}",
        x=0.06, y=0.975, ha="left", fontsize=26, fontweight="bold",
    )  # fmt: skip
    fig.text(
        0.06, 0.875,
        f"{t:%Y-%m-%d %H:%M} UTC, RGT {line['rgt']}, cycle {line['cycle']}, beam {line['beam']} "
        f"({strength}, spot {line['spot']}); {len(ph):,} ATL03 photons inside the Greater New Haven view\n"
        f"Laser shots every ~0.7 m along track, ~11 m footprint; photons far outside the plotted height range omitted",
        ha="left", fontsize=15, color="#333",
    )  # fmt: skip
    counts = pd.Series(cls).value_counts()
    handles = [
        Line2D([], [], ls="", marker="o", ms=11, mfc=CLASSES[c][1], mec="none", label=f"{CLASSES[c][0]} ({counts.get(c, 0):,})")
        for c in reversed(order)
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=15, title="ATL08 photon class", title_fontsize=15, framealpha=0.9)
    fig.text(0.985, 0.012, "NASA ICESat-2 ATL03/ATL08 release 007 via SlideRule Earth", ha="right", fontsize=11, color="#555")
    render.save_figure(fig, out / f"profile_{line['n']}_labeled.png")
    print(f"  wrote profile_{line['n']}.png and profile_{line['n']}_labeled.png")


def main():
    lines = load_lines()
    for view in VIEWS.values():
        print(view.title)
        canopy_map(view, RECENT, "canopy_height", "May-Sep 2025 and May-Sep 2026 (2026 data available through mid-July)")
        canopy_map(view, ALL_YEARS, "canopy_height_allyears", "Growing seasons (May-Sep) 2019-2026")
        tracks_map(view, lines)
    print("Profiles")
    for line in lines:
        profile(line)


if __name__ == "__main__":
    main()
