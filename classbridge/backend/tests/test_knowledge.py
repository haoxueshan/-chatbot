import io
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import current_user
from app.api.knowledge import router
from app.config import settings
from app.db import Base, get_db
from app.models import Chat, Chunk, Citation, Document, RecognitionStream, SegmentRevision, Session, Translation, User
from app.providers.aliyun import AliyunProvider, ProviderError
from app.services.documents import DocumentParseError, parse_document
from app.services.knowledge import answer_question, demo_vector, handle_task, retrieve, summarize, validate_candidate
from app.services.storage import LocalStorage, get_storage


@pytest.mark.asyncio
async def test_summary_nulls_are_not_stringified_and_output_language_is_explicit(db,monkeypatch):
    import json
    from app.models import Stage
    from app.api.sessions import stage_dict
    seed_sentence(db)
    db.get(Session,'lesson').mode='real';db.commit()
    async def generate(self,prompt,**kwargs):
        assert '简体中文' in kwargs['system']
        return json.dumps({'topic':None,'summary':None,'knowledge_points':None,
            'terms':'invalid-list','decisions':[],'action_items':[]})
    monkeypatch.setattr(AliyunProvider,'generate',generate)
    result=await summarize(db,'lesson','alice')
    stage=db.get(Stage,result['stage_id'])
    assert stage.topic=='阶段重点' and stage.knowledge_points==[] and stage.terms==[]
    assert stage.summary and stage.summary!='None'
    stage.topic='None'
    assert stage_dict(stage)['topic']=='阶段重点'  # Older saved stages also read cleanly.


@pytest.mark.asyncio
async def test_summary_non_object_response_is_rejected(db,monkeypatch):
    seed_sentence(db)
    db.get(Session,'lesson').mode='real';db.commit()
    async def generate(*args,**kwargs):return 'null'
    monkeypatch.setattr(AliyunProvider,'generate',generate)
    with pytest.raises(ProviderError,match='JSON对象'):await summarize(db,'lesson','alice')


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "storage_backend", "local")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        db.add_all([User(id="alice", username="alice", password_hash="unused"), User(id="bob", username="bob", password_hash="unused")])
        db.commit()
        yield db
    engine.dispose()


def seed_sentence(db, owner="alice", session_id="lesson", revision=1, text="Gradient descent minimizes the loss function."):
    session = db.get(Session, session_id)
    if not session:
        session = Session(id=session_id, user_id=owner, title="Lecture", mode="demo")
        db.add(session)
        db.flush()
        db.add(RecognitionStream(id="stream-" + session_id, session_id=session_id, mode="demo"))
        db.flush()
    row = SegmentRevision(id=f"seg-{session_id}-{revision}", session_id=session_id, stream_id="stream-" + session_id, sentence_id="sentence-" + session_id, source_revision=revision, start_ms=0, end_ms=3500, text=text, mode="demo")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: db.get(User, "alice")
    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"detail": {"code": exc.code, "message": exc.message}}, status_code=503)
    with TestClient(app) as client:
        yield client


def make_docx(text="Gradient descent improves the model."):
    from docx import Document
    doc = Document()
    doc.add_paragraph(text)
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def test_docx_has_real_paragraph_location_no_invented_page():
    parsed = parse_document("lecture.docx", make_docx())
    assert parsed.chunks[0].metadata["page"] is None
    assert parsed.chunks[0].metadata["location"] == "段落 1"
    assert "固定分页" in parsed.warnings[0]


def test_pptx_preserves_slide_number():
    from pptx import Presentation
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Source evidence"
    buffer = io.BytesIO()
    presentation.save(buffer)
    result = parse_document("lecture.pptx", buffer.getvalue())
    assert result.page_count == 1
    assert result.chunks[0].metadata["page"] == 1


def test_blank_pdf_is_visible_error_not_empty_success():
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(DocumentParseError, match="OCR"):
        parse_document("scan.pdf", buffer.getvalue())


