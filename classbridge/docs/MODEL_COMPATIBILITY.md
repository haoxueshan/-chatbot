# 阿里云模型与协议兼容记录

2026-11-02识别逻辑复核：官方[客户端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-client-events)仍要求task-started后发送音频、finish-task结束；max_sentence_silence默认800ms。[服务端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-server-events)以sentence_id关联句子，sentence_end区分中间/最终结果。适配增加启动task_id校验，应用去重重复定稿并拒绝迟到中间结果降级；没有新增云端请求参数。这一轮只做协议文档复核和本地测试，没有新增真实API或课堂效果验证，详见ASR_LOGIC_REVIEW.md。


本轮真实验证使用人工构造的韩语文字样本，两次文本模型调用（首次调用后Windows GBK控制台输出韩文失败，第二次完整记录）：原文“오늘은 작업 기역을 배웁니다.”，提供术语“작업기억”后返回一处通过服务器校验的修改，候选为“오늘은 작업기억을 배웁니다.”。样本在独立临时数据库中运行并清理，不修改用户已有字幕。两次均是付费文本模型入口；没有新音频识别调用，没有真实课堂准确率结论。

建议绑定原句版本并与原文分离，采纳时由用户生成新版本；原音频、原文、原引用保留。模型仍可能推测错误，服务端规则只能限制改动与校验证据，不能证明讲话者原意。当前私人账号已按用户请求开启，其他账号默认关闭；每15秒最多安排一句抽查，四个任务积压上限、单次尝试。详见API及实时排查文档。

