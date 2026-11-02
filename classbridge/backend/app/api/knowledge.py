from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from itsdangerous import BadSignature, SignatureExpired
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DBSession

from app.api.auth import current_user
from app.config import settings
from app.db import get_db
from app.models import AudioAsset, Chat, Chunk, Citation, Document, Session, User, uid
from app.providers.aliyun import AliyunProvider, ProviderError
from app.services.events import enqueue
from app.services.knowledge import answer_question
from app.services.storage import get_storage, signer


router = APIRouter(prefix="/api", tags=["Knowledge"])


def owned_document(db, user_id, document_id):
    row = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user_id))
    if not row:
        raise HTTPException(404, detail={"code": "document_not_found", "message": "资料不存在或无权访问。"})
    return row


def owned_session(db, user_id, session_id):
    row = db.scalar(select(Session).where(Session.id == session_id, Session.user_id == user_id))
    if not row:
        raise HTTPException(404, detail={"code": "session_not_found", "message": "会话不存在或无权访问。"})
    return row


def public_document(document, db=None):
    chunk=db.scalar(select(Chunk).where(Chunk.document_id==document.id).limit(1)) if db else None
    return {"id": document.id, "name": document.name, "session_id": document.session_id, "content_type": document.content_type, "version": document.version, "status": document.status, "error": document.error, "size_bytes": document.size_bytes, "page_count": document.page_count, "created_at": document.created_at,"index_mode":chunk.metadata_json.get('embedding_mode') if chunk else None}


