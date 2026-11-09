# 实时翻译字幕稳定性验证（2026-11-09）

基线：`b6429189ceb32cfb50239b15b7af7661815cf62c`。
分支：`fix/translation-subtitle-stability`。所有验证均为 Mock，未调用付费 API。

## 已复现及修复

- 传统预译：20 次同文本、不同 end_ms 的 partial 导致 20 次调用、19 次取消。现在请求身份绑定原文内容，时间戳/原文版本继续更新；同一有效输入不重新请求，失败输入不自动重试。兼容增长等待在途请求，实质改写立即失效。每句最多 64 个尝试摘要，沿用未定稿句上限、两个在途传统请求及现有进程级请求预算；每 100 ms 使用现有维护循环检查最小变化、边界和最长等待条件。
- 增量预译：兼容增长曾取消仍有效请求。现在保留在途请求，避免候选前缀倒退，并保留仍兼容的完整预览。时间戳更新只刷新存活时间，不伪造 StablePrefix 的独立文本一致性。活跃重复假设不会因 TTL 被误清理并重试失败输入。
- 预译到定稿：传统完整预译也通过现有 candidate / Outbox 通道交给正式 worker，检查原文、stream、sentence、绑定后的 source_revision、目标语言对应的 spec、完整结束及 TTL。失败、不完整、过期或配置不匹配均拒绝复用；不开启 StablePrefix 来绕过传统模式。
- 正式时间戳修订：保留新的 SegmentRevision、索引任务、正式译文版本和事件。只复用同会话/流/句/原文/目标语言的已完成正式结果，校验任务保存的配置摘要、完整结束及译文内容摘要。历史任务缺少证明、译文已更改或配置改变时正常调用正式 MT。
- 正式流：两种模式均使用 `translation_emit_seconds`（默认 250 ms），首个有效 token 立即发布，结束时提交完整结果；保留原有空 delta 过滤，不把重复 token 当成重复快照删除。正式及可复用预译均要求模型流正常结束。
- 前端：源文本变更版本与时间戳版本区分；同版本等价快照保留可视对象引用，同时维护 event_id、event_seq 和终态。新请求保留自己的身份，可暂时显示兼容的完整旧预览；新请求完成后允许合法缩短。实质改写、旧 stream、旧请求、错误目标语言以及尚无对应原文的未来版本仍受隔离。
- 滚动：合并到浏览器动画帧，仅在实际底部位置改变且用户仍跟随时滚动。观察容器和末尾内容尺寸；用户阅读历史时停跟，保留“回到最新”。观察器和动画帧均清理。

## 同负载对比

这些是确定性事件回放次数，不是成本、真实网络延迟或翻译质量测量。

| 场景/指标 | 基线 | 修复后 |
|---|---:|---:|
| A：partial ASR 事件 / 有效文本变化 | 20 / 1 | 20 / 1 |
| A：传统预译请求 / 额外重复请求 | 20 / 19 | 1 / 0 |
| A：定稿前 MT 取消次数 | 19 | 0 |
| A：translation.partial 事件 | 20 | 1 |
| B：20 个等价预览的可视对象更新 | 20 | 0 |
| B：19 次时间戳修订造成在途预览消失 | 19 | 0 |
| C：20 次同高度译文更新触发滚动 | 20 | 0 |
| D：100 token 正式流的 partial 事件（关闭增量） | 7 | 4 |
| D：100 token 正式流的 partial 事件（开启增量） | 4 | 4 |
| D：完整最终输出 / final 事件 | 100 token / 1 | 100 token / 1 |
| E：时间戳正式修订的 MT 次数 / final 事件 | 2 / 2 | 1 / 2 |
| F：传统完整预译到正式定稿的 MT 次数 | 2 | 1 |

A 以 1.3 秒虚拟间隔输入同一句韩语，MT 发出首段后阻塞；取消计数不含最终清理。D 以 10 ms 虚拟间隔输出 100 个 token；两种模式首个 token 均立即发布。B 保持事件身份不同以测量快照而非 event_id 去重。正式译文均验证持久化/恢复完整，迟到 partial 不降级 final。

复跑基准（需本地保留基线 Git 对象）：

```text
cd classbridge/backend
..\.venv\Scripts\python.exe tests/benchmark_translation.py

cd ../frontend
node --import tsx tests/benchmark_subtitles.ts
```

C 在 `uiInteraction.test.ts` 的真实 React DOM / Mock 尺寸及帧回调中验证；D/E/F 在 `test_translation_scheduling.py` 验证。相同测试先在未修复逻辑上失败，再验证通过。

## 回归结果

- 指定后端定向测试：113 通过。
- `INCREMENTAL_TRANSLATION_ENABLED=false`：276 通过、1 跳过。
- `INCREMENTAL_TRANSLATION_ENABLED=true`：276 通过、1 跳过。
- 前端：82 通过；TypeScript 与生产构建通过。
- 新测试覆盖 ko→zh-CN/en/ja/ar、en→ko，在途/完成/失败三种预译；原有全部 14 种目标语言、RTL、Outbox、来源版本、清空、重连、未定稿与正式恢复回归保持通过。
- PostgreSQL + pgvector 隔离迁移测试因未配置独立实例跳过；SQLite 路径已验证。

## 边界

未进行真实 Qwen、实体 Safari 或长课堂验收；不声称模型准确率、真实首字延迟或计费下降。请求取消不保证云端停止计费。合法改写、失效预览与正式结果仍允许替换，不将临时结果伪装成正式证据。

仅参考 [SimulStreaming](https://github.com/ufal/SimulStreaming)、[WhisperLiveKit 的调度实现](https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/whisperlivekit/translation_alignatt.py)、[Sokuji](https://github.com/kizuna-ai-lab/sokuji) 的公开策略方向，未复制其实现、引入推理引擎或假设 Qwen 提供注意力对齐。
