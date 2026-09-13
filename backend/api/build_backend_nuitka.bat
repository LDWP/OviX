@echo off
REM Build script for OviX Backend using Nuitka
REM This compiles the Python backend into a standalone executable

echo Building OviX Backend with Nuitka...

cd /d %~dp0

python -m nuitka ^
    --standalone ^
    --onefile ^
    --enable-plugin=numpy ^
    --include-package=pywikibot ^
    --include-package=fastapi ^
    --include-package=uvicorn ^
    --include-package=pandas ^
    --include-package=bs4 ^
    --include-package=yaml ^
    --include-package=dotenv ^
    --include-data-dir=../../config=config ^
    --output-dir=../../dist/nuitka ^
    --output-filename=ovix_backend.exe ^
    backend_entry.py

echo Build complete!
pause