def test_office_zip_bomb_is_rejected():
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.txt", b"0" * (2 * 1024 * 1024))
    with pytest.raises(DocumentParseError, match="压缩比例"):
        parse_document("bad.docx", buffer.getvalue())


@pytest.mark.asyncio
async def test_latest_stable_sentences_retrieved_before_embedding_and_isolate_owner(db):
    seed_sentence(db, text="Outdated algorithm description")
    current = seed_sentence(db, revision=2, text="Gradient descent minimizes the loss function.")
    seed_sentence(db, owner="bob", session_id="secret", text="Bob confidential gradient descent secret")
    rows = await retrieve(db, "alice", "gradient descent", "history", None, [], "demo")
    assert {row["session_id"] for row in rows} == {"lesson"}
    assert rows[0]["source_revision"] == 2
    assert all("confidential" not in row["quote"] and "Outdated" not in row["quote"] for row in rows)


@pytest.mark.asyncio
async def test_index_idempotence_and_citations_bind_revision(db):
    segment = seed_sentence(db)
    first = await handle_task("index_segment", {"segment_id": segment.id}, db)
    db.commit()
    second = await handle_task("index_segment", {"segment_id": segment.id}, db)
    assert first == second
    assert len(list(db.scalars(select(Chunk)))) == 1
    result = await answer_question(db, "alice", "loss function", "session", "lesson", [], "demo")
    assert result["mode"] == "demo"
    assert "模拟演示" in result["answer"]
    assert result["citations"][0]["source_revision"] == 1
    citation = result["citations"][0]
    assert validate_candidate(db, "alice", citation)
    assert not validate_candidate(db, "bob", citation)
    seed_sentence(db, revision=2, text="Corrected source")
    assert validate_candidate(db, "alice", citation), "Old immutable evidence remains traceable"


@pytest.mark.asyncio
async def test_fabricated_model_citation_is_rejected(db, monkeypatch):
    seed_sentence(db)
    session = db.get(Session, "lesson")
    session.mode = "real"
    db.commit()
    async def embeddings(self, text): return [demo_vector(t) for t in text]
    async def rerank(self, question, documents, top_n=8): return [(i, 0.8) for i in range(len(documents))]
    async def generate(self, *args, **kwargs): return '{"answer":"Fabricated [E999]","evidence_ids":["E999"]}'
    monkeypatch.setattr(AliyunProvider, "embeddings", embeddings)
    monkeypatch.setattr(AliyunProvider, "rerank", rerank)
    monkeypatch.setattr(AliyunProvider, "generate", generate)
    with pytest.raises(ProviderError, match="引用"):
        await answer_question(db, "alice", "loss", "session", "lesson", [], "real")
    assert not list(db.scalars(select(Chat)))


@pytest.mark.asyncio
async def test_summary_every_item_has_revision_no_invented_owner(db):
    segment = seed_sentence(db)
    db.add(Translation(segment_id=segment.id, source_revision=1, translation_revision=1, text="梯度下降最小化损失函数。", mode="demo"))
    db.commit()
    result = await summarize(db, "lesson", "alice")
    db.commit()
    from app.models import Stage
    stage = db.get(Stage, result["stage_id"])
    assert stage.knowledge_points[0]["sources"][0]["source_revision"] == 1
    assert stage.action_items == []
    assert (await summarize(db, "lesson", "alice"))["skipped"] == "no_new_stable_sentences"


@pytest.mark.asyncio
async def test_uncited_model_claim_becomes_insufficient_evidence(db, monkeypatch):
    seed_sentence(db)
    db.get(Session, "lesson").mode = "real"
    db.commit()
    async def embeddings(self, texts): return [demo_vector(t) for t in texts]
    async def rerank(self, question, documents, top_n=8): return [(i, 0.8) for i in range(len(documents))]
    async def generate(self, *args, **kwargs): return '{"answer":"An unsupported confident claim.","evidence_ids":[]}'
    monkeypatch.setattr(AliyunProvider, "embeddings", embeddings)
    monkeypatch.setattr(AliyunProvider, "rerank", rerank)
    monkeypatch.setattr(AliyunProvider, "generate", generate)
    result = await answer_question(db, "alice", "loss", "session", "lesson", [], "real")
    assert "证据不足" in result["answer"]
    assert "unsupported" not in result["answer"]
    assert result["citations"] == []


