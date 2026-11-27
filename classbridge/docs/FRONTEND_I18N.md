# 前端国际化（P3.3）

## 范围与语言

支持简体中文（默认 `zh-CN`）、English（`en`）、한국어（`ko`）。
登录页、工作台顶部和偏好设置的外观区域提供原生语言选择框，支持键盘和读屏。
语言切换通过 React Context 即时更新文字、`html.lang` 和页面标题，不刷新页面，不以语言作为组件 key。

`ui_language`、`asr_language_mode`、`target_language` 相互独立。界面切换不修改识别配置、字幕目标语言、历史原文、译文、摘要、问题、回答或知识库内容，也不会触发重新翻译。

## 实现结构

- `frontend/src/i18n/index.ts`：语言类型、语言选项、本地存储、资源汇总、类型化翻译函数和 Intl 格式化工具。
- `frontend/src/i18n/I18nProvider.tsx`：Context、账号语言加载、即时切换及串行持久化。
- `frontend/src/i18n/*.ts`：按首页、设置、文件夹、资料库、问答、模型、会话、诊断等功能拆分的本地静态三语资源。
- `frontend/src/i18n/errors.ts`：结构化错误码到本地资源的映射。
- `frontend/src/components/LanguageSwitcher.tsx`：复用的原生 select 入口。

中文键集合是类型基准，英文及韩文必须提供相同键。测试比较所有键、非空值及插值占位符；支持 `{count}` 等文本插值和 `_one` 单数形式。所有内容通过 React 文本节点输出，无 HTML 插值。未知键显示通用错误，不暴露内部键；缺失翻译回退中文。

新增语言时扩展语言联合类型、语言选项、资源汇总及后端 Literal；为所有模块提供同键资源，更新测试矩阵。不得将动态业务数据当成翻译键。

## 偏好保存与兼容

登录前仅使用 `classbridge.ui_language` localStorage；存储不可用时依然可以在内存切换。登录后读取当前账号 `/api/settings`，有效服务端值优先。

后端 `Preferences.ui_language` 默认 `zh-CN`，复用 `User.settings` JSON，无新字段、表或迁移。旧账号缺少字段及非法历史值读取时回退中文；新的非法提交返回验证错误。由于 GET 为旧账号补默认值，旧账号登录后使用中文，而不是继承登录前的本地选择。

切换仅 PATCH `{"ui_language":"en"}`，不提交完整偏好快照。串行请求防止较早写入晚于最新选择完成；账号与修订号保护避免过期响应覆盖展示。界面即刻切换，保存失败明确标记“本地已应用但账号保存失败”，可再次选择重试。设置页中的其他未保存编辑不因 UI 语言切换重置。

## 错误、历史数据与格式

连接状态使用稳定机器标识，在渲染层翻译。已知结构化错误码使用本地说明，未知错误显示通用提示，不直接暴露供应商完整响应或凭据。历史事件不回写数据库，有结构化分类时显示本地标题，原始历史信息作为内容保留。

日期、数字、相对时间工具分别采用 `Intl.DateTimeFormat`、`Intl.NumberFormat`、`Intl.RelativeTimeFormat`，使用浏览器当前时区；录音时间轴和技术指标单位保持原义。

保留 P2 字体栈（含 Apple SD Gothic Neo、Malgun Gothic、Noto Sans KR），不下载外部字体。长英文按钮允许换行，不通过缩小字号规避溢出。

## 生命周期安全

语言仅参与展示。Provider、App、SessionView 不以语言为 key；语言及翻译函数不加入音频采集或连接生命周期依赖。不修改 AudioCapture、AudioWorklet、PCM 传输、ASR 聚合、Worker、增量翻译或 `ASR_RECOVERY_ENABLED` 安全门禁。

`uiInteraction.test.ts` 中使用 Mock 音频和 WebSocket 检查录音期间三语切换，保护实例与启动次数、连接、会话及目标语言。此测试不能证明真实供应商 task_id、真实设备 PCM 连续性或长时课堂效果；没有调用付费模型。

## 验证与构建

在 `backend` 下执行 `python -m pytest -q`，分别设置 `INCREMENTAL_TRANSLATION_ENABLED=false` / `true`。

在 `frontend` 下执行：

```sh
npm test
npm run typecheck
npm run build
```

浏览器脚本：`frontend/tests/browser/responsive.mjs`。设置 `AUDIT_I18N=1` 增加三语、明暗主题及 320、375、390、768、1024、1280、1440、1920 宽度矩阵；`PLAYWRIGHT_MODULE` 可指向已有 playwright-core，`AUDIT_OUTPUT` 指定截图目录。实际 Chromium 使用 Mock HTTP/WebSocket，不是实机 iPad/Safari 测试。实际结果见 [TEST_RESULTS.md](TEST_RESULTS.md)。

## 保留的语言边界与限制

- 用户会话标题、文件夹名、文件名、术语、字幕、历史事件原始信息、模型回答不翻译。
- 登录页双语示例和设置页术语输入示例保留原文。
- 自动生成会话标题仍沿用既有中文内容及日期策略，保存后不随 UI 语言变化。
- PDF、Markdown、TXT 导出正文及固定中文报告标题保持原有独立语言边界；只翻译前端导出入口，不重构导出服务。
- 模型 ID、技术诊断标识和产品名称保留。
- 三语资源一致性不等于人工母语审校；真实设备字体呈现、读屏和供应商录音需要独立验收。

## 部署与回退

后端设置 schema 更新需要重启 API；前端需要重新构建并发布静态文件。本轮不自动重启现有服务，不修改真实数据库。

普通回退直接选择简体中文。版本回退需先备份工作区，再恢复发布前的前后端构建；不要对有未提交修改的目录执行破坏性 reset。JSON 中新增字段可由旧版本忽略，无需数据库降级。不要更改识别恢复门禁或音频策略来处理界面问题。