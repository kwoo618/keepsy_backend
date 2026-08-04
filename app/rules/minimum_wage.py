"""최저임금 규칙 — 순수 결정론 (AI 금지)."""

from app import constants
from app.schemas import Terms, Violation, Worker


def check(terms: Terms, worker: Worker) -> tuple[list[Violation], list[str]]:
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
