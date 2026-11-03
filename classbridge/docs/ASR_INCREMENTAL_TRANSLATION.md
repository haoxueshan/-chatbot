# 增量翻译试验（方案 A）

日期：2026-11-03；基线 `79dd0e2823ec2f0e0702db686c38ffd17536e797`；分支 `feature/asr-incremental-translation`。

## 范围与开关

`INCREMENTAL_TRANSLATION_ENABLED=false` 默认保留既有行为；只在独立试验环境设置为 `true`。不改变 ASR/MT 模型、音频格式、AudioWorklet、20ms 帧、语种/热词/场景设置和正式原文版本。此开关由服务器配置，网页不收集密钥。

## 第一阶段：基线与稳定预览

修改前完整后端回归：103 passed，18.63s。源码检查发现本地 worker 每 600ms 扫描，Celery beat 每 3s 派发；临时翻译按 12 字符/1.2s 触发，任意新原文版本会使旧请求结果失效。轮询间隔不是实测端到端延迟。

`StablePrefixProcessor` 比较两个不同完整假设中的完整词/韩语词节，保留原始空白和标点。无结束边界的末词不确认；相同事件不增加共识；一致词仍需 350ms 最小存续时间。后续改写允许回退，所有输出仅为可撤回预览，绝不创建 SegmentRevision 或索引。每流/句独立；定稿清理，最多 64 句、每句 2048 字符、30s 空闲过期。超长假设不截断原文，只退出推测处理。

参考核验（2026-11-03）：[WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit)、[WhisperStreaming LocalAgreement](https://github.com/ufal/whisper_streaming)、[SimulStreaming](https://github.com/ufal/SimulStreaming)。只借鉴连续假设一致和提交/预览分离思想，没有复制其实现或安装服务。Qwen 提供句子文本修订和云端定稿，不提供本地 token/attention；因此不能移植 AlignAtt，也不能把一致前缀永久提交。

[Qwen MT 官方文档](https://help.aliyun.com/zh/model-studio/machine-translation) 支持 `qwen-mt-flash` 流式文本响应、`translation_options` 语种、术语和领域提示；MT token 流不等同于持续音频同传。本次保留现有请求参数，不新增猜测的上下文参数。

## 测量口径

- `source_first_ms`：服务端第一条原文到达，距音频 start_ms 的估计值。
- `source_final_ms`：服务端定稿到达，距音频 end_ms 的估计值。
- `translation_queue_ms`：任务 created_at 到当前执行尝试开始，使用 UTC 墙钟；包括重试等待，跨进程需要校时。负值归零且 `translation_queue_clock_skew=true`，不能据此证明时钟准确。
- `translation_model_first_ms` / `translation_model_final_ms`：同进程 monotonic 模型请求首个文本/结束耗时。
- `translation_first_ms` / `translation_final_ms`：source_final 延迟 + 原文保存至执行的墙钟间隔 + 模型耗时，是服务端音频终点参考估计，**不包含事件发布轮询、网络和浏览器绘制耗时**。

不记录课堂原文/译文或密钥到诊断日志。现有业务数据库按原有私有存储规则保存正式内容。

第一阶段测试：`pytest -q tests/test_stable_prefix.py tests/test_providers.py tests/test_live_ordering.py`：38 passed。覆盖韩英混合、词尾改写、重复、最小时间、回退、1万句有界缓存、stream 清理和两种时钟。

## 真实效果限制

## 第二阶段：有界临时翻译

按完整词共识触发，三个完整词或保守的谓语/标点提示可形成候选；2.4s 最大等待到达时可翻译有边界的当前假设，但不将它标记为稳定/正式。这只是启发式，不保证韩语句意完整。100ms 定时检查使没有新事件的假设也可触发。仍保留 1.2s 请求间隔，新增不足 6 字符时延后，单句最多 64 个不同候选，不自动重试失败文本。

一个 API 进程内所有会话共享最多 1 个临时请求、每分钟最多 20 次的预算；达到上限直接暂缓，不排无限队列。支持最多两个同时录音的现有单 API 部署。多 API 进程/多副本的集群级额度仍需另行分配（本次不声称 Redis 分布式限流已实现）。正式后台任务不获取临时预算，避免被预览占满应用内并发；两者仍共享云端账号额度。

新尾部仍以已请求的完整前缀开头时，可继续接收该前缀的结果，事件明确包含 `preview_source_text`，并绑定当前原文版本；原文重写则使请求身份立即失效。取消任务不代表云端一定停止计费，取消后的迟到 token 仍通过句子身份和请求代数拒绝。预览不持久化，定稿/结束清理。模型异常仅计入无内容计数，不中断 ASR。

第二阶段测试：`pytest -q tests/test_incremental_translation.py tests/test_stable_prefix.py tests/test_live_ordering.py`：18 passed。新增覆盖 timer fallback、相同文本不重翻、取消后迟到结果、多句预算、失败不重试、1万句缓存边界、定稿清理、模拟隔离、开关回退以及预览不产生正式原文/索引。

用户确认没有人工标注音频。因此真实课堂首次原文/中文与定稿 P50/P95、韩语 CER、英语 WER、术语正确率以及实际 API 账单变化均待验证；不能将后续 Mock 回放结果当作真实模型质量或成本提升。
