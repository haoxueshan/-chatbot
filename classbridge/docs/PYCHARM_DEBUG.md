# PyCharm 本地运行与调试

2026-11-01检查：现有Python3.13.5虚拟环境和Node.js24.16.0可用；pip依赖检查通过；后端46项测试通过，前端10项测试通过，TypeScript/Vite生产构建通过；本地数据库迁移0002。API健康检查和前端HTTP均通过。没有调用付费API，没有进行PyCharm GUI断点实测或真实课堂验收。

## 打开正确目录和解释器

在PyCharm打开 `D:\Program Files (x86)\GitDate\同声传译chatbot\classbridge`。不要只打开backend，也不要把整个父目录当成本配置的PROJECT_DIR。

设置 → Python → 解释器 → 添加本地解释器 → 现有环境：

```text
D:\Program Files (x86)\GitDate\同声传译chatbot\classbridge\.venv\Scripts\python.exe
```

不需要创建新的venv或重新安装依赖。Node.js/npm使用现有系统安装。若没有JavaScript/npm运行配置选项，前端在IDE终端启动即可。

## 先停止占用端口的旧实例

当前检查时8000和5173均有服务。点击IDE运行前，在PowerShell终端、项目根目录执行：

```powershell
.\deploy\stop-local.ps1
```

此脚本仅停止它之前记录且PID/启动时间吻合的进程。若占用的是PyCharm手动启动的服务，使用对应Run/Debug窗口的红色停止按钮；终端启动的服务用Ctrl+C。不要同时运行一键启动脚本和IDE后端。

## 后端运行配置

推荐直接运行：打开 `backend/main.py`，右键Run或Debug。文件包含 `if __name__ == "__main__": main()`，会自动固定backend工作目录，再启动单进程Uvicorn。无需填写模块名或参数。仍使用项目现有.venv；默认8000端口，可在参数中设置 `--port 8001`（前端代理默认8000，改端口后需相应修改）。当前入口默认host为0.0.0.0，可用 `--host 127.0.0.1` 限制为本机监听。

`.run/` 当前提供数据库升级、后端测试共享配置；配置本身不含密钥。API直接右键运行main.py即可；也可按下表手动建立命名运行配置。

运行 → 编辑配置 → ＋ → Python：

| 项目 | API | 迁移 | 测试 |
| --- | --- | --- | --- |
| 名称 | ClassBridge API (Debug) | ClassBridge Database Upgrade | ClassBridge Backend Tests |
| 目标类型 | 脚本路径 | 模块名称 | 模块名称 |
| 脚本 / 模块 | `$PROJECT_DIR$/backend/main.py` | alembic | pytest |
| 参数 | 留空 | `upgrade head` | `tests -q` |
| 工作目录 | `$PROJECT_DIR$/backend` | `$PROJECT_DIR$/backend` | `$PROJECT_DIR$/backend` |
| 解释器 | 项目的现有.venv | 同左 | 同左 |

先运行迁移，再启动API。已有数据库不用重新创建管理员。点击绿色运行或Debug按钮。不要直接右键运行 `app/main.py`，它没有启动ASGI服务器的入口。

断点调试使用单进程、无自动重载的配置，代码修改后停止并重新Debug。若只需要自动重载，可另建uvicorn模块配置，参数为 `app.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log`，工作目录backend；不要同时运行两个API实例。脚本入口不接受 `--reload`。

本地采用 `TASK_MODE=local`，outbox任务执行器与API处于同一进程，所以services/workers的断点也能在API调试器下命中。生产Celery在独立进程，不能期待仅调试API就能命中生产worker。

## 前端运行

当前Vite配置使用80端口，因此以下 `npm run dev` 的网站入口是 **http://localhost/**（或http://127.0.0.1/）。API仍为8000；代理目标使用127.0.0.1:8000。`0.0.0.0` 只用于监听，不作为代理目标。根目录.env已允许这两个不带端口的本地Origin，修改.env后必须重启API。

一键启动脚本 `deploy/start-local.ps1` 会显式覆盖Vite端口为5173；该脚本启动时使用http://127.0.0.1:5173。两种方式选一种即可。若登录提示“请求来源不受信任”，先核对浏览器地址的协议、主机、端口是否与ALLOWED_ORIGINS完全对应；不要关闭Origin校验或使用通配符。

在PyCharm单独终端执行：

```powershell
Set-Location -LiteralPath 'D:\Program Files (x86)\GitDate\同声传译chatbot\classbridge\frontend'
npm run dev
```

保持终端运行。Vite开发服务器支持前端热更新。后端和前端需要同时运行，Vite将/api和/ws转发到8000。

- 网站（本节npm启动）：<http://localhost/>
- Swagger：<http://127.0.0.1:8000/api/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>
- 登录凭据：根目录 `.local/credentials.txt`，不要提交或截图分享。

