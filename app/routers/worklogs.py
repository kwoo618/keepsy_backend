"""POST /analyze/worklogs — 패턴 + 체불액 + 시효 (AI 미사용, 결정론).

캐시 없음 — 매 호출 전달받은 전체 기록으로 재계산.
"""

import os

from fastapi import APIRouter

from app.schemas import AnalyzeWorklogsRequest, AnalyzeWorklogsResponse
from app.services import patterns, statute

router = APIRouter()


@router.post("/analyze/worklogs", response_model=AnalyzeWorklogsResponse)
def analyze_worklogs(req: AnalyzeWorklogsRequest) -> AnalyzeWorklogsResponse:
    as_of = os.getenv("AS_OF_OVERRIDE") or req.as_of
    unpaid = patterns.build_unpaid(req)
    return AnalyzeWorklogsResponse(
        reduction_pattern=patterns.detect_reduction(req.terms, req.worklogs, as_of),
        repeated_deviation=patterns.detect_repeated_deviation(req.worklogs),
        unpaid=unpaid,
        statute=statute.build_statute(req.payments, unpaid.total, as_of),
    )
