# Page, picker and URL state

The parts of the site that are not maps: start-up, the image menu, the URL,
keyboard shortcuts, and the page markup and styles. Most of it is standard
DOM code, so this page is short.

## Start-up <Badge type="tip" text="standard" />

`main.js` first loads `env.json` and sets up the credentials dialog
([Where the website runs, and credentials](./time#where-the-website-runs-and-credentials)).
It then loads the catalog and shows a message with instructions if the
catalog is missing or empty. It reads the selected place from the URL
(`Place`, [Place search](./search)), creates the Viewer, the Grid, the
Animation and the ICESat-2 tool, restores the state from the URL, and shows
the right tab.

::: code-group
<<< @/../website/js/main.js#cog-opened [website/js/main.js#cog-opened]
:::

COG layers appear once their file's header has been read
([Opening COGs](./cog-layers#opening-cogs)). The first listener redraws the
Viewer, the Grid and the Animation when that happens; the second refreshes
every map when an API key is entered or cleared.

## State in the URL <Badge type="warning" text="decision" />

::: code-group
<<< @/../website/js/main.js#url-restore [website/js/main.js#url-restore]
<<< @/../website/js/main.js#url-save [website/js/main.js#url-save]
:::

Everything a user chooses is kept in the URL hash, so any state can be
bookmarked or shared:

| Key | Meaning |
|---|---|
| `tab=grid` | Grid or animation tab, or a location tool (`icesat2`), open |
| `loc` | The selected place, unless Greater New Haven: a starred place's id (`donnelly`), `none`, or `<name>\|<w,s,e,n>\|<lon,lat>` for a searched one ([Place search](./search)) |
| `a`, `b`, `mode` | Viewer image A, comparison image B, and mode (swipe, opacity, spy) |
| `cols`, `g` | Grid columns and the images in its slots, `\|`-separated, empty for empty slots |
| `anim`, `from`, `to` | Animation tab: image and date range |
| `beam` | ICESat-2 tool: `<line>@<pos>[@<basemap>]`, the sample line, the position along it in meters, and the basemap unless the default (`2@3500@ct-ortho-2023`) |

Images carry their time: `landsat/truecolor@2026-06-01..2026-08-31;px=median;cc=30`
(timestep, optional end of a window, options and filters that differ from
the defaults); without `@` an image follows the latest timestep with data in
view. See [Time, live data and credentials](./time#one-map-s-selection-slot).

The hash is updated with `history.replaceState`, so changing images does not
add browser-history entries. Unknown or unbuilt product ids are ignored. An
`@<view>` suffix from links made by an older version is ignored (only an
`@` followed by a date is a time); so is `labels=0` (the landmark labels
are gone since 0.6). The map position is *not* in the URL, but the selected
place is, and the maps open on it.

## Keyboard shortcuts <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/main.js#keyboard [website/js/main.js#keyboard]
:::

In the Viewer, `[` and `]` step through image A's group, and `,` and `.`
step image A to the previous / next timestep with data in view. In the
Viewer and the Grid, `0` goes back to the selected place (or Greater New
Haven). In the Animation tab, space plays / pauses and ← → step frames.

The shortcuts are single keys, so they act only while the open tab's panel
or one of its maps has focus, not page-wide (WCAG 2.1.4). They are ignored
while typing in a field, on a control with its own use for the key (a
button, link, slider or tab), and while the picker or a calendar is open.
On a map, the arrow keys pan it. The footer's **Keyboard shortcuts** button
opens a dialog that lists them (`index.html`, `#shortcuts-dialog`).

## The image picker <Badge type="tip" text="standard" />

`picker.js`: a button showing the current image (with its group path), and
a shared popup with a search box and a collapsible tree.

::: code-group
<<< @/../website/js/picker.js#picker-tree [website/js/picker.js#picker-tree]
:::

Search matches every word against the product's label, title, menu title,
groups and id. While searching, all groups are open, and groups without
matches are hidden. Collapsed groups are remembered across pickers. Arrow
keys move between items, Enter picks the first match, and Escape, a click
outside or tabbing out closes the popup. Catalog text is escaped before it
goes into `innerHTML`.

Products whose coverage (`coverage.bbox`) misses the map in view are dimmed,
with a ⌖ and "No data in view: covers …" as the tooltip; a group whose items
all miss it is dimmed too (Location-specific › Connecticut, away from
Connecticut). Unlike a locked product, a dimmed one can still be picked: the
map then says "Dataset unavailable here". The test, `coverageMiss` in
`slot.js`, is the one the maps use.

The menu starts with the street maps, then the datasets that work anywhere,
and ends with **Location-specific**: statewide Connecticut services (CT
orthoimagery, CT lidar) and every image pre-built for Greater New Haven,
labeled "pre-built, Greater New Haven" (`TREE` in
`scripts/website/build_catalog.py`).

## Markup and styles <Badge type="tip" text="standard" />

`index.html` holds the static layout: a skip link to the main content; the
header with the Bowerbird name, the tabs, the place search, the location
tools menu and the Credentials button; the panels of the Viewer, the Grid,
the Animation and the ICESat-2 tool; the footer (the Keyboard shortcuts
button and Yale's required links; `main.js` sets the copyright year); the
grid canvas; the picker popup; and the Keyboard shortcuts and Credentials
dialogs. It loads the Yale webfonts, the stylesheet, and one module script;
the modules import the vendored bundles themselves.

::: code-group
<<< @/../website/index.html#head-scripts [website/index.html#head-scripts]
<<< @/../website/index.html#map-frame-markup [website/index.html#map-frame-markup]
:::

Each map sits in a "map frame", a CSS grid with the latitude axis on the left
and the longitude axis below:

::: code-group
<<< @/../website/css/style.css#map-frame-css [website/css/style.css#map-frame-css]
:::

`style.css` follows the look of geospatial.yale.edu: the Yale blue two-tier
header, the YaleNew and Mallory typefaces, and outlined pill controls. Its
custom properties at the top (`--yale-blue`, `--a`/`--b` for the comparison
tags, `--nodata`) are the colors used everywhere. The `#grid-deck` rules
that make the grid canvas work are shown on
[Viewer, compare and grid](./viewer-and-grid#one-canvas-for-the-grid).
