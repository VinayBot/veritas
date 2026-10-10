from __future__ import annotations

from conftest import wait_for_document
from httpx import AsyncClient
from sqlalchemy import select

from app.chunking.models import ChunkRow
from app.core.db import session_scope

# Needs to clear MIN_CHUNKS_FOR_TOURNAMENT (3 baseline chunks, i.e. >1,024 tokens at the
# baseline's size=512/overlap=64) with real margin — below that threshold the advisor is a
# deliberate no-op (see app/profiler/service.py), so every test here needs a document that's
# comfortably past it. Measured at ~1,680 tokens / 4 baseline chunks.
_HANDBOOK_SECTIONS = [
    (
        "Vacation Policy",
        "Employees accrue two paid vacation days for every month of continuous service, up to "
        "a maximum of twenty-four days per calendar year. Requests must be submitted through "
        "the HR portal at least two weeks before the intended start date, and a manager must "
        "approve the request before it is considered confirmed. Unused vacation days roll over "
        "into the following year, but the rollover balance is capped at ten days; anything "
        "beyond that cap is forfeited at the end of the calendar year unless local law requires "
        "otherwise. Part-time employees accrue vacation on a pro-rated basis according to their "
        "contracted weekly hours. Employees on an approved leave of absence continue to accrue "
        "vacation at half the normal rate for the duration of the leave, resuming the full rate "
        "immediately upon return. Vacation balances are visible at all times on the HR portal's "
        "dashboard, and employees are encouraged to plan time off well ahead of major holidays "
        "when approval queues tend to fill up quickly across every department.",
    ),
    (
        "Expense Reimbursement",
        "Employees must submit expense reports within thirty days of the original purchase date "
        "to be eligible for reimbursement. Reports that include a single line item over five "
        "hundred dollars require written approval from the employee's manager before the report "
        "can be submitted to finance. All reports must include itemized receipts; credit card "
        "statements alone are not sufficient documentation. International travel expenses must "
        "be converted to the home currency using the exchange rate in effect on the date of "
        "purchase, not the date of submission. Mileage for personal vehicle use is reimbursed "
        "at the standard rate published annually by finance, and parking or toll receipts "
        "should be attached separately rather than bundled into a single scanned image. "
        "Reimbursements are processed in the next regular payroll cycle after approval, and "
        "employees can track the status of a submitted report from the same portal used for "
        "the original submission.",
    ),
    (
        "Remote Work Guidelines",
        "Employees may work remotely for up to three days per week, subject to manager "
        "approval and the needs of their specific team. Equipment requests, including monitors, "
        "keyboards, and docking stations, are submitted through the IT helpdesk portal and "
        "typically ship within five business days. Remote employees are expected to be "
        "reachable during their team's core collaboration hours and to attend any meetings "
        "that are designated as in-person-required at least one week in advance. Home office "
        "stipends of a fixed annual amount are available to any employee who works remotely at "
        "least one day per week on a regular basis, and the stipend can be used for furniture, "
        "lighting, or supplemental internet costs. Teams that are fully distributed, with no "
        "members sharing a primary office, may request an exception to the three-day cap "
        "through their department head.",
    ),
    (
        "Code of Conduct",
        "All employees are expected to treat colleagues, clients, and vendors with respect and "
        "professionalism in every interaction. Harassment, discrimination, and retaliation of "
        "any kind are strictly prohibited and will be investigated promptly by the People team. "
        "Employees who witness or experience a violation of this policy are encouraged to "
        "report it through the confidential ethics hotline, which is staffed by an independent "
        "third party and available around the clock. Conflicts of interest, including "
        "outside employment, significant financial stakes in a vendor or competitor, or close "
        "personal relationships with someone in a reporting line, must be disclosed to HR as "
        "soon as they arise. Retaliation against anyone who files a good-faith report, "
        "including subtle changes in assignments or exclusion from meetings, is itself treated "
        "as a serious violation of this policy.",
    ),
    (
        "Parental Leave",
        "Employees who have completed at least six months of continuous service are eligible "
        "for sixteen weeks of paid parental leave following the birth, adoption, or fostering "
        "of a child. Leave may be taken in a single continuous block or split into two blocks "
        "within the first year, subject to manager approval for the split arrangement. "
        "Employees intending to take parental leave should notify their manager and HR at "
        "least thirty days before the expected start date whenever possible. Health benefits "
        "continue uninterrupted during parental leave at the same cost-sharing arrangement as "
        "active employment, and employees returning from parental leave are guaranteed a role "
        "at the same level and comparable compensation to the one they left. A phased return, "
        "at reduced hours for up to four weeks, is available on request and does not count "
        "against the sixteen weeks of paid leave.",
    ),
    (
        "Performance Reviews",
        "Formal performance reviews are conducted twice a year, in the first weeks of January "
        "and July. Each review includes a self-assessment, a manager assessment, and a "
        "calibration discussion among managers to ensure consistency across teams. Compensation "
        "adjustments tied to performance reviews are communicated no later than four weeks "
        "after the calibration discussion concludes, and employees may request a follow-up "
        "conversation with HR if they have concerns about the outcome. Ratings are assigned on "
        "a five-point scale, and any rating at the bottom two points automatically triggers a "
        "structured improvement plan with explicit milestones reviewed every thirty days. "
        "Peer feedback is collected confidentially from at least three colleagues chosen by the "
        "employee and two chosen by the manager, and is summarized rather than quoted verbatim "
        "in the final written review.",
    ),
    (
        "Equipment and IT Security",
        "Company-issued laptops must have full-disk encryption and the standard endpoint "
        "security agent installed before they leave the IT department, and employees may not "
        "disable either without written approval from security. Lost or stolen devices must be "
        "reported to the IT helpdesk within twenty-four hours so the device can be remotely "
        "locked and wiped. Multi-factor authentication is mandatory for every system that "
        "handles customer data, and shared accounts without individual attribution are not "
        "permitted under any circumstances. Personal devices used to access company email or "
        "chat must be enrolled in the mobile device management program, which enforces a "
        "passcode and remote-wipe capability but does not access personal photos or messages.",
    ),
    (
        "Travel and Safety",
        "Business travel to any location on the company's restricted-travel list requires "
        "pre-approval from both the employee's manager and the security team, regardless of "
        "trip duration. Employees traveling internationally are automatically enrolled in a "
        "travel-tracking service that can locate and assist them in the event of a natural "
        "disaster, civil unrest, or medical emergency. All business travel must be booked "
        "through the approved travel portal so that the company can maintain accurate records "
        "of employee location for safety purposes. Employees are reimbursed for reasonable "
        "incidental expenses while traveling, including a daily meal allowance that varies by "
        "destination city according to a published cost-of-living table.",
    ),
    (
        "Learning and Development",
        "Every employee has an annual learning stipend that can be used for conference "
        "tickets, online courses, certification exams, or job-related books, and unused funds "
        "do not roll over into the following year. Managers set aside time each quarter for a "
        "development conversation that is kept separate from the formal performance review so "
        "that career growth discussions do not get crowded out by rating conversations. "
        "Internal mobility is encouraged, and employees who have been in their current role "
        "for at least a year may apply to posted internal openings without needing their "
        "current manager's prior approval, though the manager is notified once an interview is "
        "scheduled. A mentorship program pairs new hires with a volunteer mentor outside their "
        "immediate team for their first six months.",
    ),
    (
        "Workplace Health and Safety",
        "Every office maintains a stocked first-aid kit and at least two employees trained in "
        "basic first aid and CPR on each floor during business hours. Any workplace injury, "
        "regardless of severity, must be reported to a manager and to facilities within "
        "twenty-four hours so an incident report can be filed. Ergonomic equipment, including "
        "adjustable chairs, standing desks, and monitor arms, is available on request through "
        "facilities at no cost to the employee. Fire drills are conducted twice a year without "
        "advance notice, and floor wardens are responsible for confirming their area is clear "
        "before reporting to the designated assembly point.",
    ),
    (
        "Confidentiality and Data Handling",
        "Employees must not share confidential business information, including unreleased "
        "product plans, financial results, or customer data, outside the company without "
        "explicit written authorization. Customer data accessed for support or analysis "
        "purposes may only be used for the specific purpose it was accessed for and must never "
        "be exported to a personal device or personal cloud storage account. Confidentiality "
        "obligations continue after an employee leaves the company and survive the termination "
        "of employment indefinitely for trade secrets. Any suspected data breach, however "
        "small, must be reported to the security team immediately rather than investigated "
        "informally by the employee who discovered it.",
    ),
]


