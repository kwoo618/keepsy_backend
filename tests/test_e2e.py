"""E2E — /health, 계약 판정 그라운드 트루스, worklogs 패턴·체불·시효, 에러 형식, 진정서 PDF.

Gemini 추출 테스트는 GEMINI_API_KEY가 있을 때만, PDF 테스트는 WeasyPrint(Pango)가
로드되는 환경(배포 이미지)에서만 실행된다 — 판정 로직 자체는 전부 무조건 검증.
"""

import base64
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import schemas
from app.main import app

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
client = TestClient(app)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False


# ── 기본 ──────────────────────────────────────────────────────────


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_fixtures_validate_against_schemas():
    verdict = _load("expected_verdict.json")
    schemas.AnalyzeContractRequest.model_validate(verdict["request"])
    for job in _load("seed_worklogs.json")["jobs"]:
        schemas.AnalyzeWorklogsRequest.model_validate(job["request"])


# ── /analyze/contract — 그라운드 트루스: 정확히 4건 (RED 3 + YELLOW 1) ──


def test_analyze_contract_matches_expected_verdict():
    data = _load("expected_verdict.json")
    res = client.post("/analyze/contract", json=data["request"])
    assert res.status_code == 200
    violations = res.json()["violations"]
    assert len(violations) == 4
    by_rule = {v["rule_id"]: v for v in violations}
    assert len(by_rule) == 4
    for expected in data["expected_violations"]:
        got = by_rule[expected["rule_id"]]
        for key in ("grade", "clause_id", "stat_code", "legal_basis"):
            assert got[key] == expected[key], (expected["rule_id"], key, got[key])


def test_analyze_contract_freelance_demotes_all_to_yellow():
    data = _load("expected_verdict.json")
    req = json.loads(json.dumps(data["request"]))
    req["worker"]["contract_type"] = "freelance"
    res = client.post("/analyze/contract", json=req)
    assert res.status_code == 200
    body = res.json()
    assert body["violations"] and all(v["grade"] == "YELLOW" for v in body["violations"])
    assert any("근로자성" in n or "프리랜서" in n for n in body["notes"])


# ── /analyze/worklogs — job1: reduction_pattern / job2: 시급 null YELLOW 경로 ──


def test_analyze_worklogs_job1_reduction_pattern():
    job1 = _load("seed_worklogs.json")["jobs"][0]
    res = client.post("/analyze/worklogs", json=job1["request"])
    assert res.status_code == 200
    body = res.json()

    rp = body["reduction_pattern"]
    assert rp["detected"] is True
    assert rp["grade"] == "YELLOW"
    assert rp["contracted_weekly"] == 14.5
    assert rp["avg_actual_weekly"] == 16.2
    assert rp["estimated_weekly_holiday_pay"] > 0

    assert body["repeated_deviation"]["detected"] is False  # planned 없음 → 감지 생략

    unpaid = body["unpaid"]
    assert unpaid["minimum_wage_gap"] == 53136  # (10,320-9,500)원 × 64.8h
    assert unpaid["weekly_holiday"] == rp["estimated_weekly_holiday_pay"]
    assert unpaid["total"] == unpaid["minimum_wage_gap"] + unpaid["weekly_holiday"]

    st = body["statute"]
    assert len(st["items"]) == 1
    item = st["items"][0]
    assert item["status"] == "claimable"
    assert item["expires_on"] == "2029-07-10"  # pay_date 2026-07-10 + 3년
    assert st["claimable_total"] == unpaid["total"]
    assert st["expired_total"] == 0
    assert st["nearest_expiry_days"] == item["days_left"] > 0


def test_analyze_worklogs_job2_null_wage_yellow_path():
    job2 = _load("seed_worklogs.json")["jobs"][1]
    res = client.post("/analyze/worklogs", json=job2["request"])
    assert res.status_code == 200
    body = res.json()

    assert body["reduction_pattern"]["detected"] is False  # 주 9h — 축소 패턴 아님

    unpaid = body["unpaid"]
    # 7월 실근로 27h × 최저임금 10,320원 = 278,640원 − 지급 250,000원
    assert unpaid["minimum_wage_gap"] == 28640
    assert unpaid["weekly_holiday"] == 0
    assert any("시급 미확인" in a for a in unpaid["assumptions"])
    assert any("공제" in a for a in unpaid["assumptions"])

    st = body["statute"]
    assert st["expired_total"] == 0
    assert st["claimable_total"] == unpaid["total"]


def test_analyze_worklogs_repeated_deviation_info():
    # planned_end 22:00 대비 20~30분 조기 종료 4회 — 동일 방향·유사 범위 → INFO
    logs = [
        {"work_date": d, "planned_start": "17:00", "planned_end": "22:00",
         "actual_start": "17:00", "actual_end": e, "break_minutes": 30, "is_retroactive": False}
        for d, e in [("2026-07-07", "21:40"), ("2026-07-14", "21:35"),
                     ("2026-07-21", "21:30"), ("2026-07-28", "21:40")]
    ]
    req = {"terms": {"hourly_wage": 10320, "weekly_hours": 14.5}, "worklogs": logs,
           "payments": [], "has_overtime": None, "as_of": "2026-08-05"}
    res = client.post("/analyze/worklogs", json=req)
    assert res.status_code == 200
    rd = res.json()["repeated_deviation"]
    assert rd["detected"] is True
    assert rd["grade"] == "INFO"
    assert rd["count"] == 4
    assert rd["direction"] == "early_end"


# ── 공통 에러 형식 (불변 규칙 6) ──────────────────────────────────


def test_extract_without_input_returns_invalid_input():
    res = client.post("/contract/extract", json={})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_INPUT"


def test_malformed_body_returns_common_error_shape():
    res = client.post("/analyze/contract", json={"terms": {}})  # worker 누락
    assert res.status_code == 400
    assert res.json() == {"error": {"code": "INVALID_INPUT", "message": "요청 본문이 API 명세와 다릅니다."}}


# ── 조건부: Gemini 추출 / WeasyPrint PDF ─────────────────────────


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="GEMINI_API_KEY 미설정")
def test_contract_extract_sample_text():
    raw = (FIXTURES / "sample_contract.txt").read_text(encoding="utf-8")
    res = client.post("/contract/extract", json={"raw_text": raw})
    assert res.status_code == 200
    body = res.json()
    assert body["terms"]["hourly_wage"] == 9500
    assert body["confidence"] in ("high", "low")


@pytest.mark.skipif(not _weasyprint_available(), reason="WeasyPrint(Pango) 미설치 — 배포 이미지에서 실행")
def test_petition_generate_returns_pdf_base64():
    req = {
        "petitioner": {"name": "김지원", "birth_date": "2008-03-15", "phone": None, "address": None},
        "respondent": {"workplace_name": "OO편의점 OO점", "owner_name": "박OO", "workplace_address": None},
        "employment": {"start_date": "2026-02-01", "end_date": None, "job": "편의점 판매"},
        "claim": {
            "violations_summary": ["최저임금 미달", "위약금 예정 조항", "주휴수당 미지급"],
            "unpaid_total": 186696,
            "detail_rows": [{"item": "주휴수당", "period": "2026.06", "amount": 133560}],
        },
    }
    res = client.post("/petition/generate", json=req)
    assert res.status_code == 200
    pdf_bytes = base64.b64decode(res.json()["pdf_base64"])
    assert pdf_bytes.startswith(b"%PDF")
