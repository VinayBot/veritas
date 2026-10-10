from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from app.api.schemas.documents import DocumentResponse, UploadResponse, UrlIngestRequest
from app.core.errors import AppError
from app.ingestion import service

router = APIRouter(tags=["documents"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("/documents/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)) -> UploadResponse:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise AppError("file_too_large", f"File exceeds {MAX_UPLOAD_BYTES} bytes", 413)
    try:
        document_id = await service.ingest_upload(
            file.filename or "upload", content, file.content_type
        )
    except service.IngestionError as exc:
        raise AppError(exc.code, exc.message, 422) from exc
    return UploadResponse(document_id=document_id, job_id=document_id)


@router.post("/documents/url", response_model=UploadResponse)
async def ingest_url(body: UrlIngestRequest) -> UploadResponse:
    try:
        document_id = await service.ingest_url(str(body.url), body.depth)
    except service.IngestionError as exc:
        raise AppError(exc.code, exc.message, 422) from exc
    return UploadResponse(document_id=document_id, job_id=document_id)


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str) -> DocumentResponse:
    doc = await service.get_document(document_id)
    if doc is None:
        raise AppError("document_not_found", f"No document with id {document_id}", 404)
    return DocumentResponse.model_validate(doc)


@router.post("/documents/{document_id}/retry", response_model=DocumentResponse)
async def retry_document(document_id: str) -> DocumentResponse:
    try:
        await service.retry_ingestion(document_id)
    except service.IngestionError as exc:
        status_code = 404 if exc.code == "document_not_found" else 422
        raise AppError(exc.code, exc.message, status_code) from exc
    doc = await service.get_document(document_id)
    assert doc is not None
    return DocumentResponse.model_validate(doc)


@router.post("/documents/{document_id}/cancel", response_model=DocumentResponse)
async def cancel_document(document_id: str) -> DocumentResponse:
    try:
        await service.cancel_ingestion(document_id)
    except service.IngestionError as exc:
        status_code = 404 if exc.code == "document_not_found" else 422
        raise AppError(exc.code, exc.message, status_code) from exc
    doc = await service.get_document(document_id)
    assert doc is not None
    return DocumentResponse.model_validate(doc)
