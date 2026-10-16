# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"]
# ///
"""Website layers for the Connecticut statewide orthoimagery, 1934-2023: the
website requests each tile from the CT ECO image service of the selected year
(exportImage, JPEG of the server's 8-bit band values) and shows the values as
they are (no stretch), so there is no local copy of the multi-gigapixel mosaics.

Years (a drop-down: the flights are years apart):
  1934  Fairchild aerial survey, black and white (MAGIC mosaic)
  1990  black and white;  2004  black and white (statewide)
  2008  color, urban areas;  2012, 2016, 2019, 2023  color + near infrared

Products: truecolor (R, G, B, or gray for the black-and-white years) and
cir (NIR, R, G; 2012 on). Figures of the 2023 flight: scripts/ct-ortho-2023/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import web

DATASET = "ct-ortho"
BASE = "https://cteco.uconn.edu/ctraster/rest/services/images"
SOURCE = "Connecticut statewide orthoimagery (CT State GIS Office, CT DEEP, UConn MAGIC), via CT ECO image services (cteco.uconn.edu)"

# region ortho-years
# year: (service, native pixel (m), bands, flown)
YEARS = {
    "1934": ("Mosaic_1934_MAGIC", 0.885, 1, "1934 (Fairchild Aerial Surveys), black and white"),
    "1990": ("Ortho_1990", 1.0, 1, "spring 1990, black and white"),
    "2004": ("Ortho_2004", 0.253, 1, "spring 2004, black and white"),
    "2008": ("Ortho_2008_UrbanArea", 0.3, 3, "spring 2008, color (urban areas)"),
    "2012": ("Ortho_2012", 0.305, 4, "spring 2012 (leaf-off), 4-band"),
    "2016": ("Ortho_2016", 0.0762, 4, "spring 2016 (leaf-off), 4-band"),
    "2019": ("Ortho_2019", 0.152, 4, "spring 2019 (leaf-off), 4-band (16-bit, server stretch)"),
    "2023": ("Ortho_2023", 0.0762, 4, "2023-03-27 to 04-13 (leaf-off), 4-band"),
}
# endregion ortho-years


def fmt_m(m: float) -> str:
    return f"{m * 100:.1f} cm" if m < 0.2 else f"{m:.2g} m"


def source(years: dict, band_ids) -> dict:
    """One arcgis source whose service (and resolution) follow the selected year."""
    variants = {
        year: web.arcgis_variant(f"{BASE}/{service}/ImageServer", native_m, band_ids=band_ids if nbands >= 3 else None)
        for year, (service, native_m, nbands, _) in years.items()
    }
    latest = max(years)
    service, native_m, _, _ = years[latest]
    return web.arcgis_source(f"{BASE}/{service}/ImageServer", native_m, band_ids=band_ids, variants=variants)


def time(years: dict) -> dict:
    labels = {y: f"{y}: {years[y][3]}" for y in years}
    return web.time_spec("year", web.avail_list(list(years), labels=labels), label="Flight", widget="list")


def main():
    cir_years = {y: v for y, v in YEARS.items() if v[2] == 4}
    sources = {"truecolor": source(YEARS, [0, 1, 2]), "cir": source(cir_years, [3, 0, 1])}
    native = {y: fmt_m(v[1]) for y, v in YEARS.items()}
    products = {
        "truecolor": web.product(
            title="Connecticut orthoimagery, true color",
            subtitle="Statewide aerial orthophotos; server 8-bit values shown as is",
            native="7.6 cm to 1 m, by year",
            native_by_time=native,
            source=SOURCE,
            landmark_color="yellow",
            layers=[web.layer("truecolor", web.identity())],
            time=time(YEARS),
        ),
        "cir": web.product(
            title="Connecticut orthoimagery, color infrared (NIR, red, green)",
            subtitle="Statewide aerial orthophotos; server 8-bit values shown as is",
            native="7.6 to 30 cm, by year",
            native_by_time=native,
            source=SOURCE,
            layers=[web.layer("cir", web.identity())],
            time=time(cir_years),
        ),
    }
    web.write_spec(DATASET, sources, products, dict(coverage=web.CONNECTICUT, min_zoom=12))


if __name__ == "__main__":
    main()
