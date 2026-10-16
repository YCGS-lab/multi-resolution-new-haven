# syntax=docker/dockerfile:1
# Lambda container image (arm64, Python 3.14 managed base image; SnapStart-capable).
# Build:  docker buildx build --platform linux/arm64 -t ycgs-titiler .

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
