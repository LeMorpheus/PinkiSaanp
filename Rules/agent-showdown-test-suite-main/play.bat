@echo off
setlocal
set IMAGE=codewars-kit
set SCRIPT_DIR=%~dp0

if not exist "%SCRIPT_DIR%out" mkdir "%SCRIPT_DIR%out"
if not exist "%SCRIPT_DIR%my_bots" mkdir "%SCRIPT_DIR%my_bots"

where docker >nul 2>&1
if errorlevel 1 (
    echo [Error] Docker Desktop is required to run the testkit on Windows.
    echo Please install Docker Desktop and ensure the Docker daemon is running.
    exit /b 1
)

docker image inspect %IMAGE% >nul 2>&1
if errorlevel 1 (
    echo [testkit] Docker image %IMAGE% not found. Building (one-time setup)...
    docker build -t %IMAGE% "%SCRIPT_DIR%"
)

docker run --rm -it -v "%SCRIPT_DIR%out:/app/out" -v "%SCRIPT_DIR%my_bots:/app/my_bots" %IMAGE% play %*
