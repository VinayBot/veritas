from __future__ import annotations

from typing import Any, Protocol

import numpy as np
from pydantic import BaseModel


class VectorHit(BaseModel):
    chunk_id: str
    score: float
    text: str
    metadata: dict[str, Any]


class VectorStore(Protocol):
    def add(
        self,
        ids: list[str],
        embeddings: np.ndarray,
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None: ...

    def query(
        self, embedding: np.ndarray, k: int, where: dict[str, Any] | None = None
    ) -> list[VectorHit]: ...

    def delete_by_doc(self, doc_id: str) -> None: ...
