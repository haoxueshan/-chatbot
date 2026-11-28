# ClassBridge P4 实施与验证报告

日期：2026-11-27；续作更新：2026-11-28。修改前基线：`62d269f1ecab297b2bed53ef6c383b7e895b7729`。
工作区已有的未跟踪 i18n / browser 日志保持原样。本次没有推送、部署或访问真实付费模型，没有更改 `.env`、API Key、用户数据库或迁移文件。

## 修复与完成边界

| 范围 | 状态与实现 |
| --- | --- |
| ProviderError | 已提取通用异常；旧 Aliyun 导入仍是同一类型。Soniox 使用无供应商文案的状态分类，不再导入 Aliyun。 |
| Qwen 协议 | 已提取 run-task、finish-task、服务端事件及句子归一化纯函数。严格布尔、整型时间、范围、任务身份、必需字段与嵌套对象校验。未知/外来任务不会刷新活性。 |
| partial 时间 | `end_ms=None` 保留；合法 words 最大结束时间为 `provisional_end_ms`。应用层只加一次 offset；UI 兼容数值附带 confirmed/provisional/unknown，显示约数或问号。 |
| final 保护 | 非法 final 进入结构化故障路径；之前 partial 仍在未确认状态。空 final 只计数，不把 partial 定稿。Qwen/Soniox 不接受没有修订证据的冲突 final；保留原有显式版本保存流程。 |
| 浏览器 PCM | 已实现 Framer / Resampler flush、Worklet request_id 确认、AudioCapture.finish(500ms) 与 useLive 正常/紧急收尾。正常 flush 保留 generation 和帧监听，最后 PCM 先于 stop。 |
| 配置 | 已新增 frozen dataclass；在正式流创建时解析一次并关联现有 asr_snapshot.effective。Live 路径 Adapter 不再二次覆盖；旧调用入口保留兼容处理。 |
| 状态与持久化 | 已提取 normalize_update、HypothesisStore、lookup_transcript、persist_final_update。沿用 save_final、SegmentRevision、Translation、ProcessingTask 和 Outbox。consume 外部入口不变。 |
| partial 快速路径 | **未采用跳过数据库的内存快速路径**。多 API 进程下没有可靠失效通知，仍逐次检查用户归属/active_stream；11-28 将首次版本检查与会话检查合为一条 SQL，并逐次检查其他进程的正式证据。100 条 partial 从 101 次 SELECT 减至 100 次，不宣称显著提速。 |
| 翻译 | 保留现有 IncrementalTranslator、StablePrefixProcessor、PreviewBudget 和 handoff，默认参数未变。输入仍是归一化原文而非供应商 JSON。 |
| words.fixed | 仅校验并保留词级辅助信息；**未启用稳定前缀提示**，未证明当前课堂条件下可靠，不改变默认翻译行为。 |
| 诊断 | 复用 audio_diagnostics，增加音频发送、事件、心跳、partial/final 时间年龄及保守停滞提示。年龄单位 ms，未知为 null。只有提示，不自动停止/重连。 |
| 能力与 VAD | 模型协议兼容性与账号权限/真实调用验证分开描述。已知默认 Qwen 模型支持可选 VAD 参数；全为 None 默认不发送。未知模型仍可添加，但拒绝未经验证的高级参数。 |
| 评测 | 复用 evaluation.py，增加同文件 A/B/C 顺序比较、PCM 哈希、修订/重复/未确认句子统计。CLI 默认拒绝付费请求。 |
| RAG/摘要/界面 | 沿用现有正式证据消费和后台任务隔离；保留中英韩、主题、文件夹、历史、导出和 RAG，不另建主链路。 |

## 模块和依赖变化

新增运行模块：

- `backend/app/providers/errors.py`：供应商无关异常与状态码类别。
- `backend/app/providers/asr/aliyun_protocol.py`：无网络、数据库或翻译依赖的 Qwen 协议函数。
- `backend/app/services/asr_config_resolver.py`：有效参数解释和不含密钥的快照。
- `backend/app/services/transcript_state.py`：纯内存、有界状态；200 未确认、512 正式身份、2048 final 指纹限制不变。
- `backend/app/services/transcript_processor.py`：时间/身份 DTO、数据库检查和正式保存边界。

