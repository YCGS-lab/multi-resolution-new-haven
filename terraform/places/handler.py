"""Place search for the website: a thin proxy to Amazon Location Places (v2).

Behind an API Gateway HTTP API (main.tf), which allows the website's origin
(CORS) and caps the request rate; the Lambda's role may only call the three
operations below. Results are not cached (Places' default "SingleUse" intended
use does not allow storing them).

    GET /suggest?q=<text>[&near=<lon>,<lat>]
        Up to 5 places, points of interest or addresses for a partial query
        (Suggest, "Label" pricing: titles and ids only):
        {"results": [{"id", "title"}]}
    GET /place?id=<place id>
        A suggested place (GetPlace, "Core" pricing):
        {"title", "point": [lon, lat], "bbox": [w, s, e, n] | null}
    GET /geocode?q=<text>[&near=<lon>,<lat>]
        The best match of a full query (Geocode, "Core" pricing): as /place,
        or {"point": null} when nothing matches.
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

MAX_QUERY = 200
MAX_ID = 1000
MAX_SUGGESTIONS = 5
# Bias towards Greater New Haven when the website does not say where its map is.
DEFAULT_NEAR = [-72.92, 41.30]

_client = None


def client():
    global _client
    if _client is None:
        _client = boto3.client("geo-places", region_name=os.environ.get("AWS_REGION"))
    return _client


def response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body),
    }


def near(params: dict) -> list[float]:
    """The bias position: `near=<lon>,<lat>`, else Greater New Haven."""
    try:
        lon, lat = (float(v) for v in params.get("near", "").split(","))
    except ValueError:
        return DEFAULT_NEAR
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return DEFAULT_NEAR
    return [lon, lat]


def query(params: dict) -> str | None:
    q = (params.get("q") or "").strip()
    return q if 0 < len(q) <= MAX_QUERY else None


def place_out(item: dict) -> dict:
    """Title, point and box of a GetPlace / Geocode result."""
    return {"title": item.get("Title", ""), "point": item.get("Position"), "bbox": item.get("MapView")}


def suggest(params: dict) -> dict:
    q = query(params)
    if q is None:
        return response(400, {"error": f"q: 1 to {MAX_QUERY} characters"})
    res = client().suggest(QueryText=q, MaxResults=MAX_SUGGESTIONS, MaxQueryRefinements=0, BiasPosition=near(params), Language="en")
    results = [
        {"id": it["Place"]["PlaceId"], "title": it.get("Title", "")}
        for it in res.get("ResultItems", [])
        if it.get("SuggestResultItemType") == "Place" and it.get("Place", {}).get("PlaceId")
    ]
    return response(200, {"results": results})


def place(params: dict) -> dict:
    pid = params.get("id") or ""
    if not 0 < len(pid) <= MAX_ID:
        return response(400, {"error": "id: a place id from /suggest"})
    return response(200, place_out(client().get_place(PlaceId=pid, Language="en")))


def geocode(params: dict) -> dict:
    q = query(params)
    if q is None:
        return response(400, {"error": f"q: 1 to {MAX_QUERY} characters"})
    items = client().geocode(QueryText=q, MaxResults=1, BiasPosition=near(params), Language="en").get("ResultItems", [])
    return response(200, place_out(items[0]) if items else {"title": "", "point": None, "bbox": None})


ROUTES = {"/suggest": suggest, "/place": place, "/geocode": geocode}


def handler(event, context):
    """API Gateway HTTP API (payload format 2.0) event -> response."""
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")
    route = ROUTES.get(path)
    if route is None:
        return response(404, {"error": f"unknown path {path}; one of {', '.join(ROUTES)}"})
    if method != "GET":
        return response(405, {"error": "GET only"})
    try:
        return route(event.get("queryStringParameters") or {})
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        log.warning("places %s: %s", path, e)
        if code in ("ValidationException", "ResourceNotFoundException"):
            return response(400 if code == "ValidationException" else 404, {"error": code})
        if code == "ThrottlingException":
            return response(429, {"error": "too many requests"})
        return response(502, {"error": "place search failed"})