def _handbook_bytes() -> bytes:
    body = "\n\n".join(f"# {title}\n\n{text}" for title, text in _HANDBOOK_SECTIONS)
    return body.encode("utf-8")


async def _upload_handbook(client: AsyncClient) -> str:
    files = {"file": ("handbook.md", _handbook_bytes(), "text/markdown")}
    resp = await client.post("/api/v1/documents/upload", files=files)
    assert resp.status_code == 200
    document_id = resp.json()["document_id"]
    await wait_for_document(client, document_id)
    return document_id


async def _upload_tiny_doc(client: AsyncClient) -> str:
    """Deliberately below MIN_CHUNKS_FOR_TOURNAMENT, so ingestion does NOT auto-trigger an
    advisor recommendation — for tests of the "no recommendation yet" paths."""
    files = {
        "file": (
            "note.md",
            b"# Note\n\nThe office is closed on public holidays.",
            "text/markdown",
        )
    }
    resp = await client.post("/api/v1/documents/upload", files=files)
    assert resp.status_code == 200
    document_id = resp.json()["document_id"]
    await wait_for_document(client, document_id)
    return document_id


async def _chunk_ids(document_id: str) -> set[str]:
    async with session_scope() as session:
        rows = (
            await session.execute(select(ChunkRow.chunk_id).where(ChunkRow.doc_id == document_id))
        ).all()
    return {r[0] for r in rows}


