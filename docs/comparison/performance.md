# Performance

Measured with the [benchmark](/build/benchmark): headless Chromium 141, both
versions served side by side from the same data, medians of 3 runs, without
and with 40 ms of added latency per request. The full tables, with every
run, are in [benchmarks/2026-10-10](/benchmarks/2026-10-10). The
[migration report](/deck-gl-raster#performance) has the original discussion.

::: danger No GPU
The test machine had no GPU. WebGL ran in software (SwiftShader), which
makes per-pixel work, now the new version's main job, far more expensive
than on real hardware. **Frame times below are an upper bound. Re-measure
on hardware before concluding anything about frame rates.**
:::

| Scenario | Before | After | After / before |
|---|---:|---:|---:|
| JavaScript + wasm loaded (gzipped) | 0.68 MB | 0.47 MB | 0.69× |
| Load, Landsat true color: time to finished map | 3.42 s | 2.25 s | 0.66× |
| Load, impervious classes (0.5 m) | 3.39 s | 2.21 s | 0.65× |
| Load, JPEG imagery (4.8 m) | 4.90 s | 4.44 s | 0.91× |
| Load, shaded DEM | 2.98 s | 2.16 s | 0.73× |
| Load, sparse tracks over a basemap | 4.75 s | 3.22 s | 0.68× |
| Zoom ×4, impervious classes | 2.14 s | 1.63 s | 0.76× |
| Zoom ×4, impervious classes, +40 ms latency | 2.44 s | 4.29 s | **1.76×** |
| Zoom ×4, JPEG imagery | 4.49 s | 2.71 s | 0.60× |
| Zoom ×4, sparse tracks | 4.55 s | 0.17 s | 0.04× |
| Switch through 5 Landsat products | 1.94 s | 1.30 s | 0.67× |
| … main-thread blocking | 975 ms | 210 ms | 0.22× |
| … COG bytes downloaded | 0 | 8.2 MB | |
| Grid of four | 5.49 s | 4.83 s | 0.88× |
| Pan, single-layer products: frame p50 (software GL) | 67–83 ms | 133–150 ms | ~2× |
| Pan, sparse tracks: frame p50 (software GL) | 83 ms | 517 ms | 6.2× |

## Reading the results

- **Faster to a finished map** in most scenarios. Decoding moved to workers
  and coloring to the GPU, so the main thread no longer colors every tile
  pixel. The biggest win is zooming the sparse tracks (25×), which the old
  version re-dilated on the CPU for every tile.
- **Less JavaScript**: one bundle instead of deck.gl's 2.1 MB browser build
  plus geotiff.js and its decoders.
- **More requests**, the main regression. deck.gl-raster makes one range
  request per 512 × 512 COG tile, where geotiff.js fetched and cached large
  blocks. Locally this costs nothing; with latency and 6 requests at a time
  it made a high-resolution zoom 1.76× slower. The site now allows 24
  concurrent requests over HTTP/2 (CloudFront), which was not measured.
  deck.gl-raster's unreleased code batches and coalesces range requests,
  which should help once `COGLayer` uses it.
- **Re-downloading on product switches.** Each product is a new layer with
  its own tile cache. On the deployed site, `max-age=300` lets the browser
  cache serve the repeats.
- **Software-rendered frames are slower.** Replacing the generated shader with
  a trivial one did not change the frame time, and deck.gl's CPU time per
  frame stayed at 3–4 ms. So the cost is rasterizing deck.gl-raster's mesh
  layer, a `SimpleMeshLayer` derivative with lighting, in software. The
  `dilate_px` search costs most under SwiftShader, which appears to run the
  whole neighbor loop for every pixel even where the occupancy texture says
  there is no data nearby.

## Correctness, not measured in time

- Native pixel edges now land exactly on the geotransform: within 0.5 px of
  the expected position at deep zoom, against up to ~17 px off before.
- Sparse points are no longer dropped between tiles.
