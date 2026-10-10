# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "rasterio", "pyproj", "matplotlib", "pillow", "requests", "boto3"]
# ///
"""Landsat 8 OLI panchromatic band (B8, 15 m) from Collection 2 Level-1, for
the same scene as the Level-2 products (data/landsat/scene.json).

Level-1 data are only on the AWS requester-pays bucket s3://usgs-landsat, so
this does a windowed read of just the padded view intersect from the COG
(a few hundred KB of transfer) and saves it as data/landsat/<L1 id>_B8_newhaven.tif.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rasterio
from rasterio.session import AWSSession
from rasterio.windows import from_bounds as window_from_bounds

import scene as scene_mod
from common import config, views

PAD_M = 60.0  # 4 pan pixels


def pan_path(sc: dict) -> Path:
    return config.data_dir(scene_mod.DATASET) / f"{sc['l1_product_id']}_B8_newhaven.tif"


def main():
    sc = scene_mod.load()
    # region requester-pays-window
    creds = config.credentials()
    aws = AWSSession(
        aws_access_key_id=creds["aws_access_key_id"],
        aws_secret_access_key=creds["aws_secret_access_key"],
        region_name="us-west-2",
        requester_pays=True,
    )
    out = pan_path(sc)
    with rasterio.Env(aws, AWS_REQUEST_PAYER="requester", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(sc["l1_pan_s3"]) as ds:
            bounds = views.all_bounds_in(ds.crs, PAD_M)
            win = window_from_bounds(*bounds, ds.transform).round_offsets().round_lengths()  # pad >> 0.5 px rounding
            pan = ds.read(1, window=win)
            profile = ds.profile | {
                "driver": "GTiff",
                "width": win.width,
                "height": win.height,
                "transform": ds.window_transform(win),
                "compress": "deflate",
                "predictor": 2,
                "tiled": True,
                "blockxsize": 256,
                "blockysize": 256,
            }
            profile.pop("photometric", None)
    # endregion requester-pays-window
    print(f"read {win.width}x{win.height} px window of {sc['l1_pan_s3'].rsplit('/', 1)[-1]}")
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(pan, 1)
        dst.update_tags(
            L1_PRODUCT_ID=sc["l1_product_id"],
            DATETIME=sc["datetime"],
            BAND="B8 panchromatic, Level-1 DN (quantized calibrated)",
            SOURCE=sc["l1_pan_s3"],
        )
    print(f"wrote {out.relative_to(config.REPO)} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
