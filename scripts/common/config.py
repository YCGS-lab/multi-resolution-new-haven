"""Repository paths and credentials."""

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
FIGURES = REPO / "figures"
CREDENTIALS = REPO / "_credentials.toml"


def data_dir(dataset: str) -> Path:
    """`data/<dataset>/`, created if needed."""
    d = DATA / dataset
    d.mkdir(parents=True, exist_ok=True)
    return d


def figure_dir(dataset: str) -> Path:
    """`figures/<dataset>/`, created if needed."""
    d = FIGURES / dataset
    d.mkdir(parents=True, exist_ok=True)
    return d


def figure_paths(dataset: str, view_name: str, product: str) -> tuple[Path, Path]:
    """Paths for the data-only and labeled versions of one figure."""
    d = figure_dir(dataset)
    return d / f"{view_name}_{product}.png", d / f"{view_name}_{product}_labeled.png"


def credentials() -> dict:
    """Contents of `_credentials.toml` (planet_api_key, cds_api_key, aws_*)."""
    with open(CREDENTIALS, "rb") as f:
        return tomllib.load(f)
