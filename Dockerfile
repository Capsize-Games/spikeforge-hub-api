# The hub API deliberately has no torch dependency: it stores and indexes
# artifacts, it never loads one. That keeps this image in the tens of
# megabytes rather than the gigabytes the dashboard image needs, which on a
# host whose root disk sits at 98% is the difference between a deploy that
# works and one that fails at build time.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# capsize-auth is not on PyPI yet, so it is installed from source first and
# the project install below then finds it already satisfied. Override this to
# a local path to build against a working copy:
#   docker build --build-arg CAPSIZE_AUTH_SPEC=./vendor/capsize-auth .
ARG CAPSIZE_AUTH_SPEC="capsize-auth @ git+https://github.com/capsize-games/capsize-auth.git@main"

# Dependency metadata first, so a source-only change reuses the layer.
COPY pyproject.toml README.md LICENSE ./
COPY hub_api/__init__.py hub_api/__init__.py
COPY vendor* ./vendor/
RUN pip install --no-cache-dir "${CAPSIZE_AUTH_SPEC}" && \
    pip install --no-cache-dir .

COPY hub_api hub_api
COPY migrations migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir --no-deps .

# Runs as a non-root user; the volume's artifact and staging directories are
# owned by this uid on the host.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin hub
USER 10001

EXPOSE 8878

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=20s \
    CMD python -c "import urllib.request;\
urllib.request.urlopen('http://127.0.0.1:8878/health')"

CMD ["python", "-m", "hub_api"]
