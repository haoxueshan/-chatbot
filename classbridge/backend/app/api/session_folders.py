"""Private, single-level session folder API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession
from app.api.auth import current_user
from app.db import get_db
from app.models import User, Session, SessionFolder
from app.services.session_folders import (
    FolderInput, BatchFolderSelection, MAX_FOLDERS, lock_owner, owned_folder,
    public_folder, set_name, commit_folder,
)

router = APIRouter(prefix='/api/session-folders', tags=['Session folders'])


@router.get('')
def list_folders(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    counts = dict(db.query(Session.folder_id, func.count(Session.id))
                  .filter(Session.user_id == user.id).group_by(Session.folder_id).all())
    rows = db.query(SessionFolder).filter_by(user_id=user.id).order_by(
        SessionFolder.created_at, SessionFolder.id).all()
    return [public_folder(row, counts.get(row.id, 0)) for row in rows]


@router.post('', status_code=201)
def create_folder(body: FolderInput, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    lock_owner(db, user.id)
    if db.query(SessionFolder).filter_by(user_id=user.id).count() >= MAX_FOLDERS:
        raise HTTPException(409, detail={'code': 'folder_limit', 'message': '最多创建 100 个文件夹'})
    row = SessionFolder(user_id=user.id)
    set_name(db, row, body.name)
    db.add(row)
    commit_folder(db)
    return public_folder(row)


@router.post('/move-sessions')
def move_sessions(body: BatchFolderSelection, user: User = Depends(current_user),
                  db: DBSession = Depends(get_db)):
    lock_owner(db, user.id)
    if body.folder_id is not None:
        owned_folder(db, user.id, body.folder_id)
    rows = db.query(Session).filter(
        Session.user_id == user.id, Session.id.in_(body.session_ids)).all()
    if len(rows) != len(body.session_ids):
        raise HTTPException(404, detail={'code': 'session_not_found', 'message': '会话不存在'})
    # Validate the entire batch before changing anything. Classification alone
    # must never alter source revisions, translations, tasks or audio retention.
    for row in rows:
        row.folder_id = body.folder_id
    commit_folder(db)
    return {'ok': True, 'moved': len(rows)}


@router.patch('/{folder_id}')
def rename_folder(folder_id: str, body: FolderInput, user: User = Depends(current_user),
                  db: DBSession = Depends(get_db)):
    lock_owner(db, user.id)
    row = owned_folder(db, user.id, folder_id)
    set_name(db, row, body.name)
    commit_folder(db)
    count = db.query(Session).filter_by(user_id=user.id, folder_id=row.id).count()
    return public_folder(row, count)


@router.delete('/{folder_id}')
def delete_folder(folder_id: str, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    lock_owner(db, user.id)
    row = owned_folder(db, user.id, folder_id)
    # Explicitly clear classification only; never invoke session deletion or
    # touch audio, documents, subtitles, tasks, or citation history.
    db.query(Session).filter_by(user_id=user.id, folder_id=row.id).update(
        {Session.folder_id: None}, synchronize_session=False)
    db.delete(row)
    commit_folder(db)
    return {'ok': True}