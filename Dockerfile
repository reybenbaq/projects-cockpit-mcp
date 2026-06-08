# syntax=docker/dockerfile:1.10

# ---- builder: install the package + deps into an isolated prefix ----
# python:3.12-slim pinned by digest for reproducible, supply-chain-safe builds.
# Tag documents intent; the digest enforces it.
# Resolved 2026-06-01; refresh via Dependabot (.github/dependabot.yml) or:
#   docker buildx imagetools inspect python:3.12-slim
FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203 AS builder

WORKDIR /build

# Locked dependency closure first: it changes rarely, so this layer caches
# independently of source edits. requirements.txt pins every transitive dep
# to an exact version for reproducible builds.
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# Then the package itself, with its dependencies already satisfied.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --prefix=/install --no-deps .

# ---- runtime: slim (not distroless) because project_status shells out to git ----
FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203 AS runtime

# git is the one runtime binary the cockpit needs (read-only: status, log).
# Deliberately not version-pinned. The digest-pinned base is the durable
# supply-chain control, and `apt-get update` pulls current security patches
# for git. An exact `git=<ver>` pin rots fast: Debian rotates the package
# out of the repo on each CVE, which breaks clean clones with
# "version not found".
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
