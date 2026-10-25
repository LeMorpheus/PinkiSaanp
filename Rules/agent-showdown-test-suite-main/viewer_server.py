#!/usr/bin/env python3
"""Codewars Replay Visualizer Server.

Serves the Raylib WASM web visualizer on port 8000 and exposes endpoints
for loading game replays from the replays directory.
"""
from __future__ import annotations

import mimetypes
import os
import sys
from pathlib import Path

# Add MIME type for WebAssembly
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("audio/ogg", ".ogg")

HERE = Path(__file__).resolve().parent

def get_replay_dir() -> Path:
    env_dir = os.environ.get("REPLAY_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    for candidate in [
        HERE / "out" / "replays",
        HERE / "logs",
        Path("out/replays").resolve(),
        Path("logs").resolve(),
        Path("/app/out/replays").resolve(),
        Path("/app/logs").resolve(),
    ]:
        if candidate.is_dir():
            return candidate.resolve()
    p = (HERE / "out" / "replays").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_web_dir() -> Path:
    env_dir = os.environ.get("WEB_DIR")
    if env_dir and Path(env_dir).is_dir():
        return Path(env_dir).resolve()
    for candidate in [
        HERE / "web",
        Path("web").resolve(),
        Path("/app/web").resolve(),
    ]:
        if candidate.is_dir():
            return candidate.resolve()
    return (HERE / "web").resolve()

REPLAY_DIR = get_replay_dir()
WEB_DIR = get_web_dir()

def run_fastapi(port: int):
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="Codewars Replay Visualizer")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.api_route("/api/logs/{log_id}", methods=["GET", "HEAD"])
    def get_log(log_id: str):
        stem = log_id.removesuffix(".pbrp")
        path = REPLAY_DIR / f"{stem}.pbrp"
        if not path.is_file():
            path = REPLAY_DIR / log_id
        if not path.is_file():
            raise HTTPException(404, f"Replay '{log_id}' not found in {REPLAY_DIR}")
        return FileResponse(path, media_type="application/octet-stream")

    @app.get("/api/replays")
    def list_replays():
        if not REPLAY_DIR.exists():
            return []
        ids = []
        for f in REPLAY_DIR.glob("*.pbrp"):
            try:
                ids.append(int(f.stem))
            except ValueError:
                pass
        return sorted(ids)

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    print(f"\n=======================================================")
    print(f" Codewars Visualizer running at http://localhost:{port}")
    print(f" Replays directory: {REPLAY_DIR}")
    print(f" Web assets:        {WEB_DIR}")
    print(f"=======================================================\n", flush=True)

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


def run_http_server(port: int):
    import http.server
    import socketserver
    import urllib.parse

    class VisualizerHTTPHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEB_DIR), **kwargs)

        def guess_type(self, path):
            if str(path).endswith(".wasm"):
                return "application/wasm"
            if str(path).endswith(".ogg"):
                return "audio/ogg"
            return super().guess_type(path)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            clean_path = parsed.path

            if clean_path.startswith("/api/logs/"):
                log_id = clean_path.split("/api/logs/")[1]
                stem = log_id.removesuffix(".pbrp")
                target = REPLAY_DIR / f"{stem}.pbrp"
                if not target.is_file():
                    target = REPLAY_DIR / log_id
                if not target.is_file():
                    self.send_error(404, f"Replay '{log_id}' not found")
                    return
                try:
                    data = target.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as e:
                    self.send_error(500, str(e))
                return

            if clean_path.startswith("/api/replays"):
                ids = []
                for f in REPLAY_DIR.glob("*.pbrp"):
                    try:
                        ids.append(int(f.stem))
                    except ValueError:
                        pass
                import json
                body = json.dumps(sorted(ids)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return

            return super().do_GET()

    print(f"\n=======================================================")
    print(f" Codewars Visualizer (builtin) at http://localhost:{port}")
    print(f" Replays directory: {REPLAY_DIR}")
    print(f" Web assets:        {WEB_DIR}")
    print(f"=======================================================\n", flush=True)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", port), VisualizerHTTPHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")


def main():
    port = int(os.environ.get("PORT", 8000))
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])

    try:
        import fastapi
        import uvicorn
        run_fastapi(port)
    except ImportError:
        run_http_server(port)


if __name__ == "__main__":
    main()
