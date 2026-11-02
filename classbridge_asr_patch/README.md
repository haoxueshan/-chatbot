# ClassBridge 第一、二阶段优化补丁

目标仓库：`https://github.com/haoxueshan/-chatbot`（`classbridge/` 应用目录）

**当前状态**：这是可在本地仓库应用的源码修改脚本；GitHub 连接器拒绝写入新分支（HTTP 403），因此尚未提交至远端，也没有在你的 iPad／教室使用真实音频验证准确率。

## 变更范围

1. **韩英课堂预设**：设置页一键选择 `ko_en`、热词权重 4、远场声学配置及标准浏览器采音处理；需要用户再点击“保存偏好”才生效。保留其他场景的 `auto` 默认，不强行限定所有会话为韩英。
2. **修复旧术语项兼容**：术语记录中 `source` 为空但 `term` 有值时，正确回退到 `term`，避免热词被忽略。术语不会自动从不可靠的转录错误中生成；必须录入正确人名与专业原词。
3. **ASR 拾音参数**：增加远场 `far_field_meeting_16k`／近场 `near_meeting_16k` 选择，使用阿里云官方 WebSocket 参数 `vad_model`；默认远场，保留原 800ms 断句与 16kHz PCM16 / 20ms 帧。
4. **麦克风选择**：真实会话可选择浏览器提供的音频输入设备、刷新设备列表；选中的 `deviceId` 只存在该浏览器的 localStorage，不上传服务器。设备断开后会要求重新选择，不悄悄换成错误设备。
5. **浏览器采音 A/B**：`standard` 保留当前回声消除、降噪、自动增益全部开启；`natural` 关闭浏览器音频处理以用于对比测试（不代表降噪增强，硬件 DSP 仍可能生效）。
6. **质量提示**：AudioWorklet 上报 RMS 与当前输入峰值，峰值接近满幅时在会话页显示提示；这不等同于声学识别置信度，也不会使用音量门限裁掉轻声韩语词尾。
7. **回归测试**：扩展后端 ASR 请求参数、设置校验、WebSocket 模式事件测试，以及前端采音参数和设置渲染测试。

## 应用步骤（Windows / PyCharm）

先在本地 `git` 工作副本中创建新分支并确保代码已提交或备份。应用脚本会验证所有锚点，发现源码版本不符则不写入任何文件。

```powershell
cd 你的仓库目录
# 包含 classbridge 子目录的 -chatbot 根目录

git switch -c feature/asr-classroom-audio
python C:\下载目录\apply_classbridge_asr.py --repo .
python C:\下载目录\apply_classbridge_asr.py --repo . --apply

cd classbridge
Push-Location backend
python -m pytest -q
Pop-Location
Push-Location frontend
npm test
npm run build
Pop-Location

git diff --check
git diff --stat
```

不要在有未提交本地修改、正在录音或未备份的项目上直接应用。脚本不碰数据库、`.env` 或历史语音；更新后停止录音、重启 `backend/main.py` 并刷新浏览器才能使后端配置生效。

## 在应用内验证

1. 设置页选择“应用韩英远场课堂预设”，填写来自本课材料的**经确认**原词／人名（例如每次先 3–5 个），再保存。
2. 在真实会话顶部选择实际话筒并刷新设备。教授距离较远先选择远场声学配置；使用领夹麦或近距离话筒时单独测试近场。
3. 分别使用标准采音与原声对照模式，录制**同一条件**的短样本；对照有人工正确文本的韩语 CER、英语 WER、专业词准确率、漏句与字幕延迟。录音需要说话者许可。
4. 输入峰值接近 1.0 且声音失真时检查设备增益；声音很低先检查麦克风距离和输入设备。只有无声/电平读数不能推导语音质量。
5. 优先做 20–30 秒短样本，再评估真实教室远场长时间录音；不要根据模拟模式或静音 API 测试宣称识别准确率提高。

## 不包含的工作

本补丁没有擅自提高 ASR VAD 灵敏度、启动实时降噪神经网络、接管操作系统音频驱动、自动猜测教授人名、改变默认断句阈值或开启云端模型付费测试。这些更改需要在有标注的真实语音对照下验证，否则可能导致更严重漏句。

官方参数参考：

- [Qwen-Audio-ASR-Streaming 客户端事件：vad_model / vocabulary / language_hints](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-client-events)
- [阿里云提升识别准确率：热词与上下文](https://help.aliyun.com/zh/model-studio/improve-asr-accuracy)
