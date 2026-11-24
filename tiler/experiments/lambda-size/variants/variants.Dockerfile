# syntax=docker/dockerfile:1
# Size experiments for the tiler's zip package (see ../REPORT.md). Context: tiler/.
#   docker buildx build -f experiments/lambda-size/variants/variants.Dockerfile --target v1 \
#     --output type=local,dest=OUT .        -> OUT/tiler.zip
# Variants, smallest change first; each builds on the one before. The chosen build (V1 plus
# V3's numpy) is tiler/Dockerfile's `zip` target.

ARG PYTHON_VERSION=3.14
# What the request set never loads (bench/trace.py, bench/unused.py): extension modules for other
# Python versions, numpy's test modules, Pillow's AVIF/FreeType/LCMS/WebP/Tk plugins and the
# libraries only they link, rasterio's example module, dask.dataframe, f2py, zarr.testing,
# and cramjam (starlette-cramjam's compression middleware is never added).
ARG TRIM_PATHS="color_operations/*.cpython-31[0-3]-*.so numpy/_core/_*_tests.*.so numpy/_core/_simd.*.so \
numpy/f2py dask/dataframe zarr/testing rasterio/_example.*.so \
PIL/_avif.*.so PIL/_imagingcms.*.so PIL/_imagingft.*.so PIL/_imagingtk.*.so PIL/_webp.*.so \
pillow.libs/libavif* pillow.libs/libfreetype* pillow.libs/libharfbuzz* pillow.libs/liblcms2* \
pillow.libs/libbrotli* pillow.libs/libwebp* pillow.libs/libsharpyuv* pillow.libs/libpng16*"
ARG TRIM_PKGS="cramjam starlette-cramjam"

# region builder
# Same as tiler/Dockerfile's builder (locked dependencies from wheels), plus binutils (strip).
FROM public.ecr.aws/lambda/python:${PYTHON_VERSION} AS builder
RUN dnf install -y git findutils expat binutils patchelf && dnf clean all
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes --output-file requirements.txt \
 && uv pip install --no-cache --compile-bytecode --target /asset -r requirements.txt
RUN find /asset -type d \( -name tests -o -name test \) -prune -exec rm -rf {} + \
 && find /asset -name '*.pyi' -delete
# endregion builder

# region p0
# P0, the baseline: PR #6's package. The wheels as they are, dependencies in deps.tar.zst,
# unpacked to /tmp at init (ycgs_titiler.lambda_entry).
FROM builder AS p0build
COPY package/slim.py /build/slim.py
COPY src/ycgs_titiler /app/ycgs_titiler
RUN cp -r /app/ycgs_titiler /asset/ && mkdir -p /asset/lib && cp /usr/lib64/libexpat.so.1 /asset/lib/ \
 && python /build/slim.py /asset /tiler.zip --tarball
FROM scratch AS p0
COPY --from=p0build /tiler.zip /
# endregion p0

# region v1
# V1: the same wheels, trimmed: stripped shared objects, one copy of the PROJ data, and the
# files the request set never loads (TRIM_PATHS, TRIM_PKGS).
FROM builder AS v1build
ARG TRIM_PATHS
ARG TRIM_PKGS
COPY package/slim.py /build/slim.py
COPY src/ycgs_titiler /app/ycgs_titiler
RUN set -f && cp -r /app/ycgs_titiler /asset/ && mkdir -p /asset/lib && cp /usr/lib64/libexpat.so.1 /asset/lib/ \
 && python /build/slim.py /asset /tiler.zip --strip --share-proj-data --max-mb 1000 \
      --drop $TRIM_PKGS --drop-paths $TRIM_PATHS
FROM scratch AS v1
COPY --from=v1build /tiler.zip /
# endregion v1

