# 第一、二阶段交付报告

日期：2026-11-02（Asia/Seoul）。范围仅为韩英语种/术语与远场采音，不修改模型、RAG核心、数据库结构、历史字幕或密钥。

## 分支与补丁

当前分支 `feature/asr-classroom-audio`，HEAD `71647b1f4acb439028dbc919e0702570f2db8a66`。开始时 `git status --short` 为空。`git log -3 --oneline` 实际只有两条：

```text
71647b1 上传补丁
b7a2843 1.0
```

实际读取补丁README、脚本与业务文件，确认补丁未应用。先执行 `classbridge/.venv/Scripts/python.exe classbridge_asr_patch/apply_classbridge_asr.py --repo .`，全部14个文件锚点通过；随后仅执行一次 `--apply`。没有重新建分支、强行覆盖冲突或重复应用补丁。之后对初始补丁作了下述修复。当前源码保存在工作区，未提交、未推送、未合并main。

## 修改文件与原因

以下路径相对于classbridge目录；每项均为实际源码。

| 文件 | 修改前 → 修改后、主要接口与原因 |
| --- | --- |
| backend/app/services/asr_options.py | source空串会丢掉旧term → source或term回退；保留NFC、去重、原词和长度限制 |
| backend/app/api/settings.py | 无声学/浏览器模式 → 增加asr_acoustic_profile far/near、audio_processing_mode standard/natural，枚举验证，沿用用户settings JSON与PATCH |
| backend/app/providers/aliyun.py | 依赖云端默认VAD → stream_asr新增vad_model可选参数，白名单校验后放入parameters；非法值在连接前拒绝 |
| backend/app/ws/live.py | 不报告声学模式 → 每个新任务读取账号设置、固定far/near映射，在ready报告实际采用配置；缺字段默认far |
| frontend/src/lib/types.ts | 增加上述偏好与ready事件声学类型 |
| frontend/src/lib/classroomPreset.ts（新增） | classroomPreset纯函数生成表单草稿，ko_en/4/far/standard；保留词表、背景及其他设置 |
| frontend/src/components/Settings.tsx | 增加课堂预设、声学模式和音频处理选择；预设不调用API，仍须保存；现有保存/读取通路携带新增字段 |
| frontend/src/lib/audio.ts | 固定通话处理、无法选设备 → captureConstraints精确deviceId，standard/natural；getSettings仅提取处理开关/采样率/声道，不向服务端发送设备ID；缺设备拒绝且释放资源；处理Safari interrupted状态 |
| frontend/public/audio/quality.js（新增） | InputQuality按约200ms统计所有输入回调的RMS/Peak；连续3窗口中每窗口至少1%采样达到0.98才提示可能削波；统计状态有界 |
| frontend/public/audio/capture-worklet.js | 原每8次回调只测最后一次 → 使用连续窗口监测；PCM输出逻辑与pcm.js重采样器未改 |
| frontend/src/lib/useLive.ts | 接收设备和处理选项，报告实际浏览器配置、窗口峰值与服务端声学模式；开始/停止重置质量状态 |
| frontend/src/components/SessionView.tsx | 增加真实设备列表/刷新/localStorage选择、设备变化监听及清理；错误可见、迟到枚举淘汰、采音中禁用切换；当前声学模式来自ready，不用偏好冒充当前生效值 |
| backend/tests/test_core.py | 增加用户near配置传递、ready与新字段422/持久化验证 |
| backend/tests/test_providers.py | auto/ko_en/ko × far/near六组真实请求结构替身断言，保持PCM和结束协议测试 |
| backend/tests/test_classroom_audio.py（新增） | 空source回退/NFC去重、旧用户默认、新设置恢复、非法VAD连接前拒绝 |
| frontend/tests/audio.test.ts | 默认standard及精确设备natural约束 |
| frontend/tests/audioReady.test.ts | getSettings实际值、未报告字段、设备ID不进入公开诊断、取消和晚到ready清理 |
| frontend/tests/settings.test.ts | 设置页预设与模式入口渲染 |
| frontend/tests/classroomAudio.test.ts（新增） | 预设草稿隔离、完整窗口峰值/连续高峰/恢复、设备失效无回退且关闭AudioContext |

`git diff --stat` 在写此报告前：15个已跟踪文件，188行增加、40行删除；另有4个新增源码/测试文件，Git默认diff --stat不统计未跟踪文件。新增本报告后共15个修改、5个新增。`git status --short`列出的文件即上表与本报告，没有.env、用户数据库、RAG代码或模型配置变更。`git diff --check`通过；Git提示audioReady.test.ts将由LF转CRLF，不是检查失败。

