# 实时音频可靠性：2026-11-26

基线及执行时 origin/main：`2bafeca170d6a0386391ddbef12c0940b7f1d525`。分支 `fix/asr-pipeline-stability`。
代码提交：`072be3e6a9ca184bdb8873e01a71d44063e8735d`（含配套测试及配置）。

Phase A、B 已实现；Phase C 自动重连识别及音频重放未实现，配置打开时拒绝启动。没有调用真实模型，没有读取用户数据库或密钥，没有修改真实 `.env`、重启用户服务、推送或合并 main。

## 确认的问题与边界

- 原逐帧发送为 640 字节 / 20ms，每秒 50 条音频 WebSocket 消息；2 秒队列保护早于默认 5 秒上游发送超时。队列原来只计算尚未取出的数据，没有统一计算聚合、在途及存档数据。
- 本地 Outbox Worker 与 API 共享事件循环，其中同步数据库/解析操作可能阻塞音频调度。普通后台积压 200 项会终止采集。
- 周期摘要调度的数据库异常会使维护任务退出，继而终止录音。本次先用失败测试复现，再隔离该调度失败；正式原文数据库失败仍按原保护停止。
- 旧 `send_wait_ms` 表示上一次发送耗时，不能描述当前卡住的发送。历史“采集缺口”没有充分区分丢失、延迟和不确定结果。
- WAV 最终发布原来通过 `read_bytes()` 加载整个文件；长录音会产生大内存副本。本次改为文件流上传/分块复制，保留发布失败的私有临时文件。

以上为代码路径和 Mock 证据，不是对某次真实 VPN/云服务故障的唯一根因判定。没有调整 VAD、热词、降噪、重采样、语言选择或翻译预算。

## 实际链路

```text
浏览器 AudioWorklet（仍为 20ms PCM16LE / 16kHz / mono）
 → 本站 WebSocket（运行时缓冲上限 + 当前帧检查）
 → 轻量接纳、有界 PCM 队列
   ├→ Aliyun：100ms 聚合 → 有限超时发送 → finish-task → 定稿排空
   ├→ Soniox：保留原发送协议和分帧
   └→ 已授权音频保留：批量 WAV 写入 → 文件流发布
ASR 接收 → 原有 64 项 FIFO → 原文版本事务 + Outbox
本地后台任务 → 一个专用线程/事件循环（现有 2 项任务并发）
```

### 聚合和容量

`pcm_batch_stream()` 只有一个待完成的 `anext()`；定时 flush 不取消它。按字节顺序输出，结束时排空尾帧再发送 `finish-task`，取消时关闭迭代器。支持 20/40/60/80/100/200ms；默认 100ms，等待上限 100ms。超时 flush 可能产生短包，绝不补造音频、丢静音、重采样或自动重放。

官方核验日期 2026-11-26：[WebSocket API 的 3200 字节/100ms 示例](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-websocket-api)、[客户端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-client-events)、[服务端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-server-events)。本次不更改已有 workspace/region/endpoint 配置；文档支持不等于真实课堂效果通过。

所有时长转换使用 **32 字节/ms**，不是帧数乘 20。默认服务器未完成发送预算 8000ms，包含队列、聚合、预读及发送中音频；WAV 预算独立为 8000ms，包括正在写入的批次。每个队列另有 4096 节点上限，防止大量极小帧绕过预算。

应用按保守副本开销核算实时缓冲：`2 × (未发送字节 + 待存档字节) + 128 × 队列节点数 + 音频文件复制预留64KiB`。每会话默认 4MiB，每 API 进程 16MiB；这不是 Python 进程 RSS、TLS、SDK 内部缓存或内核 socket 缓冲的上限。文件发布不再生成整份 WAV 字节副本，S3/OSS 接收可关闭的文件对象；其 SDK 内部内存及真实上传尚未实测。

超过硬上限先关闭接纳，再记录诊断及停止；拒绝帧单独计数，正常停止排空已接受帧。若异常收尾仍有未发送/发送状态不明的数据，在释放内存前通过持久化事件记录。浏览器的 `bufferedAmount` 包含控制帧，界面明确标记为估算。