2026-11-02韩语词语、人名及专业词误识别：复核[官方热词/上下文说明](https://help.aliyun.com/zh/model-studio/improve-asr-accuracy)及[客户端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-client-events)。现支持热词权重2/3/4（默认仍2）和400字符内的用户自填课程背景，经input.context中的user/input_text传递；不追加虚构prompt参数。官方说明上下文需含实际原词，仅写语义相关描述效果有限；过高热词权重可能导致其他词被错替换，因此不自动把所有词升为高权重。

修复provider原先截取末400字符的方向，改为保留开头400字符；API拒绝超长背景。热词采用NFC规范化，报告缺原词、过长、重复等原因；ready事件仅回传有效数量/权重/背景字数，不记录背景全文。最新真实会话ready事件已确认ko_en生效，用户术语表仍为空，课程背景为空；尚待用户提供正确词例，未自动猜测或添加人名。本轮只完成配置链路与本地测试，**新增付费调用0，新增热词/背景的真实准确率及实体Safari效果未验证**。

2026-11-01韩语误判语种修复：复核[官方客户端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-client-events)，language_hints支持ko/en，未设置时全部语言自动识别。新增当前用户偏好auto（不传提示）、ko_en（传["ko","en"]）、ko（传["ko"]）。保留系统默认auto；针对本次用户确认的韩语被识别为中文/其他语言问题，将现有私人账号设置为ko_en。新建上游任务时读取偏好，ready事件回传实际采用模式；设置不改变已保存原文或当前任务。

接口实测：使用现有服务端配置发送**一次200毫秒PCM静音**，携带language_hints=["ko","en"]，收到task-started、发送200ms音频并正常task-finished，text_events=0。这是一次真实计费入口调用，验证参数被接口接受；**没有验证韩语识别准确率、韩英交替效果或iPad实机效果**。断句、VAD、采音和模型未调整。后端70项、前端23项和构建通过。

2026-11-01原文延迟排查：根据[热词官方规范](https://help.aliyun.com/zh/model-studio/improve-asr-accuracy)和[客户端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-client-events)，将当前用户术语原词接入已有vocabulary参数，使用温和权重2，过滤不符合长度限制的项。仍自动识别输入语言，模型、VAD及音频规格不变。本轮另外消除应用侧重复TLS证书加载的事件循环阻塞，添加仅应用内部的capture.health事件；没有向模型添加诊断参数。协议参数已查文档并通过本地请求断言，新的热词课堂效果、iPad延迟改善尚未实测，见[排查记录](REALTIME_TROUBLESHOOTING.md)。

2026-11-01后续真实使用证据：用户在iPad发起的会话已保存约42分钟采音、242条原文版本和对应后台处理记录，随后三次发生不同持续时长的积压中断。这是已有真实会话的数据库检查，不是本轮重新发起的模型测试，也不代表长课堂稳定性已通过。已复核下文客户端/服务端事件文档，保持task-started/PCM/finish-task协议；本轮改动是应用侧准备握手、转发调度、发送监测和异常清理，未编造模型参数。详情见 [实时中断排查](REALTIME_TROUBLESHOOTING.md)。

## 2026-11-01 真实短样本接入修复

实际业务空间专属域名在WebSocket升级阶段返回HTTP400，响应code为 `BadRequest.IllegalEndpoint`，message为 `Workspace endpoint is invalid.`；任务和音频尚未提交，因此不能诊断为音频格式不支持。当前配置的旧式数字空间编号未能用于该专属接入域名，正确API Host需从百炼控制台复制，不能猜测或直接增加前缀。

依据官方[地域与接入域名](https://www.alibabacloud.com/help/zh/model-studio/regions/)仍支持的北京DashScope兼容域名，已在本地私有.env显式配置以下覆盖值；不是失败后自动回退，也没有更换模型或地域：

```dotenv
ASR_WS_URL=wss://dashscope.aliyuncs.com/api-ws/v1/inference
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
```

真实验证结果：qwen-audio-3.1-asr-flash-streaming的一次200毫秒、16kHz、mono PCM16静音样本正常task-started并最终task-finished；不代表自然语音识别或韩英混说效果通过。qwen-mt-flash的一次单词请求Hello成功返回“你好”。除此之外的真实模型调用、课堂质量和延迟仍待验证。本次使用真实计费入口，不能再将这些测试记为0付费调用；样本严格限制为上述一次ASR任务和一次MT请求，握手诊断未发送音频。

已修复握手错误分类：有界解析响应中的code，不记录原始响应或认证头；非法业务空间地址映射region_mismatch而非format_error。新增回归验证失败握手不会消费音频迭代器。Provider测试17项通过。后端进程需重启后读取新的.env。

兼容域名用于当前验证，官方建议生产迁移到正确的业务空间专属域名，并指出兼容域名不再支持新特性。取得真实API Host后，应同步覆盖三个地址并重新验收，不把这一兼容配置当成已修正原Workspace ID。以下首次交付记录按原时间保留。

首次核验：2026-10-29（Asia/Seoul）。继续开发时复核：2026-10-30（Asia/Seoul）。下面是实际读取的阿里云官方页面与本项目采用的协议，不是根据模型名称推断出的接口。

## 验证等级

| 等级 | 本次结果 |
| --- | --- |
| 文档支持 | 下列全部默认模型均在官方文档中找到；北京地域作为默认部署选择 |
| 本地协议测试 | 通过 HTTP/WebSocket 受控测试替身验证请求结构、流式解析、结束事件、错误分类和引用校验；详见 `backend/tests/test_providers.py`、`test_knowledge.py` |
| 真实接口测试通过 | 首次交付时未验证；2026-11-01的ASR静音任务及单词MT有限验证见顶部记录，其余仍未验证 |
| 真实课堂效果验证 | **尚未验证**：韩英混说、教室远场、真实麦克风、iPhone/iPad 实体 Safari、长时连续录音与真实延迟均未实测 |

模拟模式不请求麦克风、不调用阿里云，不会证明真实同传可用。真实接口失败只返回错误；代码没有自动切换到模拟数据的路径。

## 实际采用的模型

| 用途 / 环境变量 | 默认模型 | 核验的地域与官方依据 | 本项目接口 |
| --- | --- | --- | --- |
| 持续识别 `ASR_MODEL` | `qwen-audio-3.1-asr-flash-streaming` | 北京、新加坡：[模型页](https://help.aliyun.com/zh/model-studio/qwen-audio-3-1-asr-flash-streaming)、[实时指南](https://help.aliyun.com/zh/model-studio/real-time-speech-recognition-user-guide) | WebSocket 双工 inference |
| 会后识别 `FILETRANS_MODEL` | `qwen-audio-3.1-asr-flash-filetrans` | 北京、新加坡：[模型页](https://help.aliyun.com/zh/model-studio/qwen-audio-3-1-asr-flash-filetrans)、[非实时指南](https://help.aliyun.com/zh/model-studio/non-realtime-speech-recognition-user-guide) | HTTP 异步提交、轮询、结果 JSON |
| 翻译 `TRANSLATION_MODEL` | `qwen-mt-flash` | 北京、新加坡：[翻译文档](https://help.aliyun.com/zh/model-studio/machine-translation) | OpenAI 兼容 chat completions + SSE |
| 阶段提取 `SUMMARY_MODEL` | `qwen3.7-flash` | 模型页列北京、新加坡及其他地域：[模型页](https://help.aliyun.com/zh/model-studio/qwen3-7-flash) | OpenAI 兼容，关闭思考，JSON 输出 |
| RAG 回答 `ANSWER_MODEL` | `qwen3.7-plus` | 模型页列北京、新加坡及其他地域：[模型页](https://help.aliyun.com/zh/model-studio/qwen3-7-plus) | OpenAI 兼容，关闭思考，JSON 输出 |
| 向量 `EMBEDDING_MODEL` | `text-embedding-v4` | 北京、新加坡：[同步 API](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api) | OpenAI 兼容 embeddings，1024 维，每批最多 10 条 |
| 重排 `RERANK_MODEL` | `qwen3-rerank` | 北京、新加坡：[模型页](https://help.aliyun.com/zh/model-studio/qwen3-rerank)、[排序 API](https://help.aliyun.com/zh/model-studio/text-rerank-api) | DashScope native HTTP |

地区出现于文档不代表本账号已获权限。首次上线须在同一地域、同一业务空间检查模型授权、额度和 IP 限制。模型列表参考：[ASR](https://help.aliyun.com/zh/model-studio/asr-model)、[文本生成](https://help.aliyun.com/zh/model-studio/text-generation-model)、[向量与重排](https://help.aliyun.com/zh/model-studio/embedding-rerank-model)。默认保留用户指定模型，没有擅自换用更新型号。

## 业务空间、认证与地址

官方当前推荐北京、新加坡业务空间专属域名；不同地域的 API Key 不能混用。API Key 可限定业务空间、IP 和模型权限。密钥只读取服务端 `DASHSCOPE_API_KEY`，认证为 `Authorization: Bearer …`。不在界面、日志或前端存储中呈现密钥。[获取与配置 API Key](https://help.aliyun.com/zh/model-studio/get-api-key)

默认设置 `DASHSCOPE_REGION=cn-beijing`，填入服务器环境变量 `DASHSCOPE_WORKSPACE_ID` 后构造以下地址：

```text
OPENAI_BASE_URL=https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
ASR_WS_URL=wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference
DASHSCOPE_BASE_URL=https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1
```

三个完整地址均可显式覆盖；`DASHSCOPE_BASE_URL` 是 native `/api/v1`，**不是** OpenAI 兼容地址。新加坡使用 `ap-southeast-1`。文档仍提及旧 `dashscope.aliyuncs.com` 接入域名，但本项目默认构造新的业务空间地址。旧地址是否适用于具体账号须实测，不在配置缺失时盲猜。[实时指南](https://help.aliyun.com/zh/model-studio/real-time-speech-recognition-user-guide)、[异步识别地址](https://help.aliyun.com/zh/model-studio/fun-asr-recorded-speech-recognition-http-api)

## 持续 ASR 协议

采用 `inference` 的 `run-task / result-generated / finish-task` 协议；没有将另一个模型的 `realtime`、`input_audio_buffer.append` 事件混入此适配器。

1. 建立经过 TLS 校验的 WebSocket，发送 UUID `task_id`，`streaming=duplex`；payload 中 `task_group=audio`、`task=asr`、`function=recognition`、`model`、`parameters` 和 `input`。
2. 本应用 AudioWorklet 输出单声道 16 kHz、有符号 16 bit 小端 PCM。`format=pcm`、`sample_rate=16000`。先等 `task-started`，再持续发送短二进制帧。浏览器转换真实采样，不以 MIME 改名冒充转码。
3. 不传 `language_hints`，让韩语和英语自动识别。可选热词按官方 `parameters.vocabulary`；上下文只使用 `input.context` 的受限消息结构。
4. 停止采音后发 `finish-task`，payload 为 `{"input":{}}`，继续接收最终结果直到 `task-finished` 或有限超时。

上述字段、热词权重、上下文顺序/数量限制依据[客户端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-client-events)。本应用选择 16 kHz PCM；官方支持的其他格式不代表前端已实现对应编码。

读取 `payload.output.sentence`：`sentence_id` 是单个上游任务内编号；`begin_time/end_time` 是毫秒，`end_time` 在中间结果可为空；`sentence_end` 决定定稿。心跳结果跳过。后端为每次识别创建独立 `stream_id`，应用身份与上游句子编号组合，统一事件字段由本项目生成。依据[服务端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-server-events)。

单次 **105 分钟是本应用保护限制**，不是阿里云账户消费上限，也不是服务端承诺的费用封顶。

## 翻译与延迟

Qwen-MT 接收一条 user 消息，内容仅为当前待翻译文本。语言配置放在 `translation_options`，本应用使用 `source_lang=auto`、`target_lang=Chinese`；术语通过 `terms:[{source,target}]`，领域提示通过 `domains`，历史译例通过 `tm_list:[{source,target}]`。适配器支持这些官方字段；实时调用默认仅传入用户术语，不拼接未经支持的 system/context 消息。`qwen-mt-flash` 的 SSE 返回 `choices[].delta.content`。[翻译文档](https://help.aliyun.com/zh/model-studio/machine-translation)

**MT 流式输出是文本翻译结果逐 token 返回，不是音频持续同传接口。** 音频持续识别和文本翻译是两个独立任务。临时原文节流翻译、原文定稿后的最终翻译，由本应用版本逻辑衔接；过期临时翻译不能覆盖定稿。四类延迟指标是应用测量项，不把受控测试的耗时当成真实教室延迟。

## 文件转写

采用 `POST /services/audio/asr/transcription`，附 `X-DashScope-Async: enable`，`input.file_urls` 仅一个受控 HTTPS URL，参数包括 `diarization_enabled=true`、`channel_id=[0]`，不限定输入语言。提交获得 `output.task_id` 后持久化，再 GET `/tasks/{task_id}`；成功仍检查每个 `subtask_status`。仅从受信任的阿里云 HTTPS 结果域下载 `transcription_url`，解析 `transcripts[].sentences[]`。输入地址不接收用户任意 URL。[异步 HTTP API](https://help.aliyun.com/zh/model-studio/fun-asr-recorded-speech-recognition-http-api)

保留音频时每次连接保存可解码 WAV，并记录偏移和采集缺口。云端需要从公网读取文件，生产可用私有 OSS/S3 短期签名 URL，或本站 HTTPS 限时路由；`localhost` 地址不能供云端访问。说话人分离只用于单声道，官方建议控制在 2 小时以内；编号不是姓名。会后结果保存为新版本，原实时引用保留，不静默改写旧记录。[非实时识别](https://help.aliyun.com/zh/model-studio/non-realtime-speech-recognition-user-guide)

## 错误、重试与范围

适配器区分 `missing_api_key`、`missing_workspace`、`authentication_failed`、`model_permission`、`region_mismatch`、`model_unavailable`、`quota_exhausted`、`rate_limited`、`timeout`、`format_error`、`network_error`。云端有些错误同时可能由密钥/地域导致，应用说明核验项，不声称能凭同一个 401 精确识别后台原因。`MODEL_TIMEOUT_SECONDS` 控制网络等待。

Provider 不自动重复付费调用。后台任务最多按 `max_attempts` 有限重试；文件任务提交前记录提交意图，结果不确定时停止自动重提，已获得 task ID 的重试仅轮询该任务。后台进程崩溃导致不确定结果会明确失败，不承诺跨云“恰好一次”计费。

正式检索只接受稳定原文/原始文档，权限过滤发生在 SQL 召回阶段，重排前及答案持久化前再次校验。模型引用只能选服务端提供的证据 ID；版本、归属和原句逐项验证。LangChain `Document` 作为文档分块数据结构，不启用外部追踪。演示向量是标明模式的本地哈希向量，与真实 `text-embedding-v4` 隔离。生产 PostgreSQL 使用 pgvector 余弦查询；SQLite 仅供本地演示和测试，向量扫描最多 3000 个候选块。

PDF/PPTX 按真实页/幻灯片引用；DOCX 无稳定分页，使用段落/表格和字符位置，不虚构页码。扫描件、图片、复杂图表未接 OCR，界面返回解析警告或失败。文件限制为应用设定：40 MB、1000 页/幻灯片、5000 块；Office ZIP 解压大小和压缩比另有限制。

本地卷、S3 兼容和原生 OSS 存储分别实现统一接口。OSS 使用 `oss2` 原生签名方法，未将 S3 端点假设套用到 OSS；云存储的真实权限、签名 URL 下载和删除均待有凭据后验证。[OSS 签名下载文档](https://help.aliyun.com/en/oss/developer-reference/python-download-using-a-presigned-url)

## 上线后的短样本验收

由管理员在服务器安全配置 key/workspace/HTTPS 后：先用 10–20 秒韩英交替录音验证模型权限、单声道采样和结束事件；再测一条术语翻译、一个小文档 embedding/rerank/问答；最后用该短音频测试会后转写和说话人编号。记录每项 request/task ID、结果状态和四类延迟，不保存 key 或完整音频到日志。只有这些步骤实际成功后，才可把本记录对应行改为“真实接口测试通过”。课堂可用性仍需独立远场与长时实测。
