@echo off
REM Urban Heat Island - Łódź: run app locally (Windows)
REM Requires Python 3 installed. Opens http://localhost:8000

cd /d "%~dp0"
echo Starting local server in: %CD%
echo Open http://localhost:8000 in your browser.
echo Press Ctrl+C to stop.
python -m http.server 8000
pause