# region v2
# V2: V1 plus one copy of each library that several wheels bundle in the same version (PROJ in
# rasterio and pyproj, GEOS in rasterio and shapely, ...), re-linked with patchelf (dedupe.py).
# Stripped before patching (strip after patchelf can damage the patched files).
FROM builder AS v2build
ARG TRIM_PATHS
ARG TRIM_PKGS
COPY experiments/lambda-size/variants/dedupe.py /build/dedupe.py
COPY package/slim.py /build/slim.py
COPY src/ycgs_titiler /app/ycgs_titiler
RUN set -f && cp -r /app/ycgs_titiler /asset/ && mkdir -p /asset/lib && cp /usr/lib64/libexpat.so.1 /asset/lib/ \
 && python /build/slim.py /asset --strip-only \
 && python /build/dedupe.py /asset \
 && python /build/slim.py /asset /tiler.zip --share-proj-data --max-mb 1000 \
      --drop $TRIM_PKGS --drop-paths $TRIM_PATHS
FROM scratch AS v2
COPY --from=v2build /tiler.zip /
# endregion v2

# region v3
# V3: V2 with numpy built from source without BLAS/LAPACK (the wheel bundles OpenBLAS and
# gfortran, ~26 MB; the tiler does no linear algebra).
FROM builder AS numpy-noblas
RUN dnf install -y gcc gcc-c++ && dnf clean all
ARG NUMPY_VERSION=2.5.3
RUN rm -rf /asset/numpy /asset/numpy.libs /asset/numpy-*.dist-info \
 && uv pip install --no-cache --target /asset --no-deps --no-binary numpy "numpy==${NUMPY_VERSION}" \
      -C setup-args=-Dallow-noblas=true -C setup-args=-Dblas=none -C setup-args=-Dlapack=none \
 && python -c "import sys; sys.path.insert(0, '/asset'); import numpy; numpy.show_config()" | grep -iA3 '"blas"\|blas:'

FROM numpy-noblas AS v3build
ARG TRIM_PATHS
ARG TRIM_PKGS
COPY experiments/lambda-size/variants/dedupe.py /build/dedupe.py
COPY package/slim.py /build/slim.py
COPY src/ycgs_titiler /app/ycgs_titiler
RUN set -f && cp -r /app/ycgs_titiler /asset/ && mkdir -p /asset/lib && cp /usr/lib64/libexpat.so.1 /asset/lib/ \
 && python /build/slim.py /asset --strip-only \
 && python /build/dedupe.py /asset \
 && python /build/slim.py /asset /tiler.zip --share-proj-data --max-mb 1000 \
      --drop $TRIM_PKGS --drop-paths $TRIM_PATHS
FROM scratch AS v3
COPY --from=v3build /tiler.zip /
# endregion v3

# region v4
# V4: V3 with PROJ and GDAL built from source, once, with only what the tiler uses, and rasterio
# and pyproj built against them. GDAL: GTiff/COG, MEM, VRT, PNG, JPEG, WEBP; curl for /vsicurl and
# /vsis3; no GEOS, HDF5, netCDF or other drivers. Same versions as the wheels' bundled copies.
FROM numpy-noblas AS natives
RUN dnf install -y gcc gcc-c++ make cmake ninja-build tar gzip xz sqlite-devel libcurl-devel zlib-devel \
      libzstd-devel libwebp-devel && dnf clean all
ARG PROJ_VERSION=9.8.1
ARG GDAL_VERSION=3.12.2
WORKDIR /src
RUN curl -fsSL https://download.osgeo.org/proj/proj-${PROJ_VERSION}.tar.gz | tar xz \
 && cmake -G Ninja -S proj-${PROJ_VERSION} -B proj-build -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/opt/geo -DCMAKE_INSTALL_LIBDIR=lib -DBUILD_TESTING=OFF -DBUILD_APPS=OFF \
      -DENABLE_TIFF=OFF -DENABLE_CURL=OFF -DBUILD_SHARED_LIBS=ON \
 && cmake --build proj-build && cmake --install proj-build && rm -rf proj-build proj-${PROJ_VERSION}