### 后台任务与结果队列

100 项提示，200 项降级：正在录音会话的摘要/字幕索引暂缓领取，已有任务不删除；正式翻译始终优先，导出/会后整理/资料解析保持可领取。5000 项硬上限才停止接纳。停止后索引和摘要恢复领取；周期摘要调度异常仅记录一次安全日志，下一正常周期重新尝试入队，不直接调用模型。

本地 Worker 使用一个受控线程，在线程内创建 SQLAlchemy Session；关闭时通知其事件循环取消并等待退出。Celery 模式不启动本地 Worker，使用同一任务筛选及原有 Outbox/幂等逻辑。没有新增服务或消息系统。

ASR 结果仍是 64 项有界 FIFO，新增队列峰值、消费耗时、partial/final 接收与 final 提交计数。未对供应商结果做新的 partial 合并，也不丢弃 final；慢消费者测试覆盖 100 条 final，最终完整排空。若数据库长期阻塞，队列仍可能满载并触发已有超时/停止保护，不能承诺绝不断线。

## 配置与回退

所有参数均为服务器环境变量；已有 `.env` 显式值优先，不需数据库迁移。登录后的 `GET /api/settings` 和本次流的 ready 事件提供 `audio_runtime` 白名单；不返回密钥、地址或文件路径。旧服务器缺少此字段时，新前端回退到旧的 2 秒保护。

| 参数 | 默认值 | 含义 |
|---|---:|---|
| ALIYUN_ASR_BATCH_ENABLED | true | 仅千问聚合；false 恢复逐帧 |
| ALIYUN_ASR_BATCH_MS / ALIYUN_ASR_BATCH_MAX_WAIT_MS | 100 / 100 | 目标音频时长/聚合等待上限 |
| AUDIO_QUEUE_WARNING_MS / HIGH_WATER_MS / MAX_MS | 1500 / 3000 / 8000 | 必须严格递增 |
| BROWSER_AUDIO_BUFFER_WARNING_MS / MAX_MS | 1500 / 8000 | 警告不停止，硬上限包含当前帧 |
| AUDIO_ARCHIVE_QUEUE_MAX_MS | 8000 | WAV 待写及正在写入的字节预算 |
| AUDIO_MAX_TOTAL_BUFFER_BYTES | 4194304 | 每个采集的应用缓冲预算 |
| AUDIO_PROCESS_MAX_BUFFER_BYTES | 16777216 | 进程预算，必须不小于单会话 |
| PROCESSING_BACKLOG_WARNING / DEGRADED / HARD_LIMIT | 100 / 200 / 5000 | 普通任务降级与硬保护 |
| ASR_DIAGNOSTICS_ENABLED | true | 启用事件循环延迟采样；基础错误计量始终保留 |
| EVENT_LOOP_LAG_SAMPLE_MS | 500 | 固定低频采样，最多保留120个样本 |
| ASR_SEND_TIMEOUT_SECONDS | 5 | 保持原默认值，单次发送有限等待 |
| ASR_EVENT_TIMEOUT_SECONDS / ASR_FINISH_TIMEOUT_SECONDS | 未设置 | 继续继承 MODEL_TIMEOUT_SECONDS（默认30） |
| ASR_RECOVERY_ENABLED / ASR_RECOVERY_AUTO_REPLAY_UNCERTAIN | false / false | 任一为true均拒绝启动 |
| ASR_RECOVERY_BUFFER_MS / MAX_ATTEMPTS / MAX_DURATION_SECONDS | 30000 / 3 / 30 | 仅保留配置接口，不分配恢复缓存、不执行重试 |
| ASR_RECOVERY_BACKOFF_INITIAL_MS / MAX_MS | 1000 / 4000 | 仅兼容读取和校验 |

上表省略重复前缀的项目均沿用同一前缀，完整名称见 `.env.example`。`AUDIO_MAX_QUEUE_FRAMES` 保留兼容读取但不再决定容量。参数非法时启动失败，不能用负值/无限值绕过保护。