修改运行模块：Provider base/factory/registry、Aliyun/Soniox、asr_profiles、audio_diagnostics、config、live；api/asr、main、workers/tasks、incremental_translation 仅更换通用异常导入。浏览器修改 PCM、Worklet、AudioCapture、useLive、字幕时间字段、SessionView、captureHealth 与中英韩资源。没有删除运行文件。

原来：通用 ASR 和 Soniox → Aliyun 异常；Aliyun WS 循环内解析原始 JSON；LiveCapture 同时持有状态/时间转换/保存判断。

现在：通用 ASR/Soniox → errors；Aliyun WS → 纯协议模块 → ASREvent；LiveCapture → TranscriptUpdate/HypothesisStore → 现有持久化/Outbox。音频只输出 PCM，与 Registry 和翻译无关。

仍由 LiveCapture 协调生命周期、故障、partial/final 调度以及翻译 handoff；这部分没有整体重写。旧入口兼容层仍存在，未来可在所有外部调用迁移后进一步缩小。

新增四个后端测试文件（protocol/config/contracts/transcript），新增前端 audioFlush 测试和离线 PCM 基准，扩展 uiInteraction。AST 检查 Provider 无模型/SQLAlchemy/RAG/翻译依赖，协议与内存状态无网络依赖。测试用 Registry Adapter 无需修改原文、Outbox、RAG 或前端。

## 配置和兼容性

原先 Profile/Live/Adapter 分散覆盖；现在正式录音统一为服务器限制 > 模型显式参数 > 用户偏好 > 默认值。语言 null 继承，[] 自动，非空列表显式；context 空串清空；vad_model 显式参数优先。Soniox terms 保留全局在前、模型在后、去重后最多 200 项的规则。

持久化沿用已有私有 profile 快照规则；新增 effective 只含公开安全字段和 context/词表数量，没有认证信息或全文。当前流配置固定，修改设置只影响下一条流。默认 Qwen 模型、100ms 聚合、浏览器 20ms、8000ms 服务端上限、5s 发送超时及全部翻译参数不变。

可选 `ASR_STALL_WARNING_SECONDS` 默认 20，范围 10–300 秒，无需修改现有 `.env`。它是诊断策略，不是供应商 VAD 或语音检测。`ASR_RECOVERY_ENABLED=false` 启动校验保留，不重放不确定音频。

VAD 参数依据：[官方客户端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-client-events)。`max_sentence_silence` 为 200–6000ms，`speech_noise_threshold` 为 -1..1，另外两项为布尔。仅默认模型允许显式发送；本次没有真实课堂效果验证。
partial/null 时间与句子结束语义依据：[官方服务端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-server-events)。没有将可撤销词级状态视为正式证据。

## 可复现性能结果

`python -m pytest -q -s tests/test_transcript_processor.py` 在同一环境、相同临时 SQLite schema、100 次不同有效 partial、相同 FIFO/计时规则下比较参考提交与当前实现。为了隔离识别消费，双方均关闭预览工作并使用 Mock UI。计时从 queue.get 前至 consume 完成，单位 ms。

| 指标 | 基线 | P4 |
| --- | ---: | ---: |
| 有效 partial | 100 | 100 |
| SQL SELECT | 101 | 100 |
| Session 创建 | 100 | 100 |
| P50 | 0.824 | 0.939 |
| P95 | 1.048 | 1.045 |
| 结果队列峰值 | 64 | 64 |
| 正式原文 / 重复正式原文 | 1 / 0 | 1 / 0 |
| 翻译任务 | 1 | 1 |
| final 后未确认项 | 0 | 0 |

这是 11-28 本机 Mock 单次测量，不是生产延迟或性能提升结论。减少了一次 SELECT，但没有显示明显的延迟收益；每条 partial 的数据库 Session 和安全校验均保留。未确认保留、数据库失败、旧流和淘汰后回查由单独回归覆盖。

`node tests/benchmark_pcm_flush.mjs` 使用每个采样率 1 秒 + 100 输入采样，同一正弦输入和 128 点分块：

| 输入采样率 | 停止前旧实现发送字节 | P4 发送字节 | 真实有效输出期望 |
| --- | ---: | ---: | ---: |
| 16000 | 32000 | 32200 | 32200 |
| 44100 | 32000 | 32074 | 32074 |
| 48000 | 32000 | 32068 | 32068 |

