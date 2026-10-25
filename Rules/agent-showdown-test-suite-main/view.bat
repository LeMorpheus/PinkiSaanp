@echo off
setlocal

set IMAGE=codewars-kit
set PORT=8000
if not "%~1"=="" set PORT=%~1
set SCRIPT_DIR=%~dp0

if not exist "%SCRIPT_DIR%out\replays" mkdir "%SCRIPT_DIR%out\replays"

where docker >nul 2>&1
if errorlevel 1 (
    where python >nul 2>&1
    if not errorlevel 1 (
        echo [visualizer] Docker not found; running viewer_server.py locally with Python...
        cd /d "%SCRIPT_DIR%"
        python viewer_server.py %PORT%
        exit /b 0
    )
    echo [Error] Neither Docker Desktop nor Python was found.
    echo Please install Docker Desktop to view replays.
    exit /b 1
)

docker image inspect %IMAGE% >nul 2>&1
if errorlevel 1 (
    echo [visualizer] Docker image '%IMAGE%' not found. Building (one-time setup)...
    docker build -t %IMAGE% "%SCRIPT_DIR%"
)

echo [visualizer] Serving replay visualizer at http://localhost:%PORT%
echo [visualizer] Press Ctrl+C to stop.
docker run --rm -it -p %PORT%:8000 -v "%SCRIPT_DIR%out:/app/out:ro" %IMAGE% view
