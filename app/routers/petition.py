"""POST /petition/generate — 진정서 초안 PDF (고정 문형 조립만)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas import PetitionRequest, PetitionResponse
from app.services import pdf

router = APIRouter()


@router.post("/petition/generate", response_model=PetitionResponse)
def generate(req: PetitionRequest):
    """진정서 초안 PDF (API_SPEC §5). 응답은 pdf_base64 — RN이 파일 저장·공유 처리.

    렌더링 예외는 원인 불문 PDF_GENERATION_FAILED(500)로 수렴 (프론트 재시도 버튼 UX).
    claim에 청구 가능분만 담는 것은 프론트 책임 — 엔진은 받은 값을 조립만 한다.
    """
    try:
        pdf_base64 = pdf.render_petition(req)
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "PDF_GENERATION_FAILED", "message": "진정서 렌더링에 실패했습니다."}},
        )
    return PetitionResponse(pdf_base64=pdf_base64)
