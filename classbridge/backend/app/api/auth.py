import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from app.config import settings
from app.db import get_db
from app.models import User, LoginSession

router = APIRouter(prefix='/api/auth', tags=['Authentication'])
hasher = PasswordHasher()
COOKIE_NAME = 'classbridge_session'


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate_cookie(db, token):
    if not token: return None
    login = db.query(LoginSession).filter_by(token_hash=token_hash(token)).first()
    if not login: return None
    expiry = login.expires_at.replace(tzinfo=timezone.utc) if login.expires_at.tzinfo is None else login.expires_at
    if expiry <= datetime.now(timezone.utc): return None
    return db.get(User, login.user_id)


def current_user(request: Request, db: DBSession = Depends(get_db)):
    user = authenticate_cookie(db, request.cookies.get(COOKIE_NAME))
    if not user: raise HTTPException(401, detail={'code':'authentication_required', 'message':'请先登录'})
    return user


def public_user(user): return {'id':user.id, 'username':user.username}


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@router.post('/login')
def login(body: LoginBody, response: Response, db: DBSession = Depends(get_db)):
    user = db.query(User).filter_by(username=body.username).first()
    try:
        if not user:
            # Equal expensive verification path discourages account enumeration.
            hasher.verify('$argon2id$v=19$m=65536,t=3,p=4$JRL/sI9wt/8eWkJM8yRHrQ$GfABgbNOuAMbCvwJKfzYgpQg63xfnwVYXsN/3Ho+5xs', body.password)
            raise VerificationError('invalid')
        hasher.verify(user.password_hash, body.password)
    except VerificationError:
        raise HTTPException(401, detail={'code':'invalid_credentials','message':'用户名或密码错误'})
    token = secrets.token_urlsafe(48)
    db.add(LoginSession(user_id=user.id, token_hash=token_hash(token), expires_at=datetime.now(timezone.utc)+timedelta(days=7)))
    db.commit()
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=settings.cookie_secure, samesite='strict', max_age=604800, path='/')
    return public_user(user)


@router.get('/me')
def me(user: User = Depends(current_user)): return public_user(user)


@router.post('/logout')
def logout(request: Request, response: Response, db: DBSession = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.query(LoginSession).filter_by(token_hash=token_hash(token)).delete()
        db.commit()
    response.delete_cookie(COOKIE_NAME, path='/')
    return {'ok':True}
