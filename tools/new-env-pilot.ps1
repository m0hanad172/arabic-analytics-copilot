param(
  [string]$ProjectRoot = (Get-Location).Path,
  [switch]$Force
)

$envPath = Join-Path $ProjectRoot "backend\.env.pilot"
$backendDir = Join-Path $ProjectRoot "backend"

if (!(Test-Path $backendDir)) {
  throw "backend folder not found at: $backendDir"
}

if ((Test-Path $envPath) -and (-not $Force)) {
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  Copy-Item $envPath "$envPath.bak.$stamp" -Force
  Write-Host "Backup created: $envPath.bak.$stamp"
}

$geminiKey = Read-Host "GEMINI_API_KEY (leave empty to keep LLM disabled)"
$llmEnabled = if ([string]::IsNullOrWhiteSpace($geminiKey)) { "0" } else { "1" }

# DB default (عدّله لو عندك اسم/باسورد مختلف)
$dbUrlDefault = "postgresql://copilot_ro:123@host.docker.internal:5433/arabic_analytics"
$dbUrl = Read-Host "DATABASE_URL (Enter to use default: $dbUrlDefault)"
if ([string]::IsNullOrWhiteSpace($dbUrl)) { $dbUrl = $dbUrlDefault }

$lines = @(
  "APP_ENV=pilot",
  "API_PREFIX=/api",
  "",
  "# --- LLM ---",
  "LLM_ENABLED=$llmEnabled",
  ($(if ($llmEnabled -eq "1") { "GEMINI_API_KEY=$geminiKey" } else { "# GEMINI_API_KEY=" })),
  "GEMINI_MODEL=gemini-1.5-flash",
  "",
  "# --- DB ---",
  "DATABASE_URL=$dbUrl",
  "",
  "# --- STT ---",
  "STT_ENABLED=1",
  "STT_MODEL=Systran/faster-whisper-small",
  "STT_DEVICE=cuda",
  "STT_COMPUTE_TYPE=float16",
  "STT_BATCH_SIZE=16",
  "STT_VAD=0",
  "STT_FFMPEG_CONVERT=1"
)

# Write UTF-8 with newline at end
Set-Content -Path $envPath -Value ($lines -join "`n") -Encoding utf8
Add-Content -Path $envPath -Value "`n" -Encoding utf8

Write-Host "Wrote: $envPath"
Write-Host "LLM_ENABLED=$llmEnabled"
