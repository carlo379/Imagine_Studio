#!/bin/sh
set -eu
cd "$(dirname "$0")"
if ! command -v node >/dev/null 2>&1 || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'; then
  echo 'Setup requires Node.js 22 or newer on PATH for Camera Control and frontend builds.' >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo 'Setup requires npm on PATH. Install it with Node.js 22 or newer.' >&2
  exit 1
fi
case "${1:-}" in
  ""|--mock-only) ;;
  *) echo 'Usage: sh setup.sh [--mock-only]' >&2; exit 2 ;;
esac
for tool in python3 git ffmpeg ffprobe; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Setup requires $tool on PATH." >&2; exit 1; }
done
python3 ffmpeg_runtime.py
if [ "${1:-}" != --mock-only ]; then
revision=357f51c49106f47136caf9b01015467b7b633fe8
if [ ! -d .deps/hermes/.git ]; then
  mkdir -p .deps/hermes
  git -C .deps/hermes init -q
  git -C .deps/hermes fetch --depth 1 https://github.com/NousResearch/hermes-agent.git "$revision"
fi
git -C .deps/hermes checkout --detach "$revision"
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci --ignore-scripts --no-audit --no-fund
npm run build
# Public source snapshots omit the historical binary fixture. Create a local
# mathematical test pattern instead; no provider, camera or production media.
if [ ! -f static/mock-video.mp4 ]; then
  ffmpeg -v error -y -f lavfi -i 'testsrc2=size=960x540:rate=24:duration=3' -an -c:v libx264 -pix_fmt yuv420p -threads 2 static/mock-video.mp4
fi
echo 'Ready: .venv/bin/python studio_server.py (mock mode; add --live for subscription access)'
