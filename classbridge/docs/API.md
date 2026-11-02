# HTTP 与 WebSocket 接口

本地在线OpenAPI：<http://127.0.0.1:8000/api/docs>。以 `/api/openapi.json` 自动生成的字段约束为准。API与前端同源；Cookie为HttpOnly、SameSite=Strict，生产Secure。所有写请求需要匹配 `ALLOWED_ORIGINS` 的Origin。不存在公开注册接口。

## HTTP

| 方法 / 路径 | 用途 |
| --- | --- |
| GET `/api/health` | 数据库连接和服务版本，不含密钥 |
| POST `/api/auth/login` | `{username,password}` 登录 |
| GET `/api/auth/me` / POST `/api/auth/logout` | 当前身份 / 撤销登录 |
| GET `/api/sessions?q=` | 私有会话及原文/译文搜索 |
| POST `/api/sessions` | `{title,kind,mode,retain_audio}`，kind为classroom/meeting/interview，mode为demo/real |
| GET `/api/sessions/{id}` | 最新稳定字幕、阶段、任务、缺口、音频状态、事件序号 |
| DELETE `/api/sessions/{id}/segments` | 清空字幕及其派生内容，保留资料；录音中拒绝 |
| DELETE `/api/sessions/{id}` | 删除会话、关联资料及私有文件、派生内容；录音中拒绝 |
| POST `/api/sessions/{id}/summarize` | 提交阶段提取 |
| POST `/api/sessions/{id}/reprocess` | 对可用保留音频提交会后校正 |
| GET `/api/sessions/{id}/versions/{sentence_id}` | 查具体原文身份的历史版本 |
| PATCH `/api/sessions/{id}/speakers` | `{mapping:{编号:人工名称}}` |
| POST `/api/sessions/{id}/exports` | `{format:"md"或"txt"或"pdf"}`，返回task_id |
| GET `/api/sessions/{id}/exports/{task_id}` | 导出状态和完成后的download_url |
| GET `/api/sessions/{id}/exports/{task_id}/file` | 私有文件下载，验证所属会话 |
| GET `/api/sessions/{id}/export?format=md` | 兼容直接导出，小样本测试使用 |
| GET / PATCH `/api/settings` | 字幕字号、主题、术语、保留策略、只读模型状态 |
| GET `/api/documents?session_id=` | 当前用户资料 |
| POST `/api/documents` | multipart：file、可选session_id、mode；PDF/PPTX/DOCX，40MB |
| GET `/api/documents/{id}` / `/{id}/file` | 提取文本及位置 / 私有原始文件 |
| DELETE `/api/documents/{id}` | 文件、块、向量及关联派生引用删除 |
| POST `/api/chat` | `{question,scope,session_id,document_ids,mode}` |
| GET `/api/chat?session_id=&mode=` | 私有问答历史及已验证引用 |

问答scope为recent（最近10分钟）、session、documents、history。session/recent必须提供会话；documents必须明确选择资料。服务端验证所有权及模式，不能靠传ID越权。真实模式缺失密钥返回明确503，不生成模拟回答。

## 本站WebSocket

`/ws/sessions/{session_id}?after_seq=最后已处理的持久化序号`，需要登录Cookie和合法Origin。连接成功只恢复记录，不开启麦克风。

客户端控制消息：

```json
{"type":"start","request_id":"当前页面本次开始请求的唯一编号"}
{"type":"stop"}
{"type":"ping"}
{"type":"capture.gap","reason":"页面切到后台","duration_ms":null}
```

真实模式先进入preparing：申请麦克风并初始化暂停的AudioWorklet，不产生PCM帧。后端收到上游task-started后发送session.state（state=recording、ready=true、request_id、offset_ms、captured_ms）；前端仅接受当前开始请求的就绪事件，随后开启Worklet并计时，再发送二进制PCM16LE、16000Hz、单声道；每帧20ms/640bytes。取消准备立即释放麦克风并取消上游准备，不产生假录音时长。旧版客户端在就绪前发送音频会明确拒绝，更新时需重启后端并刷新前端。

模拟模式不发送音频。音频原始队列最多约2秒；超限明确停止并记录缺口，不无限积压。新的识别任务获得新的stream_id。后端负责将阿里云原生事件转换成本站格式。

