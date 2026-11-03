# 多语言字幕翻译交付记录

实现与主要验证：2026-11-03；收尾提交：2026-11-04。基线：`8ab0c04f44a541588b7b79341e12289d9da61ad2`，已 fetch 并核对 main/origin/main。实现分支：`feat/multilingual-translation`，不合并 main，不推送远端。本次没有修改真实 `.env`、用户偏好或业务数据库，没有调用真实计费接口。

## 使用方式与范围

1. 「偏好设置 → 默认字幕翻译语言」选择语言并保存。
2. 「新建会话 → 字幕翻译目标语言」确认或修改本次语言。非中文选「真实课堂」；模拟演示只允许简体中文。
3. 开始后原文保持 ASR 输出，译文与状态显示固定的会话语言。修改偏好仅作用于以后新建的会话。

首批 14 种：简体中文、繁体中文、英语、韩语、日语、法语、德语、西班牙语、俄语、葡萄牙语、意大利语、泰语、越南语、阿拉伯语。界面、RAG 回答和阶段总结继续使用中文。没有引入同一会话的多翻译轨道或修改录音中的语言。

## 修改文件与行为

路径均相对于 `classbridge/`。

| 文件 | 改动 |
| --- | --- |
| `backend/app/data/translation_languages.json` | 唯一注册表：代码、中文显示名、官方 MT 名称、方向；前后端共用 |
| `backend/app/services/translation_languages.py` | 严格语言类型/映射与按目标语过滤词对；未知代码拒绝 |
| `backend/app/models/__init__.py`、`migrations/versions/0003_translation_language.py` | Session/Translation 非空目标语列、历史回填、降级保护 |
| `backend/app/api/settings.py`、`schemas/sessions.py`、`api/sessions.py` | 默认偏好、新建快照、422 校验、demo 限制、详情及导出标签 |
| `backend/app/providers/aliyun.py` | MT `target_lang` 参数；保持 SSE、完整性、超时、错误分类，不改变 ASR 协议 |
| `backend/app/ws/live.py` | 采集配置锁定 Session 语言；增量/旧版预览传参；ready 与临时事件携带语言 |
| `backend/app/services/incremental_translation.py` | spec 与 digest 纳入官方目标语；跨语言预览不能复用 |
| `backend/app/services/events.py` | outbox 任务关联原文版本和目标语，保存 Translation 语言并验证匹配，快照按语言选译文 |
| `backend/app/workers/tasks.py` | 正式翻译使用 Session 快照，拒绝错误语言/版本任务，词对过滤、完成保存；旧任务省略字段时取 Session |
| `frontend/src/lib/translationLanguages.ts` | 引用同一 JSON，统一标签、方向、带语言标签的词表编辑 |
| `frontend/src/App.tsx`、`components/Home.tsx`、`components/Settings.tsx` | 默认语言与新建选择器；保留其他偏好；demo 阻止错误语言创建 |
| `frontend/src/components/SessionView.tsx` | 动态语言/等待/完成标签、显示 ready 生效语言、阿拉伯译文 `lang/dir` |
| `frontend/src/lib/types.ts`、`events.ts`、`useLive.ts` | Session/译文语言类型、快照恢复、错误语言事件隔离；原文 map 不受翻译影响 |
| `backend/app/services/exporting.py`、`requirements*.txt` | 日文/泰文字体候选、阿拉伯逐行连字与双向排版；新增锁定的 arabic-reshaper/python-bidi |
| `.gitignore`、`.dockerignore`、`deploy/Dockerfile.*`、`frontend/vite.config.ts` | 注册表必须纳入源码/镜像；Vite 只额外公开注册表文件，不开放后端目录；Linux 补充字体包 |
| `backend/tests/test_multilingual_*.py`、`test_providers.py`、`test_exporting.py` | 语言参数、快照、任务/缓存隔离、缺密钥/失败、迁移与导出回归 |
| `frontend/tests/multilingual.test.ts`、`uiInteraction.test.ts` | 14 语 reducer、错误语言/旧事件隔离、设置/新建/字幕实际 DOM 交互 |
| `backend/tests/render_multilingual_export.py`、`docs/screenshots/multilingual-export.png` | 可重现的静态 PDF 排版样例与实际渲染截图 |

## 数据与事件兼容

旧用户缺少偏好字段时为 zh-CN。已有 Session 和 Translation 都回填 zh-CN，与用户当前偏好无关；原文、译文、时间戳、source_revision、translation_revision 不变。新建 API 省略语言时采用用户默认值，显式值优先。Session 无语言修改接口。

正式任务 payload 是 `segment_id + source_revision + target_language`，幂等键仍为原文版本的 segment_id（一会话单目标语）。预览完整性、取消、稳定前缀、正式任务优先和版本淘汰保持原逻辑，digest 包含全部原规格及 target_lang。旧无语言事件仅在 zh-CN 会话内兼容；其他目标语丢弃，不修改韩英原文。

