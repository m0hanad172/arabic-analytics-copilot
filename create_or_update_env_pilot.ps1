# === create_or_update_env_pilot.ps1 ===
# Run from project root (where backend/ exists)

$envPath = Join-Path (Get-Location) "backend\.env.pilot"

# Keys you want in .env.pilot
$vars = [ordered]@{
  "LLM_ENABLED"    = "1"
  "GEMINI_API_KEY" = "YOUR_KEY_HERE"
  "GOOGLE_API_KEY" = "YOUR_KEY_HERE"
}

# Ensure backend folder exists
$backendDir = Split-Path $envPath -Parent
if (-not (Test-Path $backendDir)) {
  throw "backend/ folder not found. Please run this from the project root."
}

# Read existing lines (or start empty)
$lines = @()
if (Test-Path $envPath) {
  $lines = Get-Content -Path $envPath -Encoding UTF8
}

# Helper: set or add KEY=VALUE
function Set-Or-AddEnvLine {
  param(
    [string[]]$Lines,
    [string]$Key,
    [string]$Value
  )
  $pattern = "^\s*$([regex]::Escape($Key))\s*="
  $idx = -1
  for ($i=0; $i -lt $Lines.Count; $i++) {
    if ($Lines[$i] -match $pattern) { $idx = $i; break }
  }
  if ($idx -ge 0) {
    $Lines[$idx] = "$Key=$Value"
  } else {
    $Lines += "$Key=$Value"
  }
  return ,$Lines
}

# Apply updates
foreach ($k in $vars.Keys) {
  $lines = Set-Or-AddEnvLine -Lines $lines -Key $k -Value $vars[$k]
}

# Write file (UTF8 no BOM)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envPath, $lines, $utf8NoBom)

Write-Host "✅ Updated: $envPath" -ForegroundColor Green
Write-Host "Now edit GEMINI_API_KEY/GOOGLE_API_KEY to your real key." -ForegroundColor Yellow
