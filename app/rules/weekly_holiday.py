"""주휴수당 시급 포함 조항 규칙 — rules/ 판정 계층. 순수 결정론, AI 금지."""

import re

from app.schemas import Terms, Violation, Worker

_INCLUSION_RE = re.compile(r"주휴\s*수당?.{0,20}포함|포괄\s*임금")


def check(terms: Terms, worker: Worker) -> tuple[list[Violation], list[str]]:
    """"주휴수당은 시급에 포함" 조항 판정 (근로기준법 제55조).

    포함 약정 자체가 곧 위법은 아니고 실지급액이 법정 기준을 충족하는지 계산해봐야
    결론이 나는 사안이라, 확정(RED)이 아닌 검토 필요(YELLOW)로 낸다.
    매칭은 type_hint("weekly_holiday_inclusion") 또는 원문 정규식 OR.
    """
    violations = []
    for clause in terms.clauses:
        if clause.type_hint == "weekly_holiday_inclusion" or _INCLUSION_RE.search(clause.text):
            violations.append(
                Violation(
                    rule_id="weekly_holiday",
                    grade="YELLOW",
                    title="주휴수당 시급 포함 조항",
                    detail=(
                        "주휴수당이 시급에 포함된 것으로 정한 조항입니다. "
                        "실제 지급액이 법정 기준을 충족하는지 검토가 필요합니다."
                    ),
                    legal_basis="근로기준법 제55조",
                    clause_id=clause.id,
                    stat_code="WH_INCLUSION",
                )
            )
    return violations, []
