# Test script for portable Python backend
# This script tests the portable Python with the OviX backend

$ErrorActionPreference = "Stop"

Write-Host "=== Testing Portable Python Backend ===" -ForegroundColor Cyan
Write-Host ""

# Set paths
$ProjectRoot = $PSScriptRoot
$PortablePython = Join-Path $ProjectRoot "resources\python\python.exe"
$BackendScript = Join-Path $ProjectRoot "backend\api\main.py"

Write-Host "Project Root: $ProjectRoot" -ForegroundColor Gray
Write-Host "Portable Python: $PortablePython" -ForegroundColor Gray
Write-Host "Backend Script: $BackendScript" -ForegroundColor Gray
Write-Host ""

# Test 1: Python version
Write-Host "Test 1: Python Version" -ForegroundColor Yellow
& $PortablePython --version
Write-Host ""

# Test 2: Import basic modules
Write-Host "Test 2: Import Basic Modules" -ForegroundColor Yellow
& $PortablePython -c "import sys; print('Python:', sys.version); import fastapi; print('FastAPI:', fastapi.__version__); import uvicorn; print('Uvicorn: OK'); import pandas; print('Pandas:', pandas.__version__)"
Write-Host ""

# Test 3: Import Pywikibot with environment
Write-Host "Test 3: Import Pywikibot (with PYWIKIBOT_DIR)" -ForegroundColor Yellow
$env:PYWIKIBOT_DIR = $ProjectRoot
$env:PYWIKIBOT_NO_USER_CONFIG = "1"
& $PortablePython -c "import os; print('PYWIKIBOT_DIR:', os.environ.get('PYWIKIBOT_DIR')); import pywikibot; print('Pywikibot:', pywikibot.__version__)"
Write-Host ""

# Test 4: Start FastAPI backend
Write-Host "Test 4: Start FastAPI Backend" -ForegroundColor Yellow
Write-Host "Setting environment variables..." -ForegroundColor Gray
$env:PROJECT_ROOT = $ProjectRoot
$env:OVIX_USER_DATA = Join-Path $env:APPDATA "OviX"
$env:OVIX_DATA_PATH = Join-Path $env:OVIX_USER_DATA "data"
$env:OVIX_LOGS_PATH = Join-Path $env:OVIX_USER_DATA "logs"
$env:OVIX_CONFIG_PATH = Join-Path $env:OVIX_USER_DATA "config"
$env:PYWIKIBOT_DIR = $ProjectRoot
$env:PYWIKIBOT_NO_USER_CONFIG = "1"
$env:API_HOST = "127.0.0.1"
$env:API_PORT = "8000"

Write-Host "Starting backend with portable Python..." -ForegroundColor Gray
$BackendProcess = Start-Process -FilePath $PortablePython -ArgumentList "-m", "uvicorn", "backend.api.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $ProjectRoot -PassThru -NoNewWindow

Write-Host "Waiting for backend to start..." -ForegroundColor Gray
Start-Sleep -Seconds 5

# Test 5: Check if backend is running
Write-Host "Test 5: Check Backend Health" -ForegroundColor Yellow
try {
    $Response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/docs" -UseBasicParsing -TimeoutSec 10
    if ($Response.StatusCode -eq 200) {
        Write-Host "Backend is running successfully!" -ForegroundColor Green
    } else {
        Write-Host "Backend returned status code: $($Response.StatusCode)" -ForegroundColor Red
    }
} catch {
    Write-Host "Backend health check failed: $_" -ForegroundColor Red
}

Write-Host ""

# Test 6: Stop backend
Write-Host "Test 6: Stop Backend" -ForegroundColor Yellow
Stop-Process -Id $BackendProcess.Id -Force
Write-Host "Backend stopped" -ForegroundColor Green

Write-Host ""
Write-Host "=== Test Complete ===" -ForegroundColor Cyan
