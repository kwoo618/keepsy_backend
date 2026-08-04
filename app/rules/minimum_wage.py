"""최저임금 규칙 — rules/ 판정 계층. 순수 결정론, AI 금지 ("판단은 코드").

수치는 constants.py에서만 읽는다. /analyze/contract에서 base.run_contract_rules가 호출.
"""

from app import constants
from app.schemas import Terms, Violation, Worker


def check(terms: Terms, worker: Worker) -> tuple[list[Violation], list[str]]:
    """최저임금 판정 (최저임금법 제6조). 입력: 확정 terms·worker → (violations, notes).

    - hourly_wage < 최저임금 → RED (확정 위반)
    - hourly_wage == null → 위반을 단정할 수 없으므로 violation 없이 notes만 남긴다.
      실제 미달분 산출은 /analyze/worklogs가 최저임금 기준으로 수행
      ("모르면 확정하지 않는다" — 정보 부족 시 RED를 만들지 않는 설계).
    """
    wage = terms.hourly_wage
    if wage is None:
        # 합의 시급 미확인 — 확정하지 않는다. 미달분 산출은 /analyze/worklogs에서 최저임금 기준으로만.
        return [], ["합의 시급 미확인 — 최저임금 기준으로만 비교했습니다."]
    if wage < constants.MINIMUM_WAGE_2026:
        return [
            Violation(
                rule_id="minimum_wage",
                grade="RED",
                title="최저임금 미달",
                detail=(
                    f"계약 시급 {wage:,}원은 2026년 최저임금 "
                    f"{constants.MINIMUM_WAGE_2026:,}원에 미달합니다."
                ),
                legal_basis="최저임금법 제6조",
                clause_id=None,
                stat_code="MIN_WAGE",
            )
        ], []
    return [], []
