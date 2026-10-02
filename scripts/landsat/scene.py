"""The Landsat 8 scene shared by all Landsat scripts (data/landsat/scene.json,
written by select_scene.py)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import config

DATASET = "landsat"
SCENE_JSON = config.DATA / DATASET / "scene.json"


def load() -> dict:
    if not SCENE_JSON.exists():
        raise SystemExit(f"{SCENE_JSON} missing; run scripts/landsat/select_scene.py first")
    return json.loads(SCENE_JSON.read_text())

