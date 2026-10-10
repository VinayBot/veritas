"""Entity resolution: group near-duplicate mentions ("Jane Smith", "J. Smith") into one
canonical entity. Embedding similarity alone over-merges (e.g. "Jane Smith" and "Jane Doe" are
embedding-close as two person names), so a fuzzy string-match is required too, and merging only
ever happens within the same NER label.
"""

from __future__ import annotations

import hashlib

import numpy as np

from app.embeddings.registry import get_embedder
from app.graphrag.extractor import Entity


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def entity_id(label: str, canonical_name: str) -> str:
    """Deterministic: the same (label, name) always maps to the same graph node, so mentions
    that normalize identically merge across chunks *and* across documents automatically — this
    is what resolves entities globally without having to search the whole graph on every
    insert. Mentions that normalize *differently* for the same real-world entity (e.g. "J.
    Smith" vs. "Jane Smith" in two different documents) are a known, documented limitation:
    resolve_entities()'s embedding+fuzzy merge only runs within one document's extraction batch.
    """
    payload = f"{label}:{normalize_name(canonical_name)}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


class ResolvedEntity:
    def __init__(self, canonical_name: str, label: str):
        self.canonical_name = canonical_name
        self.label = label
        self.mentions: list[str] = [canonical_name]

    @property
    def id(self) -> str:
        return entity_id(self.label, self.canonical_name)

    def add(self, mention: str) -> None:
        if mention not in self.mentions:
            self.mentions.append(mention)

    def __repr__(self) -> str:
        return f"ResolvedEntity({self.canonical_name!r}, {self.label!r}, mentions={self.mentions})"


def resolve_entities(
    entities: list[Entity],
    embedding_threshold: float = 0.88,
    fuzzy_threshold: float = 70.0,
    model_name: str | None = None,
) -> list[ResolvedEntity]:
    from rapidfuzz import fuzz

    if not entities:
        return []

    by_label: dict[str, list[str]] = {}
    for ent in entities:
        by_label.setdefault(ent.label, []).append(ent.text)

    embedder = get_embedder(model_name)
    resolved: list[ResolvedEntity] = []

    for label, texts in by_label.items():
        embeddings = embedder.embed(texts)
        clusters: list[ResolvedEntity] = []
        cluster_embs: list[np.ndarray] = []

        for text, emb in zip(texts, embeddings, strict=True):
            best_idx: int | None = None
            best_sim = -1.0
            for i, c_emb in enumerate(cluster_embs):
                sim = float(np.dot(emb, c_emb))
                if sim > best_sim:
                    best_sim, best_idx = sim, i

            merge = False
            if best_idx is not None and best_sim >= embedding_threshold:
                fuzzy_score = fuzz.token_sort_ratio(text, clusters[best_idx].canonical_name)
                merge = fuzzy_score >= fuzzy_threshold

            if merge and best_idx is not None:
                clusters[best_idx].add(text)
            else:
                clusters.append(ResolvedEntity(canonical_name=text, label=label))
                cluster_embs.append(emb)
        resolved.extend(clusters)

    return resolved
