"""Private ASR configuration, serialized mutations, immutable stream snapshots."""
import copy
import uuid
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import update
from app.config import settings
from app.models import User, Session, ASRProfile
from app.providers.errors import ProviderError
from app.providers.asr.registry import get_provider
from app.providers.asr.factory import create_asr_provider
from app.services.asr_options import asr_language_hints


class ProfileInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    provider: str=Field(min_length=1,max_length=32)
    model_id: str=Field(min_length=1,max_length=120,pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$')
    display_name: str=Field(min_length=1,max_length=100)
    language_hints: list[str] | None=Field(default=None,max_length=4)
    enabled: bool=True
    is_default: bool=False
    credential_ref: str=Field(max_length=80)
    provider_options: dict=Field(default_factory=dict)


class ProfilePatch(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    provider: str | None=None
    model_id: str | None=None
    display_name: str | None=None
    language_hints: list[str] | None=None
    enabled: bool | None=None
    is_default: bool | None=None
    credential_ref: str | None=None
    provider_options: dict | None=None


FIELDS=tuple(ProfileInput.model_fields)


def lock_owner(db,user_id):
    # Row write lock on PG, writer serialization on SQLite; no settings changes.
    db.execute(update(User).where(User.id==user_id).values(settings=User.settings).execution_options(synchronize_session=False))


def bootstrap(db,user):
    lock_owner(db,user.id)
    db.refresh(user)
    if not (user.settings or {}).get('asr_profiles_initialized'):
        if not db.query(ASRProfile).filter_by(user_id=user.id).first():
            provider=settings.asr_provider
            definition=get_provider(provider)
            db.add(ASRProfile(id=str(uuid.uuid5(uuid.NAMESPACE_URL,'classbridge-asr:'+user.id)),user_id=user.id,
                provider=provider,model_id=settings.asr_model if provider=='aliyun' else definition.default_model,
                display_name='原默认 '+definition.name,credential_ref=definition.credential_ref,
                enabled=True,is_default=True,language_hints=None,provider_options={}))
        user.settings={**(user.settings or {}),'asr_profiles_initialized':True}
        db.flush()


def owned(db,user_id,profile_id):
    row=db.query(ASRProfile).filter_by(id=profile_id,user_id=user_id).first()
    if not row:raise HTTPException(404,detail={'code':'asr_profile_not_found','message':'模型配置不存在或已删除，请重新选择。'})
    return row


def data_of(row):return {key:copy.deepcopy(getattr(row,key)) for key in FIELDS}


def validate_data(data):
    try:
        value=ProfileInput.model_validate(data)
        definition=get_provider(value.provider)
        if value.credential_ref!=definition.credential_ref:raise ValueError('请选择供应商对应的服务器密钥引用')
        if value.language_hints is not None:
            if len(set(value.language_hints))!=len(value.language_hints) or any(h not in definition.languages for h in value.language_hints):
                raise ValueError('语言提示不受此 Adapter 支持或存在重复')
        options=definition.options.model_validate(value.provider_options).model_dump(exclude_none=True)
        advanced=('max_sentence_silence','multi_threshold_mode_enabled','speech_noise_threshold','keep_dialect')
        if value.provider=='aliyun' and value.model_id!=definition.default_model and any(key in options for key in advanced):
            raise ValueError('当前模型的可选 VAD 参数兼容性尚未验证')
        if any(not term.strip() or len(term)>128 for term in options.get('terms',[])):
            raise ValueError('术语须为 1–128 字符')
        if value.is_default and (not value.enabled or definition.adapter is None):
            raise ValueError('默认模型必须启用且已接入')
        return {**value.model_dump(),'provider_options':options}
    except (ValidationError,ValueError,ProviderError) as exc:
        # Never echo arbitrary request fields (a mistakenly pasted secret included).
        message=str(exc) if isinstance(exc,ValueError) and not isinstance(exc,ValidationError) else '模型字段、语言或供应商参数无效；不接受 URL、密钥正文或未知参数。'
        raise HTTPException(422,detail={'code':'invalid_asr_profile','message':message}) from exc


def snapshot(row,user=None):
    data={'profile_id':row.id,**data_of(row)}
    data['language_hints_source']='user' if data['language_hints'] is None else 'model'
    if data['language_hints'] is None and user is not None:
        data['language_hints']=asr_language_hints((user.settings or {}).get('asr_language_mode','auto')) or []
    data['runtime']={key:getattr(settings,key) for key in ('asr_ws_url','dashscope_workspace_id','dashscope_region',
        'model_timeout_seconds','asr_event_timeout_seconds','asr_finish_timeout_seconds','asr_send_timeout_seconds',
        'aliyun_asr_batch_enabled','aliyun_asr_batch_ms','aliyun_asr_batch_max_wait_ms')}
    return data


def configuration_status(row,user=None):
    try:
        if not row.enabled:raise ProviderError('asr_profile_disabled','模型已停用。')
        create_asr_provider(snapshot=snapshot(row,user)).ensure_configured()
        return {'valid':True,'code':'configured_unverified','message':'本地配置有效；未验证账号模型权限，未调用付费 API。'}
    except ProviderError as exc:return {'valid':False,'code':exc.code,'message':exc.message}


def public(row,user=None):
    return {'id':row.id,**data_of(row),'created_at':row.created_at.isoformat(),'updated_at':row.updated_at.isoformat(),
        'model_compatibility':{'protocol':'documented' if row.model_id==get_provider(row.provider).default_model else 'unverified',
                             'account_access':'unverified','real_call_verified':False},
        'capabilities':get_provider(row.provider).public()['capabilities'],'validation':configuration_status(row,user)}


def select(db,user,profile_id=None):
    bootstrap(db,user)
    row=owned(db,user.id,profile_id) if profile_id else db.query(ASRProfile).filter_by(user_id=user.id,is_default=True).first()
    if not row:raise HTTPException(409,detail={'code':'asr_default_missing','message':'请在设置中选择默认 ASR 模型。'})
    status=configuration_status(row,user)
    if not status['valid']:raise ProviderError(status['code'],status['message'])
    return row,snapshot(row,user)


def prevent_in_use(db,user_id,profile_id):
    if db.query(Session).filter(Session.user_id==user_id,Session.asr_profile_id==profile_id,
            Session.status.in_(['preparing','recording','processing'])).first():
        raise HTTPException(409,detail={'code':'asr_profile_in_use','message':'模型正在录音或收尾，请先停止并等待完成。'})
