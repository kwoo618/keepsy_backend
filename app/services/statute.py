"""소멸시효 계산 — 순수 결정론 (AI 금지).

시효는 지급기별 pay_date + 3년 → as_of 기준 claimable/expired 분리 (퇴사일 단일 기준 금지).
체불 총액은 지급기별 산출 근거가 없는 경우 균등 분배한다 (단순 배분 — assumptions에 고지됨).
"""

from datetime import date

from app import constants
from app.schemas import Payment, Statute, StatuteItem


def _parse_date(value: str) -> date:
    year, month, day = map(int, value.split("-"))
    return date(year, month, day)


def _add_years(d: date, years: int) -> date:
    try:
        return date(d.year + years, d.month, d.day)
    except ValueError:  # 2/29 → 2/28
        return date(d.year + years, d.month, 28)


def build_statute(payments: list[Payment], unpaid_total: int, as_of: str) -> Statute:
    if not payments:
        return Statute(claimable_total=0, expired_total=0, items=[], nearest_expiry_days=None)

    as_of_date = _parse_date(as_of)
    ordered = sorted(payments, key=lambda p: p.pay_date)
    base = unpaid_total // len(ordered)
    amounts = [base] * len(ordered)
    amounts[-1] += unpaid_total - base * len(ordered)

    items = []
    claimable_total = 0
    expired_total = 0
    nearest: int | None = None
    for payment, amount in zip(ordered, amounts):
        expires = _add_years(_parse_date(payment.pay_date), constants.WAGE_STATUTE_YEARS)
        days_left = (expires - as_of_date).days
        status = "claimable" if days_left >= 0 else "expired"
        if status == "claimable":
            claimable_total += amount
            nearest = days_left if nearest is None or days_left < nearest else nearest
        else:
            expired_total += amount
        items.append(
            StatuteItem(
                pay_date=payment.pay_date,
                amount=amount,
                expires_on=expires.isoformat(),
                days_left=days_left,
                status=status,
            )
        )

    return Statute(
        claimable_total=claimable_total,
        expired_total=expired_total,
        items=items,
        nearest_expiry_days=nearest,
    )
