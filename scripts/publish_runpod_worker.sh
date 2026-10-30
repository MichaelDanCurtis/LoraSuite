#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
REGISTRY_IMAGE=${1:-ghcr.io/michaeldancurtis/lorasuite-runpod-worker}

command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 2; }
command -v shasum >/dev/null 2>&1 || { echo "shasum is required" >&2; exit 2; }

DIGEST=$(
  cd "$ROOT"
  find workers/runpod -type f ! -path '*/__pycache__/*' -print0 \
    | sort -z \
    | xargs -0 shasum -a 256 \
    | shasum -a 256 \
    | cut -c1-16
)
TAG="worker-$DIGEST"
IMAGE="$REGISTRY_IMAGE:$TAG"

docker build --platform linux/amd64 -t "$IMAGE" "$ROOT/workers/runpod"
docker push "$IMAGE"

printf '%s\n' "$IMAGE"
