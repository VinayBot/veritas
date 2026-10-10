from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    document_id: str | None = None
    mode: str = "hybrid"
    k: int = Field(default=5, ge=1, le=50)
    use_hyde: bool = False
    rerank: bool = False
    dedupe_strategy: str | None = None  # "mmr" | "cosine" | "ngram" | None
    compress: bool = False
    max_context_tokens: int = Field(default=1000, ge=50, le=8000)


class SearchHit(BaseModel):
    chunk_id: str
    score: float
    text: str
    dense_rank: int | None = None
    bm25_rank: int | None = None
    dense_score: float | None = None
    bm25_score: float | None = None
    rerank_score: float | None = None


class SearchResponse(BaseModel):
    hits: list[SearchHit]
