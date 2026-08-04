"""판정 규칙 실행기 — 순수 파이썬 결정론, 판정에 AI 금지 (CLAUDE.md 불변 규칙 1).

freelance는 전체 판정 YELLOW 강등 + 근로자성 notes ("모르면 확정하지 않는다").
"""

from app.rules import minimum_wage, penalty_clause, probation, weekly_holiday
from app.schemas import AnalyzeContractResponse, Terms, Worker

_RULES = (minimum_wage.check, penalty_clause.check, weekly_holiday.check, probation.check)


def run_contract_rules(terms: Terms, worker: Worker) -> AnalyzeContractResponse:
    """규칙 4개(minimum_wage → penalty → weekly_holiday → probation)를 실행해 합친다.

    공통 후처리 두 가지:
    - employee_count=unknown → 가산수당 판정을 내지 않았음을 notes로 고지
      (5인 미만 여부를 모르면 가산수당 규칙 자체를 만들지 않는 스코프 결정)
    - contract_type=freelance → RED 전부 YELLOW 강등 + 근로자성 안내.
      형식이 프리랜서라도 실질은 근로자일 수 있으나 그 사실 판단은 엔진 밖의
      일이므로, 확정 대신 검토 필요로 낮춰서 낸다.
    """
    violations = []
    notes = []
    for check in _RULES:
        rule_violations, rule_notes = check(terms, worker)
        violations.extend(rule_violations)
        notes.extend(rule_notes)

    if worker.employee_count == "unknown":
        notes.append("직원 수 미상: 가산수당 관련 판정은 표시하지 않았습니다.")

    if worker.contract_type == "freelance":
        for violation in violations:
            if violation.grade == "RED":
                violation.grade = "YELLOW"
        notes.append(
            "프리랜서 계약: 실질적인 근로자성이 인정되면 노동관계법이 적용될 수 있습니다 — "
            "전체 판정을 검토 필요(YELLOW)로 표시했습니다."
        )

    return AnalyzeContractResponse(violations=violations, notes=notes)