旧词对 `memory = 记忆` 属于 zh-CN。可以编辑 `[en] 기억 = memory`、`[ja] 기억 = 記憶`，API 保存为带 target_language 的字典。无标签原文热词、课程背景和 ASR language_hints 不随翻译目标改变。没有重新引入 AI 推测矫正。

## 升级与运行

先停止 API 和 worker，按 [部署备份说明](DEPLOYMENT.md) 备份数据库及文件卷。SQLite 使用停服复制或 SQLite backup，不能在写入期间仅复制 `.db` 而遗漏 WAL。保留原配置和管理员。

在 `classbridge/` 的 PowerShell 终端复用现有环境：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt -c backend/requirements.lock.txt
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe main.py
```

PyCharm 仍使用 `.venv/Scripts/python.exe`，先运行 Alembic 配置 `upgrade head`，再右键 Run/Debug `backend/main.py`。前端在另一个终端 `cd classbridge/frontend` 后 `npm run dev`；原默认入口 `http://localhost/`、API `http://127.0.0.1:8000/api/docs` 不变。生产应同时升级 API、worker 和前端，避免旧 worker 按中文翻译新会话。

SQLite 需要 3.35+ 原生 DROP COLUMN（当前 Python 3.13 附带版本满足）。全新升级、带旧字幕升级、降到0002、再升级测试覆盖历史中文数据。若已创建非中文会话/译文，降级会在删除任一语言列之前拒绝；需要回滚时恢复升级前完整备份，不能删语言字段再把非中文历史回填成中文。

## 验证记录

全部自动化使用临时数据库及 Mock MT，没有使用课堂音频或真实账号验证多语质量。

| 验证 | 最终结果 |
| --- | --- |
| 后端完整 pytest，INCREMENTAL_TRANSLATION_ENABLED=false | 214 passed，1 skipped，29.80秒 |
| 后端完整 pytest，INCREMENTAL_TRANSLATION_ENABLED=true | 214 passed，1 skipped，30.72秒 |
| 前端 npm test | 71 passed，2026-11-04复验3.19秒 |
| npm run typecheck | 通过 |
| npm run build | 通过，Vite 6.4.5，2026-11-04复验4.59秒 |
| pip check | No broken requirements found |
| SQLite 新建/历史升级、降级再升级、非中文降级保护 | 通过 |
| PostgreSQL 本迁移 DDL 编译 | 通过；真实 PG 测试是上述唯一 skipped |
| Vite 注册表模块与后端文件隔离 | 200 / 403 符合预期 |
| 14语 PDF 字形测试及渲染检查 | Windows 样例通过；Linux 容器待验证 |

MT MockTransport 检查了 14 组实际 HTTP payload 的 `translation_options.target_lang`、`source_lang=auto`、`stream=true` 和 SSE 完整结束。增量开关 false/true 均检查旧版预览、增量预览、正式任务、缓存不能跨语言复用。原 ASR 音频传输、task-started/finish-task、无目标语参数、乱序/迟到事件、未确认字幕恢复、RAG 正式证据和已删除推测功能的测试仍在完整回归内。

开发模式以临时端口 `127.0.0.1:5178` 实测：前端模块和共享 JSON 返回200；访问无关后端配置代码返回403。检查后已停止这个测试进程，没有重启用户服务或自动开启麦克风。

PDF：使用项目真实 `render_pdf` 生成静态14语样例，以 Poppler 渲染并目视检查。Windows 下韩文、日文、阿拉伯字形连接/右对齐/换行及其他样例无缺字与裁切。[实际渲染截图](screenshots/multilingual-export.png)。复现：在 backend 设置 `PYTHONPATH=.` 后，使用项目 Python 运行 `tests/render_multilingual_export.py`。中间 PDF 写入忽略的 `.local/output/pdf/`。

阿拉伯 PDF 使用 presentation forms 做显示整形，部分阅读器复制/搜索时可能返回视觉顺序而非逻辑 Unicode；需机器读取时使用 TXT/Markdown，数据库保留原始文本。字体/排版依据 [arabic-reshaper 项目文档](https://github.com/mpcabd/python-arabic-reshaper)和 [python-bidi 文档](https://python-bidi.readthedocs.io/en/latest/)。

## 限制与未验证项

- 未调用真实 Qwen MT；多语翻译质量、真实课堂延迟和实体 iPad/Safari 效果待验证。不能把 Mock 通过称作真实接口通过。
- 本机无可用 Docker Engine、PostgreSQL 服务。PostgreSQL 只完成本迁移 DDL 编译检查，实际迁移集成测试显式跳过；容器构建启动及 Linux 字体渲染未验证。
- 可用独立 PostgreSQL + pgvector 测试库时，在测试进程设置 `CLASSBRIDGE_TEST_POSTGRES_URL`，执行 `pytest tests/test_multilingual_migration.py -q`。测试使用随机临时 schema 并在完成后删除该 schema；只使用专门测试库，禁止指向业务库。
- RAG/摘要仍中文、demo 仅 zh-CN、单会话单目标语，均为本次约定范围。没有新增语言切换后的历史重翻译功能。