候选超时档位 `send=8,event=60,finish=60` 可以人工配置测试，并非新默认。默认发送仍在5秒超时，因此8秒缓冲不是“上游阻塞8秒必然恢复”的承诺。有效任务心跳继续维持事件空闲期限；其他 task_id 不刷新，finish 总期限不能被心跳延长。

回退聚合只需 `ALIYUN_ASR_BATCH_ENABLED=false`。恢复较小缓冲可设服务器 warning/high/max=`500/1000/2000`、浏览器 warning/max=`1500/2000`、archive=`2000`。这保留改进的计量和故障分类，不保证逐字节复刻旧版2秒“队列之外再加在途帧”的边界。完全回退在独立干净分支执行 `git revert 072be3e6a9ca184bdb8873e01a71d44063e8735d`，不使用 reset、不删数据；先停止录音并备份。

## 故障与诊断语义

- `capture_state` 与 `asr_state` 分别表达采集及识别状态；例如 CAPTURING/DEGRADED、STOPPED/FAILED。它们目前是生命周期诊断基础，不是已实现的自动恢复状态机。
- `server_received_pcm_bytes` 是已接纳；`server_queued_pcm_bytes` 是尚在队列；`batch_pending_pcm_bytes` 是聚合中；`upstream_inflight_pcm_bytes` 是发送中。
- `upstream_sent_pcm_bytes` / `sent_audio_ms` 只表示 WebSocket send 完成，不等于云端识别确认。`current_send_wait_ms` 与上次 `send_wait_ms` 分开。
- `archive_written_pcm_bytes` 是本地 WAV 写入成功；`archived_pcm_bytes` 仅在关闭WAV并发布文件成功后增加。存储失败不能伪装成功。
- `rejected_pcm_bytes`、`confirmed_missing_pcm_bytes`、`uncertain_delivery_pcm_bytes`、`unsent_pcm_bytes` 分开；不把所有断连时长都宣称丢失。不确定的时长为 null，不能写0伪装完整。
- `asr_result_queue_size/peak`、`asr_result_consume_ms/p95_ms`、`asr_partial_received/coalesced`、`asr_final_received/committed` 用于区分接收、消费及正式提交。coalesced 当前为0。
- 其他数值包括循环延迟、当前/进程缓冲量、后台积压、队列峰值及原有延迟指标。日志仅记录身份、白名单错误码和数值，不记录音频/正文/鉴权数据。
- 供应商诊断保留 task_id、关闭码、阶段和异常类型，未知错误码统一为 `unknown_provider_code`；无效 WebSocket 握手明确分类。首次真实错误不会被收尾异常替换。

仍使用 `capture.gap`，新增 `incident_id/capture_id/gap_kind/reason_code` 等可选字段，不更改数据库表。分类包含 audio_missing、audio_delayed、asr_interrupted、asr_result_uncertain、translation_delayed、user_paused、connection_recovering、connection_recovered、storage_failed；恢复相关类别只是协议兼容字段，不代表自动恢复已实现。

所有原始事件均保留；前端仅将同会话同 incident_id 的说明合并成一行，已确认缺帧、未知结果、暂停和历史无分类事件不混为一谈。故障时长不相加，防止重复计数。新故障/新采集有不同身份，旧无 incident_id 的事件保留原显示。停止后的诊断仍可展开查看。

## 验证结果与复现命令

完整结果以 [TEST_RESULTS.md](TEST_RESULTS.md) 本日期记录为准。全部使用 Mock，临时 SQLite，禁止真实模型调用。测试包括：

- 6种聚合尺寸、非标准偶数字节帧、尾帧、定时flush期间保持同一个读取、取消释放、官方握手及 finish 顺序。
- 100/300/500/1000/2000/3000/5000ms 与8000ms容量边界的虚拟积压；容量内顺序不变，超容量先拒绝接纳，记录真实拒绝字节。网络发送超时另行测试，不能把队列测试当成实际VPN恢复。
- 后台100/200/500项不停止，5000项硬停止；本地线程阻塞150ms时 API 仍可调度，关闭后线程任务退出。
- 加速5/30/65/105分钟，共615000个实际格式PCM帧；每帧内容/顺序、心跳、最终事件、跨会话隔离及结束无子任务残留。另有105分钟保护排空尾帧测试。
- ASR/MT双通道、14语言、版本、预译复用、正式事务、历史、Outbox及来源权限继续由完整回归覆盖。
- Chromium 11视口、128项检查，含缓冲诊断、同故障合并、自动跟随、导航/主题/旋转不新建录音连接；不等于实体Safari验证。

