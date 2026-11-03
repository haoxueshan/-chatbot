import asyncio
import contextlib
import time
from collections import defaultdict,deque
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.config import settings
from app.db import SessionLocal, init_db


@asynccontextmanager
async def lifespan(app):
    if settings.environment=='production':
        if len(settings.secret_key)<32 or settings.secret_key.startswith(('development','replace-')):
            raise RuntimeError('Production requires a random SECRET_KEY of at least 32 characters')
        if not settings.cookie_secure:raise RuntimeError('Production requires COOKIE_SECURE=true and HTTPS')
        if settings.database_url.startswith('sqlite'):raise RuntimeError('Production requires PostgreSQL and pgvector')
        if not settings.origins:raise RuntimeError('Production requires explicit ALLOWED_ORIGINS')
        if settings.task_mode!='celery':raise RuntimeError('Production requires TASK_MODE=celery')
        if any(not value.startswith('https://') for value in settings.origins):raise RuntimeError('Production requires HTTPS ALLOWED_ORIGINS')
    else:init_db()
    # An interrupted API process cannot keep a phantom microphone running after restart.
    from app.models import Session, RecognitionStream
    from app.services.events import emit
    from app.services.retired_tasks import cancel_retired_tasks
    with SessionLocal() as db:
        cancel_retired_tasks(db)
        for row in db.query(Session).filter(Session.status.in_(['preparing','recording','processing'])):
            emit(db,row,'capture.gap',message='服务器重启，未保存音频无法恢复',duration_ms=None,status='gap')
            row.status='stopped';row.active_stream_id=None
            emit(db,row,'session.state',state='stopped',status='stopped')
        for stream in db.query(RecognitionStream).filter(RecognitionStream.status.in_(['preparing','active'])):stream.status='interrupted'
        db.commit()
    worker=None
    if settings.task_mode=='local':
        from app.workers.tasks import local_worker_loop
        worker=asyncio.create_task(local_worker_loop())
    yield
    if worker:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):await worker


app=FastAPI(title=settings.app_name,version='1.0.0',lifespan=lifespan,docs_url='/api/docs',openapi_url='/api/openapi.json')
windows=defaultdict(deque)


from app.providers.aliyun import ProviderError
@app.exception_handler(ProviderError)
async def provider_error_handler(request,exc):
    status=503 if exc.code in ('missing_api_key','missing_workspace','invalid_endpoint','region_mismatch','model_permission','model_unavailable') else (429 if exc.code=='rate_limited' else 502)
    return JSONResponse(status_code=status,content={'detail':{'code':exc.code,'message':exc.message}})


@app.middleware('http')
async def security(request:Request,call_next):
    origin=request.headers.get('origin')
    if request.method in ('POST','PATCH','PUT','DELETE'):
        if origin not in settings.origins:
            return JSONResponse(status_code=403,content={'detail':{'code':'origin_forbidden','message':'请求来源不受信任'}})
    if request.url.path.startswith('/api/') and request.url.path!='/api/health':
        category='login' if request.url.path=='/api/auth/login' else ('model' if request.url.path.endswith('/chat') else 'api')
        key=(request.client.host if request.client else 'unknown',category)
        stamp=time.monotonic();queue=windows[key]
        while queue and queue[0]<stamp-60:queue.popleft()
        limit={'login':10,'model':20,'api':240}[category]
        if len(queue)>=limit:return JSONResponse(status_code=429,content={'detail':{'code':'rate_limited','message':'请求过于频繁，请稍后再试'}},headers={'Retry-After':'60'})
        queue.append(stamp)
        if len(windows)>10000:
            for stale in [k for k,v in windows.items() if not v or v[-1]<stamp-60]:windows.pop(stale,None)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Cache-Control']='no-store'
    response.headers['X-Frame-Options']='DENY'
    return response


@app.get('/api/health',tags=['Operations'])
def health():
    with SessionLocal() as db:db.execute(text('SELECT 1'))
    return {'status':'ok','database':'connected','task_mode':settings.task_mode,'version':'1.0.0'}


from app.api.auth import router as auth_router
from app.api.sessions import router as sessions_router
from app.api.settings import router as settings_router
from app.ws.live import router as ws_router
app.include_router(auth_router);app.include_router(sessions_router);app.include_router(settings_router);app.include_router(ws_router)
try:
    from app.api.knowledge import router as knowledge_router
    app.include_router(knowledge_router)
except ModuleNotFoundError as exc:
    if exc.name!='app.api.knowledge':raise
