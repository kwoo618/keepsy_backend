"""Gemini 호출 — 계약서 추출 전용. 판정에는 절대 사용하지 않는다 (CLAUDE.md 불변 규칙 1).

추출 결과는 _normalize_terms()의 결정론 후처리를 거친다 — 오추출(rate 80.0 등) 정규화 및
상식 범위 검증. 범위 이탈은 EXTRACTION_FAILED (그럴듯한 값을 넘기지 않는다).
"""

import base64
import json
import logging
import os
import re
import time

import httpx

from app.schemas import ExtractRequest, ExtractResponse, Terms

# 경량 모델 별칭 — thinking 미사용 계열이라 15초 데드라인에 안전, latest 별칭이라 버전 폐기 회피
MODEL = "gemini-flash-lite-latest"
TIMEOUT_MS = 15_000  # 불변 규칙 6: Gemini 타임아웃 15초

_log = logging.getLogger("keepsy.gemini")


class ExtractionFailed(Exception):
    pass


class AiTimeout(Exception):
    pass


_PROMPT = """당신은 아르바이트 근로계약서에서 계약 조건을 추출한다.
입력이 이미지라면: 인쇄된 계약서를 휴대폰으로 촬영한 사진이며 기울어짐·그림자·부분 흐림이
있을 수 있다. 읽어낼 수 있는 것만 추출하라.

절대 규칙: 계약서에서 찾을 수 없거나 판독이 불확실한 항목은 반드시 null.
추측하거나 일반적인 값으로 채우지 마라.

필드 정의와 예시:
- hourly_wage: 시급, 원 단위 정수. 예: "시급: 9,500원" → 9500
- weekly_hours: 주 소정근로시간, 시간 단위(소수 허용). 예: "주 소정근로시간 14.5시간" → 14.5
- work_days: 근무 요일 배열. 예: "매주 화·목·토요일" → ["화", "목", "토"]
- start_time / end_time: 근무 시작·종료 시각 "HH:MM" 24시간제. 예: "오후 5시 ~ 10시" → "17:00" / "22:00"
- break_minutes: 휴게시간, 분 단위 정수. 예: "휴게시간 30분" → 30
- probation: 수습 조건. rate는 0~1 비율. 예: "수습 6개월간 시급의 80% 지급" → {"months": 6, "rate": 0.8}
- contract_period_months: 계약 기간, 개월 수 정수. 예: "2026년 2월 1일부터 2027년 1월 31일까지 (12개월)" → 12
- workplace_name: 사업장(가게) 이름. 예: "사업주(갑): OO편의점 문래점 대표 박OO" → "OO편의점 문래점"
- owner_name: 사업주(대표자) 이름. 예: 위 문장에서 → "박OO"
- contract_start_date / contract_end_date: 계약 시작·종료일 "YYYY-MM-DD". 예: "2026년 2월 1일부터" → "2026-02-01"
- clauses: 문제 소지가 있는 조항의 원문 (위약금/손해배상 예정, 주휴수당 시급 포함 등).
  id는 c1, c2 … 순번. type_hint는 penalty | weekly_holiday_inclusion | other 중 하나.
  예: "퇴사 시 위약금 20만원을 배상한다" → {"id": "c1", "text": "(조항 원문 그대로)", "type_hint": "penalty"}

아래 스키마의 JSON만 출력하라 (설명·마크다운 금지):
{"hourly_wage": int|null, "weekly_hours": number|null, "work_days": [string]|null,
 "start_time": "HH:MM"|null, "end_time": "HH:MM"|null, "break_minutes": int|null,
 "probation": {"months": int|null, "rate": number|null}|null,
 "contract_period_months": int|null,
 "workplace_name": string|null, "owner_name": string|null,
 "contract_start_date": "YYYY-MM-DD"|null, "contract_end_date": "YYYY-MM-DD"|null,
 "clauses": [{"id": string, "text": string, "type_hint": string}]}
"""