```powershell
# 从 classbridge/backend，使用现有虚拟环境；所有环境设置仅影响当前终端。
$env:DASHSCOPE_API_KEY=''; $env:SONIOX_API_KEY=''; $env:PYTHONUTF8='1'
$env:DATABASE_URL='sqlite:///:memory:'; $env:TASK_MODE='disabled'
$env:INCREMENTAL_TRANSLATION_ENABLED='false'
..\.venv\Scripts\python.exe -m pytest -q
$env:INCREMENTAL_TRANSLATION_ENABLED='true'
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe tests/benchmark_asr_reliability.py
# 从 classbridge/frontend
npm test
npm run typecheck
npm run build
```

浏览器：已有 Playwright/Chromium；启动隔离 Vite `npm run dev -- --host 127.0.0.1 --port 5177 --strictPort`，设置 `PLAYWRIGHT_MODULE` 指向现有安装，`AUDIT_URL=http://127.0.0.1:5177`、`AUDIT_OUTPUT=../.local/asr-reliability-browser`、`AUDIT_AUDIO_DIAGNOSTICS=1`，运行 `node tests/browser/responsive.mjs`。所有业务请求/录音WebSocket由脚本Mock，不接触用户数据。

## 同输入性能对照

[完整测量JSON](ASR_PIPELINE_BENCHMARK.json)。加载上述基线的真实 Aliyun 源码作为对照；同一3000帧/1920000字节，虚拟输入每帧20ms、每次Mock发送1ms。所有模式输出SHA256一致、60条Mock正式结果、无重复/缺字节、无剩余任务。

| 模式 | 上游音频消息 | 聚合等待P95(ms) | Mock首条结果(ms) | 实际执行(ms) | tracemalloc峰值(bytes) |
|---|---:|---:|---:|---:|---:|
| 基线20ms | 3000 | 0 | 1113 | 237.924 | 63303 |
| 本轮逐帧关闭聚合 | 3000 | 0 | 1113 | 283.411 | 58619 |
| 本轮40ms | 1500 | 20 | 1065 | 416.432 | 93246 |
| 本轮60ms | 1000 | 40 | 1077 | 388.619 | 88574 |
| 本轮100ms | 600 | 80 | 1050 | 346.498 | 70582 |

100ms消息数下降80%，代价是本fixture增加80ms聚合等待。无真实网络成本的本地循环中总执行时间没有改善，不能宣称CPU或真实端到端延迟降低。Mock首条结果取决于合成peer及调度，不能解释为真实ASR首字速度。结果队列峰值本轮为1；旧版未埋点的字段和本provider-only基准未包含的服务端输入队列峰值标为null。真实入口队列/背压由单独的确定性测试覆盖。

## 兼容、部署与未完成事项

不改数据库结构、历史字幕、语言方向、翻译调度、Provider Registry、AudioWorklet或CSS。Aliyun新增传输聚合，Soniox只增加共享诊断，保持原协议/Token映射/收尾。自定义ASR Adapter必须在send成功后更新metrics中的sent_audio_ms，不能冒充云端确认。

部署前停止当前录音并等待收尾、备份。已有schema0005无需因本轮执行迁移；正式生产仍要求PostgreSQL/Celery/HTTPS及原Origin/Cookie限制。保持单API进程，16MiB是每进程预算，不是多进程全局限额。

