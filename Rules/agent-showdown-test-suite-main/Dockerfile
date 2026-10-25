# syntax=docker/dockerfile:1
FROM python:3.12-slim

LABEL description="Codewars Standalone Player Testkit and Replay Visualizer"

# Install toolchains so players can test bots in Python, C++, Java, or Node.js
RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ \
    make \
    default-jdk-headless \
    nodejs \
    ca-certificates \
    curl \
 && rm -rf /var/lib/apt/lists/*

# Install web visualizer backend dependencies
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"

WORKDIR /app

# Copy testkit standalone binary
COPY testkit /app/testkit
RUN chmod +x /app/testkit && ln -sf /app/testkit /usr/local/bin/testkit

# Copy Raylib WASM visualizer web assets
COPY web /app/web

# Copy visualizer server
COPY viewer_server.py /app/viewer_server.py

# Copy benchmark bots
COPY bots /app/bots

# Copy container entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Environment settings
ENV PYTHONUNBUFFERED=1 \
    REPLAY_DIR=/app/out/replays \
    WEB_DIR=/app/web

# Ensure directories for mounts exist
RUN mkdir -p /app/out /app/my_bots

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["view"]