建议全程使用127.0.0.1，避免localhost与127.0.0.1来回切换导致Cookie不一致。Swagger写请求同样需要先通过 `/api/auth/login` 登录。已补齐开发模板和当前development环境中8000端口的合法Origin，重启API后生效。

## 密钥与配置

程序自动读取 `classbridge/.env`，不是 `.env.example`。只检查配置是否存在，不打印实际值。最新复检key与workspace均已填写，尚未进行真实云调用验证；修改后需重启API生效。

```dotenv
ENVIRONMENT=development
TASK_MODE=local
DATABASE_URL=sqlite:///./data/classbridge.db
DATA_DIR=./data
COOKIE_SECURE=false
DASHSCOPE_API_KEY=在本地文件中填写密钥
DASHSCOPE_WORKSPACE_ID=实际北京业务空间ID
DASHSCOPE_REGION=cn-beijing
```

保留现有.env中的其他设置，不要整文件替换成此片段。密钥、业务空间、模型权限和地域必须匹配。配置修改后重启API；Pydantic设置在进程启动时读取。PyCharm运行配置中的同名环境变量优先于.env，调试配置里有旧值时需移除。

模拟模式不需要key/workspace，不请求麦克风也不调用付费接口。真实模式需新建真实会话；原来的模拟会话不会因填了key自动变成真实。先用10–20秒短录音验收。网页设置里的“已配置”不代表云端实际调用通过。

## 从哪里下断点

| 想排查的问题 | 位置 |
| --- | --- |
| 登录、Cookie、401 | `backend/app/api/auth.py` 的login/current_user |
| 创建、删除、恢复会话 | `backend/app/api/sessions.py` |
| WebSocket连接/开始/停止/音频 | `backend/app/ws/live.py` 的websocket_session、LiveCapture.start/audio/stop/consume |
| 字幕保存、版本和outbox | `backend/app/services/events.py` 的save_final/save_translation/enqueue |
| 翻译或ASR云接口错误 | `backend/app/providers/aliyun.py` 的stream_asr/translate_stream/classify_error |
| 上传解析、RAG、引用 | `backend/app/api/knowledge.py`、`services/documents.py`、`services/knowledge.py` |
| 后台翻译、摘要、导出 | `backend/app/workers/tasks.py` 的execute_task及对应services |
| 前端WebSocket消息和状态 | `frontend/src/lib/useLive.ts` |
| 浏览器麦克风/AudioWorklet | `frontend/src/lib/audio.ts`、`frontend/public/audio/` |
| 乱序、版本淘汰、字幕显示 | `frontend/src/lib/events.ts`、`components/SessionView.tsx` |

先使用模拟模式下断点，F8逐行、F7进入、F9继续。实时音频流长期暂停会触发队列保护、超时或缺口，建议用条件断点/日志点短暂停留；后台任务断点暂停过久也可能触发中断恢复保护。不要为了断点测试关闭有界队列保护。

前端按F12打开浏览器开发者工具：Network里看/api请求和/ws连接；Messages里看事件type、stream_id、版本和event_seq；Sources里定位TS/TSX源码下断点。不要记录或分享带签名文件URL、登录Cookie或完整隐私音频。

## 命令行运行测试

在backend目录：

```powershell
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m pytest tests/test_core.py::test_demo_stop_replay_refresh_and_gap -q
..\.venv\Scripts\python.exe -m alembic current
```

在frontend目录：

```powershell
npm test
npm run typecheck
npm run build
```

## 常见问题

| 现象 | 检查 |
| --- | --- |
| No module named app | 模块目标uvicorn；工作目录backend；现有解释器 |
| No module named uvicorn/fastapi | 选错解释器；应选项目.venv，不是系统Python |
| 8000/5173被占用 | 停掉旧脚本实例或对应IDE/终端实例 |
| Vite启动而页面接口502 | API未启动或端口不是8000 |
| 登录后仍401 | 浏览器使用同一主机名；开发COOKIE_SECURE=false；检查旧环境变量 |
| 接口写请求403 | 合法Origin；Swagger也需允许8000；改.env后重启API |
| 登录账号不见/历史为空 | 工作目录错误，新建了另一份相对路径SQLite；回到backend，不要删除原库 |
| 真实模式503 | 检查missing_api_key或missing_workspace；当前workspace为空 |
| 模型认证/权限/地域错误 | 核查阿里云同地域key、业务空间及模型权限，不能用模拟结果代替成功 |
| 点开始却没有麦克风请求 | 当前可能是模拟会话；真实模式还需安全上下文和麦克风设备 |
| 断点没命中 | 用Debug启动；关闭reload；确认请求发到该实例，后台任务是否独立进程 |

Docker/生产部署与未验证事项见DEPLOYMENT.md和FEATURE_STATUS.md。当前主机没有可用Docker Engine，PostgreSQL/Redis/Celery容器和真实云调用不在本次通过范围内。
