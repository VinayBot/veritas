"""Chunking strategy name -> factory. `pruned candidate grid` (Phase 8's advisor) will pick
from these; today, ingestion always runs the baseline."""

from __future__ import annotations

from typing import Any

from app.chunking.base import Chunker
from app.chunking.strategies.fixed import FixedChunker
from app.chunking.strategies.parent_child import ParentChildChunker
from app.chunking.strategies.recursive import RecursiveChunker
from app.chunking.strategies.semantic import SemanticChunker
from app.chunking.strategies.sentence_window import SentenceWindowChunker
from app.chunking.strategies.structure_aware import StructureAwareChunker

_FACTORIES: dict[str, type] = {
    "fixed": FixedChunker,
    "recursive": RecursiveChunker,
    "sentence_window": SentenceWindowChunker,
    "semantic": SemanticChunker,
    "structure_aware": StructureAwareChunker,
    "parent_child": ParentChildChunker,
}

BASELINE_STRATEGY = "recursive"
BASELINE_SIZE = 512
BASELINE_OVERLAP = 64


def get_chunker(strategy: str, **kwargs: Any) -> Chunker:
    if strategy not in _FACTORIES:
        raise ValueError(f"Unknown chunking strategy: {strategy!r}. Known: {sorted(_FACTORIES)}")
    return _FACTORIES[strategy](**kwargs)


def get_baseline_chunker(model_name: str | None = None) -> Chunker:
    return RecursiveChunker(size=BASELINE_SIZE, overlap=BASELINE_OVERLAP, model_name=model_name)


def supported_strategies() -> list[str]:
    return sorted(_FACTORIES.keys())
