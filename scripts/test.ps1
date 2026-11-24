# Run the backend test-suite on Windows (PowerShell) against the Docker *test* database.
#   .\scripts\test.ps1
# Requires: Docker Desktop, and a Python 3.12 virtual environment in backend\.venv with `pip install -e ".[dev]"`.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path .env)) { throw "Create .env first:  copy .env.example .env   (and set JWT_SECRET)" }

# Read POSTGRES_USER / POSTGRES_PASSWORD from .env
$cfg = @{}
Get-Content .env | ForEach-Object { if ($_ -match '^\s*([A-Z_]+)\s*=\s*([^#\r\n]*)') { $cfg[$Matches[1]] = $Matches[2].Trim() } }
$user = $cfg["POSTGRES_USER"]; $pass = $cfg["POSTGRES_PASSWORD"]
if (-not $user -or -not $pass) { throw "POSTGRES_USER / POSTGRES_PASSWORD missing in .env" }

docker compose up -d db
Write-Host "Waiting for PostgreSQL..."
do { Start-Sleep -Seconds 2; docker compose exec -T db pg_isready -U $user | Out-Null } until ($LASTEXITCODE -eq 0)

# The dedicated test database is created automatically on a fresh volume; create it if the volume is older.
$exists = docker compose exec -T db psql -U $user -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='docint_test'"
if ("$exists".Trim() -ne "1") { docker compose exec -T db psql -U $user -d postgres -c "CREATE DATABASE docint_test" | Out-Null }

# The tests TRUNCATE tables, so they only ever run against a database whose name ends with "test".
# docker-compose.yml publishes PostgreSQL on host port 5433 (5432 may be used by another stack).
$env:TEST_DATABASE_URL = "postgresql+psycopg://${user}:${pass}@127.0.0.1:5433/docint_test"
Set-Location backend
& .\.venv\Scripts\python.exe -m pytest -q