@router.get("/documents")
def documents(session_id: str | None = None, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    query = select(Document).where(Document.user_id == user.id)
    if session_id:
        owned_session(db, user.id, session_id)
        query = query.where(Document.session_id == session_id)
    return [public_document(document,db) for document in db.scalars(query.order_by(Document.created_at.desc()))]


@router.post("/documents", status_code=201)
async def upload_document(file: UploadFile = File(...), session_id: str | None = Form(None), mode: Literal["demo", "real"] = Form("demo"), user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    if session_id:
        owned_session(db, user.id, session_id)
    if mode == "real":
        AliyunProvider().ensure_ready()
        AliyunProvider().base()
    name = Path((file.filename or "").replace("\\", "/")).name
    extension = Path(name).suffix.lower()
    content_types = {".pdf": "application/pdf", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    if extension not in content_types or len(name) > 250:
        raise HTTPException(415, detail={"code": "unsupported_document", "message": "仅接受 PDF、PPTX、DOCX，文件名最多 250 字符。"})
    data = bytearray()
    limit = settings.upload_max_mb * 1024 * 1024
    try:
        while part := await file.read(1024 * 1024):
            data.extend(part)
            if len(data) > limit:
                raise HTTPException(413, detail={"code": "upload_too_large", "message": f"资料超过 {settings.upload_max_mb} MB 应用上限。"})
    finally:
        await file.close()
    if not data or (extension == ".pdf" and not data.startswith(b"%PDF")) or (extension != ".pdf" and not data.startswith(b"PK")):
        raise HTTPException(415, detail={"code": "invalid_file_content", "message": "文件内容与扩展名不符，或文件为空。"})
    document_id = uid()
    key = f"documents/{user.id}/{document_id}/v1{extension}"
    storage = get_storage()
    await asyncio.to_thread(storage.put, key, bytes(data))
    document = Document(id=document_id, user_id=user.id, session_id=session_id, name=name, content_type=content_types[extension], storage_key=key, size_bytes=len(data), status="pending")
    try:
        db.add(document)
        db.flush()
        enqueue(db, user.id, "document", f"document:{document.id}:1", {"document_id": document.id, "mode": mode}, document_id=document.id)
        db.commit()
    except Exception:
        db.rollback()
        await asyncio.to_thread(storage.delete, key)
        raise
    return public_document(document)


@router.get("/documents/{document_id}")
def document_detail(document_id: str, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    document = owned_document(db, user.id, document_id)
    chunks = db.scalars(select(Chunk).where(Chunk.document_id == document.id, Chunk.user_id == user.id).order_by(Chunk.page, Chunk.position)).all()
    return {**public_document(document), "chunks": [{"id": chunk.id, "text": chunk.text, "page": chunk.page, "position": chunk.position, "location": chunk.metadata_json.get("location"), "source_revision": chunk.source_revision} for chunk in chunks], "index_mode": chunks[0].metadata_json.get("embedding_mode") if chunks else None}


@router.get("/documents/{document_id}/file")
def document_file(document_id: str, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    document = owned_document(db, user.id, document_id)
    try:
        data = get_storage().read(document.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(404, detail={"code": "file_missing", "message": "资料原文件不可用。"}) from exc
    return Response(data, media_type=document.content_type, headers={"Content-Disposition": "inline; filename*=UTF-8''" + quote(document.name), "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    document = owned_document(db, user.id, document_id)
    if document.session_id:
        session = owned_session(db, user.id, document.session_id)
        if session.status in ("preparing", "recording", "processing", "capturing", "active", "stopping"):
            raise HTTPException(409, detail={"code": "capture_active", "message": "录音期间不能删除当前会话的资料。"})
    # Erase saved derived answers containing this source as well as their quotations.
    chat_ids = select(Citation.chat_id).where(Citation.document_id == document_id)
    db.execute(delete(Chat).where(Chat.id.in_(chat_ids), Chat.user_id == user.id))
    get_storage().delete(document.storage_key)
    db.delete(document)
    db.commit()
    return {"ok": True}


@router.get("/storage/signed", include_in_schema=False)
def signed_object(token: str = Query(max_length=4096), db: DBSession = Depends(get_db)):
    try:
        data, timestamp = signer().loads(token, max_age=3600, return_timestamp=True)
        if (datetime.now(timezone.utc) - timestamp).total_seconds() > data["ttl"]:
            raise SignatureExpired("expired")
        key = data["key"]
    except (BadSignature, KeyError, TypeError) as exc:
        raise HTTPException(403, detail={"code": "expired_link", "message": "访问链接无效或已过期。"}) from exc
    # A still-valid URL becomes unusable immediately when the underlying record is deleted.
    doc = db.scalar(select(Document).where(Document.storage_key == key))
    asset = db.scalar(select(AudioAsset).where(AudioAsset.storage_key == key))
    if not doc and not asset:
        raise HTTPException(404, detail="文件不存在")
    if asset:
        expiry = asset.expires_at if asset.expires_at.tzinfo else asset.expires_at.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc) or asset.status != "ready":
            raise HTTPException(410, detail="音频已过期或未完成保存")
    try:
        value = get_storage().read(key)
    except FileNotFoundError as exc:
        raise HTTPException(404, detail="文件不可用") from exc
    return Response(value, media_type=doc.content_type if doc else "audio/wav", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


class ChatBody(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    scope: Literal["recent", "session", "documents", "history"] = "session"
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    mode: Literal["demo", "real"] = "demo"


@router.post("/chat")
async def ask(body: ChatBody, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    if not body.question.strip():
        raise HTTPException(422, detail="问题不能为空。")
    session = owned_session(db, user.id, body.session_id) if body.session_id else None
    if body.scope in ("session", "recent") and not session:
        raise HTTPException(422, detail="请选择会话。")
    if session and session.mode != body.mode:
        raise HTTPException(409, detail={"code": "mode_mismatch", "message": "问答模式须与会话一致，真实失败不会切换成模拟回答。"})
    if body.scope == "documents" and not body.document_ids:
        raise HTTPException(422, detail="请选择至少一份资料。")
    for document_id in body.document_ids:
        owned_document(db, user.id, document_id)
    if body.mode == "real":
        AliyunProvider().ensure_ready()
        AliyunProvider().base()
    return await answer_question(db, user.id, body.question.strip(), body.scope, body.session_id, body.document_ids, body.mode)


@router.get("/chat")
def chat_history(session_id: str | None = None, mode: Literal['demo','real'] | None = None, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    query = select(Chat).where(Chat.user_id == user.id)
    if mode: query=query.where(Chat.mode==mode)
    if session_id:
        owned_session(db, user.id, session_id)
        query = query.where(Chat.session_id == session_id)
    rows = list(db.scalars(query.order_by(Chat.created_at.desc()).limit(100)))
    result = []
    for chat in reversed(rows):
        citations = db.scalars(select(Citation).where(Citation.chat_id == chat.id)).all()
        result.append({"id": chat.id, "question": chat.question, "answer": chat.answer, "mode": chat.mode, "scope": chat.scope, "created_at": chat.created_at, "citations": [{"id": citation.id, "chunk_id": citation.chunk_id, "label": getattr(citation, "label", None), "kind": citation.kind, "session_id": citation.session_id, "document_id": citation.document_id, "sentence_id": citation.sentence_id, "source_revision": citation.source_revision, "page": citation.page, "position": getattr(citation, "position", None), "location": getattr(citation, "location", None), "quote": citation.quote} for citation in citations]})
    return result
