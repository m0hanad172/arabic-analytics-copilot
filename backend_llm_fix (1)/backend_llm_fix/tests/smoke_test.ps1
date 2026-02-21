$ErrorActionPreference = "Stop"

$base = $env:BASE_URL
if ([string]::IsNullOrWhiteSpace($base)) { $base = "http://127.0.0.1:8000/api" }

# Ensure console can display UTF-8
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding

function Decode-B64([string]$s) {
  [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($s))
}

function Call-Json {
  param([string]$Method, [string]$Url, [object]$BodyObj = $null)

  try {
    if ($null -ne $BodyObj) {
      $body = $BodyObj | ConvertTo-Json -Depth 10
      return Invoke-RestMethod -Method $Method -Uri $Url -ContentType "application/json; charset=utf-8" -Body $body -ErrorAction Stop
    } else {
      return Invoke-RestMethod -Method $Method -Uri $Url -ErrorAction Stop
    }
  } catch {
    $resp = $_.Exception.Response
    if ($null -ne $resp) {
      $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
      $text = $reader.ReadToEnd()
      throw "HTTP $($resp.StatusCode.value__) from $Url`n$text"
    }
    throw
  }
}

# Assert that works with bool/string/array/object/null
function Assert($cond, [string]$msg) {
  $ok = $false

  if ($cond -is [bool]) { $ok = $cond }
  elseif ($null -eq $cond) { $ok = $false }
  elseif ($cond -is [string]) { $ok = -not [string]::IsNullOrWhiteSpace($cond) }
  elseif ($cond -is [System.Array]) { $ok = ($cond.Count -gt 0) }
  else {
    try { $ok = [bool]$cond } catch { $ok = ($null -ne $cond) }
  }

  if (-not $ok) { throw $msg }
}

function Print-Header([string]$t) {
  ""
  "=============================="
  $t
  "=============================="
}

try {
  Print-Header "1) health"
  $h = Call-Json GET "$base/health"
  Assert ($h.status -eq "ok") "health not ok"
  "OK: /health => " + ($h | ConvertTo-Json -Depth 10)

  Print-Header "2) schema"
  $s = Call-Json GET "$base/schema"
  Assert (-not [string]::IsNullOrWhiteSpace([string]$s.allowed_schema)) "schema missing allowed_schema"
  Assert ($null -ne $s.catalog) "schema missing catalog"
  "OK: /schema keys => " + ($s.catalog.PSObject.Properties.Name -join ", ")

  Print-Header "3) schema refresh"
  $sr = Call-Json POST "$base/schema/refresh"
  Assert (-not [string]::IsNullOrWhiteSpace([string]$sr.allowed_schema)) "schema/refresh missing allowed_schema"
  "OK: /schema/refresh"

  Print-Header "4) query debug_sql allowed"
  $qok = Call-Json POST "$base/query" @{
    question="x"
    debug_sql="SELECT * FROM bi.vw_fact_sales_line_clean LIMIT 3;"
    execute=$true
    max_rows=10
  }
  Assert (-not [string]::IsNullOrWhiteSpace([string]$qok.sql)) "query(debug_sql) missing sql"
  Assert ($qok.row_count -ge 0) "query(debug_sql) missing row_count"
  "OK: /query debug_sql SELECT allowed"
  "SQL => " + $qok.sql

Print-Header "5) query debug_sql blocked (multi statement)"
try {
$qbad = Call-Json POST "$base/query" @{
    question="x"
    debug_sql="SELECT 1; SELECT 2;"
    execute=$false
}
throw "Expected failure but request succeeded"
} catch {
# نعتبر أي 400/422 نجاح، لأن الهدف: "ينمنع" مش "رسالة معينة"
$msg = $_.Exception.Message
if ($msg -match "HTTP 400" -or $msg -match "HTTP 422") {
    "OK: blocked multi statement (got expected client error)"
} else {
    throw "Expected 400/422 but got:`n$msg"
}
}


  Print-Header "6) ask rule-based (no cache)"
  $q1 = Decode-B64 "2KfYudmE2Ykg2KfZhNmF2K/ZhiDZhdio2YrYudin"  # اعلى المدن مبيعا
  $a1 = Call-Json POST "$base/ask?use_llm=0&use_cache=0" @{ question=$q1 }
  Assert ($a1.meta.used_llm -eq $false) "expected used_llm=false for rule-based"
  Assert (-not [string]::IsNullOrWhiteSpace([string]$a1.result.sql)) "ask missing sql"
  "OK: rule-based meta => " + ($a1.meta | ConvertTo-Json -Depth 10)
  "SQL => " + $a1.result.sql
  
  Print-Header "7) ask cache behavior (deterministic)"

  # نستخدم سؤال ثابت (إنجليزي) لتفادي مشاكل الترميز
  $q2 = "Top 10 cities by net sales"

  # 1) أول نداء: use_cache=0 يجبر النظام ما يستخدم الكاش حتى لو موجود
  $a2 = Call-Json POST "$base/ask?use_llm=0&use_cache=0" @{ question=$q2 }
  Assert ($a2.meta.used_cache -eq $false) "expected first call used_cache=false (use_cache=0 forces miss)"
  "OK: first call forced no-cache ✅"
  "meta => " + ($a2.meta | ConvertTo-Json -Depth 10)

  # 2) ثاني نداء: use_cache=1 يسمح باستخدام الكاش (لازم يصير hit)
  $a3 = Call-Json POST "$base/ask?use_llm=0&use_cache=1" @{ question=$q2 }
  Assert ($a3.meta.used_cache -eq $true) "expected second call used_cache=true (use_cache=1 should hit)"
  "OK: second call cache hit ✅"
  "meta => " + ($a3.meta | ConvertTo-Json -Depth 10)

  "OK: cache miss->hit ✅"


  Print-Header "8) ask Gemini (no cache) — accept fallback but report it"
  $q3 = Decode-B64 "2YLYp9ix2YYg2LXYp9mB2Yog2KfZhNmF2KjZiti52KfYqiDZiNin2YTYrti12YjZhdin2Kog2K3Ys9ioINin2YTZhdiv2YrZhtipINmI2KfZhNix2KjYuSDZiNin2LnYsdi2INij2LnZhNmJIDU="  # قارن صافي...
  $g1 = Call-Json POST "$base/ask?use_llm=1&use_cache=0" @{ question=$q3 }
  Assert (-not [string]::IsNullOrWhiteSpace([string]$g1.result.sql)) "ask Gemini missing sql"
  if ($g1.meta.used_llm -eq $true) { "OK: Gemini used ✅" } else { "WARN: Gemini not used (fallback) ⚠️" }
  "Gemini meta => " + ($g1.meta | ConvertTo-Json -Depth 10)
  "SQL => " + $g1.result.sql

  Print-Header "9) logs list"
  $logs = Call-Json GET "$base/logs?limit=5"
  Assert ($logs) "logs response empty"
  "OK: /logs => " + ($logs | ConvertTo-Json -Depth 10)

  Print-Header "10) eval smoke (execute=true, use_llm=false)"
  $sm = Call-Json GET "$base/eval/smoke?execute=true&use_llm=false"
  Assert ($sm.total -ge 1) "smoke total should be >= 1"
  Assert ($sm.passed -eq $sm.total) ("smoke failed: passed {0} / total {1}" -f $sm.passed, $sm.total)
  "OK: smoke passed {0}/{1}" -f $sm.passed, $sm.total

  ""
  "✅ ALL TESTS PASSED"
  exit 0

} catch {
  ""
  "❌ TESTS FAILED"
  $_.Exception.Message
  exit 1
}
