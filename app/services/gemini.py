"""Gemini 호출 — 계약서 추출 전용. 판정에는 절대 사용하지 않는다 (CLAUDE.md 불변 규칙 1)."""

import base64
import json
import logging
import os

import httpx

from app.schemas import ExtractRequest, ExtractResponse, Terms

# 특정 버전은 폐기될 수 있어(gemini-2.5-flash 404 사례) 최신 flash 공식 별칭을 사용
MODEL = "gemini-flash-latest"
TIMEOUT_MS = 15_000  # 불변 규칙 6: Gemini 타임아웃 15초

_log = logging.getLogger("keepsy.gemini")


class ExtractionFailed(Exception):
    pass


class AiTimeout(Exception):
    pass


_PROMPT = """다음 아르바이트 근로계약서에서 계약 조건을 추출하라.
- 계약서에 없는 항목은 null
- 시각은 "HH:MM", 금액은 원 단위 정수, 시간은 소수 허용
- clauses에는 위약금/손해배상 예정, 주휴수당 시급 포함 등 문제 소지가 있는 조항의 원문을 담고, id는 c1, c2 … 순번
- type_hint는 penalty | weekly_holiday_inclusion | other 중 하나
아래 스키마의 JSON만 출력하라:
{"hourly_wage": int|null, "weekly_hours": number|null, "work_days": [string]|null,
 "start_time": "HH:MM"|null, "end_time": "HH:MM"|null, "break_minutes": int|null,
 "probation": {"months": int|null, "rate": number|null}|null,
 "contract_period_months": int|null,
 "clauses": [{"id": string, "text": string, "type_hint": string}]}
"""


def _image_mime(data: bytes) -> str:
    return "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"


def _is_deadline_exceeded(exc: Exception) -> bool:
    return getattr(exc, "code", None) == 504 or "DEADLINE_EXCEEDED" in str(exc)


def _thinking_config_unsupported(exc: Exception) -> bool:
    text = str(exc)
    return getattr(exc, "code", None) == 400 or "INVALID_ARGUMENT" in text or "thinking" in text.lower()


def _strip_code_fence(text: str) -> str:
    """모델이 JSON을 ```json … ``` 로 감싸 보낸 경우 펜스를 벗긴다."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rstrip()
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def extract_terms(req: ExtractRequest) -> ExtractResponse:
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

    base_config = {"response_mime_type": "application/json", "temperature": 0}
    try:
        try:
            # 추출은 추론이 불필요 — thinking을 꺼서 15초 데드라인 안에 응답하게 한다
            result = client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    **base_config,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
        except Exception as exc:
            if not _thinking_config_unsupported(exc):
                raise
            _log.info("thinking_budget=0 미지원 모델 — 기본 설정으로 재시도: %r", exc)
            result = client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(**base_config),
            )
        terms = Terms.model_validate(json.loads(_strip_code_fence(result.text or "")))
    except httpx.TimeoutException as exc:
        _log.warning("Gemini 클라이언트 타임아웃(%sms)", TIMEOUT_MS)
        raise AiTimeout() from exc
    except Exception as exc:  # API 오류·파싱 실패·필드 불일치 포함
        if _is_deadline_exceeded(exc):  # 서버 측 504도 타임아웃으로 분류
            _log.warning("Gemini 서버 데드라인 초과(%sms)", TIMEOUT_MS)
            raise AiTimeout() from exc
        _log.warning("Gemini 추출 실패 — 원인: %r", exc)
        raise ExtractionFailed() from exc

    core_fields = (terms.hourly_wage, terms.weekly_hours, terms.start_time, terms.end_time)
    confidence = "low" if any(field is None for field in core_fields) else "high"
    return ExtractResponse(terms=terms, confidence=confidence)
