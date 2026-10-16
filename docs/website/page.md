# Page, picker and URL state

The parts of the site that are not maps: start-up, the image menu, the URL,
keyboard shortcuts, and the page markup and styles. Most of it is standard
DOM code, so this page is short.

## Start-up <Badge type="tip" text="standard" />

`main.js` loads the catalog and shows a message with instructions if the
catalog is missing or empty. It then creates the Viewer and the Grid,
restores the state from the URL, and shows the right tab.

::: code-group
<<< @/../website/js/main.js#cog-opened [website/js/main.js#cog-opened]
:::

COG layers appear once their file's header has been read
([Opening COGs](./cog-layers#opening-cogs)). This listener redraws both maps
when that happens.

## State in the URL <Badge type="warning" text="decision" />

::: code-group
<<< @/../website/js/main.js#url-restore [website/js/main.js#url-restore]
<<< @/../website/js/main.js#url-save [website/js/main.js#url-save]
:::

Everything a user chooses is kept in the URL hash, so any state can be
bookmarked or shared:

| Key | Meaning |
|---|---|
| `tab=grid` | Grid, animation or ICESat-2 tab open |
| `a`, `b`, `mode` | Viewer image A, comparison image B, and mode (swipe, opacity, spy) |
| `cols`, `g` | Grid columns and the images in its slots, `\|`-separated, empty for empty slots |
| `anim`, `from`, `to` | Animation tab: image and date range |
| `beam` | ICESat-2 tab: sample line and position along it (`2@3500`) |
| `labels=0` | Landmarks and scale bar hidden |

Images carry their time: `landsat/truecolor@2026-06-01..2026-08-31;px=median;cc=30`
(timestep, optional end of a window, options and filters that differ from
the defaults); without `@` an image follows the latest timestep with data in
view. See [Time, live data and credentials](./time#one-map-s-selection-slot).

The hash is updated with `history.replaceState`, so changing images does not
add browser-history entries. Unknown or unbuilt product ids are ignored. An
`@<view>` suffix from links made by an older version is ignored (only an
`@` followed by a date is a time). The map position is *not* in the URL.

## Keyboard shortcuts <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/main.js#keyboard [website/js/main.js#keyboard]
:::

`L` toggles labels, `[` and `]` step through image A's group, `,` and `.`
step image A to the previous / next timestep with data in view, and `0`
resets the view; in the animation tab, space plays / pauses and ← → step
frames. Shortcuts are ignored while typing in a field or while the picker,
a calendar or the credentials dialog is open.

## The image picker <Badge type="tip" text="standard" />

`picker.js`: a button showing the current image (with its group path), and
a shared popup with a search box and a collapsible tree.

::: code-group
<<< @/../website/js/picker.js#picker-tree [website/js/picker.js#picker-tree]
:::

Search matches every word against the product's label, title, groups and
id. While searching, all groups are open, and groups without matches are
hidden. Collapsed groups are remembered across pickers. Arrow keys move
between items, Enter picks the first match, and Escape or a click outside
closes the popup. Catalog text is escaped before it goes into `innerHTML`.

## Markup and styles <Badge type="tip" text="standard" />

`index.html` holds the static layout: header, tabs, viewer controls, the
grid toolbar, the grid canvas and the picker popup. It loads the Yale
webfonts, the stylesheet, and one module script; the modules import the
vendored bundle themselves.

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
