from __future__ import annotations

from app.profiler.features import DocumentProfile, content_class, lexical_diversity
from app.rag_engines.advisor import BASE, RULES, confidence_from_margin, recommend
from app.rag_engines.registry import STRATEGIES


def profile(**overrides: object) -> DocumentProfile:
    base: dict = {
        "document_id": "doc-1",
        "tokens": 6_000,
        "characters": 30_000,
        "pages_estimated": 12,
        "language": "en",
        "heading_density": 0.01,
        "table_ratio": 0.0,
        "list_ratio": 0.02,
        "code_ratio": 0.0,
        "content_class": "mixed",
        "avg_sentence_length": 18.0,
        "avg_paragraph_length": 40.0,
        "duplication_ratio": 0.0,
        "lexical_diversity": 0.5,
        "ocr_confidence": None,
        "entity_density": 5.0,
        "unique_entity_density": 3.0,
        "unique_entities": 18,
        "entity_types": 4,
        "entity_type_spread": 1.5,
        "relation_density": 0.5,
        "cross_references": 0,
        "cross_reference_density": 0.0,
        "document_type": "mixed",
    }
    base.update(overrides)
    return DocumentProfile(**base)


def test_every_rule_only_touches_real_strategies() -> None:
    assert set(BASE) == set(STRATEGIES)
    for rule in RULES:
        assert set(rule.effects) <= set(STRATEGIES), rule.id
        assert set(rule.against) <= set(STRATEGIES), rule.id


def test_no_signal_keeps_the_general_default_with_low_confidence() -> None:
    result = recommend(profile())
    assert result.recommended == "hybrid_rerank"
    assert result.reasons == [
        "Nothing measured in this document argues for a more specialised strategy, so the "
        "general-purpose default stands"
    ]
    assert not any(r["fired"] for r in result.rule_trace)
    assert result.confidence < 0.7


def test_entity_dense_cross_referenced_document_gets_graph_rag_with_measured_reasons() -> None:
    result = recommend(
        profile(
            unique_entity_density=41.0,
            relation_density=3.2,
            cross_references=23,
            cross_reference_density=3.8,
        )
    )
    assert result.recommended == "graph_rag"
    joined = " ".join(result.reasons)
    assert "41 unique entities / 1k tokens" in joined
    assert "23 intra-document cross-references" in joined
    assert "Low table ratio" in joined
    assert result.runner_up in STRATEGIES and result.runner_up != "graph_rag"
    assert result.confidence > 0.6


def test_long_document_argues_against_naive_and_says_why() -> None:
    result = recommend(profile(tokens=42_000, pages_estimated=84, page_count=61))
    against = {item["id"]: item["why"] for item in result.not_recommended}
    assert "naive" in against
    assert "61 pages" in against["naive"]
    assert result.recommended == "hybrid_rerank"


def test_long_form_prose_gets_semantic_chunks() -> None:
    result = recommend(profile(content_class="prose", avg_paragraph_length=95.0))
    assert result.recommended == "semantic_chunk"
    assert "95 words" in result.reasons[0]


def test_table_heavy_document_avoids_semantic_chunks_and_graph() -> None:
    result = recommend(profile(table_ratio=0.4, content_class="tabular"))
    assert result.recommended == "hybrid_rerank"
    against = {item["id"] for item in result.not_recommended}
    assert {"semantic_chunk", "graph_rag"} <= against
    assert "40%" in result.reasons[0]


def test_short_document_prefers_a_single_pass() -> None:
    result = recommend(profile(tokens=600, pages_estimated=1))
    assert result.recommended in {"hybrid", "naive", "hybrid_rerank"}
    assert result.scores["agentic"] < BASE["agentic"]
    assert any(item["id"] == "agentic" for item in result.not_recommended)


def test_the_same_document_always_gets_the_same_recommendation() -> None:
    p = profile(unique_entity_density=20.0, relation_density=2.0, tokens=25_000)
    first, second = recommend(p), recommend(p)
    assert first.to_dict() == second.to_dict()


def test_the_rule_trace_lists_every_rule_and_what_fired() -> None:
    result = recommend(profile(table_ratio=0.3))
    assert [r["rule"] for r in result.rule_trace] == [rule.id for rule in RULES]
    fired = {r["rule"]: r["effects"] for r in result.rule_trace if r["fired"]}
    assert "table_heavy" in fired and fired["table_heavy"]["hybrid_rerank"] > 0
    # Scores are exactly the base plus the effects of the rules that fired.
    expected = dict(BASE)
    for effects in fired.values():
        for strategy, delta in effects.items():
            expected[strategy] += delta
    assert result.scores == {s: round(v, 3) for s, v in expected.items()}


def test_the_llm_guessed_document_type_never_changes_the_answer() -> None:
    answers = {
        recommend(profile(document_type=t, tokens=30_000)).recommended
        for t in ("legal", "faq", "research", "mixed")
    }
    assert len(answers) == 1


def test_confidence_is_bounded() -> None:
    assert confidence_from_margin(0.5, 0.5) == 0.5
    assert confidence_from_margin(2.0, 0.0) == 0.95


def test_content_class_and_lexical_diversity_are_measured_from_text() -> None:
    assert content_class(0.3, 0.0, 0.0, 10.0) == "tabular"
    assert content_class(0.0, 0.05, 0.02, 80.0) == "prose"
    assert content_class(0.0, 0.1, 0.2, 8.0) == "slide_like"
    varied = lexical_diversity("the quick brown fox jumps over one lazy dog near a quiet river")
    repeated = lexical_diversity("policy policy policy policy policy policy policy policy")
    assert varied > 0.8 > repeated
    assert lexical_diversity("") == 0.0
