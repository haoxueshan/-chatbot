# 多 ASR 模型管理

## 2026-11-26 传输更新

Aliyun在每次录音快照中固定 `aliyun_asr_batch_enabled/ms/max_wait_ms`（默认true/100/100），ready事件同时提供安全audio_runtime。Soniox保留原PCM分帧和协议，仅增加发送/队列诊断。新Adapter须在ws.send成功后准确更新 `metrics['sent_audio_ms']`，该值只表示发送完成，不是云端确认。配置、费用边界与Mock结果见 [音频可靠性](ASR_PIPELINE_RELIABILITY.md)。不会中途切换供应商或自动创建新识别任务。

基线 `5b27cecf1c9f14a99a17e4f2eea57934a5d4d487`；开发分支 `feat/asr-profile-management`。本次保留已有字幕版本、稳定译文预览、Outbox、RAG、音频采集和最终收尾。所有自动测试使用 Mock；没有自动请求付费 API。

## 使用

1. 服务器配置密钥并重启 API，在「偏好设置 → 语音识别模型管理」新增配置。
2. 选择供应商、真实模型 ID、语言提示、合法参数；点击「配置检查」。本地检查通过仅表示结构、密钥存在性及 Adapter 合法，不能证明账号已获模型权限。
3. 创建真实会话时选择模型；已有会话在「工具与详情」中切换。准备、录音和收尾期间，前后端均拒绝切换、修改或删除当前使用的模型。停止并完成收尾后才能切换。

「配置检查」默认不联网。「真实连通测试（可能计费）」需要单独确认，发送 200ms 静音并等待有界收尾，无自动重试，不代表识别质量验证。同一 API 进程只运行一个连通测试；接口另有频率限制。此限制不是跨多副本的全局配额。

启用但无密钥的配置可保存，不能用于录音。ElevenLabs Scribe v3 Live、Deepgram Nova-3 仅有 Registry 占位，明确显示「尚未接入」，不能选作运行或默认模型；占位的模型 ID 不代表已验证 API 支持。暂未实现 Daglo、NAVER、RTZR。

## 密钥与模型示例

在服务器 `classbridge/.env` 或进程环境中设置 `SONIOX_API_KEY`，值仅在服务器的安全编辑器/密钥管理系统中填写。不要发送到聊天、网页、前端环境、日志或仓库。`.env.example` 只提供空字段。

Soniox 配置示例（POST `/api/asr/profiles` 的 JSON）：

```json
{
  "provider": "soniox",
  "model_id": "stt-rt-v6",
  "display_name": "韩英课堂 · Soniox",
  "language_hints": ["ko", "en"],
  "enabled": true,
  "is_default": false,
  "credential_ref": "SONIOX_API_KEY",
  "provider_options": {
    "context": "人工智能课堂",
    "terms": ["Retrieval-Augmented Generation", "인공지능"],
    "language_hints_strict": false,
    "max_endpoint_delay_ms": 2000
  }
}
```

示例术语不会默认注入其他会话。`language_hints=null` 跟随现有课堂语言偏好，`[]` 自动识别，当前管理接口允许 `ko`、`en` 提示。Soniox 的 Context 会合并已有 ASR 热词；其协议不支持阿里云词权重，因此不会伪造权重参数。Soniox 不使用阿里云的 near/far VAD 参数。

Aliyun 的 `credential_ref` 固定为 `DASHSCOPE_API_KEY`，`provider_options` 仅允许 `context` 与已支持的 `vad_model`；未填写时保持原行为。Soniox 参数白名单见示例；未知字段、URL、认证头和 API Key 正文均被拒绝。供应商能力来自服务端 Registry；同供应商新增模型 ID 无需改 Factory，但真实模型支持情况仍需供应商确认。

凭据引用只指向固定服务端环境变量，不是任意文件路径或任意环境变量名。ASR 连接仅允许已登记的官方 Host；Soniox 固定为 `stt-rt.soniox.com`。Aliyun 保留 `ASR_WS_URL` 但限制为官方 `dashscope.aliyuncs.com` 或业务空间 `*.maas.aliyuncs.com`、443 端口及官方路径，不能配置私人代理 URL。

切换 Soniox 只改变实时 ASR。中文及其他 14 种字幕翻译、会后文件转写、总结、Embedding、Rerank 和 RAG 仍独立依赖阿里云配置。缺少 DashScope 密钥时 Soniox 原文可运行，依赖阿里云的功能会明确报错。

## 接口

