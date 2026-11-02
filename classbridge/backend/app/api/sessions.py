from io import BytesIO
from html import escape
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from app.schemas.sessions import CreateSession, ExportRequest
from typing import Literal
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from app.api.auth import current_user
from app.config import settings
from app.db import get_db
from app.models import User, Session, SegmentRevision, Translation, Event, Stage, AudioAsset, RecognitionStream, Chunk, Chat, Citation, ProcessingTask, Outbox, Fact, ActionItem, Document
from app.services.events import latest_segments, serialize_segment, enqueue, emit
from app.services.timing import captured_duration_ms
from app.schemas.stages import stage_text

router = APIRouter(prefix='/api/sessions', tags=['Sessions'])


def owned_session(db, session_id, user_id):
    row = db.query(Session).filter_by(id=session_id,user_id=user_id).first()
    if not row: raise HTTPException(404,detail={'code':'not_found','message':'会话不存在'})
    return row


def stage_dict(row,current_versions=None):
    return {'id':row.id,'topic':stage_text(row.topic,'阶段重点'),'summary':stage_text(row.summary),'knowledge_points':row.knowledge_points,
            'terms':row.terms,'decisions':row.decisions,'action_items':row.action_items,'sources':row.sources,
            'source_sentence_ids':[s.get('sentence_id') for s in row.sources if s.get('sentence_id')],
            'mode':row.mode,'created_at':row.created_at.isoformat(),
            'superseded':current_versions is not None and any(current_versions.get(s.get('sentence_id'))!=s.get('source_revision') for s in row.sources)}


def session_dict(db, row, detail=False):
    audio = db.query(AudioAsset).filter_by(session_id=row.id).all()
    result = {'id':row.id,'title':row.title,'kind':row.kind,'mode':row.mode,'status':row.status,
      'retain_audio':row.retain_audio,'created_at':row.created_at.isoformat(),'duration_ms':row.duration_ms,
      'event_seq':row.event_seq,'active_stream_id':row.active_stream_id,'captured_ms':captured_duration_ms(db,row.id),
      'audio_status':'available' if any(a.status=='ready' for a in audio) else ('recording' if any(a.status=='writing' for a in audio) else 'not_saved')}
    if detail:
        owner=db.get(User,row.user_id)
        result['speaker_names']=(owner.settings or {}).get('speaker_maps',{}).get(row.id,{}) if owner else {}
        current_segments=latest_segments(db,row.id)
        current_versions={s.sentence_id:s.source_revision for s in current_segments}
        result['segments'] = [serialize_segment(db,s) for s in current_segments]
        result['stages'] = [stage_dict(s,current_versions) for s in db.query(Stage).filter_by(session_id=row.id).order_by(Stage.created_at).all()]
        result['gaps'] = [e.payload for e in db.query(Event).filter_by(session_id=row.id,type='capture.gap').order_by(Event.event_seq).all()]
        result['tasks'] = [{'id':t.id,'kind':t.kind,'status':t.status,'error':t.error} for t in db.query(ProcessingTask).filter_by(session_id=row.id).order_by(ProcessingTask.created_at.desc()).limit(30)]
        result['audio'] = [{'id':a.id,'offset_ms':a.offset_ms,'duration_ms':a.duration_ms,'status':a.status,'expires_at':a.expires_at.isoformat(),'gaps':a.gaps} for a in audio]
    return result


@router.get('')
def list_sessions(q: str = Query('',max_length=250), user: User = Depends(current_user), db: DBSession=Depends(get_db)):
    query = db.query(Session).filter_by(user_id=user.id)
    if q:
        ids = db.query(SegmentRevision.session_id).join(Session,Session.id==SegmentRevision.session_id).filter(Session.user_id==user.id,SegmentRevision.text.contains(q,autoescape=True))
        translated = db.query(SegmentRevision.session_id).join(Translation,Translation.segment_id==SegmentRevision.id).join(Session,Session.id==SegmentRevision.session_id).filter(Session.user_id==user.id,Translation.text.contains(q,autoescape=True))
        query = query.filter(or_(Session.title.contains(q,autoescape=True),Session.id.in_(ids),Session.id.in_(translated)))
    return [session_dict(db,s) for s in query.order_by(Session.created_at.desc()).limit(500)]


