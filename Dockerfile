# Tombaugh API image. Build from the repository root:
#
#   docker build -t tombaugh-api .
#   docker run --rm -p 8080:8080 tombaugh-api
#
# The image mirrors the repository layout (/app/api/tombaugh next to /app/cache/fixtures), so
# repo-relative paths resolve the same way as on a developer machine.

FROM python:3.12-slim

# Same uv release that wrote api/uv.lock; keep it in step with .github/workflows/ci.yml.
ARG UV_VERSION=0.11.3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/api/.venv/bin:${PATH}" \
    TOMBAUGH_CACHE_DIR=/data/cache

# Unprivileged user with a fixed id, so files on a persistent volume keep their owner across image
# rebuilds. /data/cache exists in the image for runs without a volume.
RUN groupadd --gid 10001 tombaugh \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin tombaugh \
 && mkdir -p /data/cache \
 && chown -R 10001:10001 /data

RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore "uv==${UV_VERSION}"

WORKDIR /app/api

# Dependencies first: this layer is rebuilt only when the lockfile changes.
# --no-install-project matters. Measured on 14 Nov 2026: installing the project before its source
# is copied leaves an editable install with no path file, and `import tombaugh` then fails outside
# this directory.
COPY api/pyproject.toml api/uv.lock api/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# The package itself, installed now that its source exists, then byte-compiled because the runtime
# user cannot write __pycache__ next to the root-owned source.
COPY api/tombaugh ./tombaugh
RUN uv sync --frozen --no-dev \
 && python -m compileall -q tombaugh

# Recorded real fields, so fixture mode works with no network and no volume.
COPY cache/fixtures /app/cache/fixtures

# The API never runs as root. Fly.io mounts volumes owned by root, so a USER instruction alone would
# leave /data unwritable; the container therefore starts as root for one mkdir and chown, then drops
# to uid 10001 before the server starts. Started as any other user (docker run --user), the
# entrypoint runs the command unchanged.
COPY --chmod=0755 <<'EOF' /usr/local/bin/tombaugh-entrypoint
#!/bin/sh
set -eu
cache_dir="${TOMBAUGH_CACHE_DIR:-/data/cache}"
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$cache_dir"
    if [ "$(stat -c %u "$cache_dir")" != "10001" ]; then
        chown -R 10001:10001 "$cache_dir"
    fi
    export HOME=/home/tombaugh
    exec setpriv --reuid=10001 --regid=10001 --clear-groups --no-new-privs -- "$@"
fi
exec "$@"
EOF

EXPOSE 8080

ENTRYPOINT ["tombaugh-entrypoint"]
CMD ["uvicorn", "tombaugh.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
