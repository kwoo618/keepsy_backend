"""위약금·손해배상 예정 조항 규칙 — rules/ 판정 계층. 순수 결정론, AI 금지."""

import re

from app.schemas import Terms, Violation, Worker

_PENALTY_RE = re.compile(r"위약금|손해\s*배상|배상액|변상|배상한다")


def check(terms: Terms, worker: Worker) -> tuple[list[Violation], list[str]]:
    """위약금·손해배상 예정 조항 판정 (근로기준법 제20조 — "예정" 자체가 금지라 즉시 RED).

    AI 추출의 type_hint("penalty")와 조항 원문 키워드 정규식을 OR로 매칭 —
    추출이 type_hint를 놓쳐도 원문으로 잡기 위한 이중 장치. 매칭 조항마다
    clause_id를 연결한 RED violation을 낸다 (프론트가 원문 하이라이트에 사용).
    """
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
