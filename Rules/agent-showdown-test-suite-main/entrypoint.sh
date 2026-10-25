#!/usr/bin/env bash
set -e

# Visualizer server mode
if [ "$1" = "view" ] || [ "$1" = "viewer" ] || [ "$1" = "server" ]; then
    shift
    exec python3 /app/viewer_server.py "$@"
fi

# Match runner mode
if [ "$1" = "play" ] || [ "$1" = "testkit" ] || [ "$1" = "run" ]; then
    shift
    exec /app/testkit "$@"
fi

# If options or bot names passed directly
if [ $# -gt 0 ]; then
    exec /app/testkit "$@"
fi

# Default: show help
exec /app/testkit --help
