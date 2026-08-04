"""Keepsy 판정 엔진 — FastAPI 앱, CORS, GET /health."""

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
    # 공통 에러 형식 (불변 규칙 6)
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "INVALID_INPUT", "message": "요청 본문이 API 명세와 다릅니다."}},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