长度规则为输出采样位置落在真实输入区间内，即 `ceil(input_samples * 16000 / input_rate)`。滤波边界补零不计为新增录音。正常连续处理算法保持不变。零尾帧、重复 flush、资源释放、超时、断线、麦克风失效、服务器提前停止、卸载均使用确定性输入测试。正常 stop 实际网络耗时未实测；500ms 仅是浏览器 flush 等待上限，之后仍须等待服务器 finish。

## 测试记录

最终完整运行结果见同目录 [TEST_RESULTS.md](TEST_RESULTS.md) 的 P4 更新。原始日志保存在被忽略的 `test-results/p4-*.log`，浏览器检查结果在 `test-results/p4-responsive/`。历史日志没有被覆盖。

11-27 回归为后端 542 项、前端 139 项；11-28 续作另增加跨进程数据库变化、时间状态变化、A/B/C 输入保护、实际 wire 参数一致性和 flush 超时测试。11-28 最终两种后端模式各 554 passed、1 skipped，前端 140 passed，类型检查及生产构建通过；新增 12 项后端、1 项前端用例。没有删除或放宽原有安全断言。Windows 的 `python` 命令指向未安装解释器的 Store 别名，实际使用仓库 `.venv/Scripts/python.exe`。

## 验证边界与剩余工作

- Qwen/Soniox WebSocket 握手、发送、超时、finish、断线及资源释放通过协议 Mock 测试；没有调用真实云端，不能证明账户权限或真实识别准确率。
- 真实韩英混合 CER/WER/MER、术语召回需要同一录音和人工参考文本；本次只验证评分规则/工具，Mock 文本不能视为真实准确率。
- 长流测试是加速的确定性 PCM，包含 105 分钟等效输入；没有真实课堂连续录音验收。
- Chromium 模拟布局与 React 生命周期不代表实体 iPad Safari、系统后台/音频设备中断或实际 VPN 验收。
- SQLite 测试使用临时文件。未提供独立生产 PostgreSQL 测试环境，不能宣称 PostgreSQL 集成通过。
- 未实现跨进程无查询 partial 快速路径、自动恢复/重放或词级稳定性驱动翻译，均保留安全回退。
- 音频中断/flush 超时只记录不确定性，不宣称完全排空；没有估造丢失字节数。无此前 partial 的损坏 final 只能记录协议错误，不能构造“合法 partial”代替。

## 11-28 续作

- 合并 lookup_transcript 查询，使用标量版本子查询和 final 重复 EXISTS，避免加载整个 Session/SegmentRevision 对象；每次读取都检查归属和活动流。新增另一数据库连接写入 final、变更 owner/active_stream、删除会话的回归。检查反映的是当前语句可见状态，不宣称跨进程全局锁或缓存强一致性。
- HypothesisStore 去重包含 end_time_state；数值相同但未知时间变为供应商已知时间时会更新状态。
- Qwen/Soniox Mock WebSocket 捕获实际发送 JSON，验证模型、语言提示、context、词表及参数快照一致，输入配置在启动后修改不能污染已冻结任务。
- A/B/C 在每次创建供应商任务之前检查 PCM 哈希和 WAV 完整性；发现文件变化立即停止，不再创建后续任务。报告不再使用无修订依据的冲突 final 替换先前证据，增加 conflicting_finals 计数；空 final 不制造完成状态。
- useLive 增加 flush timeout 回归，已接收尾帧先发出，再记录不确定性，最后只发送一次 stop。
- 本机未发现 docker 命令，也没有独立 PostgreSQL 测试地址；没有连接或修改现有用户数据库来代替集成验收。

## 部署与回退

本次没有执行部署。无需迁移，版本仍是 0005；无需编辑现有 `.env`。发布时先停止活动录音，部署代码并重启 API；Worker 使用相同代码包，建议一并重启；前端必须重新构建发布，避免旧 AudioCapture 与新 Worklet 混用。

回退时同样先结束活动流，将 API/Worker/前端恢复到参考提交对应的同一版本。无需数据库降级或删除记录，新增快照 JSON 字段是向后兼容扩展。不要对包含用户修改的工作区使用 `git reset --hard`。本次变更保留在工作区供审阅，未自动创建提交或推送。
