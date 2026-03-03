param(
  [string]$DbName = "arabic_analytics",
  [string]$Container = "aac-pg",
  [string]$DumpPath = "db\db_dump.sql",
  [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"

Write-Host "Restoring $DumpPath into DB '$DbName' on container '$Container' ..."

if (!(Test-Path $DumpPath)) {
  Write-Host "ERROR: Dump file not found: $DumpPath"
  exit 1
}

# Wait for container
$maxWait = 60
for ($i=0; $i -lt $maxWait; $i++) {
  docker ps --format "{{.Names}}" | Select-String -SimpleMatch $Container | Out-Null
  if ($LASTEXITCODE -eq 0) { break }
  Start-Sleep -Seconds 1
}
docker ps --format "{{.Names}}" | Select-String -SimpleMatch $Container | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "ERROR: Container '$Container' not running. Start DB first:"
  Write-Host "  docker compose -f compose.db.yml -p aac up -d"
  exit 1
}

# Wait for Postgres ready
for ($i=0; $i -lt $maxWait; $i++) {
  docker exec $Container pg_isready -U postgres -d postgres *> $null
  if ($LASTEXITCODE -eq 0) { break }
  Start-Sleep -Seconds 1
}
docker exec $Container pg_isready -U postgres -d postgres *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "ERROR: Postgres not ready after $maxWait seconds."
  exit 1
}

# (Optional) recreate DB
if ($ForceRecreate) {
  Write-Host "ForceRecreate enabled: dropping DB '$DbName' ..."
  docker exec -it $Container psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $DbName WITH (FORCE);"
}

# Ensure DB exists
docker exec -it $Container psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "SELECT 1 FROM pg_database WHERE datname = '$DbName';" *> $null
if ($LASTEXITCODE -ne 0) {
  # If query failed for any reason, try to create
  Write-Host "Ensuring DB '$DbName' exists..."
}
docker exec -it $Container psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$DbName') THEN CREATE DATABASE $DbName; END IF; END $$;"

# Restore
Write-Host "Restoring dump (this may take a moment)..."
Get-Content -Raw -Encoding UTF8 $DumpPath | docker exec -i $Container psql -U postgres -d $DbName -v ON_ERROR_STOP=1

Write-Host "Restore complete. Quick checks:"
docker exec -it $Container psql -U postgres -d $DbName -c "\dn"
docker exec -it $Container psql -U postgres -d $DbName -c "SELECT COUNT(*) AS fact_rows FROM bi.fact_sales_line;" 2>$null

Write-Host "Done."