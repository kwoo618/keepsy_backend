# Keepsy 엔진 스모크 테스트 — 데모 시나리오 체인 검증
# 실행: PC PowerShell에서  .\smoke_test.ps1
# 위치: keepsy_backend 루트에 저장 (fixtures/sample_contract.txt 참조)
# 주의: extract는 Gemini 실호출 1회 — 연타 실행 금지 (분당 쿼터)

$BASE = "https://165-140-22-175.nip.io"
$pass = 0; $fail = 0

function Check($name, $cond, $detail) {
    if ($cond) { Write-Host "  PASS  $name" -ForegroundColor Green; $script:pass++ }
    else { Write-Host "  FAIL  $name — $detail" -ForegroundColor Red; $script:fail++ }
}

Write-Host "`n[1/6] GET /health" -ForegroundColor Cyan
$h = Invoke-RestMethod "$BASE/health"
Check "health ok" ($h.status -eq "ok") "응답: $($h | ConvertTo-Json -Compress)"

Write-Host "`n[2/6] POST /contract/extract (Gemini 실호출)" -ForegroundColor Cyan
# [IO.File]::ReadAllText 사용 이유: ① UTF-8 자동 인식 (PS5.1 Get-Content 기본값은 CP949)
# ② Get-Content 문자열엔 PSPath 등 확장 프로퍼티가 붙어 ConvertTo-Json이 객체로 직렬화해 버림
$raw = [IO.File]::ReadAllText((Join-Path (Get-Location) "fixtures\sample_contract.txt"))
$ex = Invoke-RestMethod "$BASE/contract/extract" -Method Post -ContentType "application/json; charset=utf-8" `
      -Body ([Text.Encoding]::UTF8.GetBytes((@{ raw_text = $raw } | ConvertTo-Json)))
$t = $ex.terms
Check "시급 9500"            ($t.hourly_wage -eq 9500)              "실제: $($t.hourly_wage)"
Check "주간 14.5h"           ($t.weekly_hours -eq 14.5)             "실제: $($t.weekly_hours)"
Check "수습 6개월/0.8"       ($t.probation.months -eq 6 -and $t.probation.rate -eq 0.8) "실제: $($t.probation | ConvertTo-Json -Compress)"
Check "조항 2건 추출"        ($t.clauses.Count -eq 2)               "실제: $($t.clauses.Count)건"

Write-Host "`n[3/6] POST /analyze/contract (extract 결과를 그대로 — 프론트 흐름 재현)" -ForegroundColor Cyan
$worker = @{ age = 18; employment_status = "working"; employee_count = "unknown";
             contract_type = "written"; is_simple_labor = $true }
$av = Invoke-RestMethod "$BASE/analyze/contract" -Method Post -ContentType "application/json; charset=utf-8" `
      -Body ([Text.Encoding]::UTF8.GetBytes((@{ terms = $t; worker = $worker } | ConvertTo-Json -Depth 6)))
$grades = ($av.violations | ForEach-Object { $_.grade }) -join ","
Check "판정 4건"             ($av.violations.Count -eq 4)           "실제: $($av.violations.Count)건 [$grades]"
# @() 필수: PS5.1에서 단일 매치는 PSCustomObject로 나와 .Count가 빈 값이 된다 (PS6+에서 수정된 동작)
Check "RED 3 + YELLOW 1"     (@($av.violations | Where-Object grade -eq "RED").Count -eq 3 -and
                              @($av.violations | Where-Object grade -eq "YELLOW").Count -eq 1) "실제: [$grades]"
Check "stat_code 4종"        (($av.violations.stat_code | Sort-Object) -join "," -eq "MIN_WAGE,PENALTY,PROBATION,WH_INCLUSION") "실제: $($av.violations.stat_code -join ',')"
Check "legal_basis 전부 존재" (-not ($av.violations | Where-Object { -not $_.legal_basis })) "null 있음"

Write-Host "`n[4/6] POST /analyze/worklogs (4주 축소 패턴 + 시효)" -ForegroundColor Cyan
$logs = @()
$weeks = @( @("2026-07-06","2026-07-07","2026-07-09","2026-07-11"),  # 각 주 화목토 근무 가정
            @("2026-07-13","2026-07-14","2026-07-16","2026-07-18"),
            @("2026-07-20","2026-07-21","2026-07-23","2026-07-25"),
            @("2026-07-27","2026-07-28","2026-07-30","2026-08-01") )
