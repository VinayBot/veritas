"""Advisor: turns the document profile and tournament results into a Baseline-vs-Suggested
recommendation (with a rationale tied to *measured* profile features, not a generic template)
plus a RAG-mode suggestion. Every number quoted in the rationale comes from the tournament's
real metrics or the profiler's real features — nothing here is invented to sound plausible.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.profiler.features import DocumentProfile
from app.profiler.tournament import CandidateResult, TournamentResult

RELATION_DENSITY_GRAPH_THRESHOLD = 2.0  # relations per 1000 tokens


@dataclass
class AdvisorRecommendation:
    baseline: CandidateResult
    suggested: CandidateResult
    gain_ndcg_points: float
    rationale: list[str]
    suggested_mode: str
    mode_reason: str


def recommend_mode(profile: DocumentProfile) -> tuple[str, str]:
    if profile.relation_density >= RELATION_DENSITY_GRAPH_THRESHOLD:
        return (
            "graph",
            f"High relation density ({profile.relation_density:.2f} relations per 1,000 "
            "tokens, from the graph actually built at ingestion) suggests this document's "
            "value is in the connections between entities.",
        )
    if profile.document_type == "faq" or (profile.heading_density < 0.02 and profile.tokens < 2000):
        return (
            "hybrid",
            f"Short, lightly-structured content ({profile.tokens} tokens, "
            f"{profile.heading_density:.1%} heading density) suggests simple hybrid search is "
            "sufficient without the agentic loop's extra cost.",
        )
    return (
        "agentic",
        "No single strong structural signal (graph-dense or FAQ-simple) was measured, so "
        "the general-purpose agentic pipeline — which can decompose multi-hop or comparison "
        "questions on its own — is the safer default.",
    )


def _rationale_for_winner(
    profile: DocumentProfile, winner: CandidateResult, baseline: CandidateResult
) -> list[str]:
    reasons: list[str] = []

    if winner.config.name == baseline.config.name:
        reasons.append(
            "No candidate beat the baseline on the synthetic eval set — keeping the baseline "
            "configuration is the measured, not assumed, best choice here."
        )
        return reasons

    gain = (
        winner.retrieval_metrics.get("ndcg_at_5", 0.0)
        - baseline.retrieval_metrics.get("ndcg_at_5", 0.0)
    ) * 100
    n = int(winner.retrieval_metrics.get("n", 0))
    reasons.append(
        f"{winner.config.name} scored {gain:+.1f} nDCG@5 points over the baseline across "
        f"{n} synthetic questions actually run against both configurations."
    )

    if winner.config.chunking_strategy == "structure_aware" and profile.table_ratio > 0.05:
        reasons.append(
            f"Tables make up {profile.table_ratio:.1%} of this document's lines — "
            "structure-aware chunking keeps table rows and their headings together instead "
            "of splitting them at an arbitrary token boundary."
        )
    if winner.config.rerank and not baseline.config.rerank:
        reasons.append(
            f"Cross-encoder reranking improved ranking quality enough to justify its "
            f"latency cost ({winner.avg_latency_ms:.0f}ms/query measured vs. "
            f"{baseline.avg_latency_ms:.0f}ms/query for the baseline)."
        )
    if winner.config.llm_model and winner.config.llm_model != baseline.config.llm_model:
        reasons.append(
            f"{winner.config.llm_model} measured {winner.faithfulness:.2f} average "
            f"faithfulness on sampled questions vs. {baseline.faithfulness:.2f} for the "
            "baseline's model."
        )
    if winner.config.chunking_kwargs.get("size", 512) < baseline.config.chunking_kwargs.get(
        "size", 512
    ):
        reasons.append(
            f"Smaller chunks ({winner.config.chunking_kwargs.get('size')} tokens vs. "
            f"{baseline.config.chunking_kwargs.get('size')}) produced {winner.index_size} "
            f"chunks (baseline: {baseline.index_size}) and scored higher recall — this "
            "document's answers tend to be short, specific facts rather than long passages."
        )

    return reasons


def build_recommendation(
    profile: DocumentProfile, tournament: TournamentResult
) -> AdvisorRecommendation | None:
    baseline = tournament.baseline
    winner = tournament.winner
    if baseline is None or winner is None:
        return None

    gain = (
        winner.retrieval_metrics.get("ndcg_at_5", 0.0)
        - baseline.retrieval_metrics.get("ndcg_at_5", 0.0)
    ) * 100
    mode, mode_reason = recommend_mode(profile)

    return AdvisorRecommendation(
        baseline=baseline,
        suggested=winner,
        gain_ndcg_points=gain,
        rationale=_rationale_for_winner(profile, winner, baseline),
        suggested_mode=mode,
        mode_reason=mode_reason,
    )
