# 实时识别与字幕可靠性增量检查（2026-11-23）

基线 `cfe0a9363ee158f1e8f5ef846c5ef4424f2b2dea`，分支 `fix/asr-reliability-provider`。本轮只有 Mock、临时测试数据库和合成 PCM；真实模型调用为 0。没有读取密钥内容、修改用户历史、数据库迁移或默认开启增量翻译。

## 已有能力与实际修复

基线已有 2 秒 PCM 字节预算、收音与字幕处理隔离、离线程数据库/音频写入、缓存 TLS 上下文、连续 48k/44.1k 重采样、MT 输入去重、完成预览快照和持久化 handoff。本轮保留这些实现，没有更改采音、VAD、模型、词表权重、翻译调度或响应式样式。

| 文件 | 本轮修改 |
| --- | --- |
| `backend/app/providers/aliyun.py` | 当前任务事件/心跳刷新活动时间，异任务不刷新；`finish-task` 起使用绝对收尾截止时间；结束发送阻塞及收到完成消息后等待发送完成，也受同一截止时间约束。保留首个错误、任务取消及 64 项结果队列。 |
| `backend/app/config.py`、`.env.example` | 三个 ASR 配置项，兼容旧配置，见下表。 |
| `backend/app/providers/asr/{__init__,base,factory}.py` | 结构化 ASR 接口与工厂，直接复用现有 Aliyun 实现；不复制传输逻辑、不改 MT/RAG。 |
| `backend/app/api/sessions.py`、`backend/app/ws/live.py` | 真实会话预检查和识别入口使用工厂；补充数值诊断；外层停止预算兼容独立收尾超时。 |
| `frontend/src/components/SessionView.tsx` | 原 reducer 已保留兼容快照，但失败分支曾遮住它。现在继续展示有效快照，并明确提示更新失败、尚未正式完成。没有改动 `events.ts`、原文或快照规则。 |
| `backend/app/providers/asr/evaluation.py` | 标准 WAV 回放和有参考文本的离线评分，显式授权才允许真实模型调用。 |
| `backend/tests/test_providers.py`、`test_transport.py`、`test_asr_evaluation.py` | 收尾/失联/异任务/取消、65 分钟时序、诊断、韩英参数、离线指标与付费门禁回归。 |
| `backend/tests/benchmark_audio_transport.py` | 可选基线 SHA；增加 ASR 事件、任务数、内存测量，全部 Mock。 |
| `frontend/tests/uiInteraction.test.ts` | 从事件输入到实际 DOM 验证失败后的兼容译文可见，保留单个 WebSocket。 |
| `docs/MODEL_COMPATIBILITY.md`、本文 | 官方协议核验、复现数据、部署与未验证边界。 |

## 超时与诊断含义

| 配置 | 默认 | 用法 |
| --- | --- | --- |
| `ASR_PROVIDER` | `aliyun` | 唯一已实现选项。`daglo/naver/rtzr` 或拼写错误明确返回 `unsupported_asr_provider`；不自动切换，也不生成模拟字幕。 |
| `ASR_EVENT_TIMEOUT_SECONDS` | 未设置，继承 `MODEL_TIMEOUT_SECONDS`（默认 30） | 正数、最多 300 秒；连续静音有有效心跳不超时，无当前任务事件达到时限则 `asr_event_timeout`。 |
| `ASR_FINISH_TIMEOUT_SECONDS` | 未设置，继承 `MODEL_TIMEOUT_SECONDS`（默认 30） | 正数、最多 300 秒；从开始发送 `finish-task` 计算固定截止时间，不能被心跳延长，超时报 `asr_finish_timeout`。 |

TCP ping/pong 不等于 ASR 应用事件；这里依据官方 `heartbeat`。音频发送依然由 `ASR_SEND_TIMEOUT_SECONDS=5` 保护；浏览器无音频仍由既有 15 秒输入检测处理；用户停止先排空有界队列，再发送结束指令；应用总时长仍是 105 分钟。没有无限等待或自动重开付费 ASR。

