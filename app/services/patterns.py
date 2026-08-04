"""근무기록 패턴 분석 — 순수 결정론 (AI 금지).

- 근로시간 축소 패턴(reduction_pattern): 계약 주간 < 15h 이고 4주 평균 실근로 ≥ 15h
- 반복 이탈(repeated_deviation): planned_end 대비 actual_end 편차 동일 방향·유사 범위 4회 이상 → INFO
- 체불액(unpaid): 최저임금 미달분 + 주휴수당 추정
날짜·시각은 KST 문자열로 받고, 산술에만 datetime.date를 쓴다 (timezone 객체 금지).
"""

from collections import defaultdict
from datetime import date, timedelta

from app import constants
from app.schemas import (
    AnalyzeWorklogsRequest,
    ReductionPattern,
    RepeatedDeviation,
    Terms,
    Unpaid,
    Worklog,
)

# 반복 이탈의 "유사 범위" 판정 폭(분) — 법령 수치 아님, 감지 휴리스틱
DEVIATION_SIMILAR_BAND_MINUTES = 30


def _parse_date(value: str) -> date:
    year, month, day = map(int, value.split("-"))
    return date(year, month, day)


def _parse_minutes(hhmm: str) -> int:
    hours, minutes = map(int, hhmm.split(":"))
    return hours * 60 + minutes


def _actual_minutes(log: Worklog) -> int:
    if not log.actual_start or not log.actual_end:
        return 0
    start = _parse_minutes(log.actual_start)
    end = _parse_minutes(log.actual_end)
    if end < start:  # 자정 넘김
        end += 24 * 60
    return max(0, end - start - log.break_minutes)


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # 월요일 시작 주


def _weekly_minutes(worklogs: list[Worklog]) -> dict[date, int]:
    totals: dict[date, int] = defaultdict(int)
    for log in worklogs:
        totals[_week_start(_parse_date(log.work_date))] += _actual_minutes(log)
    return totals


def _applicable_wage(terms: Terms) -> int:
    if terms.hourly_wage is None:
        return constants.MINIMUM_WAGE_2026
    return max(terms.hourly_wage, constants.MINIMUM_WAGE_2026)


def _weekly_holiday_pay(weekly_minutes: dict[date, int], weeks: list[date], wage: int) -> int:
    """주 실근로 15h 이상인 주에 대해 (주간시간/40)×8×시급 추정 합계."""
    total = 0.0
    for week in weeks:
        hours = weekly_minutes.get(week, 0) / 60
        if hours >= constants.WEEKLY_HOLIDAY_MIN_WEEKLY_HOURS:
            total += min(hours, 40) / 40 * 8 * wage
    return int(round(total))


def detect_reduction(terms: Terms, worklogs: list[Worklog], as_of: str) -> ReductionPattern:
    weekly = _weekly_minutes(worklogs)
    current_week = _week_start(_parse_date(as_of))
    window = [current_week - timedelta(weeks=k) for k in range(4, 0, -1)]  # as_of 직전 완결 4주
    avg_hours = round(sum(weekly.get(w, 0) for w in window) / 4 / 60, 2)

    contracted = terms.weekly_hours
    detected = (
        contracted is not None
        and contracted < constants.WEEKLY_HOLIDAY_MIN_WEEKLY_HOURS
        and avg_hours >= constants.WEEKLY_HOLIDAY_MIN_WEEKLY_HOURS
    )
    return ReductionPattern(
        detected=detected,
        grade="YELLOW" if detected else None,
        contracted_weekly=contracted,
        avg_actual_weekly=avg_hours,
        estimated_weekly_holiday_pay=(
            _weekly_holiday_pay(weekly, window, _applicable_wage(terms)) if detected else None
        ),
    )


def detect_repeated_deviation(worklogs: list[Worklog]) -> RepeatedDeviation:
    deviations = []
    for log in worklogs:
        if not log.planned_end or not log.actual_end:
            continue  # planned가 없으면 감지 생략
        deviations.append(_parse_minutes(log.actual_end) - _parse_minutes(log.planned_end))

    best: tuple[int, str] | None = None
    for direction, name in (
        ([d for d in deviations if d < 0], "early_end"),
        ([d for d in deviations if d > 0], "late_end"),
    ):
        if (
            len(direction) >= constants.REPEATED_DEVIATION_MIN_COUNT
            and max(direction) - min(direction) <= DEVIATION_SIMILAR_BAND_MINUTES
            and (best is None or len(direction) > best[0])
        ):
            best = (len(direction), name)

    if best is None:
        return RepeatedDeviation(detected=False, grade=None, count=None, direction=None)
    return RepeatedDeviation(detected=True, grade="INFO", count=best[0], direction=best[1])


def build_unpaid(req: AnalyzeWorklogsRequest) -> Unpaid:
    terms = req.terms
    assumptions = []
    weekly = _weekly_minutes(req.worklogs)
    total_minutes = sum(weekly.values())

    overtime_minutes = 0
    if req.has_overtime and req.overtime:
        overtime_minutes = int(req.overtime.hours * 60)
        assumptions.append(
            f"초과근무 {req.overtime.hours}시간·가산 {req.overtime.pay:,}원은 최저임금 비교에서 분리했습니다."
        )
    else:
        assumptions.append("소정근로시간 기준 계산 (초과근무 미반영 고지)")
    base_minutes = max(0, total_minutes - overtime_minutes)

    wage = terms.hourly_wage
    minimum = constants.MINIMUM_WAGE_2026
    if wage is not None:
        gap = 0
        if wage < minimum:
            # 합의 시급으로 지급됐다는 가정하에 최저임금과의 차액 × 실근로시간
            gap = int(round((minimum - wage) * base_minutes / 60))
            assumptions.append(f"적용 시급 {minimum:,}원 (2026년 최저임금)")
            assumptions.append("합의 시급대로 지급되었다는 가정의 미달분입니다.")
    else:
        # 합의 시급 미확인 — 지급기별로 (기간 내 실근로 × 최저임금) 대비 지급액 부족분만 산출
        assumptions.append(f"적용 시급 {minimum:,}원 (2026년 최저임금)")
        assumptions.append("합의 시급 미확인 — 최저임금 기준으로만 산출했습니다.")
        gap = 0
        for payment in req.payments:
            period_minutes = sum(
                _actual_minutes(log)
                for log in req.worklogs
                if payment.period_start <= log.work_date <= payment.period_end
            )
            paid = payment.paid_amount + (payment.known_deductions or 0)
            gap += max(0, int(round(period_minutes / 60 * minimum)) - paid)

    if any(p.known_deductions is None for p in req.payments):
        assumptions.append("공제 내역 미확인 — 공제 전 기준 미달만 확정 표시")

    weekly_holiday = _weekly_holiday_pay(weekly, list(weekly.keys()), _applicable_wage(terms))
    if weekly_holiday > 0:
        assumptions.append("주휴수당이 별도 지급되지 않았다는 가정의 추정액입니다.")

    return Unpaid(
        minimum_wage_gap=gap,
        weekly_holiday=weekly_holiday,
        total=gap + weekly_holiday,
        assumptions=assumptions,
    )