## ASR结构（示例，不含密钥）

```json
{
  "header": {"action":"run-task","task_id":"<本次UUID>","streaming":"duplex"},
  "payload": {
    "task_group":"audio","task":"asr","function":"recognition",
    "model":"qwen-audio-3.1-asr-flash-streaming",
    "parameters": {
      "format":"pcm","sample_rate":16000,"heartbeat":true,
      "language_hints":["ko","en"],
      "vocabulary":{"작업기억":4,"강화학습":4,"RAG":4},
      "vad_model":"far_field_meeting_16k"
    },
    "input":{"context":[{"role":"user","content":[{"type":"input_text","text":"인지심리학 수업. 작업기억."}]}]}
  }
}
```

auto省略language_hints；ko传["ko"]；near传near_meeting_16k。背景最多400字符，无背景时input为空对象。例词不自动写入账号。原文语言与中文翻译分离；800ms默认断句未改。远场本就是默认模式，显式参数不等于识别率提高。协议依据：[阿里云客户端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-client-events)、[热词与上下文](https://help.aliyun.com/zh/model-studio/improve-asr-accuracy)。

## 音频与诊断

仅枚举设备不会申请开麦。设备ID仅保存在本浏览器localStorage；指定设备使用exact约束，失效不会悄悄换设备，用户可手动选系统默认。无授权时名称可能为空；枚举失败显示提示，异步结果在卸载或新一轮枚举后失效。录音中禁止切换。

standard请求回声消除、降噪、自动增益开启；natural请求全部关闭以供对照。页面另外展示getSettings的实际开关，缺字段显示“未报告”；硬件DSP仍未知。保存模式后下一次录音生效，不改已有字幕。

本地质量监测不额外上传音频，不作增益、门限截断、DSP降噪或识别置信度。连续输入峰值提示与既有“未收到音频/电平低/服务端转发积压/长时间无文字”诊断分开；浏览器发送积压仍由bufferedAmount上限停止并说明原因。低音量不等于无人讲话。

链路保持AudioWorklet连续抗混叠重采样 → 16kHz Mono PCM16LE → 320采样/640字节/20ms帧 → WebSocket → FastAPI → 阿里云。准备握手、finish-task、旧版本淘汰及缺口逻辑保留。

## 本次实际测试

在classbridge目录按要求执行：

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m pytest -q
Pop-Location
Push-Location frontend
npm test
npm run build
Pop-Location
git diff --check
git diff --stat
git status
git log -3 --oneline
```

最终后端 **103 passed / 0 failed，18.51秒**；前端 **33 passed / 0 failed，0.78秒**；`tsc && vite build`通过，Vite构建3.70秒。包含既有翻译、RAG、总结、原文版本、恢复、权限、PCM及停止回归。前端以纯函数、设备替身与组件静态渲染验证，未冒充浏览器点击或实体设备验收。

本轮从新要求生效后新增付费API调用为0。此前较大范围审查中的真实接口检查属于此前工作，不是本阶段准确率验证。未修改密钥、数据库或历史数据。之前的隔离验收服务已停止，没有停止用户PyCharm后端。

## 启用与实测

停止当前录音，重启PyCharm的backend/main.py，刷新前端。设置页应用课堂预设、填入已确认韩语原词，再保存。真实会话选择麦克风并开始，核对ready的声学模式与浏览器实际开关。

真实韩语准确率、课堂远场、实体iPad Safari、不同模式A/B及长时稳定性均**未在本阶段实测**。设备授权前后标签、断开/重新插入后ID变化，仍需Windows Chrome/Edge和Safari实机矩阵；自动测试不能替代它们。

人工验收使用同一音频、固定设备距离/增益、人工正确文本，每次只变一个参数：纯韩语比较auto/ko_en/ko；混合句检查英文术语；姓名只填人工确认热词；专业术语比较权重2/4；远距离和背景噪声比较standard/natural；外接近场麦比较far/near；最后连续录音观察内存/队列和漏句。建议先20–30秒再长录音，测试调用由用户执行并控制预算。

记录每组Korean CER（NFC后韩文字符编辑距离/参考字符数，明确是否忽略空白标点）、English WER、术语正确数/总数、语种误判数、漏句数、平均/P95原文首字及定稿延迟、浏览器与服务器最大队列积压。短样本不推导长课稳定性，没有人工标注不得计算或宣称准确率提升。
