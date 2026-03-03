param(
  # Docker
  [string]$Container = "aac-pg",

  # Database
  [string]$DbName = "arabic_analytics",
  [string]$SuperUser = "postgres",

  # CSV (host) + path inside container
  [string]$CsvHostPath = "",
  [string]$CsvContainerPath = "/tmp/bi_ready_clean.csv",

  # SQL files
  [string]$DbBootstrapSql = "",
  [string]$Phase4BootstrapSql = "",

  # Strip CREATE DATABASE/USER/ROLE lines if present in SQL
  [switch]$StripDbRoleStatements = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail($msg) {
  Write-Host "`n[ERROR] $msg`n" -ForegroundColor Red
  exit 1
}
function Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }

function Ensure-Docker {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker not found in PATH."
  }
  docker version *> $null
  if ($LASTEXITCODE -ne 0) { Fail "Docker daemon not reachable." }
}

function Ensure-ContainerRunning([string]$name) {
  $running = $null
  try { $running = docker inspect -f "{{.State.Running}}" $name 2>$null } catch {}
  if (-not $running) { Fail "Container '$name' not found. Create it first." }

  if ($running.Trim() -ne "true") {
    Info "Container '$name' is stopped. Starting..."
    docker start $name | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "Failed to start container '$name'." }
  }
  Ok "Container is running: $name"
}

function Ensure-Defaults {
  $scriptDir = Split-Path -Parent $PSCommandPath
  $repoRoot = Resolve-Path (Join-Path $scriptDir "..") | Select-Object -ExpandProperty Path

  if ([string]::IsNullOrWhiteSpace($CsvHostPath)) {
    $script:CsvHostPath = Join-Path $repoRoot "data\clean\bi_ready_clean.csv"
  } else { $script:CsvHostPath = $CsvHostPath }

  if ([string]::IsNullOrWhiteSpace($DbBootstrapSql)) {
    $script:DbBootstrapSql = Join-Path $repoRoot "backend\app\db\db_bootstrap.sql"
  } else { $script:DbBootstrapSql = $DbBootstrapSql }

  if ([string]::IsNullOrWhiteSpace($Phase4BootstrapSql)) {
    $script:Phase4BootstrapSql = Join-Path $repoRoot "backend\app\db\phase4_db_bootstrap.sql"
  } else { $script:Phase4BootstrapSql = $Phase4BootstrapSql }

  if (-not (Test-Path -LiteralPath $script:CsvHostPath))       { Fail "CSV not found: $script:CsvHostPath" }
  if (-not (Test-Path -LiteralPath $script:DbBootstrapSql))    { Fail "SQL not found: $script:DbBootstrapSql" }
  if (-not (Test-Path -LiteralPath $script:Phase4BootstrapSql)){ Fail "SQL not found: $script:Phase4BootstrapSql" }

  Info "RepoRoot: $repoRoot"
  Info "CSV:      $script:CsvHostPath"
  Info "SQL #1:   $script:DbBootstrapSql"
  Info "SQL #2:   $script:Phase4BootstrapSql"
}

function Ensure-Database([string]$container, [string]$superUser, [string]$dbName) {
  Info "Ensuring database '$dbName' exists..."
  $exists = docker exec -i $container psql -U $superUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$dbName';"
  if (-not $exists.Trim()) {
    docker exec -i $container psql -U $superUser -d postgres -c "CREATE DATABASE $dbName;" | Out-Null
    Ok "Created database: $dbName"
  } else {
    Ok "Database exists: $dbName"
  }
}

function Copy-CSV([string]$csvHostPath, [string]$container, [string]$csvContainerPath) {
  Info "Copying CSV into container: $csvContainerPath"
  & docker cp "$csvHostPath" ("${container}:$csvContainerPath") | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Fail "docker cp failed. Check CSV path and container name."
  }
  Ok "CSV copied."
}

function Write-FilteredTempSql([string]$srcPath, [bool]$stripStatements) {
  $content = Get-Content -LiteralPath $srcPath -Raw -Encoding UTF8

  if ($stripStatements) {
    $content = $content -replace '(?im)^\s*CREATE\s+DATABASE\b.*?;\s*$', ''
    $content = $content -replace '(?im)^\s*CREATE\s+(USER|ROLE)\b.*?;\s*$', ''
    $content = $content -replace '(?im)^\s*GRANT\s+.*\s+ON\s+DATABASE\b.*?;\s*$', ''
    $content = $content -replace '(?im)^\s*ALTER\s+DATABASE\b.*?;\s*$', ''
  }

  $tmp = Join-Path $env:TEMP ("aac_sql_" + [Guid]::NewGuid().ToString("N") + ".sql")
  # UTF-8 without BOM (works in all PowerShell versions)
  [System.IO.File]::WriteAllText($tmp, $content, (New-Object System.Text.UTF8Encoding($false)))
  return $tmp
}

function Run-SqlFile([string]$container, [string]$superUser, [string]$dbName, [string]$sqlPath, [bool]$stripStatements) {
  Info "Running SQL: $sqlPath"
  $tmp = Write-FilteredTempSql -srcPath $sqlPath -stripStatements $stripStatements
  try {
    $cmd = "docker exec -i $container psql -v ON_ERROR_STOP=1 -U $superUser -d $dbName < `"$tmp`""
    cmd.exe /c $cmd
    if ($LASTEXITCODE -ne 0) { Fail "SQL failed: $sqlPath" }
    Ok "Executed: $sqlPath"
  } finally {
    Remove-Item $tmp -ErrorAction SilentlyContinue | Out-Null
  }
}

function Post-Checks([string]$container, [string]$superUser, [string]$dbName) {
  Info "Post-checks..."
  docker exec -i $container psql -U $superUser -d $dbName -c "\dn" | Out-Host
  docker exec -i $container psql -U $superUser -d $dbName -c "select count(*) as fact_rows from bi.fact_sales_line;" | Out-Host
  docker exec -i $container psql -U $superUser -d $dbName -c "select bi_meta.get_catalog('bi');" | Out-Host
  Ok "All checks done."
}

# ---------------- MAIN ----------------
Ensure-Docker
Ensure-ContainerRunning -name $Container
Ensure-Defaults

Ensure-Database -container $Container -superUser $SuperUser -dbName $DbName
Copy-CSV -csvHostPath $script:CsvHostPath -container $Container -csvContainerPath $CsvContainerPath

Run-SqlFile -container $Container -superUser $SuperUser -dbName $DbName -sqlPath $script:DbBootstrapSql -stripStatements $StripDbRoleStatements
Run-SqlFile -container $Container -superUser $SuperUser -dbName $DbName -sqlPath $script:Phase4BootstrapSql -stripStatements $StripDbRoleStatements

Post-Checks -container $Container -superUser $SuperUser -dbName $DbName
Ok "Restore Phase 4 completed successfully."
