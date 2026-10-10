from __future__ import annotations

from pydantic import BaseModel


class CouncilMemberAnswer(BaseModel):
    model: str
    label: str
    answer: str
    latency_ms: float


class CouncilPeerReview(BaseModel):
    reviewer_model: str
    scores: dict[str, float]


class CouncilRunResponse(BaseModel):
    id: str
    session_id: str
    query: str
    members: list[str]
    chairman_model: str
    member_answers: list[CouncilMemberAnswer]
    peer_reviews: list[CouncilPeerReview]
    agreement_score: float
    final_answer: str