async def test_profile_endpoint_returns_real_computed_profile(client: AsyncClient) -> None:
    document_id = await _upload_handbook(client)
    resp = await client.get(f"/api/v1/documents/{document_id}/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == document_id
    assert body["tokens"] > 0
    assert body["pages_estimated"] >= 1
    assert 0.0 <= body["heading_density"] <= 1.0
    assert body["document_type"] in (
        "legal",
        "policy",
        "research",
        "faq",
        "manual",
        "web_article",
        "mixed",
    )


async def test_profile_endpoint_404_for_unknown_document(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/documents/does-not-exist/profile")
    assert resp.status_code == 404
    assert resp.json()["code"] == "document_not_found"


async def test_advisor_run_then_get_round_trip(client: AsyncClient) -> None:
    document_id = await _upload_handbook(client)

    run_resp = await client.post(f"/api/v1/documents/{document_id}/advisor/run")
    assert run_resp.status_code == 200
    run_body = run_resp.json()
    assert run_body["document_id"] == document_id
    assert run_body["baseline"]["name"]
    assert run_body["suggested"]["name"]
    assert run_body["rationale"]
    assert run_body["suggested_mode"] in ("graph", "hybrid", "agentic")
    assert run_body["decision"] is None

    get_resp = await client.get(f"/api/v1/documents/{document_id}/advisor")
    assert get_resp.status_code == 200
    assert get_resp.json()["suggested"]["name"] == run_body["suggested"]["name"]


async def test_advisor_run_422_for_a_document_too_small_to_compare(
    client: AsyncClient,
) -> None:
    document_id = await _upload_tiny_doc(client)
    resp = await client.post(f"/api/v1/documents/{document_id}/advisor/run")
    assert resp.status_code == 422
    assert resp.json()["code"] == "advisor_unavailable"


async def test_advisor_get_404_before_any_run(client: AsyncClient) -> None:
    # Tiny doc: ingestion's auto-advisor stage is a deliberate no-op below
    # MIN_CHUNKS_FOR_TOURNAMENT, so there is genuinely no recommendation yet.
    document_id = await _upload_tiny_doc(client)
    resp = await client.get(f"/api/v1/documents/{document_id}/advisor")
    assert resp.status_code == 404
    assert resp.json()["code"] == "no_recommendation"


async def test_advisor_decision_requires_prior_recommendation(client: AsyncClient) -> None:
    document_id = await _upload_tiny_doc(client)
    resp = await client.post(
        f"/api/v1/documents/{document_id}/advisor/decision", json={"decision": "accept"}
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "no_recommendation"


async def test_advisor_decision_rejects_invalid_value(client: AsyncClient) -> None:
    document_id = await _upload_handbook(client)
    await client.post(f"/api/v1/documents/{document_id}/advisor/run")

    resp = await client.post(
        f"/api/v1/documents/{document_id}/advisor/decision", json={"decision": "maybe"}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_decision"


async def test_advisor_decision_ignore_leaves_index_untouched(client: AsyncClient) -> None:
    document_id = await _upload_handbook(client)
    await client.post(f"/api/v1/documents/{document_id}/advisor/run")
    before = await _chunk_ids(document_id)

    resp = await client.post(
        f"/api/v1/documents/{document_id}/advisor/decision", json={"decision": "ignore"}
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "ignore"
    assert await _chunk_ids(document_id) == before


async def test_advisor_decision_accept_reindexes_with_suggested_config(
    client: AsyncClient,
) -> None:
    document_id = await _upload_handbook(client)
    run_resp = await client.post(f"/api/v1/documents/{document_id}/advisor/run")
    suggested_strategy = run_resp.json()["suggested"]["chunking_strategy"]
    chunk_ids_before = await _chunk_ids(document_id)
    assert chunk_ids_before

    resp = await client.post(
        f"/api/v1/documents/{document_id}/advisor/decision", json={"decision": "accept"}
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "accept"

    chunk_ids_after = await _chunk_ids(document_id)
    assert chunk_ids_after, "re-index must leave the document with real chunks, not zero"
    # the old chunk rows are gone — this is a real re-index, not an additive append.
    assert chunk_ids_before.isdisjoint(chunk_ids_after)

    doc_resp = await client.get(f"/api/v1/documents/{document_id}")
    doc_body = doc_resp.json()
    assert doc_body["chunk_strategy"] == suggested_strategy
    assert doc_body["chunk_count"] == len(chunk_ids_after)

    # retrieval and the graph both still work against the re-indexed document.
    chat_resp = await client.post(
        "/api/v1/chat",
        json={
            "message": "How many vacation days do employees accrue per month?",
            "document_id": document_id,
            "mode": "hybrid",
        },
    )
    assert chat_resp.status_code == 200

    graph_resp = await client.get(f"/api/v1/graph/{document_id}")
    assert graph_resp.status_code == 200