Session返回captured_ms（已结束识别流的累计采音时长），与duration_ms（含暂停间隔的证据时间轴终点）分开。105分钟限制使用累计采音时长，字幕、引用和音频仍使用原时间轴offset_ms，不改写历史来源时间。

事件公共字段：`type,event_id,event_seq,session_id,stream_id,mode`；按适用性附 `sentence_id,source_revision,translation_revision,start_ms,end_ms,status,text,translation`。时间单位毫秒，时间范围相对会话，音频连接有独立偏移。事件示意值不代表真实识别结果：

```json
{"type":"transcript.final","event_id":"uuid","event_seq":12,"session_id":"uuid","stream_id":"new-stream-uuid","sentence_id":"stream-uuid:0","source_revision":2,"translation_revision":0,"start_ms":0,"end_ms":3500,"status":"final","mode":"real","text":"source text"}
```

| type | 处理 |
| --- | --- |
| transcript.partial | 当前句临时原文，可替换，不入索引 |
| transcript.final | 稳定原文，新版本持久化；同时事务创建后续任务 |
| translation.partial | 临时译文；source_status=final时是稳定原文的流式译文 |
| translation.final | 绑定原文版本的最终译文 |
| segment.updated | 版本更新或retired墓碑，不能简单字符串追加 |
| segment.suggestion | 绑定原文版本的辅助校正建议，或suggestion=null表示忽略；独立于原文/译文，不直接入索引 |
| processing.failed | 可读错误code/message；带task_kind的后台失败不等同麦克风断线 |
| capture.gap | 已知或未知时长缺口，不能恢复未上传音频 |
| capture.health | 真实采集中每2秒的瞬时诊断，不入数据库、不重放；前端仅接收当前stream_id |
| session.state | 连接/采集/收尾/停止/恢复状态及队列信息 |
| connection.pong | 对ping的瞬时回应，event_seq=0，不改变会话/录音状态、不投递模型任务 |

持久化事件序号严格递增，按after_seq重放。瞬时中间事件 `event_seq=0` 不重放；最终原文和最终译文、收尾状态、缺口可恢复。稳定原文翻译中的持久化partial允许在停止后完成，但低版本结果不能覆盖定稿。清空保留序号单调性并发送cleared标记，防止旧消息复活。关闭页面后恢复必须手动再次开启采音。

浏览器建连超时为10秒，连续失败最多自动重试6次；快速连接后立即断开的循环不会重置次数。连接稳定30秒后重置失败次数。每10秒发送一次ping，等待响应最长45秒（留出后端收尾时间），任意服务端消息都可确认连接仍可用。回到前台或网络恢复时主动检查连接，旧连接回调被丢弃；任何连接恢复均不自动开始采音。断线状态下可随时点击“重新连接”。

音频发送和识别接收任务共同监测，发送失败立即传播，不等待下一条识别消息。单次发送的应用超时由ASR_SEND_TIMEOUT_SECONDS配置，默认5秒；它不是传给阿里云的参数。网络包突发到达时让出事件循环供发送任务消费。退出时先取消并回收发送/接收子任务，再关闭连接，保留首次失败，不让清理错误覆盖原始积压原因。processing.failed可带diagnostics：队列帧数/时长、已发送音频时长、发送耗时、距上次发送/上游事件的时长和上游关闭码；不包含音频、字幕、密钥、原始响应或关闭原因文本。

## 引用与错误

capture.health携带diagnostics：received_audio_ms、sent_audio_ms、queued_audio_ms、last_audio_age_ms（未收到时为null）、last_transcript_age_ms（尚无结果时从采集就绪计时）、transcript_events、input_dbfs（最近一秒收到的PCM电平，不是语音概率）。供应商心跳只更新last_upstream_event_age_ms，不冒充文本结果。已发送表示交给WebSocket发送操作，不表示云端完成识别。当前stream_id不匹配的诊断不会更新页面。

GET/PATCH /api/settings支持asr_language_mode：auto（默认，省略云端language_hints）、ko_en（["ko","en"]）、ko（["ko"]），其他值422。PATCH仅更新显式传入字段，保留术语和人工说话人映射等其他偏好。此选项是输入语种提示，不是翻译目标；target_language仍为zh-CN。每次新建上游任务读取当前用户的设置，在session.state的ready事件中回传asr_language_mode，前端显示实际采用值。中途修改不改变正在进行的上游任务，下次开始录音时生效；旧后端没有报告时显示“服务端未报告”。

