"""진정서 PDF 렌더링 — 고정 문형 조립만 (불변 규칙 7). 자유 서술·즉석 법조문 생성 금지.

null 필드는 빈칸으로 출력한다 ("본인 작성 보조" 구조).
"""

import base64
import html
from pathlib import Path
from string import Template

from app.schemas import PetitionRequest

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "petition.html"


def _blank(value) -> str:
    return "" if value is None else html.escape(str(value))


def render_petition(req: PetitionRequest) -> str:
    """PetitionRequest → 진정서 PDF base64 문자열.

    고정 문형 템플릿(templates/petition.html)에 값 치환만 한다 — 자유 서술과
    즉석 법조문 생성 금지 (불변 규칙 7). null은 빈칸으로 렌더링해 사용자가
    검토 화면에서 직접 채우는 "본인 작성 보조" 구조를 지킨다.
    사용자 입력은 전부 html.escape 후 삽입(마크업 주입 방지).
    string.Template을 쓰는 이유: str.format은 CSS 중괄호와 충돌하기 때문.
    """
    from weasyprint import HTML  # 지연 임포트 — Pango가 있는 배포 환경에서만 로드

    violations_list = "".join(
        f"<li>{html.escape(v)}</li>" for v in req.claim.violations_summary
    )
    detail_rows = "".join(
        f"<tr><td>{html.escape(r.item)}</td><td>{html.escape(r.period)}</td>"
        f"<td class='amount'>{r.amount:,}원</td></tr>"
        for r in req.claim.detail_rows
    )

    page = Template(_TEMPLATE_PATH.read_text(encoding="utf-8")).substitute(
        petitioner_name=_blank(req.petitioner.name),
        petitioner_birth=_blank(req.petitioner.birth_date),
        petitioner_phone=_blank(req.petitioner.phone),
        petitioner_address=_blank(req.petitioner.address),
        respondent_workplace=_blank(req.respondent.workplace_name),
        respondent_owner=_blank(req.respondent.owner_name),
        respondent_address=_blank(req.respondent.workplace_address),
        employment_start=_blank(req.employment.start_date),
        employment_end=_blank(req.employment.end_date),
        employment_job=_blank(req.employment.job),
        violations_list=violations_list,
        detail_rows=detail_rows,
        unpaid_total=f"{req.claim.unpaid_total:,}",
    )
    return base64.b64encode(HTML(string=page).write_pdf()).decode()
