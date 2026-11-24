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
# lazily: much faster cold starts without SnapStart). Bytecode only, boto3 from
# the runtime, dependencies as deps.tar.zst unpacked to /tmp at init
# (ycgs_titiler.lambda_entry; a zip may hold 250 MB unpacked). Byte-identical
# across builds. `--target zip --output type=local,dest=DIR` -> DIR/tiler.zip.
FROM builder AS zipbuild
COPY package/slim.py /build/slim.py
COPY src/ycgs_titiler /asset/ycgs_titiler
RUN mkdir -p /asset/lib && cp /usr/lib64/libexpat.so.1 /asset/lib/ \
 && python /build/slim.py /asset /tiler.zip --tarball

FROM scratch AS zip
COPY --from=zipbuild /tiler.zip /
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
