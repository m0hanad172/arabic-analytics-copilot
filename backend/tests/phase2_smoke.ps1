$ErrorActionPreference = "Stop"
chcp 65001 | Out-Null
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

function Invoke-Copilot($question, $maxRows=10, $execute=$false) {
  $json = @{ question=$question; max_rows=$maxRows; execute=$execute } | ConvertTo-Json -Depth 5
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
  return Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/query" `
    -ContentType "application/json; charset=utf-8" -Body $bytes
}

$tests = @(
  @{
    name="Monthly net_sales 2016"
    q="اعطني صافي المبيعات شهريا في 2016"
    mustContain=@("vw_sales_monthly","WHERE order_year = 2016","ORDER BY month_start")
    mustNotContain=@("Fallback","fact_sales_line LIMIT")
    max=12
  },
  @{
    name="Group-by city 2016"
    q="اعطني المبيعات حسب المدينة في 2016"
    mustContain=@("FROM bi.fact_sales_line","GROUP BY","WHERE order_year = 2016","city")
    mustNotContain=@("Fallback","LIMIT 10`r`nSELECT *")
    max=10
  },
  @{
    name="Top 10 products 2016"
    q="أفضل 10 منتجات في 2016"
    mustContain=@("GROUP BY 1,2","ORDER BY net_sales","WHERE order_year = 2016")
    mustNotContain=@("Fallback")
    max=10
  },
  @{
    name="Top 5 categories 2014 month 3"
    q="أفضل 5 فئات في 2014 شهر 3"
    mustContain=@("product_category","WHERE order_year = 2014 AND order_month = 3","GROUP BY 1")
    mustNotContain=@("Fallback")
    max=5
  },
  @{
    name="Avg ship delay by ship mode 2015"
    q="متوسط تأخير الشحن حسب طريقة الشحن في 2015"
    mustContain=@("AVG(ship_delay_days)","ship_mode","WHERE order_year = 2015","GROUP BY 1")
    mustNotContain=@("Fallback")
    max=10
  },
  @{
    name="Monthly profit_after_shipping 2016"
    q="اعطني الربح بعد الشحن شهريا في 2016"
    mustContain=@("vw_sales_monthly","profit_after_shipping","WHERE order_year = 2016")
    mustNotContain=@("Fallback")
    max=12
  }
)

$passed = 0
$failed = 0

foreach ($t in $tests) {
  $resp = Invoke-Copilot $t.q $t.max $false
  $sql = ($resp.sql | Out-String).Trim()
  $exp = ($resp.explanation | Out-String).Trim()

  $ok = $true

  foreach ($m in $t.mustContain) {
    if ($sql -notmatch [regex]::Escape($m)) { $ok = $false }
  }
  foreach ($m in $t.mustNotContain) {
    if (($exp + " " + $sql) -match $m) { $ok = $false }
  }

  if ($ok) {
    Write-Host "[PASS] $($t.name)"
    $passed++
  } else {
    Write-Host "[FAIL] $($t.name)"
    Write-Host "  Q: $($t.q)"
    Write-Host "  SQL: $sql"
    Write-Host "  EXP: $exp"
    $failed++
  }
}

Write-Host ""
Write-Host "Passed: $passed  Failed: $failed"
if ($failed -gt 0) { exit 1 }
