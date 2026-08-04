"""판정 규칙 실행기 — 순수 파이썬 결정론, 판정에 AI 금지 (CLAUDE.md 불변 규칙 1).

freelance는 전체 판정 YELLOW 강등 + 근로자성 notes ("모르면 확정하지 않는다").
"""

from app.rules import minimum_wage, penalty_clause, probation, weekly_holiday
from app.schemas import AnalyzeContractResponse, Terms, Worker

_RULES = (minimum_wage.check, penalty_clause.check, weekly_holiday.check, probation.check)


def run_contract_rules(terms: Terms, worker: Worker) -> AnalyzeContractResponse:
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
