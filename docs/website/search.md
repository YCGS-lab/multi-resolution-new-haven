# Place search and location tools

The header has a search box that takes the maps anywhere and a **Location
tools** menu. Both work from one shared state, the *selected place*
(`website/js/location.js`): the place the maps open on and go back to (⤢ and
`0`), and the place the location-specific tools are matched against.

## The selected place <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/location.js#place-state [website/js/location.js#place-state]
<<< @/../website/js/location.js#starred [starred places]
:::

A place is `{name, bbox?, point?, id?}`. **Starred** places are offered before
anything is typed: Greater New Haven (the catalog's extent, and the default)
and Donnelly, Idaho, an example with no tools yet. A **searched** place
comes from the Places API with a point (a marker on the maps) and usually a
box. × clears the place; the maps then go back to the catalog's extent.

Selecting a place fits the viewer, the grid and the animation map to it
(`placeViewState` in `mapview.js`), closes a tool not made for it, and puts
it in the URL (`loc`, except for the default).

## The search box <Badge type="warning" text="decision" />

::: code-group
<<< @/../website/js/location.js#search-box [website/js/location.js#search-box]
<<< @/../website/js/location.js#places-api [Places API client]
:::

Typing lists the matching starred places, then up to five suggestions from
the Places API, biased towards the center of the map in view. Picking a
suggestion asks for its position and box (`/place`); Enter with nothing
picked takes the first item, or geocodes the text (`/geocode`). Arrow keys,
Enter and Escape work as in the image picker.

::: warning Design decision: light on a per-request API
Every Places request is billed, so the box asks only when it is worth it:
three characters at least, 300 ms after the last keystroke, at most one
request every 500 ms and one in flight (a newer one aborts it), and each
answer is kept for the page session. A word typed at normal speed costs two
or three suggestion requests. Answers that arrive after a newer search
started are dropped.
:::

Without `services.places` in `env.json` (e.g. a local `just serve`), the box
offers only the starred places. To try the search locally against a
deployment, add `?service.places=<its places_url>` to the page URL (its CORS
allows `extra_cors_origins`, e.g. `http://localhost:8000`).

## The Places API <Badge type="warning" text="decision" />

::: code-group
<<< @/../terraform/places/handler.py [terraform/places/handler.py]
<<< @/../terraform/places/main.tf#http-api [HTTP API]
<<< @/../terraform/places/main.tf#iam [IAM]
:::

`terraform/places` (called by `terraform/complete`, which puts its URL in
`env.json` as `services.places`) is a small Python Lambda behind an API
Gateway HTTP API in the default provider's region, set up like one of the
tiler's regional deployments but much smaller (a zip, boto3 only). It calls
[Amazon Location Places (v2)](https://docs.aws.amazon.com/location/latest/developerguide/places.html):

| Route | Places operation | Price bucket | Price (us-east-1) |
|---|---|---|---|
| `/suggest?q=&near=` | `Suggest` (places only; no query refinements) | Label | $0.20 per 1,000 |
| `/place?id=` | `GetPlace` | Core | $0.50 per 1,000 |
| `/geocode?q=&near=` | `Geocode` (best match) | Core | $0.50 per 1,000 |

The role may call these three operations and nothing else; no key reaches
the browser. API Gateway allows only the website's origin (and
`extra_cors_origins`) and throttles the stage (`places_throttling_rate_limit`,
5 requests/s, burst 10, for all users together); the Lambda's reserved
concurrency is 5. Responses say `Cache-Control: no-store`: Places results
requested for single use may not be stored, and suggestions cannot be
requested any other way.

::: info Why Amazon Location, and why a proxy
Alternatives considered: Nominatim (OpenStreetMap) forbids autocomplete on
its public servers; Photon is free and suits autocomplete but is a
best-effort public service with weaker US address data; Mapbox, MapTiler or
Geoapify would mean another account and key. Amazon Location bills to the
account that already runs the site, with US address and place data from its
providers. Calling it from the browser with an Amazon Location API key would
need no Lambda, but the key would be public (its referrer restriction can be
spoofed) and nothing would limit the request rate; the proxy keeps the
credentials server-side and puts the rate limit and the cost guard in front.
:::

### Cost <Badge type="warning" text="decision" />

A search is typically two to four suggestion requests and one `/place`:
about $0.001-0.0013. A thousand searches a month cost about $1.30; Lambda and
API Gateway add cents. New accounts get 10,000 Label and 20,000 Core requests
a month free for three months.

The worst case is the throttle ceiling, someone calling the API in a loop:
5 requests/s of Core requests is $9/h. The [cost guard](/tiler/guard) caps
that. `terraform/complete` hands the place search to the tiler module's guard
(`guard_extra_apis`, `guard_extra_functions`). An alarm on the API's request
count emails at 500/h (~$0.25/h at most). Above 2,000/h for 15 minutes
(~$1/h) it runs the kill switch, which sets the place search's reserved
concurrency to 0 along with the tiler's. The monthly budget backstop counts
Amazon Location Service too. `tofu apply` restores everything.

## Location tools <Badge type="tip" text="standard" />

::: code-group
<<< @/../website/js/location.js#tools [website/js/location.js#tools]
<<< @/../website/js/location.js#tools-menu [tools menu]
:::

A location tool is a tab panel made for one starred place. The ICESat-2
photon profiles are the only one so far, for Greater New Haven
([ICESat-2 profiles](./time#icesat-2-profiles-a-location-tool)). The menu
first lists the selected place's tools: those whose starred place contains
the selected place's center, so a searched address in New Haven counts. It
then lists the other places' tools; picking one of those selects its place
first. The tool's panel replaces the tabs' (no tab is underlined, and the
**Location tools** button is outlined), and `tab=icesat2` in the URL still
opens it.
