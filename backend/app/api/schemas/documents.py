from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class UploadResponse(BaseModel):
    document_id: str
    job_id: str  # Phase 2 runs ingestion synchronously, so job_id == document_id for now.


class UrlIngestRequest(BaseModel):
    url: HttpUrl
    depth: int = Field(default=0, ge=0, le=2)


class DocumentResponse(BaseModel):
    id: str
    filename: str
    source_type: str
    source_url: str | None
    mime_type: str | None
    status: str  # "queued" | "running" | "ready" | "failed" | "cancelled"
    current_stage: str | None
    error_message: str | None
    error_stage: str | None
    enrichment_status: str | None  # "running" | "done" | "failed" | "cancelled" | None
    enrichment_error: str | None
    raw_text_chars: int | None
    quality_score_before: float | None
    quality_score_after: float | None
    fix_log: list[dict]
    language: str | None
    ocr_confidence: float | None
    pii_counts: dict[str, int]
    chunk_count: int | None
    chunk_strategy: str | None
    graph_entity_count: int | None
    graph_triple_count: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentSummary(BaseModel):
    id: str
    filename: str
    source_type: str
    status: str
    enrichment_status: str | None
    chunk_count: int | None
    chunk_strategy: str | None
    graph_entity_count: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]
    total: int


class DeleteDocumentResponse(BaseModel):
    document_id: str
    chunks_removed: int
    graph_edges_removed: int
