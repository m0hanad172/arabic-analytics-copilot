param(
  [string]$DbName = "arabic_analytics",
  [string]$Container = "aac-pg",
  [string]$DumpPath = "db\db_dump.sql"
)

Write-Host "Restoring $DumpPath into $DbName on container $Container ..."

if (!(Test-Path $DumpPath)) {
  Write-Host "ERROR: Dump file not found: $DumpPath"
  exit 1
}

# Wait for Postgres
docker exec $Container pg_isready -U postgres -d $DbName *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Waiting for Postgres to be ready..."
  Start-Sleep -Seconds 3
}

docker exec -i $Container psql -U postgres -d $DbName < $DumpPath
Write-Host "Done."