- PyCharm：停止当前 API 运行配置，仍用现有 `.venv` 和 `backend/main.py` 重新启动；TASK_MODE=local 的Worker随API重启。前端开发服刷新页面；静态部署需重新构建。
- 容器：从classbridge执行 `docker compose --env-file .env -f deploy/compose.yaml up -d --build --no-deps api worker beat frontend`；本次未执行该命令，未验证容器运行或真实云存储。更新环境变量需要重建进程，仅刷新浏览器无效。
- 回退时一并部署匹配的API和前端，不能在录音中热切换。没有增加自动付费请求；聚合和缓冲也不保证降低按音频时长计费的金额。

自动恢复门禁原因：供应商无逐帧接收确认，断线时无法可靠区分未发送与已接收未识别音频；新stream的时间轴、存档和正式版本跨重放对齐尚未验证。因此不创建新付费任务、不自动切换供应商、不重放状态不确定音频，恢复配置true明确报错。未分配30秒恢复环形缓存，未实现RECOVERING/恢复成功状态机。

真实韩英课堂/重叠讲话、VPN抖动、实体iPhone/iPad Safari后台限制、麦克风、云端账号、S3/OSS实际上传和容器部署均未验证。浏览器后台仍按原策略停止；无法承诺锁屏录音。PostgreSQL迁移回归需要独立测试数据库，跳过项不能算通过。慢数据库仍可能导致结果队列背压；线程隔离不会消除SQLite文件锁竞争。

实际界面截图：[移动端诊断](screenshots/asr-reliability/mobile-audio-diagnostics.png)，[128项浏览器检查](screenshots/asr-reliability/checks.json)。截图为运行中的前端及明确标记的模拟数据。

## 修改文件清单

- Provider/聚合器：千问聚合、Soniox诊断、统一指标契约。
- config/settings/profiles：安全运行时配置及录音快照。
- live/diagnostics/incidents：字节预算、首错、收尾、故障分类。
- main/tasks/storage：本地线程、积压降级、文件流发布。
- 前端audioRuntime/useLive/health/timeline/SessionView：容量同步、诊断和同故障展示合并；不改CSS和事件版本算法。
- tests/docs：Mock回归、基准、真实浏览器证据及部署回退说明。

- `.env.example`
- `README.md`
- `backend/app/api/settings.py`
- `backend/app/config.py`
- `backend/app/main.py`
- `backend/app/providers/aliyun.py`
- `backend/app/providers/asr/base.py`
- `backend/app/providers/asr/pcm_batcher.py`
- `backend/app/providers/asr/soniox.py`
- `backend/app/providers/transport.py`
- `backend/app/services/asr_profiles.py`
- `backend/app/services/audio_diagnostics.py`
- `backend/app/services/capture_incidents.py`
- `backend/app/services/storage.py`
- `backend/app/workers/tasks.py`
- `backend/app/ws/live.py`
- `backend/tests/benchmark_asr_reliability.py`
- `backend/tests/test_audio_buffering.py`
- `backend/tests/test_capture_gap_incidents.py`
- `backend/tests/test_core.py`
- `backend/tests/test_pcm_batcher.py`
- `backend/tests/test_processing_backpressure.py`
- `backend/tests/test_project_review.py`
- `backend/tests/test_providers.py`
- `backend/tests/test_retired_correction.py`
- `backend/tests/test_transport.py`
- `docs/ASR_MODELS.md`
- `docs/ASR_PIPELINE_BENCHMARK.json`
- `docs/ASR_PIPELINE_RELIABILITY.md`
- `docs/FEATURE_STATUS.md`
- `docs/REALTIME_TROUBLESHOOTING.md`
- `docs/TEST_RESULTS.md`
- `docs/screenshots/asr-reliability/checks.json`
- `docs/screenshots/asr-reliability/layout.json`
- `docs/screenshots/asr-reliability/mobile-audio-diagnostics.png`
- `frontend/src/components/SessionView.tsx`
- `frontend/src/lib/audio.ts`
- `frontend/src/lib/audioRuntime.ts`
- `frontend/src/lib/captureHealth.ts`
- `frontend/src/lib/timeline.ts`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/useLive.ts`
- `frontend/tests/browser/responsive.mjs`
- `frontend/tests/captureHealth.test.ts`
- `frontend/tests/timeline.test.ts`
- `frontend/tests/uiInteraction.test.ts`