@pytest.mark.asyncio
async def test_upload_atomic_outbox_parse_preview_delete_and_ownership(client, db):
    response = client.post("/api/documents", files={"file": ("notes.docx", make_docx(), "application/octet-stream")})
    assert response.status_code == 201
    document_id = response.json()["id"]
    from app.models import ProcessingTask, Outbox
    task = db.scalar(select(ProcessingTask).where(ProcessingTask.document_id == document_id))
    assert db.scalar(select(Outbox).where(Outbox.task_id == task.id))
    await handle_task("document", task.payload, db)
    db.commit()
    preview = client.get(f"/api/documents/{document_id}").json()
    assert preview["status"] == "ready" and preview["chunks"][0]["location"] == "段落 1"
    assert client.get(f"/api/documents/{document_id}/file").status_code == 200
    result = await answer_question(db, "alice", "gradient descent", "documents", None, [document_id], "demo")
    assert result["citations"][0]["document_id"] == document_id
    key = db.get(Document, document_id).storage_key
    assert client.delete(f"/api/documents/{document_id}").status_code == 200
    assert not list(db.scalars(select(Chunk).where(Chunk.document_id == document_id)))
    assert not list(db.scalars(select(Chat)))
    with pytest.raises(FileNotFoundError):
        get_storage().read(key)
    assert client.get(f"/api/documents/{document_id}").status_code == 404


def test_document_api_rejects_foreign_access_and_missing_key(client, db, monkeypatch):
    db.add(Document(id="foreign", user_id="bob", name="secret.pdf", content_type="application/pdf", storage_key="secret.pdf", status="ready"))
    db.commit()
    assert client.get("/api/documents/foreign").status_code == 404
    assert client.delete("/api/documents/foreign").status_code == 404
    assert client.post("/api/chat", json={"question": "secret", "scope": "documents", "document_ids": ["foreign"], "mode": "demo"}).status_code == 404
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    response = client.post("/api/chat", json={"question": "hello", "scope": "history", "mode": "real"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "missing_api_key"
    assert not list(db.scalars(select(Chat)))


def test_storage_refuses_traversal_and_signed_url_dies_on_delete(client, db):
    storage = get_storage()
    with pytest.raises(ValueError): storage.put("../secret", b"data")
    key = "documents/alice/private.pdf"
    storage.put(key, b"%PDF-private")
    db.add(Document(id="private", user_id="alice", name="private.pdf", content_type="application/pdf", storage_key=key))
    db.commit()
    from urllib.parse import urlsplit
    url = urlsplit(storage.signed_url(key)).path + "?" + urlsplit(storage.signed_url(key)).query
    assert client.get(url).status_code == 200
    assert client.get("/api/storage/signed?token=tampered").status_code == 403
    assert client.delete("/api/documents/private").status_code == 200
    assert client.get(url).status_code == 404


@pytest.mark.asyncio
async def test_summary_continues_bounded_batches(db):
    from app.models import ProcessingTask, Stage
    seed_sentence(db)
    for index in range(150):
        db.add(SegmentRevision(id=f'bulk-{index}', session_id='lesson', stream_id='stream-lesson',
            sentence_id=f'bulk-sentence-{index}', source_revision=1, start_ms=4000+index*1000,
            end_ms=5000+index*1000, text=f'Stable fact {index}', mode='demo'))
    db.commit()
    await summarize(db, 'lesson', 'alice')
    db.commit()
    assert len(db.scalars(select(Stage)).one().sources) == 150
    followup = db.scalars(select(ProcessingTask).where(ProcessingTask.kind == 'summarize')).one()
    assert followup.payload['session_id'] == 'lesson'
    await summarize(db, 'lesson', 'alice')
    db.commit()
    assert sum(len(stage.sources) for stage in db.scalars(select(Stage))) == 151
