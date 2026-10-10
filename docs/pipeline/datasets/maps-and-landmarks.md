# Street maps and landmarks

## Street maps

**OpenStreetMap Standard, Esri World Street Map, USGS National Map topo.**
Script: `streetmap/website-layers.py` (website only, no figures).

::: code-group
<<< @/../scripts/streetmap/website-layers.py#basemap-sources [scripts/streetmap/website-layers.py#basemap-sources]
:::

::: warning Design decision: only maps that need no key
CARTO basemaps now need an API key. Google's tiles need a key and may only
be used through Google's own map APIs. These three are free to use with
attribution, and USGS topo is public domain. Esri and USGS attribution text
is read from the services' own metadata (`?f=json`), so it stays current.
Note the ArcGIS tile URL order, `{z}/{y}/{x}` (row before column).
:::

The website draws these tiles as they come, at about their design size so
the labels stay readable; see [Image-service layers](/website/image-services#xyz-map-tiles).

## Landmarks

**Four places, geocoded once:** Tweed Airport, New Haven Green, Science Hill
(Kline Tower) and Sterling Memorial Library. Script:
`landmarks/geocode.py`. Output: `data/landmarks.json`, the only tracked file
under `data/`.

::: code-group
<<< @/../scripts/landmarks/geocode.py#landmark-queries [scripts/landmarks/geocode.py#landmark-queries]
:::

The script queries OpenStreetMap's Nominatim service with an identifying
`User-Agent`, one result per query, and 1.1 s between requests, as its usage
policy asks. It does not import `scripts/common/`.

The landmarks appear:
- on every labeled figure (`render.add_landmarks`);
- in `catalog.json` for the website's Labels toggle (`build_catalog.py`);
- as the reference point in `chirps/find_rainy_days.py`.

Sterling Memorial Library's label is placed left of its marker, to avoid
overlapping labels (`_LABEL_LEFT` in `render.py`).
