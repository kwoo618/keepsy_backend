"""위약금·손해배상 예정 조항 규칙 — 순수 결정론 (AI 금지)."""

import re

from app.schemas import Terms, Violation, Worker

_PENALTY_RE = re.compile(r"위약금|손해\s*배상|배상액|변상|배상한다")


def check(terms: Terms, worker: Worker) -> tuple[list[Violation], list[str]]:
    violations = []
    for clause in terms.clauses:
        if clause.type_hint == "penalty" or _PENALTY_RE.search(clause.text):
            violations.append(
                Violation(
                    rule_id="penalty_clause",
                    grade="RED",
                    title="위약금·손해배상 예정 조항",
                    detail="근로계약 불이행에 대한 위약금 또는 손해배상액을 미리 정하는 조항은 금지됩니다.",
                    legal_basis="근로기준법 제20조",
                    clause_id=clause.id,
                    stat_code="PENALTY",
                )
            )
    return violations, []
