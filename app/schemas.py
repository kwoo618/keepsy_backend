"""docs/API_SPEC.md의 Pydantic 번역 — 필드명 snake_case, Supabase 컬럼과 1:1.

날짜 "YYYY-MM-DD" / 시각 "HH:MM"은 전부 KST 문자열(str) — timezone 객체로 파싱·저장하지 않는다.
"""

from typing import Literal

from pydantic import BaseModel

Grade = Literal["RED", "YELLOW", "INFO"]

# ── §0 공통 에러 형식 ─────────────────────────────────────────────


class ErrorBody(BaseModel):
    code: Literal["EXTRACTION_FAILED", "AI_TIMEOUT", "INVALID_INPUT", "PDF_GENERATION_FAILED"]
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# ── §2 POST /contract/extract ────────────────────────────────────


class ExtractRequest(BaseModel):
    """image_base64 / raw_text 둘 중 하나 필수 (검증은 라우터에서 INVALID_INPUT 처리)."""

    image_base64: str | None = None
    raw_text: str | None = None


class Probation(BaseModel):
    months: int | None = None
    rate: float | None = None


class Clause(BaseModel):
    id: str
    text: str
    type_hint: str | None = None


class Terms(BaseModel):
    """extract 응답이자 이후 모든 판정의 입력 (사용자 검토·수정 반영본). 없는 항목은 null."""

    hourly_wage: int | None = None
    weekly_hours: float | None = None
    work_days: list[str] | None = None
    start_time: str | None = None
    end_time: str | None = None
    break_minutes: int | None = None
    probation: Probation | None = None
    contract_period_months: int | None = None
    # 판정 무관 참고 필드 (진정서 프리필용) — rules는 읽지 않는다
    workplace_name: str | None = None
    owner_name: str | None = None
    contract_start_date: str | None = None  # "YYYY-MM-DD"
    contract_end_date: str | None = None  # "YYYY-MM-DD"
    clauses: list[Clause] = []


class ExtractResponse(BaseModel):
    terms: Terms
    confidence: Literal["high", "low"]


# ── §3 POST /analyze/contract ────────────────────────────────────


class Worker(BaseModel):
    """판정 맥락 정보 — 등급 분기·강등(YELLOW)의 입력. unknown/null 값은 "확정하지 않음" 신호."""

    age: int | None = None
    employment_status: Literal["working", "quit"]
    employee_count: Literal["5plus", "under5", "unknown"]
    contract_type: Literal["written", "none", "freelance", "unknown"]
    is_simple_labor: bool | None = None


class AnalyzeContractRequest(BaseModel):
    terms: Terms
    worker: Worker


class Violation(BaseModel):
    rule_id: str
    grade: Grade
    title: str
    detail: str
    legal_basis: str | None = None
    clause_id: str | None = None
    stat_code: str | None = None


class AnalyzeContractResponse(BaseModel):
    violations: list[Violation] = []
    notes: list[str] = []


# ── §4 POST /analyze/worklogs ────────────────────────────────────


class Worklog(BaseModel):
    work_date: str
    planned_start: str | None = None
    planned_end: str | None = None
    actual_start: str | None = None
    actual_end: str | None = None
    break_minutes: int = 0
    is_retroactive: bool = False


class Payment(BaseModel):
    period_start: str
    period_end: str
    pay_date: str
    paid_amount: int
    known_deductions: int | None = None


class Overtime(BaseModel):
    hours: float
    pay: int


class AnalyzeWorklogsRequest(BaseModel):
    terms: Terms
    worklogs: list[Worklog] = []
    payments: list[Payment] = []
    has_overtime: bool | None = None
    overtime: Overtime | None = None  # has_overtime=true일 때만 전달
    as_of: str


class ReductionPattern(BaseModel):
    detected: bool
    grade: Grade | None = None
    contracted_weekly: float | None = None
    avg_actual_weekly: float | None = None
    estimated_weekly_holiday_pay: int | None = None


class RepeatedDeviation(BaseModel):
    detected: bool
    grade: Grade | None = None  # detected면 항상 "INFO" (위반 확정 아님)
    count: int | None = None
    direction: str | None = None  # API_SPEC 예시: "early_end"


class Unpaid(BaseModel):
    minimum_wage_gap: int
    weekly_holiday: int
    total: int
    assumptions: list[str] = []


class StatuteItem(BaseModel):
    pay_date: str
    amount: int
    expires_on: str
    days_left: int
    status: Literal["claimable", "expired"]


class Statute(BaseModel):
    claimable_total: int
    expired_total: int
    items: list[StatuteItem] = []
    nearest_expiry_days: int | None = None


class AnalyzeWorklogsResponse(BaseModel):
    reduction_pattern: ReductionPattern
    repeated_deviation: RepeatedDeviation
    unpaid: Unpaid
    statute: Statute


# ── §5 POST /petition/generate ───────────────────────────────────
# null 필드는 PDF에 빈칸 출력 — 대부분 nullable


class Petitioner(BaseModel):
    name: str | None = None
    birth_date: str | None = None
    phone: str | None = None
    address: str | None = None


class Respondent(BaseModel):
    workplace_name: str | None = None
    owner_name: str | None = None
    workplace_address: str | None = None


class Employment(BaseModel):
    start_date: str | None = None
    end_date: str | None = None
    job: str | None = None


class DetailRow(BaseModel):
    item: str
    period: str
    amount: int


class Claim(BaseModel):
    violations_summary: list[str] = []
    unpaid_total: int = 0
    detail_rows: list[DetailRow] = []


class PetitionRequest(BaseModel):
    petitioner: Petitioner
    respondent: Respondent
    employment: Employment
    claim: Claim


class PetitionResponse(BaseModel):
    pdf_base64: str