@router.post('',status_code=201)
def create_session(body: CreateSession,user: User=Depends(current_user),db:DBSession=Depends(get_db)):
    if body.mode=='real':
        from app.providers.aliyun import AliyunProvider
        AliyunProvider().ensure_configured()
    row = Session(user_id=user.id,**body.model_dump())
    db.add(row);db.commit()
    return session_dict(db,row)


@router.get('/{session_id}')
def get_session(session_id:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    return session_dict(db,owned_session(db,session_id,user.id),True)


def prevent_active(row):
    if row.status in ('preparing','recording','processing'):
        raise HTTPException(409,detail={'code':'session_active','message':'请先停止录音并等待收尾后再操作'})


@router.post('/{session_id}/corrections/{task_id}/{action}')
def decide_correction(session_id:str,task_id:str,action:Literal['accept','dismiss'],user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    row=db.query(Session).filter_by(id=session_id,user_id=user.id).with_for_update().first()
    if not row:raise HTTPException(404,detail='会话不存在')
    task=db.query(ProcessingTask).filter_by(id=task_id,session_id=row.id,user_id=user.id,kind='suggest_correction').with_for_update().first()
    if not task or task.status!='completed':raise HTTPException(404,detail='校正建议不存在')
    result=task.result or {}
    if result.get('status')=='accepted':return {'status':'accepted','source_revision':result.get('accepted_revision')}
    if result.get('status')=='dismissed' and action=='dismiss':return {'status':'dismissed'}
    source=db.get(SegmentRevision,task.payload.get('segment_id'))
    if not source or source.session_id!=row.id or result.get('status')!='suggested':raise HTTPException(409,detail='建议已失效')
    current=next((s for s in latest_segments(db,row.id) if s.sentence_id==source.sentence_id),None)
    if not current or current.id!=source.id:raise HTTPException(409,detail='原文已有新版本，请使用新版本的建议')
    if action=='dismiss':
        task.result={**result,'status':'dismissed'}
        emit(db,row,'segment.suggestion',stream_id=source.stream_id,sentence_id=source.sentence_id,
            source_revision=source.source_revision,suggestion=None)
        db.commit();return {'status':'dismissed'}
    prevent_active(row)
    from app.services.correction import validate_edits
    validated=validate_edits(source.text,{'edits':result.get('edits')},result.get('evidence',[]))
    if not validated or validated['suggested_text']!=result.get('suggested_text'):
        raise HTTPException(409,detail='建议校验失败，原文保留')
    from app.services.events import save_final
    revision=source.source_revision+1
    try:
        save_final(db,row.id,source.stream_id,source.sentence_id,revision,validated['suggested_text'],source.start_ms,source.end_ms,
            provenance='user_correction',force=True,commit=False)
        corrected=db.query(SegmentRevision).filter_by(session_id=row.id,sentence_id=source.sentence_id,source_revision=revision).one()
        corrected.speaker=source.speaker
        task.result={**result,'status':'accepted','accepted_revision':revision}
        enqueue(db,user.id,'summarize',f'summary:correction:{corrected.id}',{'session_id':row.id,'user_id':user.id},session_id=row.id)
        db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,detail='原文已更新，请刷新后查看')
    return {'status':'accepted','source_revision':revision}


def remove_derived(db,row):
    referenced_chats=db.query(Citation.chat_id).filter_by(session_id=row.id)
    db.query(Chat).filter(Chat.id.in_(referenced_chats)).delete(synchronize_session=False)
    db.query(Chunk).filter_by(session_id=row.id,document_id=None).delete(synchronize_session=False)
    for cls in (Citation,Chat,Stage,ProcessingTask,Event,SegmentRevision):
        db.query(cls).filter_by(session_id=row.id).delete(synchronize_session=False)


@router.delete('/{session_id}/segments')
def clear_segments(session_id:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    row=owned_session(db,session_id,user.id);prevent_active(row)
    from app.services.storage import get_storage
    for task in db.query(ProcessingTask).filter_by(session_id=row.id,kind='export'):
        if (task.result or {}).get('storage_key'):get_storage().delete(task.result['storage_key'])
    remove_derived(db,row)
    from app.services.storage import get_storage
    for audio in db.query(AudioAsset).filter_by(session_id=row.id):
        from app.services.storage import delete_audio_files
        delete_audio_files(audio);db.delete(audio)
    db.query(RecognitionStream).filter_by(session_id=row.id).delete(synchronize_session=False)
    # event_seq never resets: reconnect cursors cannot confuse old and new generations.
    row.duration_ms=0
    row.status='idle';row.active_stream_id=None
    emit(db,row,'session.state',state='idle',status='idle',cleared=True)
    db.commit();return {'ok':True}


@router.delete('/{session_id}')
def delete_session(session_id:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    row=owned_session(db,session_id,user.id);prevent_active(row)
    from app.services.storage import get_storage
    store=get_storage()
    for task in db.query(ProcessingTask).filter_by(session_id=row.id,kind='export'):
        if (task.result or {}).get('storage_key'):store.delete(task.result['storage_key'])
    referenced_chats=db.query(Citation.chat_id).filter_by(session_id=row.id)
    db.query(Chat).filter(Chat.id.in_(referenced_chats)).delete(synchronize_session=False)
    from app.services.storage import delete_audio_files
    for audio in db.query(AudioAsset).filter_by(session_id=row.id): delete_audio_files(audio)
    # Delete session-linked documents alongside their originals; no orphan private files.
    for doc in db.query(Document).filter_by(session_id=row.id):
        store.delete(doc.storage_key);db.delete(doc)
    db.delete(row);db.commit();return {'ok':True}


@router.post('/{session_id}/summarize',status_code=202)
def summarize(session_id:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    row=owned_session(db,session_id,user.id)
    rows=latest_segments(db,row.id)
    if not rows: raise HTTPException(409,detail={'code':'no_evidence','message':'尚无稳定原文可提取'})
    fingerprint=':'.join(f'{s.id}' for s in rows)
    import hashlib
    key=hashlib.sha256(fingerprint.encode()).hexdigest()
    task=enqueue(db,user.id,'summarize',f'summary:{row.id}:{key}',{'session_id':row.id,'user_id':user.id},session_id=row.id)
    db.commit();return {'task_id':task.id,'status':task.status}


@router.post('/{session_id}/reprocess',status_code=202)
def reprocess(session_id:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    row=owned_session(db,session_id,user.id);prevent_active(row)
    if row.mode!='real': raise HTTPException(409,detail={'code':'demo_audio_unavailable','message':'模拟会话没有真实音频，无法会后转写'})
    audio=db.query(AudioAsset).filter(AudioAsset.session_id==row.id,AudioAsset.status=='ready',AudioAsset.expires_at>datetime.now(timezone.utc)).all()
    if not audio: raise HTTPException(409,detail={'code':'audio_unavailable','message':'未保留可用音频，无法会后转写'})
    if not settings.dashscope_api_key: raise HTTPException(503,detail={'code':'missing_api_key','message':'服务器未配置模型密钥'})
    task=enqueue(db,user.id,'reprocess',f'reprocess:{row.id}:'+':'.join(a.id for a in audio),{'session_id':row.id,'user_id':user.id,'audio_ids':[a.id for a in audio]},session_id=row.id)
    db.commit();return {'task_id':task.id,'status':task.status}


@router.get('/{session_id}/versions/{sentence_id}')
def versions(session_id:str,sentence_id:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    owned_session(db,session_id,user.id)
    return [serialize_segment(db,r) for r in db.query(SegmentRevision).filter_by(session_id=session_id,sentence_id=sentence_id).order_by(SegmentRevision.source_revision)]


@router.patch('/{session_id}/speakers')
def map_speaker(session_id:str,body:dict,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    row=owned_session(db,session_id,user.id);prevent_active(row)
    mapping=body.get('mapping',{})
    if not isinstance(mapping,dict) or len(mapping)>100: raise HTTPException(422,'无效说话人映射')
    prefs=dict(user.settings or {});speakers=dict(prefs.get('speaker_maps',{}));speakers[session_id]={str(k)[:100]:str(v)[:100] for k,v in mapping.items()};prefs['speaker_maps']=speakers;user.settings=prefs
    db.commit();return {'mapping':speakers[session_id]}


def export_text(db,row,markdown=True):
    lines=[('# ' if markdown else '')+row.title, f'模式：{"模拟演示" if row.mode=="demo" else "真实识别"}', '']
    for s in latest_segments(db,row.id):
        d=serialize_segment(db,s)
        time=f'{s.start_ms//60000:02}:{s.start_ms//1000%60:02}–{s.end_ms//60000:02}:{s.end_ms//1000%60:02}'
        lines.extend([f'{"## " if markdown else ""}{time} · 来源版本 {s.source_revision}',s.text,d['translation'] or '（译文处理中）',''])
    current_versions={s.sentence_id:s.source_revision for s in latest_segments(db,row.id)}
    for stage in db.query(Stage).filter_by(session_id=row.id):
        if stage_dict(stage,current_versions)['superseded']:
            lines.append('【历史阶段：来源已更新，以下结论基于旧版本；请查看新版阶段及原句。】')
        lines.extend([f'{"## " if markdown else ""}{stage_text(stage.topic,"阶段重点")}',stage_text(stage.summary),''])
        for label, items in [('知识点',stage.knowledge_points),('术语',stage.terms),('明确决议',stage.decisions),('行动项',stage.action_items)]:
            if not items:continue
            lines.append(f'{"### " if markdown else ""}{label}')
            for item in items:
                text=item.get('text','')
                if item.get('owner'):text+=f" · 负责人：{item['owner']}"
                if item.get('due_original'):text+=f" · 日期原话：{item['due_original']}（{item.get('due_basis') or '待确认'}）"
                refs=', '.join(f"{source['sentence_id']} v{source['source_revision']}" for source in item.get('sources',[]))
                lines.append(f'- {text}' + (f' [来源：{refs}]' if refs else ''))
            lines.append('')
    return '\n'.join(lines)


@router.get('/{session_id}/export')
def export(session_id:str,format:Literal['md','txt','pdf']='md',user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    row=owned_session(db,session_id,user.id)
    content=export_text(db,row,format=='md')
    headers={'Content-Disposition':f'attachment; filename="classbridge-{row.id}.{format}"'}
    if format!='pdf': return Response(content,media_type='text/markdown' if format=='md' else 'text/plain',headers=headers)
    from app.services.exporting import render_pdf
    return Response(render_pdf(content,row.title),media_type='application/pdf',headers=headers)


@router.post('/{session_id}/exports',status_code=202)
def queue_export(session_id:str,body:ExportRequest,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    row=owned_session(db,session_id,user.id)
    task=enqueue(db,user.id,'export',f'export:{row.id}:{row.event_seq}:{body.format}',{'format':body.format},session_id=row.id)
    db.commit();return {'task_id':task.id,'status':task.status}


def owned_export(db,session_id,task_id,user_id):
    owned_session(db,session_id,user_id)
    task=db.query(ProcessingTask).filter_by(id=task_id,session_id=session_id,user_id=user_id,kind='export').first()
    if not task:raise HTTPException(404,'导出任务不存在')
    return task


@router.get('/{session_id}/exports/{task_id}')
def export_status(session_id:str,task_id:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    task=owned_export(db,session_id,task_id,user.id)
    return {'task_id':task.id,'status':task.status,'error':task.error,
            'download_url':f'/api/sessions/{session_id}/exports/{task_id}/file' if task.status=='completed' else None}


@router.get('/{session_id}/exports/{task_id}/file')
def export_file(session_id:str,task_id:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    task=owned_export(db,session_id,task_id,user.id)
    if task.status!='completed':raise HTTPException(409,'导出尚未完成')
    from app.services.storage import get_storage
    try:content=get_storage().read(task.result['storage_key'])
    except (FileNotFoundError,KeyError):raise HTTPException(404,'导出文件不存在')
    format=task.payload.get('format','pdf')
    return Response(content,media_type={'pdf':'application/pdf','md':'text/markdown','txt':'text/plain'}[format],headers={'Content-Disposition':f'attachment; filename="classbridge-{session_id}.{format}"'})
