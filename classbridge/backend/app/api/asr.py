from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from app.api.auth import current_user
from app.db import get_db
from app.models import User, ASRProfile
from app.providers.asr.registry import REGISTRY
from app.services import asr_profiles as profiles
from pydantic import BaseModel,ConfigDict
import asyncio
from app.providers.aliyun import ProviderError
from app.providers.asr.factory import create_asr_provider

router=APIRouter(prefix='/api/asr',tags=['ASR Models'])


@router.get('/providers')
def providers(user:User=Depends(current_user)):
    return [item.public() for item in REGISTRY.values()]


@router.get('/profiles')
def list_profiles(user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    profiles.bootstrap(db,user);db.commit()
    return [profiles.public(row,user) for row in db.query(ASRProfile).filter_by(user_id=user.id).order_by(ASRProfile.created_at)]


def set_default(db,user_id):
    db.query(ASRProfile).filter_by(user_id=user_id,is_default=True).update({'is_default':False})
    db.flush()


@router.post('/profiles',status_code=201)
def create(body:profiles.ProfileInput,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    values=profiles.validate_data(body.model_dump());profiles.bootstrap(db,user)
    if db.query(ASRProfile).filter_by(user_id=user.id).count()>=50:raise HTTPException(409,detail='最多保存 50 个模型配置')
    if values['is_default']:set_default(db,user.id)
    row=ASRProfile(user_id=user.id,**values);db.add(row);db.commit()
    return profiles.public(row,user)


@router.patch('/profiles/{profile_id}')
def edit(profile_id:str,body:profiles.ProfilePatch,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    profiles.lock_owner(db,user.id);row=profiles.owned(db,user.id,profile_id)
    profiles.prevent_in_use(db,user.id,profile_id)
    values=profiles.validate_data({**profiles.data_of(row),**body.model_dump(exclude_unset=True)})
    if values['is_default']:set_default(db,user.id)
    for key,value in values.items():setattr(row,key,value)
    db.commit();return profiles.public(row,user)


@router.delete('/profiles/{profile_id}')
def delete(profile_id:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    profiles.lock_owner(db,user.id);row=profiles.owned(db,user.id,profile_id)
    profiles.prevent_in_use(db,user.id,profile_id)
    db.delete(row);db.commit()
    return {'ok':True} # No cascading relation from profile to session/stream.


class ValidationRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    live: bool=False
    confirm_paid: bool=False


paid_checks=set()


@router.post('/profiles/{profile_id}/validate')
async def validate(profile_id:str,body:ValidationRequest=ValidationRequest(),user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    row=profiles.owned(db,user.id,profile_id);status=profiles.configuration_status(row,user)
    if not body.live or not status['valid']:return {**status,'paid_request':False}
    if not body.confirm_paid:raise HTTPException(422,detail='真实连通测试可能计费，请明确确认。')
    profiles.prevent_in_use(db,user.id,profile_id)
    if paid_checks:raise HTTPException(409,detail='已有模型连通测试正在运行，请稍后重试。')
    paid_checks.add(user.id)
    try:
        provider=create_asr_provider(snapshot=profiles.snapshot(row,user))
        async def audio():
            for _ in range(10):
                yield bytes(640)
                await asyncio.sleep(.02)
        async with asyncio.timeout(40):
            async for _ in provider.stream_asr(audio()):pass
        return {'valid':True,'code':'connection_verified','message':'200ms 静音连通测试完成；不代表课堂识别质量已验证。','paid_request':True}
    except ProviderError as exc:return {'valid':False,'code':exc.code,'message':exc.message,'paid_request':True}
    except TimeoutError:return {'valid':False,'code':'timeout','message':'连通测试超时，没有自动重试。','paid_request':True}
    finally:paid_checks.discard(user.id)
