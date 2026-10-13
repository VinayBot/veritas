from __future__ import annotations

import json

from conftest import wait_for_document
from httpx import AsyncClient

from app.council.service import (
    PeerReview,
    _agreement_score,
    _labels,
    get_council_run,
    run_council,
)


def test_labels_assigns_letters_in_order() -> None:
    assert _labels(3) == ["A", "B", "C"]
    assert _labels(1) == ["A"]


def test_agreement_score_is_high_when_reviewers_fully_agree() -> None:
    reviews = [
        PeerReview("m1", {"A": 8.0, "B": 3.0}),
        PeerReview("m2", {"A": 8.0, "B": 3.0}),
        PeerReview("m3", {"A": 8.0, "B": 3.0}),
    ]
    assert _agreement_score(reviews, ["A", "B"]) == 1.0


def test_agreement_score_is_low_when_reviewers_scatter_scores() -> None:
    reviews = [
        PeerReview("m1", {"A": 0.0, "B": 10.0}),
        PeerReview("m2", {"A": 10.0, "B": 0.0}),
        PeerReview("m3", {"A": 5.0, "B": 5.0}),
    ]
    score = _agreement_score(reviews, ["A", "B"])
    assert 0.0 <= score < 0.5


def test_agreement_score_zero_when_fewer_than_two_scores_per_label() -> None:
    # Only one reviewer actually scored anything — a stdev needs at least two points, so this
    # must not be silently treated as perfect agreement.
    reviews = [PeerReview("m1", {"A": 7.0}), PeerReview("m2", {})]
    assert _agreement_score(reviews, ["A", "B"]) == 0.0


async def test_run_council_produces_real_distinct_answers_and_persists(client: AsyncClient) -> None:
    context = (
        "[1] Employees accrue two paid vacation days for every month of continuous service, "
        "up to a maximum of twenty-four days per year."
    )
    result = await run_council(
        "test-session-council", "How many vacation days do employees accrue per month?", context
    )

    assert len(result.member_answers) >= 2
    assert all(m.answer for m in result.member_answers)
    assert len(result.peer_reviews) == len(result.member_answers)
    assert 0.0 <= result.agreement_score <= 1.0
    assert result.final_answer

    persisted = await get_council_run(result.id)
    assert persisted is not None
    assert persisted.session_id == "test-session-council"
    assert persisted.final_answer == result.final_answer
    assert len(persisted.member_answers) == len(result.member_answers)


async def _upload_policy_doc(client: AsyncClient) -> str:
    files = {
        "file": (
            "policy.md",
            b"# Vacation Policy\n\nEmployees accrue two paid vacation days per month of "
            b"service, up to a maximum of twenty-four days per year.",
            "text/markdown",
        )
    }
    resp = await client.post("/api/v1/documents/upload", files=files)
    document_id = resp.json()["document_id"]
    await wait_for_document(client, document_id)
    return document_id


async def test_chat_with_the_council_strategy_runs_the_real_council_and_links_the_report(
    client: AsyncClient,
) -> None:
    document_id = await _upload_policy_doc(client)
    resp = await client.post(
        "/api/v1/chat",
        json={
            "message": "How much vacation do employees get?",
            "document_id": document_id,
            "strategy": "council",
        },
    )
    assert resp.status_code == 200

    events = []
    for block in resp.text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_line, data_line = block.split("\n", 1)
        events.append((event_line.removeprefix("event: "), data_line.removeprefix("data: ")))

    raw_id = next((d for e, d in events if e == "council_run_id"), None)
    council_run_id = json.loads(raw_id) if raw_id else None
    assert council_run_id, "the council strategy must produce a council_run_id SSE event"

    done_data = json.loads(next(d for e, d in events if e == "done"))
    report_resp = await client.get(f"/api/v1/reports/{done_data['report_id']}")
    assert report_resp.json()["council_run_id"] == council_run_id

    council_resp = await client.get(f"/api/v1/council/{council_run_id}")
    assert council_resp.status_code == 200
    council_body = council_resp.json()
    assert council_body["query"] == "How much vacation do employees get?"
    assert len(council_body["member_answers"]) == len(council_body["members"])
    assert len(council_body["peer_reviews"]) == len(council_body["members"])
    assert council_body["final_answer"]


async def test_chat_without_council_leaves_council_run_id_null(client: AsyncClient) -> None:
    document_id = await _upload_policy_doc(client)
    resp = await client.post(
        "/api/v1/chat",
        json={
            "message": "How much vacation do employees get?",
            "document_id": document_id,
            "strategy": "hybrid_rerank",
        },
    )
    events = []
    for block in resp.text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_line, data_line = block.split("\n", 1)
        events.append((event_line.removeprefix("event: "), data_line.removeprefix("data: ")))
    assert not any(e == "council_run_id" for e, _ in events)


async def test_get_council_run_404_for_unknown_id(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/council/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["code"] == "council_run_not_found"
