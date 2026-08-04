"""POST /petition/generate — 진정서 초안 PDF (고정 문형 조립만)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.schemas import PetitionRequest, PetitionResponse
from app.services import pdf

router = APIRouter()


@router.post("/petition/generate", response_model=PetitionResponse)
def generate(req: PetitionRequest):
    try:
        pdf_base64 = pdf.render_petition(req)
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "PDF_GENERATION_FAILED", "message": "진정서 렌더링에 실패했습니다."}},
        )
    return PetitionResponse(pdf_base64=pdf_base64)
