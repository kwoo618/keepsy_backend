"""법령 상수 — 판정 규칙이 수치를 읽는 유일한 원본 (CLAUDE.md 불변 규칙 3).

모든 값은 오너 문서(CLAUDE.md·docs/API_SPEC.md)에 명시된 수치만 옮긴다 — 임의 기입 금지.
"""

# 2026년 최저임금 (확정 — 고용노동부 고시)
MINIMUM_WAGE_2026 = 10320

# 주휴수당 발생 최소 주 소정근로시간 (CLAUDE.md·API_SPEC §4 명시: 15h)
WEEKLY_HOLIDAY_MIN_WEEKLY_HOURS = 15

# 수습 감액 허용 요건 (CLAUDE.md 판정 사양: 계약 1년 이상 · 수습 3개월 이내 · 시급의 90% 이상)
PROBATION_MAX_MONTHS = 3
PROBATION_MIN_WAGE_RATE = 0.9
PROBATION_MIN_CONTRACT_MONTHS = 12

# 임금채권 소멸시효(년) — 지급기(pay_date)별 개별 계산 (API_SPEC §4: pay_date + 3년)
WAGE_STATUTE_YEARS = 3

# 반복 이탈(repeated_deviation) 감지 최소 횟수 (API_SPEC §4: 4회 이상)
REPEATED_DEVIATION_MIN_COUNT = 4
