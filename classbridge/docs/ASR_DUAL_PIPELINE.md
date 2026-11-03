# ClassBridge 原文与翻译双流水线验收报告

日期：2026-11-03。基线：`47e65e906c136f707b2096847508a70f8f48e389`（优化音频识别）。开始时已执行 fetch 并确认 origin/main；工作区干净。从该提交创建 `feat/asr-dual-pipeline-isolation`，未回退、合并或推送 main。

## A. 修改摘要

原文流水线：官方 ASR → 临时原文立即展示 → 官方 final 与 outbox 原子提交 → 成功后登记本地完成标记。未完成句子在上游排空后写为独立 interrupted 恢复事件，不冒充定稿。

翻译流水线：消费原文/稳定前缀快照 → 独立异步 MT → 核对身份、来源版本、翻译版本及预览请求 → 只更新译文状态。慢 MT、失败或乱序不能修改原文内容、时间戳和定稿状态。

前端 `sources` 与 `translations` 分别持有状态，字幕列表从 sources 派生。翻译先到不生成空字幕；当前原文缩短遵从 ASR 修订，不保留最长字符串冒充准确率。只保留一条、最多 2000 字符的上一版临时诊断。

## B. 修改文件清单

以下路径相对仓库根目录，每行说明旧问题、实际改动与结果。

| 文件 | 原有问题 → 修改及行为 |
|---|---|
| `classbridge/frontend/src/lib/types.ts` | 原译文共用状态 → 新增 SourceState、TranslationState、独立状态类型及未确认快照；保留 Segment 兼容字段。 |
| `classbridge/frontend/src/lib/events.ts` | 翻译可改变原文生命周期，停止删除 partial → 分离 source/translation/session/snapshot 处理器；派生视图、精确版本匹配、有限孤立译文缓存、待确认状态、清空水位保护；独立 controlSeq 防止译文序号压制录音控制事件。 |
| `classbridge/frontend/src/lib/useLive.ts` | 只恢复正式快照，清空重置游标 → 合并正式与未确认快照；附快照水位；丢连接标记本地待确认；清空保留游标。录音及连接协议保留。 |
| `classbridge/frontend/src/components/SessionView.tsx` | 共用字幕状态与含糊等待文案 → 独立显示原文和中文状态；失败明确原文保留；未确认原文即使隐藏普通原文仍可核对；卡片身份不变。 |
| `classbridge/backend/app/ws/live.py` | 提前标记 final、无未定稿恢复 → 提交成功后标记；失败可重试同结果；跟踪最后 partial；结束时持久化 interrupted，再 stopped。清理只以正式来源触发总结。 |
| `classbridge/backend/app/services/events.py` | 只有正式字幕序列化 → 加入独立状态/失败译文快照，save_interrupted/unconfirmed_segments；不改变正式 save_final/save_translation 的事务及正式来源集合。 |
| `classbridge/backend/app/api/sessions.py` | 刷新无未确认记录、清空响应无水位 → 返回 unconfirmed_segments；清空响应附 event_seq；沿用归属检查。 |
| `classbridge/backend/app/workers/tasks.py` | 翻译错误缺少句子定位 → 仅在正式来源存在时附身份和 source_revision，避免误伤采音或别的句子。 |
| `classbridge/backend/tests/test_dual_pipeline.py` | 缺少双通道/中断故障测试 → 19 个参数展开用例，覆盖阻塞 MT、持久化故障、正常排空、网络异常、证据隔离、权限、缓存淘汰及重放。 |
| `classbridge/backend/tests/test_live_ordering.py` | 一个测试没有真实会话 → 补充会话种子以验证新的流归属校验，保留原有所有排序断言。 |
| `classbridge/frontend/tests/dualPipeline.test.ts` | 缺少独立状态回归 → 13 个用例，覆盖不可变原文、版本、乱序、失败、恢复、清空和有界缓存。 |
| `classbridge/frontend/tests/events.test.ts` | 旧期望允许翻译创建新原文、停止删除 partial → 按新业务改为只有 ASR final 能定稿；停止保留待确认。其余断言保留。 |
| `classbridge/frontend/tests/incrementalTranslation.test.ts` | 旧期望切换流丢弃旧 partial → 改为旧原文待确认，旧预览仍失效；布尔状态改为明确 false，保留算法与复用断言。 |
| `classbridge/frontend/tests/sessionView.test.ts` | 未覆盖独立状态文案 → 新增真实组件 SSR 验证，未确认原文和翻译失败有明确显示。 |
| `classbridge/docs/API.md` | 未描述新恢复字段 → 补充事件、独立状态、版本/清空水位和故障约定。 |
| `classbridge/docs/TEST_RESULTS.md` | 缺少本轮证据 → 记录实际执行命令与数量，区分 Mock 与真实效果。 |
| `classbridge/docs/ASR_DUAL_PIPELINE.md` | 无本轮验收报告 → 本文提供逐文件、测试及限制说明。 |

## C. 原文丢失修复证明

