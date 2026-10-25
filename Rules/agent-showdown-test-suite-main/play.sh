#!/usr/bin/env bash
# Usage:
#   ./play.sh [options] <bot1> [bot2 [bot3 [bot4]]]
# Examples:
#   ./play.sh starter_bot random_walk
#   ./play.sh starter_bot wall_hug
#   ./play.sh -t 150 starter_bot starter_bot_cpp
set -euo pipefail

IMAGE="${IMAGE:-codewars-kit}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$SCRIPT_DIR/out" "$SCRIPT_DIR/my_bots"

if command -v docker &>/dev/null; then
    if ! docker image inspect "$IMAGE" &>/dev/null; then
        echo "[testkit] Docker image '$IMAGE' not found. Building (one-time setup)..."
        docker build -t "$IMAGE" "$SCRIPT_DIR"
    fi
    exec docker run --rm -it \
        -v "$SCRIPT_DIR/out:/app/out" \
        -v "$SCRIPT_DIR/my_bots:/app/my_bots" \
        "$IMAGE" play "$@"
elif [ -x "$SCRIPT_DIR/testkit" ] && [ "$(uname -s)" = "Linux" ]; then
    echo "[testkit] Docker not found; running local Linux testkit binary..."
    cd "$SCRIPT_DIR"
    exec ./testkit "$@"
else
    echo "Error: Docker is required to run testkit on macOS and Windows." >&2
    echo "Please install Docker Desktop and start the Docker daemon." >&2
    exit 1
fi