# ── 추출 후처리: 상식 범위 (법령 수치 아님 — 오추출 방어용) ──────
_WAGE_MIN, _WAGE_MAX = 1_000, 100_000
_WEEKLY_HOURS_MAX = 80
_BREAK_MINUTES_MAX = 480
_PROBATION_MONTHS_MAX = 24
_CONTRACT_MONTHS_MAX = 120
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _range_fail(field: str, value) -> None:
    _log.warning("추출값 상식 범위 이탈 — %s=%r → EXTRACTION_FAILED", field, value)
    raise ExtractionFailed()


def _normalize_terms(terms: Terms) -> Terms:
    """결정론 정규화 + 상식 범위 검증 — 모델 출력은 신뢰하지 않는다.

    rate > 1 → ÷100: 계약서의 "80%"를 80.0으로 옮겨 적는 오추출이 실측됐고,
    유효 비율(0~1]과 백분율 표기(1~100]는 구간이 겹치지 않아 ÷100이 안전한
    결정론 변환이다. ÷100 후에도 1을 넘으면 해석 불가로 실패시킨다.
    범위 상수들은 법령 수치가 아닌 오추출 방어용 상식 한계라 constants.py가 아닌
    이 모듈에 둔다. 이탈 시 그럴듯한 값을 판정에 넘기는 대신 EXTRACTION_FAILED —
    "그럴듯한 값을 채우는 것이 최악의 실패" 원칙의 추출 버전.
    """
    probation = terms.probation
    if probation is not None and probation.rate is not None:
        if probation.rate > 1:  # "80%"를 80.0으로 오추출한 사례 → 비율로 정규화
            probation.rate = probation.rate / 100
        if not 0 < probation.rate <= 1:
            _range_fail("probation.rate", probation.rate)
    if probation is not None and probation.months is not None:
        if not 0 <= probation.months <= _PROBATION_MONTHS_MAX:
            _range_fail("probation.months", probation.months)
    if terms.hourly_wage is not None and not _WAGE_MIN <= terms.hourly_wage <= _WAGE_MAX:
        _range_fail("hourly_wage", terms.hourly_wage)
    if terms.weekly_hours is not None and not 0 < terms.weekly_hours <= _WEEKLY_HOURS_MAX:
        _range_fail("weekly_hours", terms.weekly_hours)
    if terms.break_minutes is not None and not 0 <= terms.break_minutes <= _BREAK_MINUTES_MAX:
        _range_fail("break_minutes", terms.break_minutes)
    if terms.contract_period_months is not None and not 0 < terms.contract_period_months <= _CONTRACT_MONTHS_MAX:
        _range_fail("contract_period_months", terms.contract_period_months)
    for field in ("start_time", "end_time"):
        value = getattr(terms, field)
        if value is not None and not _TIME_RE.match(value):
            _range_fail(field, value)
    # 판정 무관 참고 필드의 날짜는 실패 대신 null 강등 — 핵심 추출을 살리는 소프트 처리
    for field in ("contract_start_date", "contract_end_date"):
        value = getattr(terms, field)
        if value is not None and not _DATE_RE.match(value):
            _log.warning("참고 필드 형식 이탈 — %s=%r → null 처리", field, value)
            setattr(terms, field, None)
    return terms


# ── 에러 분류 ─────────────────────────────────────────────────────


def _is_deadline_exceeded(exc: Exception) -> bool:
    return getattr(exc, "code", None) == 504 or "DEADLINE_EXCEEDED" in str(exc)


def _is_quota_exceeded(exc: Exception) -> bool:
    return getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc)


def _thinking_config_unsupported(exc: Exception) -> bool:
    text = str(exc)
    return getattr(exc, "code", None) == 400 or "INVALID_ARGUMENT" in text or "thinking" in text.lower()


def _image_mime(data: bytes) -> str:
    return "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"