foreach ($w in $weeks) { foreach ($d in $w[1..3]) {   # 주 3일 근무
    $logs += @{ work_date = $d; planned_start = "17:00"; planned_end = "22:00";
                actual_start = "17:00"; actual_end = "22:56"; break_minutes = 30; is_retroactive = $false } } }
# 실근로 5.43h*3일 ≈ 주 16.3h (계약 14.5h와 대비 → 축소 패턴 발화)
$wl = @{
  terms = @{ hourly_wage = 9500; weekly_hours = 14.5 }
  worklogs = $logs
  payments = @(@{ period_start="2026-06-01"; period_end="2026-06-30"; pay_date="2026-07-10";
                  paid_amount=590000; known_deductions=$null })
  has_overtime = $null
  as_of = "2026-08-05"
}
$an = Invoke-RestMethod "$BASE/analyze/worklogs" -Method Post -ContentType "application/json; charset=utf-8" `
      -Body ([Text.Encoding]::UTF8.GetBytes(($wl | ConvertTo-Json -Depth 6)))
Check "축소 패턴 YELLOW"     ($an.reduction_pattern.detected -and $an.reduction_pattern.grade -eq "YELLOW") ($an.reduction_pattern | ConvertTo-Json -Compress)
Check "체불 총액 > 0"        ($an.unpaid.total -gt 0)               "실제: $($an.unpaid.total)"
Check "시효 claimable"       ($an.statute.items[0].status -eq "claimable") ($an.statute.items[0] | ConvertTo-Json -Compress)
Check "days_left = 1070"     ($an.statute.items[0].days_left -eq 1070) "실제: $($an.statute.items[0].days_left)"

Write-Host "`n[5/6] POST /petition/generate → PDF 저장" -ForegroundColor Cyan
$pt = @{
  petitioner = @{ name="김지원"; birth_date="2008-03-15"; phone=$null; address=$null }
  respondent = @{ workplace_name="OO편의점 OO점"; owner_name="박OO"; workplace_address=$null }
  employment = @{ start_date="2026-02-01"; end_date=$null; job="편의점 판매" }
  claim = @{ violations_summary=@("최저임금 미달","위약금 예정 조항","주휴수당 미지급")
             unpaid_total=$an.unpaid.total
             detail_rows=@(@{ item="주휴수당"; period="2026.07"; amount=$an.unpaid.weekly_holiday }) }
}
$pd = Invoke-RestMethod "$BASE/petition/generate" -Method Post -ContentType "application/json; charset=utf-8" `
      -Body ([Text.Encoding]::UTF8.GetBytes(($pt | ConvertTo-Json -Depth 5)))
# 절대경로 필수: [IO.File]은 .NET CWD 기준이라 PS 위치와 다를 수 있다
$pdfPath = Join-Path (Get-Location) "smoke_petition.pdf"
[IO.File]::WriteAllBytes($pdfPath, [Convert]::FromBase64String($pd.pdf_base64))
Check "PDF 생성"             (Test-Path $pdfPath)                   "파일 없음"

Write-Host "`n[6/6] 에러 경로 — 필수 필드 누락 시 400 INVALID_INPUT" -ForegroundColor Cyan
# 엔진의 검증 실패 응답은 400 (422는 EXTRACTION_FAILED 전용) — API_SPEC 공통 에러 형식
try {
    Invoke-RestMethod "$BASE/analyze/contract" -Method Post -ContentType "application/json" -Body '{"terms":{}}' | Out-Null
    Check "400 반환" $false "에러 없이 통과됨"
} catch {
    Check "400 반환" ($_.Exception.Response.StatusCode.value__ -eq 400) "실제: $($_.Exception.Response.StatusCode.value__)"
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " 결과: $pass PASS / $fail FAIL" -ForegroundColor $(if ($fail -eq 0) {"Green"} else {"Red"})
if ($fail -eq 0) { Write-Host " 전 시나리오 통과 — smoke_petition.pdf 열어서 한글 확인으로 마무리" }
Write-Host "========================================`n"
start smoke_petition.pdf
