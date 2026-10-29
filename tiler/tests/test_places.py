"""The website's place search (terraform/places/handler.py), with the Places client stubbed."""

import importlib.util
import json
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

HANDLER = Path(__file__).resolve().parents[2] / "terraform/places/handler.py"


class FakePlaces:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def _call(self, op, kw, out):
        self.calls.append((op, kw))
        if self.error:
            raise ClientError({"Error": {"Code": self.error, "Message": "x"}}, op)
        return out

    def suggest(self, **kw):
        return self._call(
            "suggest",
            kw,
            {
                "ResultItems": [
                    {"Title": "New Haven, CT, United States", "SuggestResultItemType": "Place", "Place": {"PlaceId": "p1"}},
                    {"Title": "new haven pizza", "SuggestResultItemType": "Query", "Query": {"QueryId": "q1"}},
                    {"Title": "Yale University", "SuggestResultItemType": "Place", "Place": {"PlaceId": "p2"}},
                ]
            },
        )

    def get_place(self, **kw):
        return self._call(
            "get_place", kw, {"Title": "New Haven, CT", "Position": [-72.93, 41.31], "MapView": [-72.99, 41.25, -72.86, 41.35]}
        )

    def geocode(self, **kw):
        items = [] if kw["QueryText"] == "nowhere" else [{"Title": "1 Main St", "Position": [-116.08, 44.73]}]
        return self._call("geocode", kw, {"ResultItems": items})


@pytest.fixture
def places():
    spec = importlib.util.spec_from_file_location("places_handler", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def call(mod, fake, path, params=None, method="GET"):
    mod._client = fake
    res = mod.handler({"rawPath": path, "queryStringParameters": params, "requestContext": {"http": {"method": method}}}, None)
    return res["statusCode"], json.loads(res["body"]), res["headers"]


def test_suggest_lists_places_only(places):
    fake = FakePlaces()
    status, body, headers = call(places, fake, "/suggest", {"q": " new haven ", "near": "-116.1,44.7"})
    assert status == 200
    assert body == {"results": [{"id": "p1", "title": "New Haven, CT, United States"}, {"id": "p2", "title": "Yale University"}]}
    assert headers["Cache-Control"] == "no-store"
    op, kw = fake.calls[0]
    assert op == "suggest" and kw["QueryText"] == "new haven" and kw["BiasPosition"] == [-116.1, 44.7]
    # Label pricing: no additional features asked for
    assert "AdditionalFeatures" not in kw and kw["MaxResults"] == 5


@pytest.mark.parametrize("near", [None, "x", "1,2,3", "200,10", "10,-95"])
def test_bad_near_biases_to_new_haven(places, near):
    fake = FakePlaces()
    call(places, fake, "/suggest", {"q": "elm", **({"near": near} if near else {})})
    assert fake.calls[0][1]["BiasPosition"] == places.DEFAULT_NEAR


def test_place_and_geocode_shape(places):
    status, body, _ = call(places, FakePlaces(), "/place", {"id": "p1"})
    assert status == 200 and body == {"title": "New Haven, CT", "point": [-72.93, 41.31], "bbox": [-72.99, 41.25, -72.86, 41.35]}
    status, body, _ = call(places, FakePlaces(), "/geocode", {"q": "1 main st donnelly"})
    assert status == 200 and body == {"title": "1 Main St", "point": [-116.08, 44.73], "bbox": None}
    status, body, _ = call(places, FakePlaces(), "/geocode", {"q": "nowhere"})
    assert status == 200 and body["point"] is None


@pytest.mark.parametrize(
    "path,params",
    [("/suggest", None), ("/suggest", {"q": "  "}), ("/suggest", {"q": "x" * 201}), ("/geocode", {}), ("/place", {}), ("/place", {"id": "x" * 1001})],
)
def test_bad_input_is_400_without_calling_places(places, path, params):
    fake = FakePlaces()
    status, _, _ = call(places, fake, path, params)
    assert status == 400 and not fake.calls


def test_unknown_path_and_method(places):
    assert call(places, FakePlaces(), "/autocomplete", {"q": "a"})[0] == 404
    assert call(places, FakePlaces(), "/suggest", {"q": "a"}, method="POST")[0] == 405


@pytest.mark.parametrize(
    "code,status", [("ValidationException", 400), ("ResourceNotFoundException", 404), ("ThrottlingException", 429), ("AccessDeniedException", 502)]
)
def test_places_errors(places, code, status):
    assert call(places, FakePlaces(error=code), "/place", {"id": "p1"})[0] == status
