# Keepsy API 명세서

> 판정 엔진(FastAPI)의 유일한 계약 문서. 프론트와 백엔드는 이 문서 기준으로만 통신한다.
> 리포 `docs/API_SPEC.md`로 배치 — Claude Code가 참조하는 원본.

## 0. 공통 규약

- Base URL: `https://165-140-22-175.nip.io` (Caddy HTTPS)
- `Content-Type: application/json` (petition 응답 제외)
- **필드명 snake_case** — Supabase 컬럼명과 1:1, 프론트는 select 결과를 그대로 전달
- **날짜 `"YYYY-MM-DD"` / 시각 `"HH:MM"`** — KST 문자열, timezone 객체 금지
- 금액: 원 단위 정수 / 시간: 시간 단위 소수 허용
- 판정 등급 enum: `"RED"`(확정위반) / `"YELLOW"`(검토필요) / `"INFO"`(정보안내)
- 프론트는 **React Native 앱** — 계약서 촬영 이미지는 base64 인코딩 전 **긴 변 1500px 내외로 리사이즈** 권장 (추출 품질 충분, 전송 시간 단축). 엔진은 HTTPS 필수(Android/iOS 평문 차단)
- CRUD(알바·기록·급여·증거·캘린더·인증)는 엔진에 없다 — 프론트↔Supabase 직접 (§6)

**공통 에러 형식**
```json
{ "error": { "code": "EXTRACTION_FAILED", "message": "조항을 추출하지 못했습니다. 직접 입력해 주세요." } }
```
| 코드 | 상황 | 프론트 동작 (합의) |
| --- | --- | --- |
| EXTRACTION_FAILED | AI 추출 실패 | 텍스트 직접 입력 화면 유도 |
| AI_TIMEOUT | Gemini 15초 초과 | 텍스트 직접 입력 화면 유도 |
| INVALID_INPUT | 요청 검증 실패 | 해당 폼 복귀 + 안내 |
| PDF_GENERATION_FAILED | 진정서 렌더링 실패 | 재시도 버튼 |

---

## 1. `GET /health`

응답 `200`: `{ "status": "ok" }` — 배포·연결 확인용. 프론트(RN 앱)·서버 연결 테스트의 시작점.

---

## 2. `POST /contract/extract` — 계약서 → 구조화 조건 (AI: 추출만)

**Request** (둘 중 하나 필수)
```json
{
  "image_base64": "...",
  "raw_text": "..."
}
```

**Response 200**
```json
{
  "terms": {
    "hourly_wage": 9500,
    "weekly_hours": 14.5,
    "work_days": ["화", "목", "토"],
    "start_time": "17:00",
    "end_time": "22:00",
    "break_minutes": 30,
    "probation": { "months": 6, "rate": 0.8 },
    "contract_period_months": 12,
    "clauses": [
      { "id": "c1", "text": "계약 기간 중 퇴사 시 위약금 200,000원을 배상한다", "type_hint": "penalty" },
      { "id": "c2", "text": "주휴수당은 시급에 포함된 것으로 본다", "type_hint": "weekly_holiday_inclusion" }
    ]
  },
  "confidence": "high"
}
```
- 없는 항목은 `null`. `confidence: "low"`면 프론트가 검토 화면 강조
- 응답은 **반드시 검토·수정 화면을 거친 뒤** 확정 — 수정본이 이후 판정 입력. 계약서 없음(수동 입력) 경로는 이 API를 건너뛰고 같은 `terms` 스키마를 프론트가 직접 구성 (`hourly_wage: null` 허용, `clauses: []`)

---

## 3. `POST /analyze/contract` — 위법 판정 (AI 미사용, 결정론)

