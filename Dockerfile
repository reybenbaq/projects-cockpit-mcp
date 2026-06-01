# syntax=docker/dockerfile:1.10

# ---- builder: install the package + deps into an isolated prefix ----
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --prefix=/install .

# ---- runtime: slim (not distroless) because project_status shells out to git ----
FROM python:3.12-slim AS runtime

# git is the one runtime binary the cockpit needs.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/* && \
    git config --system --add safe.directory '*'

RUN groupadd --system --gid 10001 app && \
    useradd  --system --uid 10001 --gid app --no-create-home --shell /sbin/nologin app

COPY --from=builder /install /usr/local

ENV HOST=0.0.0.0 \
    PORT=8848 \
    GIT_OPTIONAL_LOCKS=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER app:app
EXPOSE 8848

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8848/healthz', timeout=3)"]

ENTRYPOINT ["projects-cockpit"]
