"""Frozen schema for revision 0001. Never import live application models here.

Future schema changes belong in new Alembic revisions.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, JSON, ForeignKey, UniqueConstraint, Index
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import declarative_base
Base = declarative_base()


def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)
def idcol(): return Column(String(36), primary_key=True, default=uid)


class User(Base):
    __tablename__ = 'users'
    id = idcol()
    username = Column(String(100), nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    settings = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)


class LoginSession(Base):
    __tablename__ = 'login_sessions'
    id = idcol()
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class Session(Base):
    __tablename__ = 'sessions'
    id = idcol()
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title = Column(String(250), nullable=False)
    kind = Column(String(20), default='classroom', nullable=False)
    mode = Column(String(10), default='demo', nullable=False)
    status = Column(String(20), default='idle', nullable=False)
    retain_audio = Column(Boolean, default=False, nullable=False)
    duration_ms = Column(Integer, default=0, nullable=False)
    event_seq = Column(Integer, default=0, nullable=False)
    active_stream_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class RecognitionStream(Base):
    __tablename__ = 'recognition_streams'
    id = idcol()
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    status = Column(String(20), default='active', nullable=False)
    offset_ms = Column(Integer, default=0, nullable=False)
    ended_ms = Column(Integer, nullable=True)
    mode = Column(String(10), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)


class SegmentRevision(Base):
    __tablename__ = 'segment_revisions'
    id = idcol()
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    stream_id = Column(String(36), ForeignKey('recognition_streams.id', ondelete='CASCADE'), nullable=False)
    sentence_id = Column(String(120), nullable=False, index=True)
    source_revision = Column(Integer, default=1, nullable=False)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    mode = Column(String(10), nullable=False)
    status = Column(String(20), default='final', nullable=False)
    speaker = Column(String(100), nullable=True)
    provenance = Column(String(30), default='realtime', nullable=False)
    latency = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (UniqueConstraint('session_id', 'sentence_id', 'source_revision'),)


class Translation(Base):
    __tablename__ = 'translations'
    id = idcol()
    segment_id = Column(String(36), ForeignKey('segment_revisions.id', ondelete='CASCADE'), nullable=False, index=True)
    source_revision = Column(Integer, nullable=False)
    translation_revision = Column(Integer, default=1, nullable=False)
    text = Column(Text, nullable=False)
    status = Column(String(20), default='final', nullable=False)
    mode = Column(String(10), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (UniqueConstraint('segment_id', 'translation_revision'),)


class Event(Base):
    __tablename__ = 'events'
    id = idcol()
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    event_seq = Column(Integer, nullable=False)
    type = Column(String(40), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (UniqueConstraint('session_id', 'event_seq'),)


class ProcessingTask(Base):
    __tablename__ = 'processing_tasks'
    id = idcol()
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=True, index=True)
    document_id = Column(String(36), ForeignKey('documents.id', ondelete='CASCADE'), nullable=True, index=True)
    kind = Column(String(40), nullable=False)
    status = Column(String(20), default='pending', nullable=False)
    idempotency_key = Column(String(250), nullable=False, unique=True)
    payload = Column(JSON, default=dict, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    error = Column(Text, nullable=True)
    result = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class Outbox(Base):
    __tablename__ = 'outbox'
    id = idcol()
    task_id = Column(String(36), ForeignKey('processing_tasks.id', ondelete='CASCADE'), nullable=False, unique=True)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)


class Stage(Base):
    __tablename__ = 'stages'
    id = idcol()
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    topic = Column(String(500), nullable=False)
    summary = Column(Text, nullable=False)
    knowledge_points = Column(JSON, default=list, nullable=False)
    terms = Column(JSON, default=list, nullable=False)
    decisions = Column(JSON, default=list, nullable=False)
    action_items = Column(JSON, default=list, nullable=False)
    sources = Column(JSON, default=list, nullable=False)
    mode = Column(String(10), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)


class Fact(Base):
    __tablename__ = 'facts'
    id = idcol()
    stage_id = Column(String(36), ForeignKey('stages.id', ondelete='CASCADE'), nullable=False)
    kind = Column(String(30), nullable=False)
    text = Column(Text, nullable=False)
    sources = Column(JSON, default=list, nullable=False)


class ActionItem(Base):
    __tablename__ = 'action_items'
    id = idcol()
    stage_id = Column(String(36), ForeignKey('stages.id', ondelete='CASCADE'), nullable=False)
    text = Column(Text, nullable=False)
    owner = Column(String(250), nullable=True)
    due_original = Column(String(250), nullable=True)
    due_normalized = Column(String(250), nullable=True)
    due_basis = Column(Text, nullable=True)
    sources = Column(JSON, default=list, nullable=False)


class Document(Base):
    __tablename__ = 'documents'
    id = idcol()
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='SET NULL'), nullable=True, index=True)
    name = Column(String(500), nullable=False)
    content_type = Column(String(100), nullable=False)
    storage_key = Column(String(500), nullable=False)
    version = Column(Integer, default=1, nullable=False)
    status = Column(String(30), default='pending', nullable=False)
    error = Column(Text, nullable=True)
    size_bytes = Column(Integer, default=0, nullable=False)
    page_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)


class Chunk(Base):
    __tablename__ = 'chunks'
    id = idcol()
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    document_id = Column(String(36), ForeignKey('documents.id', ondelete='CASCADE'), nullable=True, index=True)
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=True, index=True)
    sentence_id = Column(String(120), nullable=True)
    source_revision = Column(Integer, default=1, nullable=False)
    page = Column(Integer, nullable=True)
    position = Column(Integer, default=0, nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(JSON().with_variant(Vector(1024), 'postgresql'), nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)


class Chat(Base):
    __tablename__ = 'chats'
    id = idcol()
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    mode = Column(String(10), nullable=False)
    scope = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)


class Citation(Base):
    __tablename__ = 'citations'
    id = idcol()
    chat_id = Column(String(36), ForeignKey('chats.id', ondelete='CASCADE'), nullable=False)
    chunk_id = Column(String(36), ForeignKey('chunks.id', ondelete='SET NULL'), nullable=True)
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=True)
    document_id = Column(String(36), ForeignKey('documents.id', ondelete='CASCADE'), nullable=True)
    sentence_id = Column(String(120), nullable=True)
    source_revision = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False)
    page = Column(Integer, nullable=True)
    quote = Column(Text, nullable=False)


class AudioAsset(Base):
    __tablename__ = 'audio_assets'
    id = idcol()
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    stream_id = Column(String(36), ForeignKey('recognition_streams.id', ondelete='CASCADE'), nullable=False)
    storage_key = Column(String(500), nullable=False)
    offset_ms = Column(Integer, default=0, nullable=False)
    duration_ms = Column(Integer, default=0, nullable=False)
    status = Column(String(20), default='writing', nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    gaps = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)