def _strip_code_fence(text: str) -> str:
    """모델이 JSON을 ```json … ``` 로 감싸 보낸 경우 펜스를 벗긴다."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rstrip()
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


# ── 호출 ─────────────────────────────────────────────────────────


def _timed_call(client, contents, config):
    started = time.monotonic()
    result = client.models.generate_content(model=MODEL, contents=contents, config=config)
    usage = getattr(result, "usage_metadata", None)
    thoughts = getattr(usage, "thoughts_token_count", None) if usage else None
    # thinking 토큰이 0/None이면 thinking 비활성이 실제 적용된 것 — 지연 검증용 로그
    _log.info("Gemini 응답 %.1fs / model=%s / thinking 토큰=%s", time.monotonic() - started, MODEL, thoughts)
    return result


def _generate(client, types, contents, config, quota_retry_left: int = 1):
    """generate_content 래퍼 — 자동 복구 두 가지만 담당하고 나머지 예외는 위로 올린다.

    1) thinking_budget=0을 거부하는 모델 → 기본 설정으로 1회 전환 (즉시 400이라 지연 없음)
    2) 429 쿼터 → 1초 대기 후 1회 재시도 (일시 쿼터와 진짜 실패를 구분)
    분류(504→AI_TIMEOUT 등)는 extract_terms 쪽 책임 — 여기서 하지 않는다.
    """
    try:
        return _timed_call(client, contents, config)
    except Exception as exc:
        if config.thinking_config is not None and _thinking_config_unsupported(exc):
            _log.info("thinking_budget=0 미지원 — 기본 설정으로 전환: %r", exc)
            fallback = types.GenerateContentConfig(response_mime_type="application/json", temperature=0)
            return _generate(client, types, contents, fallback, quota_retry_left)
        if _is_quota_exceeded(exc) and quota_retry_left > 0:
            _log.warning("Gemini 429 쿼터 초과 — 1초 대기 후 1회 재시도")
            time.sleep(1)
            return _generate(client, types, contents, config, quota_retry_left - 1)
        raise


def extract_terms(req: ExtractRequest) -> ExtractResponse:
    """계약서 이미지/텍스트 → 구조화 Terms. AI의 역할은 여기서 끝난다 — 판정은 순수 코드.

    흐름: Gemini JSON 모드 호출(thinking 비활성) → 코드펜스 제거 → 스키마 검증 →
    결정론 정규화(_normalize_terms) → confidence 산정.
    오류 매핑: 클라이언트/서버(504) 타임아웃 → AiTimeout / API 오류·파싱 실패·
    범위 이탈·429 재시도 소진 → ExtractionFailed. 라우터가 공통 에러 형식으로 변환.
    confidence: 핵심 4필드(시급·주간시간·시작·종료) 중 하나라도 null이면 "low" —
    프론트가 검토 화면을 강조하는 신호로 쓴다.
    """
    from google import genai  # 지연 임포트 — 판정 경로가 AI 의존성을 갖지 않게 한다
    from google.genai import types

    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(timeout=TIMEOUT_MS),
    )
    contents: list = [_PROMPT]
    if req.raw_text:  # 백도어 — 이미지 없이 텍스트 직접 입력
        contents.append("계약서 텍스트:\n" + req.raw_text)
    else:
        image = base64.b64decode(req.image_base64)
        contents.append(types.Part.from_bytes(data=image, mime_type=_image_mime(image)))

    initial_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0,
        thinking_config=types.ThinkingConfig(thinking_budget=0),  # 추출엔 추론 불필요
    )
    try:
        result = _generate(client, types, contents, initial_config)
        terms = _normalize_terms(
            Terms.model_validate(json.loads(_strip_code_fence(result.text or "")))
        )
    except (AiTimeout, ExtractionFailed):
        raise
    except httpx.TimeoutException as exc:
        _log.warning("Gemini 클라이언트 타임아웃(%sms)", TIMEOUT_MS)
        raise AiTimeout() from exc
    except Exception as exc:  # API 오류·파싱 실패·필드 불일치 포함
        if _is_deadline_exceeded(exc):  # 서버 측 504도 타임아웃으로 분류
            _log.warning("Gemini 서버 데드라인 초과(%sms)", TIMEOUT_MS)
            raise AiTimeout() from exc
        if _is_quota_exceeded(exc):
            _log.warning("Gemini 429 쿼터 초과 지속 — EXTRACTION_FAILED 처리")
        else:
            _log.warning("Gemini 추출 실패 — 원인: %r", exc)
        raise ExtractionFailed() from exc

    core_fields = (terms.hourly_wage, terms.weekly_hours, terms.start_time, terms.end_time)
    confidence = "low" if any(field is None for field in core_fields) else "high"
    return ExtractResponse(terms=terms, confidence=confidence)
