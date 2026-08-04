"""수습 감액 규칙 — 순수 결정론 (AI 금지).

- is_simple_labor=true  → 기간·비율과 무관하게 감액 자체 RED
- 기본 체크(감액 허용 요건): 계약 1년 이상 · 수습 3개월 이내 · 시급의 90% 이상
- is_simple_labor=null  → 기본 체크 위반 시 YELLOW + notes ("모르면 확정하지 않는다")
- is_simple_labor=false → 기본 체크 위반 시 RED
"""

from app import constants
from app.schemas import Terms, Violation, Worker


def check(terms: Terms, worker: Worker) -> tuple[list[Violation], list[str]]:
    """수습 감액 판정 (최저임금법 제5조). 분기 순서:

    1) 감액 없음(probation 없음·rate null·rate ≥ 1) → 판정 대상 아님
    2) is_simple_labor=true → 요건 검사 없이 감액 자체 RED
       (단순노무 종사자는 수습 감액 허용 예외가 적용되지 않으므로)
    3) 기본 체크 — 감액이 허용되려면 세 요건 전부 충족: 계약 1년 이상 ·
       수습 3개월 이내 · 시급의 90% 이상 (수치는 constants.py).
       contract_period_months가 null(무기계약·기간 미상)이면 "1년 미만" 위반으로
       세지 않는다 — 기간의 정함이 없는 계약은 1년 이상 요건을 배제할 근거가 없고,
       미상 정보로 위반을 확정하지 않는 원칙("모르면 확정하지 않는다") 때문.
    4) 기본 체크 위반 시 등급: is_simple_labor=false(확인됨) → RED /
       null(미확인) → YELLOW + notes — 단순노무 여부에 따라 결론이 뒤집힐 수 있어서.
    """
    p = terms.probation
    if p is None or p.rate is None or p.rate >= 1.0:
        return [], []  # 감액 없음

    if worker.is_simple_labor is True:
        return [
            Violation(
                rule_id="probation",
                grade="RED",
                title="수습 감액 불가 (단순노무)",
                detail="단순노무 종사자는 수습 기간·비율과 무관하게 최저임금 감액이 허용되지 않습니다.",
                legal_basis="최저임금법 제5조",
                clause_id=None,
                stat_code="PROBATION",
            )
        ], []

    violates = (
        (p.months is not None and p.months > constants.PROBATION_MAX_MONTHS)
        or p.rate < constants.PROBATION_MIN_WAGE_RATE
        or (
            terms.contract_period_months is not None
            and terms.contract_period_months < constants.PROBATION_MIN_CONTRACT_MONTHS
        )
    )
    if not violates:
        return [], []

    detail = (
        f"수습 감액 허용 요건(계약 {constants.PROBATION_MIN_CONTRACT_MONTHS}개월 이상 · "
        f"수습 {constants.PROBATION_MAX_MONTHS}개월 이내 · "
        f"시급의 {int(constants.PROBATION_MIN_WAGE_RATE * 100)}% 이상)을 벗어난 감액입니다."
    )
    if worker.is_simple_labor is None:
        return [
            Violation(
                rule_id="probation",
                grade="YELLOW",
                title="수습 감액 요건 위반 의심",
                detail=detail,
                legal_basis="최저임금법 제5조",
                clause_id=None,
                stat_code="PROBATION",
            )
        ], ["단순노무 종사 여부 미확인 — 확인되면 수습 판정 등급이 달라질 수 있습니다."]
    return [
        Violation(
            rule_id="probation",
            grade="RED",
            title="수습 감액 요건 위반",
            detail=detail,
            legal_basis="최저임금법 제5조",
            clause_id=None,
            stat_code="PROBATION",
        )
    ], []
