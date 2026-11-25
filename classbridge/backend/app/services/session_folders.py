"""Owner-scoped folder operations; deletion only removes classification."""
import unicodedata
from typing import Annotated
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from app.models import SessionFolder, User

MAX_FOLDERS = 100


class FolderInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=240)

    @field_validator('name')
    @classmethod
    def normalize_name(cls, value):
        value = ' '.join(unicodedata.normalize('NFKC', value).split())
        if not value or len(value) > 80 or any(unicodedata.category(c).startswith('C') for c in value):
            raise ValueError('文件夹名称须为 1–80 个字符，且不含控制字符')
        return value


class FolderSelection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    folder_id: str | None = Field(max_length=36)


class BatchFolderSelection(FolderSelection):
    session_ids: list[Annotated[str, Field(min_length=1, max_length=36)]] = Field(
        min_length=1, max_length=100)

    @field_validator('session_ids')
    @classmethod
    def unique_ids(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('会话 ID 不得重复')
        return value


def lock_owner(db, user_id):
    db.execute(update(User).where(User.id == user_id).values(settings=User.settings)
               .execution_options(synchronize_session=False))


def owned_folder(db, user_id, folder_id):
    row = db.query(SessionFolder).filter_by(id=folder_id, user_id=user_id).first()
    if row is None:
        raise HTTPException(404, detail={'code': 'folder_not_found', 'message': '文件夹不存在'})
    return row


def public_folder(row, count=0):
    return {'id': row.id, 'name': row.name, 'session_count': count,
            'created_at': row.created_at.isoformat(), 'updated_at': row.updated_at.isoformat()}


def set_name(db, row, name):
    key = name.casefold()
    duplicate = db.query(SessionFolder).filter_by(user_id=row.user_id, name_key=key)
    if row.id:
        duplicate = duplicate.filter(SessionFolder.id != row.id)
    if duplicate.first():
        raise HTTPException(409, detail={'code': 'folder_name_conflict', 'message': '已有同名文件夹'})
    row.name, row.name_key = name, key


def commit_folder(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail={'code': 'folder_conflict', 'message': '文件夹已发生变化，请刷新后重试'}) from exc