**Request**
```json
{
  "terms": { "...": "extract 응답의 terms, 사용자 수정 반영본" },
  "worker": {
    "age": 18,
    "employment_status": "working",
    "employee_count": "unknown",
    "contract_type": "written",
    "is_simple_labor": true
  }
}
```
- `employment_status`: `working | quit` / `employee_count`: `5plus | under5 | unknown`
- `contract_type`: `written | none | freelance | unknown` / `is_simple_labor`: `true | false | null`

**Response 200**
```json
{
  "violations": [
    {
      "rule_id": "minimum_wage",
      "grade": "RED",
      "title": "최저임금 미달",
      "detail": "계약 시급 9,500원은 2026년 최저임금 10,320원에 미달합니다.",
      "legal_basis": "최저임금법 제6조",
      "clause_id": null,
      "stat_code": "MIN_WAGE"
    }
  ],
  "notes": ["직원 수 미상: 가산수당 관련 판정은 표시하지 않았습니다."]
}
```

**판정 규칙 (엔진 내부 동작 명세)**
| 조건 | 결과 |
| --- | --- |
| `hourly_wage < 10320` | RED (최저임금법 6조) |
| `hourly_wage == null` (수동 등록·시급 미입력) | 최저임금 기준으로만 비교, 미달 시 **YELLOW** + notes("합의 시급 미확인") |
| 위약금·손배 예정 조항 | RED (근기법 20조) |
| "주휴수당 시급 포함" 조항 | YELLOW |
| 수습 위반 + `is_simple_labor=true` | 기간·비율 무관 감액 자체 **RED** |
| 수습 위반 + `is_simple_labor=null` | 기본 체크(1년 이상·3개월·90%)만, 위반 시 YELLOW + notes |
| `contract_type="freelance"` | 전체 판정 YELLOW 강등 + notes(근로자성 안내) |

---

## 4. `POST /analyze/worklogs` — 패턴 + 체불액 + 시효 (AI 미사용)

**Request**
```json
{
  "terms": { "hourly_wage": 9500, "weekly_hours": 14.5 },
  "worklogs": [
    {
      "work_date": "2026-07-21",
      "planned_start": "17:00", "planned_end": "22:00",
      "actual_start": "17:00", "actual_end": "21:40",
      "break_minutes": 30,
      "is_retroactive": false
    }
  ],
  "payments": [
    {
      "period_start": "2026-06-01", "period_end": "2026-06-30",
      "pay_date": "2026-07-10", "paid_amount": 590000,
      "known_deductions": null
    }
  ],
  "has_overtime": null,
  "as_of": "2026-08-05"
}
```
- `worklogs`는 프론트가 Supabase에서 select한 **최신 전체 기록** — 캐시 없음, 수정·삭제 즉시 반영은 이 구조가 보장
- `planned_*`는 calendar_events에서 조인해 전달 (반복 이탈 감지용, 없으면 null → 해당 감지 생략)
- `has_overtime: true`면 요청에 `overtime: {hours, pay}` 추가 — 최저임금 비교에서 분리. null/false면 assumptions에 스코프 고지 포함

**Response 200**
```json
{
  "reduction_pattern": {
    "detected": true,
    "grade": "YELLOW",
    "contracted_weekly": 14.5,
    "avg_actual_weekly": 16.2,
    "estimated_weekly_holiday_pay": 133560
  },
  "repeated_deviation": {
    "detected": true,
    "grade": "INFO",
    "count": 4,
    "direction": "early_end"
  },
  "unpaid": {
    "minimum_wage_gap": 53136,
    "weekly_holiday": 133560,
    "total": 186696,
    "assumptions": [
      "적용 시급 10,320원 (2026년 최저임금)",
      "공제 내역 미확인 — 공제 전 기준 미달만 확정 표시",
      "소정근로시간 기준 계산 (초과근무 미반영 고지)"
    ]
  },
  "statute": {
    "claimable_total": 186696,
    "expired_total": 0,
    "items": [
      { "pay_date": "2026-07-10", "amount": 186696, "expires_on": "2029-07-10",
        "days_left": 1069, "status": "claimable" }
    ],
    "nearest_expiry_days": 1069
  }
}
```