新增asr_hotword_weight（2/3/4，默认2）及asr_context（字符串，最多400字符，默认空）。字段超限返回422，不修改已有设置。课程背景仅使用当前用户明确填写的内容，不自动使用可能错误的历史ASR字幕。GET返回只读asr_terms_status={enabled_count,skipped:[{index,reason}]}，index为原术语列表0基索引；无效词条在原列表保留便于编辑/翻译，但不送入识别热词。NFC规范化后按官方长度规则过滤，重复原词合并。session.state ready携带asr_enhancement={hotword_count,weight,context_chars}，只显示本次请求采用的数量，不宣称模型一定遵循或准确率提高。

`asr_assist_enabled`（默认false）控制文本辅助推断。启用后真实模式的4–1500字符、含至少2个韩文音节的稳定原文可进入抽查；每会话每15秒最多安排一句，最多4个待处理任务，不是每句都检查。模型由服务端CORRECTION_MODEL配置（默认qwen3.7-flash）。任务kind=suggest_correction与字幕/outbox同事务，单次尝试，失败后不自动重新调用；不据此承诺云端计费结果。关闭功能后待处理任务跳过，在途响应不再发布建议。

建议只使用当前用户的术语/背景快照及同会话此前两分钟内最多3条稳定原文。前文也可能有ASR错误，不是音频核实。输出最多3处可定位的小改动，服务端校验原片段唯一性、证据ID、非重叠、变化比例、数字及常见否定词保护。term替换必须在已填术语/背景中出现。语法/近音判断仍可能错误，不提供虚假的声学置信度。结果保存在ProcessingTask.result；不增加数据库表或迁移。

会话详情的每个segment可带suggestion，含task_id、source_revision、suggested_text、edits、服务端解析后的evidence及固定audio_verified=false。事件与任务结果在同一事务提交。推测不进入原文、翻译、RAG、摘要或导出；模型不能自行确认。前端按原文版本与event_seq处理，HTTP快照携带snapshot_seq防止旧快照恢复已忽略建议。

`POST /api/sessions/{session_id}/corrections/{task_id}/accept`：登录、Origin及会话/任务归属校验；只可在停止录音并收尾后使用。过期来源返回409。接受建议创建source_revision+1、provenance=user_correction的新版本，并事务投递翻译、索引、摘要任务；旧原文及引用保留。重复采纳不重复创建版本。

`POST /api/sessions/{session_id}/corrections/{task_id}/dismiss`：忽略建议并持久化null事件，原文保留，可在录音中执行。关闭或删除会话时按现有任务级联规则处理建议；删除后迟到结果无法重建数据。

翻译/向量等HTTP请求复用经过校验的TLS上下文，首次证书加载在线程执行，避免阻塞实时收发；每个HTTP客户端仍按请求关闭。课程术语的原词映射到ASR官方vocabulary，默认权重2、最多200项，语种提示按用户asr_language_mode配置；不符合官方热词长度规则的项不送入ASR。

采音控制事件以request_id和stream_id绑定本次开始，包含开始拒绝、preparing、ready、processing、processing.failed和stopped。前端保留身份直至收尾结束，同时检查请求前event_seq，重放旧停止/失败事件不会影响新采音。后台任务失败仍通过task_kind区分。识别源空结果/重复回调不增长版本，定稿后忽略同句partial；同流同句已见定稿按原文及时间戳去重。真实不同的定稿保留新版本；人工校正使用独立版本接口。

引用返回服务端分配的id/label、原句或chunk_id、来源版本、时间范围或页码/位置和quote。服务端只接受候选集内的模型证据编号，并重复验证用户权限、版本、原文；没有可验证引用的模型回答改为证据不足。引用不是可执行指令。

常见错误使用 `detail:{code,message}`（参数验证保留FastAPI标准422）：origin_forbidden、mode_mismatch、missing_api_key、missing_workspace、authentication_failed、model_permission、region_mismatch、model_unavailable、quota_exhausted、rate_limited、timeout、format_error、invalid_citation、source_deleted。未知资源/他人资源返回404，未登录401。日志不记录密钥、整段音频或模型完整输入。

`/api/storage/signed` 是仅供云端读取特定文件的短期签名能力路由，默认不公开目录；验证签名、过期与数据库资源存活状态。反向代理必须关闭此路径的访问日志。它不替代普通用户文件接口的登录鉴权。