接口使用现有登录 Cookie、Origin 校验、所有权检查与频率限制，不开放公开模型管理。

| 接口 | 行为 |
| --- | --- |
| GET `/api/asr/providers` | Adapter 能力、实现状态、合法参数 JSON Schema |
| GET `/api/asr/profiles` | 当前用户的配置和本地检查状态；不会返回密钥 |
| POST `/api/asr/profiles` | 新建，最多 50 个配置 |
| PATCH `/api/asr/profiles/{id}` | 修改、启停、设置默认；每用户最多一个默认 |
| DELETE `/api/asr/profiles/{id}` | 删除闲置配置，保留全部会话及录音模型快照 |
| POST `/api/asr/profiles/{id}/validate` | 空体或 `{"live":false}` 仅本地校验；联网须显式传 `{"live":true,"confirm_paid":true}` |
| PATCH `/api/sessions/{id}/asr-profile` | `{"asr_profile_id":"配置 ID"}`，仅闲置真实会话可切换 |

POST `/api/sessions` 增加可选 `asr_profile_id`。未传时采用用户默认；模拟会话不使用供应商。删除默认后不偷偷选择其他付费模型，需重新选择。错误区分 `asr_profile_not_found`、`asr_profile_disabled`、`asr_profile_in_use`、`unsupported_asr_provider`、`missing_api_key` 及供应商认证、限流、超时等原因。

每次开始录音锁定供应商、model_id、语言提示、参数及服务端运行配置快照。密钥不写入快照。历史接口返回 `asr_streams[].snapshot`；删除配置不会级联删除字幕、译文、音频或快照。`stream_id:sentence_id`、正式原文与译文版本机制不变。

## Soniox 官方协议依据

核验日期：2026-11-23。

