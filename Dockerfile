# Official Django image is deprecated; use the official Python image + uv.
# Build: install deps with uv, collect static files.
# Runtime: copy the venv + app into a clean image, run as non-root under Gunicorn.
# Migrations are NOT run here; the Kubernetes migrate Job does that per deploy.

ARG PYTHON_IMAGE=python:3.12-slim
ARG UV_VERSION=0.12.2

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------- build ----------
FROM ${PYTHON_IMAGE} AS build

COPY --from=uv /uv /uvx /bin/

# Compile bytecode at build time (the runtime filesystem is read-only),
# copy instead of hardlink (needed with cache mounts), and use the image's Python.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies first so this layer is cached until pyproject.toml / uv.lock change.
# --locked fails the build if uv.lock is out of date with pyproject.toml.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Static files are baked into the image and served by WhiteNoise.
# The dummy key only exists for this command; settings must not need the DB at import.
RUN SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput

# ---------- runtime ----------
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Root-owned and read-only to the app user: code can't be modified at runtime.
COPY --from=build /app /app

USER 10001
EXPOSE 8000

# OCI labels. Kept at the end so a changing SHA/date doesn't invalidate earlier layers.
# CI passes GIT_SHA and BUILD_DATE as --build-arg (or use docker/metadata-action).
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="fitpro" \
      org.opencontainers.image.description="FitPro Django web app" \
      org.opencontainers.image.source="https://github.com/CS4300-CS5300-FA26/team-1" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}"

# Replace "fitpro.wsgi" with your Django project module.
# --worker-tmp-dir /dev/shm: Gunicorn heartbeat files stay in memory (read-only root fs).
CMD ["gunicorn", "fitpro.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "60", \
     "--worker-tmp-dir", "/dev/shm", \
     "--access-logfile", "-"]
