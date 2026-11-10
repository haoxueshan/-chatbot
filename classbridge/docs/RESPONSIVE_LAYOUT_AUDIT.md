# 多设备响应式验收 · 2026-11-10

基线：`584d4a7de843a7267a88b6560345a95d3cbe10be`。分支：`fix/responsive-subtitle-layout`。

只调整前端呈现、复用 Dialog 并增加回归。未改后端、事件/翻译调度、语言设置、音频生命周期或依赖。

## 布局调整

- 会话标题、模式与目标语言常驻；日期、说明、资料/删除/导出/专注/侧栏操作、麦克风选项、会后校正与延迟数据集中到可键盘访问的“会话工具与详情”。错误与实时传输状态继续在正文外可见。
- 手机录音控制保持紧凑；字幕段落上下 11px，平板 15px，桌面 18px。用户译文字号未缩小。字幕区按剩余动态视口高度伸缩，不再用最小高度把正文挤出屏幕。
- 根据会话工作区实际宽度决定页签/双栏（1050px），而非设备名称。宽屏双栏约 75%/25%，正文行宽上限 900px。所有主面板继续使用原组件实例和 CSS 显隐。
- 设置页手机外间距 12px、卡片 16px；首页减少空白。会话资料和文档预览复用现有 Radix Dialog，解决布局容器内弹层的覆盖及焦点问题；文档正文独立滚动。

## 实测

已有本机 Playwright Core + Chromium 148.0.7778.96 执行，11 个视口。隔离端口 `127.0.0.1:5175`，全部业务 HTTP / WebSocket 经测试脚本 Mock；未调用真实模型、未读写生产数据。直接打开该开发端口**不包含**测试脚本的 Mock 拦截，不作为独立演示服务。

同一组 30 条韩/英原文与简体中文译文，译文字号 24px。滚动到相同历史起点，用真实 DOM Range 的文字行框计数，不含时间戳/状态行。`before.json`、`after.json` 记录 app/header/panel/list/capture 的实际尺寸；下表为 list 与视口/录音栏交集高度（四舍五入），并列出 clientHeight。基线在小屏/横屏存在容器虽有高度但被外围布局挤出可视区的情况。

| 视口 | 前→后 clientHeight(px) | 前→后实际可视高度(px) | 完整正文行数 |
|---|---:|---:|---:|
| 320×568 | 209→295 | 1→295 | 0→6 |
| 360×800 | 209→527 | 209→527 | 4→10 |
| 390×844 | 233→571 | 233→571 | 4→12 |
| 430×932 | 344→659 | 344→659 | 5→13 |
| 844×390 | 155→135 | 0→135 | 0→2 |
| 768×1024 | 513→738 | 513→738 | 6→10 |
| 1024×768 | 287→482 | 287→482 | 4→6 |
| 1180×820 | 355→534 | 355→534 | 4→7 |
| 1280×800 | 335→514 | 335→514 | 4→7 |
| 1440×900 | 435→659 | 435→659 | 4→8 |
| 1920×1080 | 615→839 | 615→839 | 6→11 |

390px 手机常规模拟会话字幕可视高度占视口约 67.6%。所有上述会话无横向溢出、录音栏完全可见。重要提示、开启详情、软键盘或系统安全区域会减少剩余空间，此比例不代表所有状态。

## 回归结果与复现

- `npm test`：83/83；保留翻译稳定性、多语言、乱序/恢复、历史跟随等回归。
- `npm run typecheck`、`npm run build`：通过。
- 浏览器：127 项尺寸/可操作性检查，覆盖 11 视口的首页、设置、资料库、会话、问答、会话资料与嵌套预览、登录；另验收新建 Dialog、焦点恢复、输入法组合事件、长词、RTL、错误提示、历史滚动与回到最新。
- 生命周期：Mock AudioCapture 的真实模式用例中，仅启动 1 次，旋转/页签/侧栏/主题/详情切换期间停止 0 次，手动停止后恰好 1 次。真实 Chromium 中同一个 Mock WebSocket 在上述呈现操作与导航抽屉开关间保持不变，无额外 start/stop。现有自动跟随的 ResizeObserver、RAF、followingRef 逻辑未改。

在 `frontend/` 中，复用已安装的 Playwright/Core：

```powershell
npm run dev -- --host 127.0.0.1 --port 5175
# 另一个终端；若本项目没有此包，将环境变量设为已有 playwright-core 的绝对路径
$env:PLAYWRIGHT_MODULE = '<已有 playwright-core 包目录>'
node tests/browser/responsive.mjs after
```

无需安装新依赖。基线文件只能在原基线代码上使用 `before` 模式生成，勿用修改后代码覆盖它们。默认后验截图覆盖同名后验文件。

## 截图索引

目录：`docs/screenshots/responsive/`。均为实际运行前端的 Chromium 截图，模拟字幕带标记。

- [手机浅色](screenshots/responsive/mobile-390-session-light.png)、[手机深色](screenshots/responsive/mobile-390-session-dark.png)、[320px 手机](screenshots/responsive/mobile-320-session.png)
- [手机横屏](screenshots/responsive/mobile-landscape-session.png)、[iPad 竖屏尺寸](screenshots/responsive/ipad-portrait-session.png)、[iPad 横屏尺寸](screenshots/responsive/ipad-landscape-session.png)
- [笔记本](screenshots/responsive/laptop-session.png)、[桌面](screenshots/responsive/desktop-session.png)、[宽屏桌面](screenshots/responsive/desktop-wide-session.png)
- [设置](screenshots/responsive/mobile-settings.png)、[首页](screenshots/responsive/mobile-home.png)、[资料库](screenshots/responsive/mobile-library.png)、[新建弹窗](screenshots/responsive/mobile-create-dialog.png)
- [问答输入：缩小可用视口](screenshots/responsive/mobile-chat-compact-viewport.png)。**不是实体软键盘截图**，因此没有生成容易误导的 `mobile-chat-keyboard.png`。
- `before-*.png` 为修改前实际截图；[before.json](screenshots/responsive/before.json)、[after.json](screenshots/responsive/after.json)、[checks.json](screenshots/responsive/checks.json) 为原始测量和检查结果。

## 设计参考与限制

只借鉴布局思路，未复制外部代码或新增依赖：既有 [Shadcn Admin 侧栏](https://github.com/satnaing/shadcn-admin/blob/main/src/components/layout/app-sidebar.tsx) 的主次导航组织；[WhisperLiveKit HTML](https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/whisperlivekit/web/live_transcription.html)、[CSS](https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/whisperlivekit/web/live_transcription.css)、[JS](https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/whisperlivekit/web/live_transcription.js) 的字幕/控制区组织；[Jitsi Toolbox](https://github.com/jitsi/jitsi-meet/blob/master/react/features/toolbox/components/web/Toolbox.tsx) 的主操作与次要工具分层；[Sokuji](https://github.com/kizuna-ai-lab/sokuji) 的多语言字幕视觉组织（未复制 AGPL 代码）。既有 Minomeet/Shadcn 归属与许可证保持原样。

未验证实体 iPhone/iPad Safari、Android 输入法软键盘和安全区域变化；Chromium 缩小视口不能替代它们。未执行真实音频或 60 分钟课堂稳定性测试。本次布局使用 CSS 容器查询，未测试缺少该能力的旧浏览器。
