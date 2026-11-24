# syntax=docker/dockerfile:1
# Lambda container image (arm64, Python 3.14 managed base image), and the same
# app as a zip package for the managed runtime (the default deployment):
#   docker buildx build --platform linux/arm64 -t ycgs-titiler .
#   docker buildx build --platform linux/arm64 --target zip --output type=local,dest=DIR .

ARG PYTHON_VERSION=3.14

# region builder
# ---------------------------------------------------------------------------
# Builder: resolve the locked dependencies (titiler-cmr is a git dependency).
FROM public.ecr.aws/lambda/python:${PYTHON_VERSION} AS builder
RUN dnf install -y git findutils expat && dnf clean all
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes --output-file requirements.txt \
 && uv pip install --no-cache --compile-bytecode --target /asset -r requirements.txt
# Trim what Lambda never needs (tests, type stubs); keep .pyc for faster init.
RUN find /asset -type d \( -name tests -o -name test \) -prune -exec rm -rf {} + \
 && find /asset -name '*.pyi' -delete
# endregion builder

# region zip
# ---------------------------------------------------------------------------
# Zip package for Lambda's managed Python runtime (no container image to load
# lazily: predictable cold starts without SnapStart), unpacked as it is: under
# Lambda's 250 MB limit (package/slim.py fails the build otherwise).
#   `--target zip --output type=local,dest=DIR` -> DIR/tiler.zip
# - numpy built without BLAS/LAPACK: the wheel bundles OpenBLAS (~25 MB), and the
#   tiler does no linear algebra;
# - bytecode only, boto3 from the runtime, shared objects stripped, one copy of
#   the PROJ data, and what the tiler never loads left out (package/trim.txt);
# - byte-identical across builds.
# Measurements: tiler/experiments/lambda-size/REPORT.md.
FROM builder AS zipbuild
RUN dnf install -y gcc gcc-c++ binutils && dnf clean all
RUN rm -rf /asset/numpy /asset/numpy.libs /asset/numpy-*.dist-info \
 && uv pip install --no-cache --target /asset --no-deps --no-binary numpy \
      "$(grep '^numpy==' /build/requirements.txt)" \
      -C setup-args=-Dallow-noblas=true -C setup-args=-Dblas=none -C setup-args=-Dlapack=none
COPY package/slim.py package/trim.txt /build/
COPY src/ycgs_titiler /asset/ycgs_titiler
RUN mkdir -p /asset/lib && cp /usr/lib64/libexpat.so.1 /asset/lib/ \
 && python /build/slim.py /asset /tiler.zip --strip --share-proj-data --trim /build/trim.txt

# The zip in a clean runtime: every shared object loads, and the handler imports.
FROM public.ecr.aws/lambda/python:${PYTHON_VERSION} AS zipcheck
COPY --from=zipbuild /tiler.zip /tmp/tiler.zip
RUN cd ${LAMBDA_TASK_ROOT} && python -m zipfile -e /tmp/tiler.zip . \
 && LD_LIBRARY_PATH=${LAMBDA_TASK_ROOT}/lib python -c "import ctypes, glob; \
[ctypes.CDLL(p) for p in glob.glob('${LAMBDA_TASK_ROOT}/**/*.so*', recursive=True)]" \
 && python -c "from ycgs_titiler.lambda_entry import handler, prune; print('zip import OK')"

FROM scratch AS zip
COPY --from=zipcheck /tmp/tiler.zip /
# endregion zip

# region final
# ---------------------------------------------------------------------------
FROM public.ecr.aws/lambda/python:${PYTHON_VERSION}
COPY --from=builder /asset ${LAMBDA_TASK_ROOT}
# rasterio's wheel links against the system libexpat, which the base image lacks
COPY --from=builder /usr/lib64/libexpat.so.1 /usr/lib64/
COPY src/ycgs_titiler ${LAMBDA_TASK_ROOT}/ycgs_titiler
RUN python -m compileall -q ${LAMBDA_TASK_ROOT}/ycgs_titiler \
 && python -c "from ycgs_titiler.handler import handler; print('import OK')"
CMD ["ycgs_titiler.handler.handler"]
# endregion final
