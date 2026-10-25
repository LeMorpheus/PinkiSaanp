#!/usr/bin/env bash
# Usage:
#   ./view.sh [port]
# Starts visualizer at http://localhost:8000
set -euo pipefail

PORT="${1:-8000}"
IMAGE="${IMAGE:-codewars-kit}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$SCRIPT_DIR/out/replays"

if command -v docker &>/dev/null; then
    if ! docker image inspect "$IMAGE" &>/dev/null; then
        echo "[visualizer] Docker image '$IMAGE' not found. Building (one-time setup)..."
        docker build -t "$IMAGE" "$SCRIPT_DIR"
    fi
    echo "[visualizer] Serving replay visualizer at http://localhost:${PORT}"
    echo "[visualizer] Press Ctrl+C to stop."
    exec docker run --rm -it \
        -p "${PORT}:8000" \
        -v "$SCRIPT_DIR/out:/app/out:ro" \
        "$IMAGE" view
elif command -v python3 &>/dev/null; then
    echo "[visualizer] Docker not found; running local Python viewer server..."
    cd "$SCRIPT_DIR"
    exec python3 viewer_server.py "$PORT"
else
    echo "Error: Neither Docker nor Python 3 was found." >&2
    exit 1
fi
