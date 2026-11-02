# ClassBridge implementation contract

Independent directory `classbridge/`. All application paths below relative to it.
API prefix `/api`. Frontend Vite proxies `/api`, `/ws` to localhost:8000.
Cookie based HttpOnly auth; CSRF by checking Origin on mutating requests and websocket, same-origin deployment.
No public registration. `python -m app.cli create-admin --username admin` interactively sets password; local demo may use explicit CLI password env. No default remote credential.

## Common response contract
- GET `/api/health` health; GET `/api/auth/me` user; POST `/api/auth/login` {username,password}; POST `/api/auth/logout`.
- GET `/api/settings` configuration without secrets plus model readiness; PATCH saves user's display/terminology preferences.
- GET `/api/sessions?q=` returns array; POST {title,kind:'classroom'|'meeting'|'interview',mode:'demo'|'real',retain_audio:false} returns session object.
- GET `/api/sessions/{id}` returns session with segments array and stages array. DELETE deletes; DELETE `/{id}/segments` clears (both reject active capture).
- POST `/{id}/summarize`; GET `/{id}/export?format=md|txt|pdf` download. POST `/{id}/reprocess` schedules saved-audio correction.
- GET `/api/documents` array; POST multipart file and optional session_id; DELETE `/{id}`; GET `/{id}` chunks/status; GET `/{id}/file` private original.
- POST `/api/chat` {session_id?,scope:'recent'|'session'|'documents'|'history',document_ids:[],question,mode:'demo'|'real'} returns {answer,citations:[{id,kind:'sentence'|'document',sentence_id?,source_revision?,session_id?,document_id?,page?,quote}],mode}.

## Session & segment
Session fields: id,title,kind,mode,status,retain_audio,created_at,duration_ms,segments?,stages?,audio_status?.
Segment fields: sentence_id,stream_id,source_revision,translation_revision,start_ms,end_ms,text,translation,status,mode.
Stage fields: id,topic,summary,knowledge_points,terms,decisions,action_items,source_sentence_ids,sources.

## WebSocket `/ws/sessions/{id}?after_seq=0`
Authenticated cookie. Server replays durable events newer than after_seq then reports session.state; does not automatically capture.
Client JSON {type:'start'} or {type:'stop'} or {type:'capture.gap',reason,duration_ms}; real PCM audio sent as binary int16 LE mono 16000Hz. Demo requires start but does not request microphone; demo independent of real providers.
Server event fields: type,event_id,event_seq,session_id,stream_id,sentence_id,source_revision,translation_revision,start_ms,end_ms,status,mode,text?,translation?,message?,state?. Types transcript.partial/final, translation.partial/final, segment.updated, processing.failed, capture.gap, session.state. Persist final events atomically with outbox tasks. New stream_id for every start. Event_seq 0 may be transient; durable sequences monotonic per session.

## Final implementation reference

See [API.md](API.md) for the delivered contract, [FEATURE_STATUS.md](FEATURE_STATUS.md) for limitations, and [TEST_RESULTS.md](TEST_RESULTS.md) for actual validation.
