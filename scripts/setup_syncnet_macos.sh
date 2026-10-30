#!/bin/sh
set -eu

SYNCNET_ROOT="${1:-$HOME/.lorasuite/models/syncnet_python}"
SYNCNET_COMMIT="907c0b579c2e2d83f0eae1b2ac9e720cde4e5623"
MODEL_URL="https://www.robots.ox.ac.uk/~vgg/software/lipsync/data/syncnet_v2.model"

command -v git >/dev/null || { echo "git is required" >&2; exit 2; }
command -v uv >/dev/null || { echo "uv is required" >&2; exit 2; }
command -v ffmpeg >/dev/null || { echo "ffmpeg is required" >&2; exit 2; }

if [ ! -d "$SYNCNET_ROOT/.git" ]; then
  mkdir -p "$(dirname "$SYNCNET_ROOT")"
  git clone https://github.com/joonson/syncnet_python.git "$SYNCNET_ROOT"
fi

git -C "$SYNCNET_ROOT" fetch --depth 1 origin "$SYNCNET_COMMIT"
git -C "$SYNCNET_ROOT" checkout --detach "$SYNCNET_COMMIT"

uv python install 3.10
uv venv --python 3.10 "$SYNCNET_ROOT/.venv"
uv pip install --python "$SYNCNET_ROOT/.venv/bin/python" \
  "numpy>=2,<3" \
  "scipy<2" \
  "torch==2.5.1" \
  "torchvision==0.20.1" \
  "opencv-contrib-python==4.13.0.92" \
  "python_speech_features==0.6"

mkdir -p "$SYNCNET_ROOT/data"
if [ ! -s "$SYNCNET_ROOT/data/syncnet_v2.model" ]; then
  curl -fL "$MODEL_URL" -o "$SYNCNET_ROOT/data/syncnet_v2.model"
fi

printf '\nSyncNet installed. Start LoraSuite with:\n'
printf '  export LORASUITE_SYNCNET_REPO=%s\n' "$(printf %s "$SYNCNET_ROOT" | sed "s/'/'\\''/g")"
