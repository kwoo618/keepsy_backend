# CLAUDE.md — Keepsy 판정 엔진

> 작업 전 이 파일 전체와 `docs/API_SPEC.md`를 읽는다. 이전 세션 기억·구버전 사양(이모지 등급, "꺾기", 챗봇, CRUD 엔드포인트)과 충돌하면 **이 파일과 API_SPEC이 이긴다.**

## 개요

Keepsy: 청소년 알바생 노동권익 보호 앱 (GEEKs 해커톤). 이 리포는 **판정 엔진** — FastAPI 무상태 계산 서버. DB 없음, JSON in/out. 팀: 백엔드 1(오너=사용자), 프론트 2(**React Native 앱** — 웹 아님, 쿠키·CORS 전제 코드 불필요), 기획 1.

## 아키텍처 경계 — "기록은 Supabase, 판단은 엔진"

- 엔진 엔드포인트는 정확히 5개: `GET /health`, `POST /contract/extract`, `POST /analyze/contract`, `POST /analyze/worklogs`, `POST /petition/generate`. **이 외 추가 금지** — CRUD·인증(`/auth/*`)·챗봇(`/petition/chat`)은 존재하지 않는 기능이다.
- CRUD는 프론트↔Supabase 직접. 판정 캐시(contracts.verdict)도 프론트가 저장 — 엔진은 캐시하지 않고 매 호출 전체 재계산.
- 로그인은 Supabase Auth 카카오 프로바이더(최후순위) — 엔진과 무관.
- Supabase 스키마 SQL은 요청 시 **텍스트로만 출력** (실행은 오너).
- 이 리포 밖 수정 금지. API_SPEC의 필드명·구조 임의 변경 금지 — 변경 필요 시 제안만 출력하고 멈춘다.

## 스택 (고정 — 대체 제안 금지)

Python 3.12 / FastAPI / Pydantic v2 / google-genai / WeasyPrint / pytest
배포: Ubuntu VPS 베어메탈 + Caddy + systemd 유닛 (Docker 미사용 — 오너 확정).

## 데이터 규약

- 필드명 **snake_case** (Supabase 컬럼과 1:1). 날짜 `"YYYY-MM-DD"`, 시각 `"HH:MM"` — KST 문자열, timezone 객체로 파싱·저장 금지. `as_of`도 문자열.
- 계약서 이미지는 `image_base64` 수신 — Storage 접근 금지. 백도어 `raw_text`.
- 상세 요청/응답 스키마는 `docs/API_SPEC.md`가 유일한 원본 — schemas.py는 그것의 Pydantic 번역이다.

## 파일 구조 (벗어나는 파일 생성 금지)

```
app/
├── main.py              # 앱, CORS, GET /health
├── schemas.py           # API_SPEC의 Pydantic 번역 (snake_case)
├── constants.py         # 법령 상수
├── routers/             # contract.py, worklogs.py, petition.py
├── rules/               # base.py + minimum_wage, penalty_clause, weekly_holiday, probation
├── services/            # gemini.py, statute.py, patterns.py, pdf.py
└── templates/petition.html
tests/test_e2e.py
fixtures/sample_contract.txt, seed_worklogs.json, expected_verdict.json
```

## 불변 규칙 (위반 시 출력 폐기)

1. **판정에 AI 금지.** rules/·statute.py·patterns.py는 순수 파이썬 결정론. Gemini는 추출·진정서 조립만.
2. **등급 3단계** `"RED"`/`"YELLOW"`/`"INFO"`, 이모지 금지. 정보 불충분(시급 null, 직종 미상, 공제 미상, freelance)이면 RED 대신 **YELLOW 강등** + notes에 사유. "모르면 확정하지 않는다."
3. **법령 수치 임의 기입 금지.** constants.py에서만 읽는다. 없는 값은 `# TODO(owner): 값 확인 필요` + 상수 이름만 추가 후 보고. 그럴듯한 값을 채우는 것이 최악의 실패.
4. **시효는 지급기별** `pay_date + 3년` → claimable/expired 분리 + nearest_expiry_days. 퇴사일 단일 기준 금지.
5. **비밀키 금지.** env 이름만: `GEMINI_API_KEY`, `ALLOWED_ORIGINS`, `AS_OF_OVERRIDE`.
6. **에러 공통 형식** `{"error":{"code","message"}}` — EXTRACTION_FAILED / INVALID_INPUT / AI_TIMEOUT / PDF_GENERATION_FAILED. Gemini 타임아웃 15초.
7. **진정서는 고정 문형 조립만.** 자유 서술·즉석 법조문 생성 금지. null 필드는 빈칸. 응답은 `pdf_base64`.
8. **사용자 문구는 엔진이 만들지 않는다.** 판정 코드·등급·숫자만 반환, 화면 문구는 프론트.

## 판정 사양 요약 (상세는 API_SPEC §3·§4)

- 용어: "꺾기" → **근로시간 축소 패턴** (`reduction_pattern`). 기존 kkeokki 식별자는 치환.
- minimum_wage: 시급 < 10,320 → RED. **시급 null → 최저임금 기준 비교, 미달 YELLOW.**
- penalty_clause: 위약금·손배 예정 → RED (근기법 20조).
- weekly_holiday: "시급 포함" 조항 → YELLOW.
- probation: 기본 체크(1년 이상·3개월·90%). `is_simple_labor=true` → 감액 자체 RED / `null` → 위반 시 YELLOW.
- freelance → 전체 YELLOW + 근로자성 notes.
- reduction_pattern: 계약 주간 < 15h 이고 4주 평균 실근로 ≥ 15h → YELLOW.
- **repeated_deviation** (신규): planned_end 대비 actual_end 편차 동일 방향·유사 범위 4회 이상 → INFO (위반 확정 아님). planned가 없으면 감지 생략.
- 체불액: 최저임금 미달분 + 주휴수당. has_overtime=true면 가산분 분리, 아니면 assumptions에 스코프 고지. 공제 미상이면 공제 전 기준 미달만 RED.

## 검증 하네스 (완료의 정의)

- `fixtures/sample_contract.txt` + `expected_verdict.json` = 그라운드 트루스: **정확히 4건** — RED(최저임금·위약금·수습) + YELLOW(주휴 포함).
- `seed_worklogs.json`: 알바 2개 — job1(편의점, 계약 14.5h/실제 4주 평균 16.2h → reduction_pattern) + job2(카페, hourly_wage null → YELLOW 경로). statute 전부 claimable.
- 모든 작업 후 `pytest -q` 직접 실행·보고. 통과 전 "완료" 금지. WeasyPrint는 한글(Noto Sans CJK KR) 렌더링 확인까지.

## 작업 방식

- **한 번에 한 단계.** 오너 지정 단계만, 선제 구현 금지. 완료 보고 3줄: 변경 파일 / pytest 결과 / 완료 기준 충족.
- 리팩토링·추상화·기능 추가 제안 금지. 돌아가는 단순한 코드가 정답.
- 오너 "동결" 선언 후 버그픽스 diff만.

## constants.py

- `MINIMUM_WAGE_2026 = 10320` (확정 — 고용노동부 고시)
- 그 외(주휴 15h·개근, 수습 3개월·90%, 시효 3년)는 오너 검증 값만 — 미검증이면 규칙 3.
