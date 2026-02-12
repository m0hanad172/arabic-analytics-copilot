param(
  [string]$Container = "aac-pg",
  [string]$DbName = "arabic_analytics",
  [string]$CsvHostPath = "E:\Arabic Analytics Copilot\data\clean\bi_ready_clean.csv",
  [string]$SqlFile = "E:\Arabic Analytics Copilot\backend\app\db\db_bootstrap.sql"
)

# 1) Copy CSV into container
Write-Host "Copying CSV to container..."
docker cp "$CsvHostPath" "$Container`:/tmp/bi_ready_clean.csv" | Out-Null

# 2) Create DB (if missing) - must run as postgres
Write-Host "Ensuring database exists..."
$exists = docker exec -i $Container psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName';"
if (-not $exists.Trim()) {
  docker exec -i $Container psql -U postgres -d postgres -c "CREATE DATABASE $DbName;" | Out-Null
  Write-Host "Created database: $DbName"
} else {
  Write-Host "Database already exists: $DbName"
}

# 3) Run bootstrap SQL against the target DB
Write-Host "Running bootstrap SQL..."
Get-Content $SqlFile -Raw | docker exec -i $Container psql -U postgres -d $DbName

Write-Host "Done. Quick check:"
docker exec -i $Container psql -U postgres -d $DbName -c "select bi_meta.get_catalog('bi');" | Out-Host