- [模型列表](https://docs.soniox.com/stt/models)：`stt-rt-v6`。
- [WebSocket API](https://docs.soniox.com/api-reference/stt/websocket-api)：PCM16LE / 单声道 / 16kHz，配置后连续二进制音频。
- [WebSocket 认证](https://docs.soniox.com/authentication/websocket-authentication)：Authorization Bearer，仅在后端连接中发送。
- [实时转写](https://docs.soniox.com/stt/rt/real-time-transcription)、[端点检测](https://docs.soniox.com/stt/rt/endpoint-detection)、[时间戳](https://docs.soniox.com/stt/concepts/timestamps)。

初始配置后使用官方 ping/pong 确认启动；短音频帧不断发送。已确认 token 追加，临时 token 仅替换当前尾部；官方 `<end>` / `<fin>` 或 `finished` 确认边界。句号本身不制造正式原文。时间范围来自 token 的实际 `start_ms/end_ms` 包络，不生成假精确时间；缺少时间证据会报错。

停止时发送空**文本**帧，然后等待 `finished`。活动期间心跳更新响应超时；结束后的截止时间固定，心跳不能无限延长。使用现有发送/事件/收尾超时与约 2 秒 PCM 预算；内部结果队列上限 64，单个未结束文本上限 65536 字符，持续满载会明确停止，不自动重启付费识别。取消会关闭 sender、receiver、心跳与 WebSocket。

## 升级与部署

先停止录音并等收尾完成；备份数据库和文件卷，停止 API、本地 worker 或 Celery worker/beat。不要对用户数据运行测试。迁移仅在已备份后由维护者执行，本次开发未迁移本机用户数据库。

Windows / PyCharm，工作目录 `classbridge/backend`，沿用已有环境：

```powershell
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe main.py
```

随后在 `classbridge/frontend` 执行 `npm run dev`；静态部署执行 `npm run build` 并发布 dist，刷新浏览器。已有的 `if __name__ == '__main__'` 启动入口保留。`create_all()` 不能代替已有数据库的 Alembic 升级。

Docker / 宝塔 / 1Panel 使用现有 PostgreSQL + pgvector、Redis/Celery、HTTPS 安全配置。在 `classbridge/`：

```sh
docker compose --env-file .env -f deploy/compose.yaml stop api worker beat frontend
docker compose --env-file .env -f deploy/compose.yaml build api worker beat migrate frontend
docker compose --env-file .env -f deploy/compose.yaml run --rm migrate
docker compose --env-file .env -f deploy/compose.yaml up -d api worker beat frontend
```

迁移 0004 对 SQLite 和 PostgreSQL 使用可空新增列与独立配置表，不重写原字幕/译文。旧用户自动得到原 Aliyun 默认配置；新用户首次访问按服务器默认初始化。现有配置初始化后，环境变量 `ASR_PROVIDER/ASR_MODEL` 不会偷偷覆盖已保存模型，应通过设置修改。

旧录音未记录模型时，历史快照标为 `legacy_environment_assumed`，UI 明示“按升级时旧配置补记”；无法还原当年真实模型。新录音记录精确配置快照。模型被删除后不自动重建。已存在新配置/快照时迁移拒绝有损 downgrade；回退应停止服务并恢复升级前备份与对应代码。单纯停用 Soniox、选择 Aliyun 不需回退数据库。

## 测试与限制

2026-11-24 实际执行结果：

| 命令 / 验证 | 结果 |
| --- | --- |
| `INCREMENTAL_TRANSLATION_ENABLED=false python -m pytest -q --tb=short` | 396 通过，1 跳过，65.55s；迁移测试的输出解码警告已修正并单独复验 |
| `INCREMENTAL_TRANSLATION_ENABLED=true python -m pytest -q --tb=short` | 396 通过，1 跳过，64.92s，无上述警告 |
| `python -m pytest -q tests/test_soniox.py` | 20 通过，包括同一响应重复 token 不误去重 |
| `npm test` | 107 通过 |
| `npm run typecheck` / `npm run build` | 通过 / 通过 |
| `node tests/browser/asr-models.mjs` | Chromium 1440×900、390×844；新增、编辑、配置检查、会话选择、无横向溢出通过，真实 API 请求 0 |

后端在项目现有 `.venv` 中执行。唯一跳过项为未配置 `CLASSBRIDGE_TEST_POSTGRES_URL` 的独立 PostgreSQL 历史迁移测试；SQLite 的旧数据迁移、重复升级、升降级测试已通过。追加用例验证两个真实模式会话分别使用 Mock Aliyun/Soniox，且原文、模型快照、句子命名空间相互独立。完整前端回归保留了 14 种目标语言、译文快照、录音生命周期及历史恢复断言。

浏览器脚本使用已有 `playwright-core`（可通过 `PLAYWRIGHT_MODULE` 指定路径），配合隔离 Vite 端口 5177。业务 HTTP 全部 Mock，拒绝非本机请求；该端口本身不提供独立 Mock 服务，验收后已停止。没有输出真实密钥，没有发起真实 ASR/MT 请求，数据库均为隔离临时数据库。

实际截图目录 `docs/screenshots/asr-models/`：`desktop-edit.png`、`desktop-settings.png`、`mobile-edit.png`、`mobile-settings.png`、`new-session.png`。截图中的配置及账号均标为 Mock，不是已连接真实服务的证据。

实际账号连通、真实课堂识别准确率、实体 Safari 和生产 PostgreSQL/Docker 运行验收仍需独立执行。Soniox 的词级时间戳能提供文本时间范围，不保证处理真正的重叠语音，也没有引入说话人分离。

## 本次修改文件清单

共 39 个文件（含 5 张实际截图）：

```text
.env.example
README.md
backend/app/api/sessions.py
backend/app/api/settings.py
backend/app/config.py
backend/app/main.py
backend/app/models/__init__.py
backend/app/providers/asr/factory.py
backend/app/schemas/sessions.py
backend/app/ws/live.py
backend/tests/test_core.py
backend/tests/test_dual_pipeline.py
backend/tests/test_live_ordering.py
backend/tests/test_migrations.py
backend/tests/test_multilingual_translation.py
backend/tests/test_project_review.py
frontend/src/components/Home.tsx
frontend/src/components/SessionView.tsx
frontend/src/components/Settings.tsx
frontend/src/lib/types.ts
frontend/src/styles/pages/settings.css
frontend/tests/uiInteraction.test.ts
backend/app/api/asr.py
backend/app/providers/asr/aliyun.py
backend/app/providers/asr/registry.py
backend/app/providers/asr/soniox.py
backend/app/services/asr_profiles.py
backend/migrations/versions/0004_asr_profiles.py
backend/tests/test_asr_profiles.py
backend/tests/test_soniox.py
docs/ASR_MODELS.md
docs/screenshots/asr-models/desktop-edit.png
docs/screenshots/asr-models/desktop-settings.png
docs/screenshots/asr-models/mobile-edit.png
docs/screenshots/asr-models/mobile-settings.png
docs/screenshots/asr-models/new-session.png
frontend/src/components/ASRModels.tsx
frontend/src/lib/asrProfiles.ts
frontend/tests/browser/asr-models.mjs
```
