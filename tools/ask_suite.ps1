# Force UTF-8 output (fixes âœ…)
try { chcp 65001 > $null } catch {}
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding


$ErrorActionPreference = "Stop"

# 1) Compile check (catches SyntaxError / missing imports early)
python -m compileall backend/app/services/ask backend/app/api/routes | Out-Host

# 2) Runtime /ask smoke
python tools/ask_diag.py

# 3) Cache-vs-LLM precedence test
python tools/test_llm_overrides_rulebased_cache.py

Write-Host "`n✅ ALL CHECKS PASSED" -ForegroundColor Green