`capture.health` 新增 `heartbeat_events`、`foreign_task_events`、`subtitle_send_wait_ms`（最近一次本站字幕发送含锁等待，失败也计时）、`pending_processing_tasks`（维护周期采样的全部待处理任务数，不冒充纯 MT 数）。保留 received/sent/queued 音频毫秒、最近事件年龄和延迟。`sent_audio_ms` 只表示本站 WebSocket 发送完成，不表示云端已识别。诊断不包含原文、译文、音频、凭据。

## 官方协议与扩展边界

阿里云[客户端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-client-events)、[服务端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-server-events)支持现有 PCM16LE/16k/mono、`task-started` 握手、`heartbeat`、`sentence_end` 和 `finish-task`/`task-finished`。`ko_en` 仍发送 `language_hints=["ko","en"]`；目标翻译语言不进入 ASR。热词保留 NFC、英文大小写、来源词去重及用户权重；上下文继续按现有输入限制使用前 400 字符，不自动补全姓名或术语。

Daglo [实时 API](https://developers.daglo.ai/guide/en/STT-Realtime.html)和[官方示例](https://developers.daglo.ai/guide/en/Quick-Realtime-Voice-To-Text.html)公开了 gRPC `StreamingRecognize`、Bearer 元数据、LINEAR16、`language_code` 和 `result.is_final`。但所列响应没有句子 ID、句子起止时间或词级时间；也未说明 `total_duration` 可以作为某条结果的权威结束时间。因此本轮**没有编写 Daglo 实际适配器**，没有添加 gRPC 依赖，也不使用到达时刻伪造证据时间戳。需补齐官方时间边界语义、访问权限及真实样本后再适配。NAVER/RTZR 同样未实现。

验证等级：以上是**文档核验 + Mock 协议验证**，不是本轮真实接口验证，更不是课堂准确率提升证明。

## 可复现测量

Windows，现有 Python 3.13 虚拟环境。以下时延是本机一次 Mock 测量，受调度影响，不代表云端/设备延迟或统计显著提升。

运行（backend 目录，PowerShell）：

```powershell
$env:CLASSBRIDGE_BENCHMARK_BASELINE='cfe0a9363ee158f1e8f5ef846c5ef4424f2b2dea'
../.venv/Scripts/python.exe tests/benchmark_audio_transport.py
../.venv/Scripts/python.exe -m pytest -q -s tests/test_providers.py -k 65_minute
```

| 同负载指标 | 基线 | 修改后 |
| --- | ---: | ---: |
| 100 帧输入/输出，实际字节 | 64,000 / 64,000 | 64,000 / 64,000 |
| 100 帧节拍回放队列峰值 | 20 ms | 20 ms |
| 音频入队路径数据库查询 | 0 | 0 |
| 入队最大耗时 | 0.089 ms | 0.118 ms |
| 发送等待最大耗时 | 0.045 ms | 0.046 ms |
| 事件循环延迟最大值 | 15.885 ms | 16.155 ms |
| 100 帧节拍回放总耗时 | 3127.578 ms | 3126.986 ms |
| 10,000 帧无节拍 ASR 回放总耗时（含 tracemalloc） | 395.72 ms | 390.00 ms |
| ASR 事件数量 | 200 | 200 |
| ASR 事件到消费者平均/最大耗时 | 0.493 / 0.847 ms | 0.477 / 1.180 ms |
| 采样的未消费事件数 | 0 | 0 |
| 峰值内部任务 / 结束残留 | 4 / 0 | 4 / 0 |
| tracemalloc 峰值 | 37,032 B | 34,242 B |
| 相同文本 20 次时间戳更新：MT 请求/取消 | 1 / 0（已有修复） | 1 / 0 |
| 替换请求失败后，有效预览被错误文案遮住 | 1 次（复现断言失败） | 0 次（DOM 断言通过） |

新增 65 分钟加速样本时钟测试：195,000 个 640 B 帧，累计 3,900,000 ms；每帧顺序与采样数量校验；780 次心跳期间无文字也不中止；队列峰值 40 ms、内部任务峰值 5、结束残留 0；仅最后一个权威 final，缺口 0。这是合成 PCM 与 Mock 网络的生命周期验证，不包含 65 分钟真实等待、浏览器/设备续航或网络抖动。

回归同时复用已有 100/300/500/1000/2000 ms 发送抖动、有界满载停止、慢数据库、慢字幕接收、停止收尾、旧流隔离、未确认字幕、14 种翻译语言、正式证据与 Outbox 测试。两个增量开关下均验证，不改变默认关闭状态。

实际执行：`INCREMENTAL_TRANSLATION_ENABLED=false` 和 `true` 分别运行 `python -m pytest -q`：均为 350 passed、1 skipped（55.21 / 55.79 秒）；前端 `npm test`：105 passed；`npm run typecheck`、`npm run build` 通过。跳过的是未配置 `CLASSBRIDGE_TEST_POSTGRES_URL` 的隔离 PostgreSQL + pgvector 测试；没有用业务代码绕过环境限制。

## 同音频多 Provider 评测工具

`evaluate_wav(provider, path, reference=..., terms=...)` 对不同适配器顺序回放同一 WAV，默认按 20 ms 实时节拍。只支持未压缩 16kHz 单声道 PCM16LE，拒绝错误格式及超过 105 分钟的输入。Mock 测试通过虚拟时钟避免实际等待。

`first_partial_ms` / `last_final_ms` 从 Provider 就绪回调计时，包含 WAV 中原有静音；`final_after_audio_ms` 是最后一个 final 相对文件音频排空的时间，若最后一句提前完成可以为负。它们不是模型内部推理耗时，也不是按人工标注语音终点计算的课堂延迟。

`score(reference, hypothesis, terms)` 完全离线，不读取设置或调用 API。只有提供人工参考原文才输出 English WER、Korean CER、混合 token 错误率和给定术语保留率；NFC、英文不区分大小写、韩语按字符忽略空格，混合计分使用英文词、数字串及其他语言字符。韩/英子集分数不等同整句错误率；错误率可大于 1。费用没有可靠计费数据时为 null，不猜测价格。

```powershell
# 默认拒绝，连配置和音频也不会读取；本轮没有执行任何授权付费命令。
../.venv/Scripts/python.exe -m app.providers.asr.evaluation sample.wav --provider aliyun --reference reference.txt --language ko_en
```

用户日后明确选择付费评测时才手动添加 `--allow-paid`，一次启动一个 ASR 任务，没有自动重试或 MT。报告只输出数值，不输出识别文本。以短录音和人工校对文本做准确率比较；本轮无真实样本，**不能声称韩语准确率提高或重叠发言问题已解决**。

## 兼容、部署与回退

旧字幕、事件类型、版本、Translation、Outbox、RAG 证据和会话语言语义不变；没有迁移。默认 `ASR_PROVIDER=aliyun`，两个新超时项不配置即兼容旧超时值；增量翻译仍由现有 `INCREMENTAL_TRANSLATION_ENABLED` 控制，默认 false。

开发仍为 SQLite + local worker。宝塔/ECS 正式生产仍必须 PostgreSQL + pgvector、Redis/Celery、HTTPS、安全 Cookie、明确来源与服务器端密钥。单实例 SQLite 只用于原有开发测试模式，本轮没有新增生产 SQLite 例外，也没有实际部署或读取服务器配置。

现有已初始化 Compose 部署更新代码后，在 `classbridge/` 手动执行：

```sh
docker compose --env-file .env -f deploy/compose.yaml up -d --no-deps --build api worker beat frontend
```

这是应用更新命令，不运行迁移、不删除卷；先结束正在进行的录音。宝塔反代继续使用现有 HTTPS/WebSocket 配置。本地 PyCharm 重启原 API 运行配置，运行 `npm run build` 更新静态前端（Vite 开发模式热更新），本地 worker 随 API 启动。

关闭实验预译可设 `INCREMENTAL_TRANSLATION_ENABLED=false`；ASR 保持 `aliyun`，删除新增超时配置可恢复原超时数值。完整代码回退使用本轮提交的 `git revert <提交 SHA>` 并重新构建应用；无需数据库回退，不重置用户工作或删除数据。本轮未执行服务器重启。

限制：实体 Safari/麦克风、真实 60 分钟课堂与 CER/WER、Daglo、实际 Redis/Celery broker 与生产 PostgreSQL/容器运行尚未验证。现有独立子进程 Celery 入口 + 临时 SQLite handoff 测试不等于真实 broker/生产部署验收。
