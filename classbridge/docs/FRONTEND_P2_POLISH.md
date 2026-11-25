# P2 前端工作台体验优化

日期：2026-11-25。源码基线：`cb0161cc25fec9704ecb064b1283493ea3d3f80b`。
分支：`style/p2-workspace-polish`。本次范围是现有页面、导航、主题与操作呈现；没有修改后端、数据结构、ASR / MT 调度、字幕事件合并或音频生命周期，也没有新增 npm 依赖。

## 已完成

- 继续使用现有 shadcn 风格 HSL 变量与 `--cb-*` 别名，补齐间距、字号、圆角、悬浮层阴影、Focus / Hover / Active / Disabled 等基础变量。页面以中性灰为主，保留紫色品牌强调；将错误、警告、成功、字幕引用高亮和音量状态色统一到已有语义色。没有第二套主题切换逻辑。
- 侧栏采用可折叠的文件夹导航分组，显示当前分类与会话数；长名称截断并保留完整提示。复用现有分类回调、管理 Dialog 和移动抽屉。仍是现有扁平文件夹，不增加嵌套文件夹、共享或知识继承。
- 会话列表将选择框、内容和操作入口排列在同一行。“移动到”放入原生 disclosure；Tab / Enter 可操作，Escape 关闭并恢复触发器焦点，移出焦点关闭。没有添加另一套菜单依赖或监听每次窗口 resize。
- 批量移动在选中会话后展开，保留最多 100 条、失败不清空、成功清空、切换筛选清空的原有规则；取消选择回到选择框。会话标题和文件夹上下文继续使用真实业务数据。
- 设置页增加现有分组的定位入口，不切换 / 卸载表单、不自动保存。模型管理明确区分加载、空数据、错误、本地配置有效和停用；本地有效不宣称真实模型已连通。
- 工作台手机快捷入口更紧凑，设置、资料库及登录页统一边框与控件风格；移除登录装饰圆环和样例卡片渐变。字幕页仅替换语义样式，不缩小用户字幕字号、不改变跟随滚动算法。

## 参考来源与许可证核对

本次阅读了以下源码 / 文档，采用布局和交互思想，自行在现有组件上实现，没有复制来源代码、品牌或资源。保留已有 `vendor/MINOMEET_LICENSE`、`vendor/SHADCN_ADMIN_LICENSE` 与前端归属声明。