RUN curl -fsSL https://download.osgeo.org/gdal/${GDAL_VERSION}/gdal-${GDAL_VERSION}.tar.xz | tar xJ \
 && cmake -G Ninja -S gdal-${GDAL_VERSION} -B gdal-build -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/opt/geo -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_PREFIX_PATH=/opt/geo \
      -DBUILD_APPS=OFF -DBUILD_TESTING=OFF -DBUILD_PYTHON_BINDINGS=OFF -DBUILD_JAVA_BINDINGS=OFF \
      -DBUILD_CSHARP_BINDINGS=OFF \
      -DGDAL_BUILD_OPTIONAL_DRIVERS=OFF -DOGR_BUILD_OPTIONAL_DRIVERS=OFF \
      -DGDAL_ENABLE_DRIVER_PNG=ON -DGDAL_ENABLE_DRIVER_JPEG=ON -DGDAL_ENABLE_DRIVER_WEBP=ON \
      -DGDAL_USE_EXTERNAL_LIBS=OFF -DGDAL_USE_CURL=ON -DGDAL_USE_ZLIB=ON -DGDAL_USE_ZSTD=ON \
      -DGDAL_USE_WEBP=ON \
 && cmake --build gdal-build && cmake --install gdal-build && rm -rf gdal-build gdal-${GDAL_VERSION}
ARG RASTERIO_VERSION=1.5.2
ARG PYPROJ_VERSION=3.8.0
RUN rm -rf /asset/rasterio /asset/rasterio.libs /asset/rasterio-*.dist-info \
           /asset/pyproj /asset/pyproj.libs /asset/pyproj-*.dist-info \
 && GDAL_CONFIG=/opt/geo/bin/gdal-config PROJ_DIR=/opt/geo PROJ_VERSION=${PROJ_VERSION} \
    uv pip install --no-cache --target /asset --no-deps --no-binary rasterio,pyproj \
      "rasterio==${RASTERIO_VERSION}" "pyproj==${PYPROJ_VERSION}" \
 && mkdir -p /asset/lib /asset/pyproj/proj_dir/share \
 && cp -a /opt/geo/lib/libgdal.so.* /opt/geo/lib/libproj.so.* /asset/lib/ \
 && cp -a /usr/lib64/libwebp.so.7* /asset/lib/ \
 && cp -r /opt/geo/share/proj /asset/pyproj/proj_dir/share/proj \
 && cp -r /opt/geo/share/gdal /asset/rasterio/gdal_data \
 && find /asset/lib /asset/rasterio /asset/pyproj -name '*.so*' -type f -exec strip --strip-unneeded {} + \
 && for f in $(find /asset/rasterio /asset/pyproj -name '*.so'); do \
      patchelf --set-rpath "\$ORIGIN/$(python -c "import os,sys; print(os.path.relpath('/asset/lib', os.path.dirname(sys.argv[1])))" $f)" $f; done \
 && for f in /asset/lib/lib*.so.*; do [ -L "$f" ] || patchelf --set-rpath '$ORIGIN' "$f"; done

FROM natives AS v4build
ARG TRIM_PATHS
ARG TRIM_PKGS
COPY experiments/lambda-size/variants/dedupe.py /build/dedupe.py
COPY package/slim.py /build/slim.py
COPY src/ycgs_titiler /app/ycgs_titiler
RUN set -f && cp -r /app/ycgs_titiler /asset/ && cp /usr/lib64/libexpat.so.1 /asset/lib/ \
 && python /build/slim.py /asset --strip-only \
 && python /build/dedupe.py /asset \
 && python /build/slim.py /asset /tiler.zip --max-mb 1000 \
      --drop $TRIM_PKGS --drop-paths $TRIM_PATHS
FROM scratch AS v4
COPY --from=v4build /tiler.zip /
# endregion v4
