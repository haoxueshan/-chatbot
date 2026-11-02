# Minomeet 真实源码审查与复用记录

核验日期：2026-10-29，交付复核：2026-10-30。仓库：<https://github.com/shareefmx/minomeet>，采用 commit **2cfd93d6dc098fe0aa7c7f92cc8f4ce55fb0975b**。读取了许可证、`client/package.json`、构建配置、`src/App.tsx`、页面、MeetingContext及services源码；记录来自真实文件，未仅根据README猜测。

## 上游实况

MIT，Copyright (c) 2026 Muhammed Shareef M。上游client版本1.2.2；React18、TypeScript5、Vite6、Tailwind3、lucide-react；`npm run dev` 启动Vite，`npm run build` 执行 `tsc && vite build`。原前端的 `services/api.ts` 指向 `/api` 下的 meetings/templates 等原业务接口，由 MeetingContext 协调状态，并非可直接连到本项目会话模型。

真实页面文件：

- `client/src/components/screens/HomeScreen.tsx`
- `client/src/components/screens/RecordingScreen.tsx`
- `client/src/components/screens/NotesScreen.tsx`
- `client/src/components/screens/SettingsScreen.tsx`
- `client/src/components/layout/{Sidebar,Titlebar,ToastHost}.tsx`

原录音页依赖 `MeetingContext`、`services/speech.ts`、原转写/音频源状态；原笔记与设置依赖原会议/模型/存储契约。直接保留这些行为会绕过本项目稳定字幕版本、后端权限和服务器密钥边界，因此重写相应实现。

## 实际复用与替换

| 上游部分 | 本项目处理 |
| --- | --- |
| package、Vite、TS、PostCSS、Tailwind | 复用基础配置与依赖组合，改项目名、代理到FastAPI，新增测试工具和锁文件 |
| `src/index.css` | 保留在 `frontend/src/upstream.css`，继续使用Tailwind基础及可用设计变量；应用样式在 `style.css` 扩展 |
| 首页/侧栏/卡片/主题 | 保留可用的信息组织、侧栏导航和卡片视觉思路，重写为中文及私人会话数据 |
| 录音页 | 重写为AudioWorklet、PCM、本站WebSocket、稳定身份/版本字幕、真实音量与状态 |
| 笔记页 | 整合为SessionView历史详情、阶段重点、任务、资料和证据引用 |
| 设置页 | 保留阅读/主题/设置入口，替换为服务端偏好和只读模型配置状态；删除浏览器密钥输入思路 |
| 原MeetingContext与API/speech/export业务 | 不复用，使用本项目API客户端、useLive、事件reducer和后端导出 |
| 导入/删除/新建/通知交互 | 按新数据契约实现；删除确认、录音中禁止破坏、空态和失败态 |

没有同时运行上游后端，也没有在新项目中留下上游mock业务接口。所有业务请求统一到FastAPI。项目没有引入assistant-ui，避免为简单的证据问答增加另一套聊天状态。

许可证完整复制至 `vendor/MINOMEET_LICENSE` 与 `frontend/LICENSE.minomeet`；发布/分发时须保留。上游检出目录位于项目外，仅用于源码审查，不是运行依赖。