| 场景 | 自动测试证据 |
|---|---|
| 原文先到、翻译后到 | 前端立即生成原文；翻译 partial/final 后 sources 对象引用与文本、状态、时间戳保持不变。后端 Mock MT 持续阻塞时，下一个 ASR partial/final 仍处理完成。 |
| 翻译失败 | 原文保持 final；只对应译文变 failed；后端失败事件有精确来源，数据库原文及 outbox 不回滚；快照可恢复 failed。 |
| 旧译文乱序 | 较低 source_revision 和 preview_request_id 无效，且不触碰原文。只有匹配来源的译文进入可见视图。 |
| 未定稿中断 | 正常未定稿结束、网络错误均写 interrupted，序号早于 stopped；没有新增正式字幕、向量或仅基于未确认内容的摘要任务。 |
| 正式保存失败 | 在原文/事件/outbox 写入后注入异常，事务回滚；finalized/final_results 未增加，重试同 final 后只保存一次。返回 None 也不能无条件标记成功。 |
| 停止与恢复 | 用户 stop 等待 Mock 上游最终句，正常最终句不生成 interrupted；API 刷新与实际 TestClient WebSocket after_seq 重放能恢复未确认记录，不自动录音。 |
| 清空、权限、证据 | 私有会话返回 404；清空后旧 interrupted 删除，前端拒绝旧快照/事件；RAG、摘要、导出不读取未确认文字，合法后续 final 替换未确认显示。 |

后端 final 身份缓存最多 512 个，指纹缓存最多 2048 个；淘汰后依据数据库正式版本拒绝迟到 partial/重复 final。未完成句子最多 200 个，超限明确停止并结算已有记录。临时翻译沿用既有并发/限流；已完成临时任务及时清理。WebSocket 单次发送最多等待 10 秒，无无限待发送任务集合。

## D. 兼容性

- 增量翻译默认 false 未改；false/true 两种配置均完整回归。稳定前缀、可撤回预览、正式翻译优先级、完整预览安全复用仍通过原测试。
- Qwen Streaming ASR、Qwen MT、语言提示、热词、课程上下文、VAD、麦克风处理、重采样和官方协议适配文件未修改。
- 正式数据库表结构及迁移未修改。SegmentRevision、Translation、Outbox 的语义保留；interrupted 只用 Event 表，不进入正式来源查询。
- RAG、历史引用、资料库、导出和真实音频 reprocess 原有测试保留且通过。人工采纳的历史 provenance 仍可追溯。
- 推测矫正没有恢复。残留搜索只在 `api/settings.py` 的旧字段清理、`services/retired_tasks.py` 的旧任务/事件墓碑，以及 `test_retired_correction.py` / `retiredCorrection.test.ts` 的负向兼容断言命中；对应代码未修改。
- 未读取或修改用户偏好、真实音频或真实数据库；测试使用临时 SQLite、Mock ASR/MT，进程环境覆盖密钥为空。未改用户 .env。

## E. 实际测试报告

环境：项目现有 `.venv`、Python 3.13；前端现有 Node/npm 与依赖。无付费模型调用。

| 命令（分别在 backend/frontend） | 实际结果 |
|---|---|
| `python -m pytest tests/test_live_ordering.py tests/test_incremental_translation.py -q` | 第一轮定向：10 passed，0 failed |
| `python -m pytest tests/test_dual_pipeline.py -q` | 开发中定向：15 passed，0 failed；之后新增 4 个边界用例 |
| `INCREMENTAL_TRANSLATION_ENABLED=true` 下 `python -m pytest tests/test_live_ordering.py tests/test_incremental_translation.py tests/test_dual_pipeline.py -q` | 最终定向：29 passed，0 failed |
| `INCREMENTAL_TRANSLATION_ENABLED=false` 下 `python -m pytest -q` | 167 passed，0 failed，21.46 秒 |
| `INCREMENTAL_TRANSLATION_ENABLED=true` 下 `python -m pytest -q` | 167 passed，0 failed，20.53 秒 |
| `npm test` | 64 passed，0 failed |
| `npm run typecheck` | 通过，0 类型错误 |
| `npm run build` | 通过，2120 模块，3.45 秒 |
| `git diff --check` | 通过 |

PowerShell 中用 `$env:INCREMENTAL_TRANSLATION_ENABLED='false'` 或 `'true'` 设置开关，再执行项目 `.venv/Scripts/python.exe -m pytest -q`。测试前将本进程 `DASHSCOPE_API_KEY` 覆盖为空，使用本地测试 Origin；不改 .env。

前端开发中曾有一项新增测试把文本字母排序当成身份排序，已修正为既有 stream/sentence 身份排序；最终结果如上，没有删除失败断言。原业务冲突测试的变更原因见 B。

## F. Git 提交

功能分支：`feat/asr-dual-pipeline-isolation`。提交信息：`feat(asr): isolate source and translation pipelines with durable interrupted captions`。最终 SHA 随交付消息提供，也可用 `git log -1 --format=%H` 查看。不推送、不合并、不删除分支。

## G. 剩余风险与启用

- 本改造防止应用的翻译/停止流程丢弃已观察到的原文；不会提高云端 ASR 自身的词语、人名、术语识别准确率。
- 云端可以合法修订或缩短 partial；云端没有识别出的讲话、进入 ASR 前丢失的音频无法凭文字恢复，也不会猜测补写。
- 进程被硬终止、断电或数据库持续不可用时，内存中的末尾 partial 可能来不及写 interrupted。正常结束和可处理的断网经过结算；存储失败有明确错误，不保证全部保存。
- 前端断线会保留当前已见文字为待确认，但只有服务端成功结算的记录可以跨刷新恢复。
- 未做真实付费接口、实体 Safari、105 分钟真实网络波动或生产 PostgreSQL/Celery 压力测试；Mock 通过不等于真实课堂效果验证。
- 本次没有重启用户运行中的服务或发布服务器。采用分支后需统一重启 API/worker（如运行 beat 也重启），使用新前端构建并刷新浏览器；无新增数据库迁移。旧版前端不会展示新增未确认记录。
