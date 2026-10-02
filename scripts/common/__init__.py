"""Shared helpers for the download / visualization scripts.

Scripts import this package by putting `scripts/` on `sys.path`:

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from common import config, render, remote, views

Any PEP 723 script that imports it must declare these dependencies:
    "numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests"
"""