| 项目及固定版本 | 阅读文件 | 许可与采用范围 |
| --- | --- | --- |
| Shadcn Admin：`e16c87f213a5ba5e45964e9b67c792105ec74d26` | [app-sidebar.tsx](https://github.com/satnaing/shadcn-admin/blob/e16c87f213a5ba5e45964e9b67c792105ec74d26/src/components/layout/app-sidebar.tsx)、[settings/index.tsx](https://github.com/satnaing/shadcn-admin/blob/e16c87f213a5ba5e45964e9b67c792105ec74d26/src/features/settings/index.tsx) | [MIT，Sat Naing](https://github.com/satnaing/shadcn-admin/blob/e16c87f213a5ba5e45964e9b67c792105ec74d26/LICENSE)。参考导航分组、内容滚动与设置分类，不引入其 Router / Provider。 |
| shadcn/ui：`055aa6b7837b1808456a24beb4c97a677864aa82` | [sidebar-11/components/app-sidebar.tsx](https://github.com/shadcn-ui/ui/blob/055aa6b7837b1808456a24beb4c97a677864aa82/apps/v4/registry/new-york-v4/blocks/sidebar-11/components/app-sidebar.tsx)、[Sidebar Blocks](https://ui.shadcn.com/blocks/sidebar) | [MIT，shadcn](https://github.com/shadcn-ui/ui/blob/055aa6b7837b1808456a24beb4c97a677864aa82/LICENSE.md)。参考折叠层级、选中项和数量标识；没有移植递归文件树及新增 Collapsible 依赖。 |
| Open WebUI：`0666e59d26a4d056e0bacee41742486badd71cf8` | [会话组织文档](https://docs.openwebui.com/features/chat-conversations/chat-features/conversation-organization/)、[LICENSE](https://github.com/open-webui/open-webui/blob/0666e59d26a4d056e0bacee41742486badd71cf8/LICENSE) | 当前为自定义 Open WebUI License，包含品牌相关条件；仅参考文件夹上下文和会话操作收纳，没有复制源码或素材。在线文档按本次日期查阅，不声称它具有上述仓库的同一提交版本。 |

## 实测对比

`tests/browser/workspace.mjs` 在同一浏览器、相同 Mock 会话及字号下测量第一条会话的完整行高。修改前包含独立选择行和始终展开的移动控件，修改后包含选择框、会话内容及折叠操作入口。

| 视口 | 修改前会话行高 | 修改后会话行高 | 修改后横向溢出 |
| --- | ---: | ---: | --- |
| 320 × 568 | 203.8 px | 129.8 px | 无 |
| 390 × 844 | 203.8 px | 105.8 px | 无 |
| 768 × 1024 | 171.0 px | 71.0 px | 无 |
| 1440 × 900 | 150.0 px | 71.0 px | 无 |

本次重点是工作台密度和主题统一，未改变字幕的高度分配。会话页面实测：390 × 844 字幕列表 `clientHeight=571px`，可完整看到 12 行双语文字；1024 × 768 为 482px；1440 × 900 为 659px。录音栏均可见。原始测量见 [session-layout.json](screenshots/p2-workspace/session-layout.json)，不将其宣传为本次字幕高度的新增提升。

## 实际验证

| 验证 | 结果 |
| --- | --- |
| `npm test` | 113 通过，0 失败，0 跳过。包含字幕快照、14 种目标语言、历史恢复、录音生命周期，以及新增导航 / 操作焦点 / 设置草稿测试。 |
| `npm run typecheck` | 通过。 |
| `npm run build` | 通过，Vite 生产构建成功。 |
| `node tests/browser/workspace.mjs after` | Chromium：25 项布局检查通过、页面异常 0；包含 7 种视口下的工作台 / 设置 / 资料库、文件夹 Dialog、手机抽屉及登录。另验证分类、批量取消和操作入口键盘交互。 |
| `node tests/browser/responsive.mjs after` | 11 种视口的字幕测量和 127 项页面 / Dialog / 问答等布局检查通过；长文本、RTL、横屏错误提示与录音栏均可访问。 |
| 录音生命周期 | 同一 Mock WebSocket 跨旋转、主题、页签、导航抽屉、侧栏切换保持不变；一次 start，没有额外 stop。单元测试也验证真实模式的 Mock AudioCapture。 |
| 真实模型 / 用户数据 | 业务 HTTP 与录音 WebSocket 均使用隔离 Mock；未调用真实 ASR / MT，未读取或修改用户数据库。 |

前端测试和构建在 `classbridge/frontend/` 执行。浏览器测试使用现有运行时的 `playwright-core`，未安装额外依赖。复现方式：

```powershell
# 终端 1，classbridge/frontend/
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5177 --strictPort

# 终端 2，classbridge/frontend/；填写本机已有包路径
$env:PLAYWRIGHT_MODULE = '<已有 playwright-core 包目录>'
$env:AUDIT_URL = 'http://127.0.0.1:5177'
node tests/browser/workspace.mjs after
$env:AUDIT_OUTPUT = '../.local/p2-responsive'
node tests/browser/responsive.mjs after
```

`workspace.mjs before` 只有在原基线源码下执行才是可比基线，不应在修改后重新生成并称作修改前数据。`AUDIT_OUTPUT` 允许独立存放本轮响应式报告，不覆盖既往验收文件。

## 截图与测量文件

全部来自实际运行的 Chromium 和明确标记的 Mock 数据，位于 [screenshots/p2-workspace/](screenshots/p2-workspace/)：

- [桌面工作台，修改前](screenshots/p2-workspace/before-1440-home-light.png) / [修改后](screenshots/p2-workspace/after-1440-home-light.png)。
- [手机工作台](screenshots/p2-workspace/after-390-home-light.png)、[手机深色抽屉](screenshots/p2-workspace/after-mobile-navigation-dark.png)。
- [深色设置页](screenshots/p2-workspace/after-desktop-settings-dark.png)、[文件夹管理](screenshots/p2-workspace/after-folder-dialog.png)。
- [桌面登录](screenshots/p2-workspace/after-1440-login.png)、[手机登录](screenshots/p2-workspace/after-390-login.png)。
- [手机字幕浅色](screenshots/p2-workspace/after-mobile-390-session-light.png) / [深色](screenshots/p2-workspace/after-mobile-390-session-dark.png)、[平板字幕](screenshots/p2-workspace/after-ipad-landscape-session.png)、[桌面字幕](screenshots/p2-workspace/after-desktop-session.png)。
- [工作台修改前数据](screenshots/p2-workspace/before.json)、[修改后数据](screenshots/p2-workspace/after.json)、[会话交互验收](screenshots/p2-workspace/session-checks.json)。

## 边界与更新

没有在实体 iPhone / iPad Safari、Android 软键盘或真实课堂中验收；缩小视口的问答输入检查不能替代真实软键盘测试。侧栏仅实现现有扁平分类的可折叠呈现，不引入嵌套、拖拽或共享功能。

本次仅前端改动，无需数据库迁移或重启 API / Worker。开发模式刷新 Vite 页面；静态部署需 `npm run build` 后发布新的 `dist/`，使用容器时重建并更新前端服务。回退本次前端提交即可，不涉及用户数据回滚。
