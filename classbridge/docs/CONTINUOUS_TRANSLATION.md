# 持续预译与正式快照（2026-11-11）

两种 `INCREMENTAL_TRANSLATION_ENABLED` 配置均保留。`false` 使用现有传统候选调度，`true` 使用 StablePrefixProcessor；两者共用请求预算、输入去重、有限请求超时与完整结果校验。不需要配置或数据库迁移。Qwen MT 仍是一次文本输入、一次有限流式输出，不是可追加输入的永久会话。

## 短句与连续增长

完整标点、保守的韩语谓词结尾及“네／예”等应答可在文本不变约 350ms 后成为可撤回候选；默认最多等待 2.4 秒，持续变化不会反复重置最大等待。重复假设不算新的 LocalAgreement 证明。请求间隔、并发、每分钟预算、缓存数量与 TTL 继续生效，不能保证预算耗尽时仍在此时间内调用 MT。传统模式原有长文本触发时机保持兼容。

仅单个句末句号增删可复用预览请求身份；问号、否定、空格、韩语词尾和省略号不做语义归一化。正式快照仍要求原文完全匹配。无词级可靠轮次信息时，只按可读表达提前预译，不新增句子或说话人，不解决重叠音频识别。

## final 与跨进程交接

`save_final()` 仍原子提交权威原文、事件、索引任务、翻译任务及 Outbox。

- 已完整结束且原文、stream、sentence、目标语言、模型、术语、规格摘要与 TTL 均匹配：worker 保存 `Translation` 与 `translation.final`，不再推理。
- 精确匹配的 MT 仍在运行：任务 payload 保存请求编号和有界期限，worker 暂不认领、不给 attempts 加一。API 的固定上限协调任务等待已有请求，完成后用独立数据库 Session 写入可验证结果并唤醒 Outbox。没有跨进程共享 asyncio 对象。
- 已明确失败、无预译或最终原文不匹配：允许一次补偿请求；自动重试关闭。结果必须完整结束才可落库。翻译任务原有重复投递保护及原文版本检查保留，SQLite 使用条件更新认领任务。
- 交接中进程退出、超时或结果未知：期限到后产生 `preview_outcome_unknown`，保留正式原文，不自动重新提交不确定的付费请求。此时可能没有正式译文，这是明确失败而非伪造完成。已认领的 worker 异常退出仍沿用 abandoned-task 恢复策略。

停止录音不取消匹配的在途翻译；只在有限收尾时间内等待。浏览器停止后不再要求临时 UI 发送成功才能生成完整快照。前端可保留与 final 原文精确匹配的预译，仍标记临时，只有持久化事件确认正式状态。改写、失效 stream、旧请求及不匹配版本继续拒绝。

## 诊断与验证范围

`capture.health.preview_metrics` 记录 ASR 事件、预译请求／完成／取消／失败及重复抑制次数；重复抑制按调度检查计数，不代表节省的实际付费次数。`ProcessingTask.result` 与原有字幕 latency 保存 `translation_reused`、`translation_fallback_requests`、首字与排队时间；字段只记录数值。任务排队时间包括有界交接等待，不等于模型耗时。

`tests/test_continuous_translation.py` 使用 Mock 覆盖短句、20 次时间戳更新、30 秒增长、在途 final、停止、流失败、14 种目标语言及重复投递。独立 Python 子进程实际调用 Celery 任务入口并共享临时 SQLite，验证进程间交接成功／丢失；这不等于已验证生产 Redis broker、PostgreSQL 或真实课堂。未调用 Qwen API，未声称解决实体设备或重叠语音识别问题。

## 本次验证记录

基线 `012017ded3d42146b9e699cd50cbe02987ee56ad`。使用 `git show` 加载该版本的调度器／LiveCapture，与修改后代码回放相同 Mock，未连接模型。复用校验与完成时间使用同一假时钟；测试数据库为临时 SQLite，provider 全部替换。

| 场景 | 基线 | 修改后 |
| --- | --- | --- |
| 增量模式“네”首次预译（虚拟时间） | 2400ms 内无输出 | 350ms |
| 传统模式：完整预译后相同 final | MT 1 次、final 1 次 | MT 1 次、final 1 次 |
| 传统模式：相同 final 在 MT 生成中到达 | MT 2 次、取消 1 次 | MT 1 次、取消 0 次 |
| 30 秒单 sentence 连续插话首次预译（虚拟时间） | 2500ms | 500ms |
| 上述 30 秒回放请求／取消数 | 6／0 | 6／0 |
| 在途 final 的完整保存结果 | 与完整 Mock 输出相同 | 与完整 Mock 输出相同 |

连续插话回放：每 5 秒追加一个完整韩语提问，每秒更新 ASR，半秒 tick，预算设为 8 次／分钟；输入按 `consume()` 的规则去除首尾空格。不据此推断真实课堂延迟或翻译质量提升。

- 完整后端 `INCREMENTAL_TRANSLATION_ENABLED=false`：337 passed，1 skipped。
- 完整后端 `INCREMENTAL_TRANSLATION_ENABLED=true`：337 passed，1 skipped。
- 跳过项：无独立 PostgreSQL + pgvector 测试服务器，多语言迁移测试未执行。
- 前端：86 passed；TypeScript 与 Vite 生产构建通过。
- 100 token 测试保留首字、4 次流式 partial 与 1 次完整 final；既有字幕滚动、录音生命周期、多语言及历史恢复回归保留。
- Celery 任务入口的独立进程 + SQLite / Outbox 验证通过；没有启动真实 Redis broker 验收。
