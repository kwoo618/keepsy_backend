"""Keepsy 판정 엔진 — 앱 조립(라우터 5개 엔드포인트), CORS, 공통 에러 핸들러, GET /health.

이 파일엔 판정 로직이 없다 — 라우팅과 횡단 관심사만 ("판단은 코드"의 코드는 rules/·services/).
"""

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import contract, petition, worklogs

app = FastAPI(title="Keepsy 판정 엔진")

_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(contract.router)
app.include_router(worklogs.router)
app.include_router(petition.router)


@app.exception_handler(RequestValidationError)
async def invalid_input_handler(request: Request, exc: RequestValidationError):
    """Pydantic 검증 실패를 FastAPI 기본 422 대신 공통 에러 형식 INVALID_INPUT(400)으로 변환."""
    # 공통 에러 형식 (불변 규칙 6)
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "INVALID_INPUT", "message": "요청 본문이 API 명세와 다릅니다."}},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
