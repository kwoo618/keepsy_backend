"""POST /contract/extract (AI: 추출만) · POST /analyze/contract (AI 미사용, 결정론)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.rules.base import run_contract_rules
from app.schemas import (
    AnalyzeContractRequest,
    AnalyzeContractResponse,
    ExtractRequest,
    ExtractResponse,
)
from app.services import gemini

router = APIRouter()


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@router.post("/contract/extract", response_model=ExtractResponse)
def extract(req: ExtractRequest):
    """계약서 → 구조화 terms (API_SPEC §2). image_base64/raw_text 중 하나 필수.

    응답은 반드시 프론트의 검토·수정 화면을 거친 뒤에야 판정 입력으로 쓰인다.
    실패는 공통 에러 형식: INVALID_INPUT(400) / AI_TIMEOUT(504) / EXTRACTION_FAILED(422).
    """
    if not req.image_base64 and not req.raw_text:
        return _error(400, "INVALID_INPUT", "image_base64 또는 raw_text 중 하나가 필요합니다.")
    try:
        return gemini.extract_terms(req)
    except gemini.AiTimeout:
        return _error(504, "AI_TIMEOUT", "추출 시간이 초과되었습니다. 직접 입력해 주세요.")
    except gemini.ExtractionFailed:
        return _error(422, "EXTRACTION_FAILED", "조항을 추출하지 못했습니다. 직접 입력해 주세요.")


@router.post("/analyze/contract", response_model=AnalyzeContractResponse)
def analyze_contract(req: AnalyzeContractRequest) -> AnalyzeContractResponse:
    """확정 terms + worker → 위법 판정 (API_SPEC §3). AI 미개입 — rules/가 전부 담당."""
    return run_contract_rules(req.terms, req.worker)