**계산 명세**
- 주 단위 집계: work_date 기준 월요일 시작 주로 그룹핑, 최근 4주 평균
- `reduction_pattern`: 계약 weekly_hours < 15 이고 4주 평균 실근로 ≥ 15 → detected
- `repeated_deviation`: planned_end 대비 actual_end 편차가 동일 방향·유사 범위로 **4회 이상** → detected. grade는 항상 INFO (법 위반 확정 아님)
- 시효: payments의 `pay_date + 3년` 지급기별 개별 계산, `as_of` 기준 claimable/expired 분리
- `terms.hourly_wage == null`: 최저임금 기준으로만 미달분 산출, assumptions에 명시

---

## 5. `POST /petition/generate` — 진정서 초안 PDF (AI: 고정 문형 조립만)

**Request**
```json
{
  "petitioner": { "name": "김지원", "birth_date": "2008-03-15", "phone": null, "address": null },
  "respondent": { "workplace_name": "OO편의점 OO점", "owner_name": "박OO", "workplace_address": null },
  "employment": { "start_date": "2026-02-01", "end_date": null, "job": "편의점 판매" },
  "claim": {
    "violations_summary": ["최저임금 미달", "위약금 예정 조항", "주휴수당 미지급"],
    "unpaid_total": 186696,
    "detail_rows": [
      { "item": "주휴수당", "period": "2026.06", "amount": 133560 }
    ]
  }
}
```

**Response 200**
```json
{ "pdf_base64": "..." }
```
- 응답 형식은 **pdf_base64로 확정** (RN 프론트: base64 → 파일 저장 → 공유 시트 표시. expo-file-system + expo-sharing 또는 react-native-share)
- `null` 필드는 PDF에 빈칸 출력 — 검토 화면에서 사용자가 직접 기입 ("본인 작성 보조" 구조)
- claim에는 **청구 가능분(claimable)만** 전달 — 소멸분 제외는 프론트 책임
- 법조문 인용·서술은 사전 검증된 고정 문형만. 챗봇 엔드포인트(`/petition/chat`)는 존재하지 않음

---

## 6. Supabase 직접 처리 (참고 — 엔진 개발 대상 아님)

| 데이터 작업 | 방식 |
| --- | --- |
| 온보딩 답변 | `profiles` insert |
| 알바 CRUD | `jobs` (삭제 = deleted_at 소프트 삭제, 조회는 공용 함수로 `deleted_at is null` 필터) |
| 캘린더 | `calendar_events` — 계약 확정 시 프론트가 3개월치 전개 bulk insert, "이 날짜만 예외"는 행 수정 + override |
| 근무기록·급여 | `worklogs`·`payments` CRUD (하드 삭제) |
| 증거 사진 | Storage `{user_id}/{job_id}/{uuid}` + `evidence` 테이블 |
| 판정 캐시 | `contracts.verdict`(jsonb)에 프론트가 저장, 계약 갱신 시에만 재판정 호출 |
| 로그인 | **Supabase Auth 카카오 프로바이더 (팀 확정)** — 최후순위, 그 전까지 익명 인증. 카카오 콘솔 Redirect URI에 `https://<project-ref>.supabase.co/auth/v1/callback` 등록 필수 |

접근 제어: 전 테이블 RLS(`auth.uid() = user_id`, 하위 테이블은 jobs 조인 정책).

---

## 7. 엔진 호출 시점 (합의 A-4)

| 장면 | 호출 | 캐시 |
| --- | --- | --- |
| 계약 확정 시 | /analyze/contract 1회 | 결과를 contracts.verdict에 저장 |
| 정산 화면 진입 시마다 | /analyze/worklogs | 없음 — 매번 최신 기록 전체 전달 |
| 진정서 "PDF 만들기" 클릭 | /petition/generate | 없음 |
