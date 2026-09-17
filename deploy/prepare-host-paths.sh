#!/usr/bin/env bash
# Idempotent host-path preparation for the hub API's bind mounts.
#
# compose.yaml binds three paths under the attached volume onto the
# containers that need them:
#
#   /mnt/HC_Volume_106876357/spikeforge/artifacts  -> hub-api:/data/artifacts
#   /mnt/HC_Volume_106876357/spikeforge/tmp         -> hub-api:/data/tmp
#   /mnt/HC_Volume_106876357/spikeforge/postgres    -> hub-db:/var/lib/postgresql/data
#
# AGENTS.md rule 1 is that no artifact byte is ever written to the host's
# root disk (it has under a gigabyte free). If the attached volume is not
# mounted at $VOLUME_ROOT, creating these directories anyway would silently
# write artifacts and the Postgres data directory onto the root disk instead
# -- exactly the failure this script exists to refuse rather than paper
# over. So it hard-fails instead of mkdir -p'ing a guess.
#
# Safe to run on every deploy: mkdir/chown/chmod are all idempotent.
set -euo pipefail

VOLUME_ROOT="/mnt/HC_Volume_106876357"
BASE="$VOLUME_ROOT/spikeforge"

# hub-api's container user, fixed by this repo's own Dockerfile:
#   `useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin hub`
HUB_UID=10001
HUB_GID=10001

# The postgres:16-alpine image's built-in `postgres` user/group. This uid is
# fixed by the upstream image (both the debian and alpine variants create it
# at 999), not guessed here.
PG_UID=999
PG_GID=999

if [ ! -d "$VOLUME_ROOT" ]; then
  echo "ERROR: $VOLUME_ROOT does not exist on this host." >&2
  echo "Refusing to create bind-mount directories on the root disk --" >&2
  echo "the attached volume must be mounted at $VOLUME_ROOT before" >&2
  echo "deploying. This is an infra prerequisite, not something this" >&2
  echo "script can fix by guessing a path." >&2
  exit 1
fi

if command -v mountpoint >/dev/null 2>&1; then
  if ! mountpoint -q "$VOLUME_ROOT"; then
    echo "ERROR: $VOLUME_ROOT exists but is not a mounted filesystem." >&2
    echo "Refusing to proceed: writing under it would land on whatever" >&2
    echo "disk actually backs that path, which may be the root disk." >&2
    exit 1
  fi
else
  echo "WARNING: 'mountpoint' is not available; skipping the check that" >&2
  echo "$VOLUME_ROOT is actually a mounted filesystem and not a plain" >&2
  echo "directory on the root disk." >&2
fi

mkdir -p "$BASE/artifacts" "$BASE/tmp" "$BASE/postgres"

chown "$HUB_UID:$HUB_GID" "$BASE/artifacts" "$BASE/tmp"
chmod 750 "$BASE/artifacts" "$BASE/tmp"

# Postgres additionally insists on tight permissions on its data directory;
# anything more permissive than 0700 makes initdb refuse to start.
chown "$PG_UID:$PG_GID" "$BASE/postgres"
chmod 700 "$BASE/postgres"

echo "Host paths ready under $BASE:"
ls -ld "$BASE/artifacts" "$BASE/tmp" "$BASE/postgres"
