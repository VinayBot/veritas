"""Per-document strategy recommendation.

No model is asked for an opinion here. The recommendation is a fixed, readable rule set over
features measured from the document (app/profiler/features.py): each rule that fires adds to
or subtracts from a strategy's score and contributes a reason that quotes the measurement it
fired on. The response includes every rule and whether it fired, so the result can be
audited line by line.

Scores start from `BASE`, which encodes one prior: a single hybrid pass with reranking is the
sensible default, and more elaborate strategies have to earn their place.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.profiler.features import DocumentProfile
from app.rag_engines.registry import STRATEGIES

BASE: dict[str, float] = {
    "hybrid_rerank": 0.50,
    "hybrid": 0.40,
    "agentic": 0.35,
    "hyde": 0.28,
    "semantic_chunk": 0.30,
    "graph_rag": 0.25,
    "naive": 0.25,
    # Never recommended on document shape alone: it is for stakes, not structure.
    "council": 0.05,
}

# Thresholds, named so the rules below read as sentences.
SHORT_TOKENS = 2_000
LONG_TOKENS = 20_000  # roughly 40 pages
ENTITY_DENSE = 15.0  # unique entities per 1,000 tokens
RELATION_DENSE = 1.5  # graph relations per 1,000 tokens
CROSS_REF_MIN = 10
CROSS_REF_DENSE = 2.0  # per 1,000 tokens
LONG_PARAGRAPH_WORDS = 60
TABLE_HEAVY = 0.15
TABLE_LIGHT = 0.05
STRUCTURED_HEADINGS = 0.05
REPETITIVE_DUPLICATION = 0.2
LOW_LEXICAL_DIVERSITY = 0.35


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    applies: Callable[[DocumentProfile], bool]
    effects: dict[str, float]
    reason: Callable[[DocumentProfile], str]
    """Strategies this rule argues against, with the reason shown under "not recommended"."""
    against: dict[str, Callable[[DocumentProfile], str]] = field(default_factory=dict)


def _pages(p: DocumentProfile) -> str:
    if p.page_count:
        return f"{p.page_count} pages"
    return f"about {p.pages_estimated} pages ({p.tokens:,} tokens)"


RULES: tuple[Rule, ...] = (
    Rule(
        "entity_dense_graph",
        f"At least {ENTITY_DENSE:.0f} unique entities per 1k tokens and "
        f"{RELATION_DENSE} extracted relations per 1k tokens",
        lambda p: p.unique_entity_density >= ENTITY_DENSE and p.relation_density >= RELATION_DENSE,
        {"graph_rag": 0.32, "agentic": 0.05},
        lambda p: (
            f"High entity density ({p.unique_entity_density:.0f} unique entities / 1k tokens) "
            f"with {p.relation_density:.1f} relations / 1k tokens in the graph built at ingest"
        ),
    ),
    Rule(
        "entity_dense_no_relations",
        f"At least {ENTITY_DENSE:.0f} unique entities per 1k tokens but few extracted relations",
        lambda p: p.unique_entity_density >= ENTITY_DENSE and p.relation_density < RELATION_DENSE,
        {"graph_rag": 0.08, "hybrid_rerank": 0.05},
        lambda p: (
            f"Many entities ({p.unique_entity_density:.0f} unique / 1k tokens) but only "
            f"{p.relation_density:.1f} relations / 1k tokens were extracted, so the graph is thin"
        ),
    ),
    Rule(
        "cross_referenced",
        f"At least {CROSS_REF_MIN} internal cross-references, {CROSS_REF_DENSE}+ per 1k tokens",
        lambda p: (
            p.cross_references >= CROSS_REF_MIN and p.cross_reference_density >= CROSS_REF_DENSE
        ),
        {"graph_rag": 0.15, "agentic": 0.22},
        lambda p: (
            f"{p.cross_references} intra-document cross-references suggest questions that need "
            "facts from more than one place"
        ),
    ),
    Rule(
        "long_document",
        f"At least {LONG_TOKENS:,} tokens",
        lambda p: p.tokens >= LONG_TOKENS,
        {"hybrid_rerank": 0.15, "agentic": 0.10, "naive": -0.25},
        lambda p: f"Long document ({_pages(p)}): reranking matters when there are many near-misses",
        against={
            "naive": lambda p: (
                f"Document is {_pages(p)}; a flat top-k over fixed chunks will miss context"
            )
        },
    ),
    Rule(
        "short_document",
        f"Fewer than {SHORT_TOKENS:,} tokens",
        lambda p: p.tokens < SHORT_TOKENS,
        {"naive": 0.22, "hybrid": 0.18, "agentic": -0.18, "graph_rag": -0.10},
        lambda p: f"Short document ({p.tokens:,} tokens): one retrieval pass already covers it",
        against={
            "agentic": lambda p: (
                f"Only {p.tokens:,} tokens; a planning and retry loop adds latency with "
                "nothing to find"
            )
        },
    ),
    Rule(
        "long_form_prose",
        f"Classified prose with paragraphs averaging {LONG_PARAGRAPH_WORDS}+ words",
        lambda p: p.content_class == "prose" and p.avg_paragraph_length >= LONG_PARAGRAPH_WORDS,
        {"semantic_chunk": 0.32},
        lambda p: (
            f"Long-form prose (paragraphs average {p.avg_paragraph_length:.0f} words, "
            f"{p.table_ratio:.0%} tables): chunk boundaries that follow meaning keep an "
            "argument intact"
        ),
    ),
    Rule(
        "table_heavy",
        f"Tables are at least {TABLE_HEAVY:.0%} of lines",
        lambda p: p.table_ratio >= TABLE_HEAVY,
        {"hybrid_rerank": 0.20, "semantic_chunk": -0.22, "graph_rag": -0.12},
        lambda p: (
            f"Tables make up {p.table_ratio:.0%} of lines: keyword matching finds exact cell "
            "values that search by meaning blurs"
        ),
        against={
            "semantic_chunk": lambda p: (
                f"Tables are {p.table_ratio:.0%} of lines; splitting on shifts in meaning "
                "breaks rows apart"
            ),
            "graph_rag": lambda p: (
                f"Tables are {p.table_ratio:.0%} of lines; relation extraction reads "
                "sentences, not cells"
            ),
        },
    ),
    Rule(
        "low_table_graph_friendly",
        f"Tables under {TABLE_LIGHT:.0%} of lines in an entity-dense document",
        lambda p: p.table_ratio < TABLE_LIGHT and p.unique_entity_density >= ENTITY_DENSE,
        {"graph_rag": 0.04},
        lambda p: (
            f"Low table ratio ({p.table_ratio:.0%}): graph traversal will not be fighting "
            "tabular layout"
        ),
    ),
    Rule(
        "structured",
        f"Headings on at least {STRUCTURED_HEADINGS:.0%} of lines",
        lambda p: p.heading_density >= STRUCTURED_HEADINGS,
        {"hybrid_rerank": 0.08},
        lambda p: (
            f"Clearly sectioned ({p.heading_density:.0%} of lines are headings): section titles "
            "give keyword search strong anchors"
        ),
    ),
    Rule(
        "repetitive",
        f"At least {REPETITIVE_DUPLICATION:.0%} near-duplicate paragraphs, or lexical diversity "
        f"under {LOW_LEXICAL_DIVERSITY}",
        lambda p: (
            p.duplication_ratio >= REPETITIVE_DUPLICATION
            or (0 < p.lexical_diversity < LOW_LEXICAL_DIVERSITY)
        ),
        {"hybrid_rerank": 0.15, "naive": -0.10},
        lambda p: (
            f"Repetitive text ({p.duplication_ratio:.0%} near-duplicate paragraphs, lexical "
            f"diversity {p.lexical_diversity:.2f}): rerank with de-duplication stops the same "
            "passage filling the context"
        ),
    ),
    Rule(
        "no_graph",
        "No relations were extracted for this document",
        lambda p: p.relation_density == 0,
        {"graph_rag": -0.30},
        lambda p: "No relations were extracted at ingest, so there is no graph to traverse",
        against={
            "graph_rag": lambda p: (
                "No relations were extracted from this document; the graph is empty"
            )
        },
    ),
    Rule(
        "low_quality_scan",
        "OCR confidence was reported below 0.8",
        lambda p: p.low_quality_scan,
        {"hybrid": 0.10, "graph_rag": -0.15, "semantic_chunk": -0.10},
        lambda p: (
            f"Scanned text with low OCR confidence ({p.ocr_confidence:.2f}): combining keyword and "
            "meaning-based search tolerates misread words better than either alone"
        ),
        against={
            "graph_rag": lambda p: (
                f"OCR confidence is {p.ocr_confidence:.2f}; entity extraction is unreliable "
                "on misread text"
            )
        },
    ),
)


@dataclass
class Recommendation:
    recommended: str
    confidence: float
    reasons: list[str]
    runner_up: str | None
    not_recommended: list[dict[str, str]]
    scores: dict[str, float]
    """Every rule, whether it fired, and what it changed — the audit trail."""
    rule_trace: list[dict]

    def to_dict(self) -> dict:
        return {
            "recommended": self.recommended,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "runner_up": self.runner_up,
            "not_recommended": self.not_recommended,
            "scores": self.scores,
            "rule_trace": self.rule_trace,
        }


def confidence_from_margin(top: float, second: float) -> float:
    """0.5 when the top two are tied (nothing in the document separated them), rising with
    the gap between them, capped at 0.95 — a rule set is never certain."""
    return round(min(0.95, 0.5 + (top - second) * 1.5), 2)


def recommend(profile: DocumentProfile) -> Recommendation:
    scores = dict(BASE)
    reasons_for: dict[str, list[tuple[float, str]]] = {s: [] for s in scores}
    against: dict[str, str] = {}
    trace: list[dict] = []

    for rule in RULES:
        fired = bool(rule.applies(profile))
        trace.append(
            {
                "rule": rule.id,
                "description": rule.description,
                "fired": fired,
                "effects": rule.effects if fired else {},
            }
        )
        if not fired:
            continue
        text = rule.reason(profile)
        for strategy, delta in rule.effects.items():
            scores[strategy] = scores[strategy] + delta
            if delta > 0:
                reasons_for[strategy].append((delta, text))
        for strategy, why in rule.against.items():
            against.setdefault(strategy, why(profile))

    ranked = sorted(scores, key=lambda s: (-scores[s], list(BASE).index(s)))
    top, second = ranked[0], ranked[1]
    reasons = [text for _, text in sorted(reasons_for[top], key=lambda r: -r[0])]
    if not reasons:
        reasons = [
            "Nothing measured in this document argues for a more specialised strategy, so the "
            "general-purpose default stands"
        ]
    return Recommendation(
        recommended=top,
        confidence=confidence_from_margin(scores[top], scores[second]),
        reasons=reasons,
        runner_up=second,
        not_recommended=[
            {"id": strategy, "why": why}
            for strategy, why in against.items()
            if strategy != top and strategy in STRATEGIES
        ],
        scores={s: round(v, 3) for s, v in scores.items()},
        rule_trace=trace,
    )
