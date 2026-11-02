# iPad / iPhone 通过 Tailscale 使用麦克风

最新状态（2026-11-01）：管理员已启用HTTPS，已实际执行Serve并配置后台运行。当前入口为 **https://desktop-nb4op0t.tail8b5cde.ts.net/**，代理到127.0.0.1:80。本机通过正常TLS证书校验读取页面与/api/health均为HTTP200；合法HTTPS Origin的空登录请求为422（参数校验），未被来源校验拦截。没有执行真实登录、iPad麦克风或付费模型调用。保持电脑上的Tailscale、前端80和后端8000运行。

后续连接复检（2026-11-01）：已通过真实登录创建一个临时模拟会话，分别经后端8000、前端80、Tailscale HTTPS/WSS连接，三条路径均收到恢复事件。测试会话已删除，测试登录已退出，没有调用模型或开启麦克风。上述“没有执行真实登录”仅指首次HTTPS验收。

若Safari停在“连接中”：前端现已增加10秒建连超时、有限重试、前台恢复检查和连接心跳；连接未完成时也显示“重新连接”。更新后重启PyCharm的backend/main.py并刷新iPad页面；旧版页面可能仍保留旧脚本。自动恢复只恢复记录，不开启麦克风。历史“采集缺口”保留为实际中断记录，不表示当前连接仍在报错。实机Safari的后台/VPN切换行为仍需在设备上复验。

Safari的getUserMedia需要安全上下文。VPN中的HTTP IP地址仍不满足要求。不要移除前端安全检查或把警告中的localhost理解成另一台服务器；localhost指当前设备本身。

## 已准备的配置

当前电脑安装了Tailscale，处于Running状态，VPN地址100.80.24.7。后台已将设备完整HTTPS域名加入根目录.env的ALLOWED_ORIGINS；frontend/.env.local通过CLASSBRIDGE_ALLOWED_HOSTS单独允许该域名，Vite保留Host校验。该前端文件不包含API密钥，已被Git忽略。

首次通过CLI尝试时，Tailscale返回“Serve is not enabled on your tailnet”；管理员随后已完成启用，当前验证结果见本文顶部。启用HTTPS涉及设备域名的公开证书透明度记录；服务访问本身由Tailnet权限控制。使用Serve，不开启Funnel。

## 操作

1. 服务器执行以下命令，若提示启用Serve，使用Tailscale管理员账号打开命令输出的启用链接，按页面说明启用HTTPS。管理员授权链接以当前CLI输出为准，不记录到仓库。

```powershell
tailscale serve --bg --https=443 http://127.0.0.1:80
```

2. 重启PyCharm中的backend/main.py；前端终端Ctrl+C后重新 `npm run dev`。保持前端80和后端8000运行。若使用一键启动脚本（前端5173），需将上面反向代理目标相应改为http://127.0.0.1:5173。

3. iPad保持Tailscale连接，使用 `https://设备完整域名.ts.net/`，不要使用 `http://100.80.24.7` 或 `https://100.80.24.7`。在新域名重新登录，点击开始录音并允许麦克风。新域名的Cookie与旧IP地址不同，需要重新登录。若证书仍不受信任，先解决证书问题，不绕过浏览器警告。

检查：

```powershell
tailscale serve status
```

应显示HTTPS域名代理到本地前端端口。浏览器地址栏不再显示不安全，开发者工具中window.isSecureContext为true；WebSocket使用同一域名的wss。若出现Blocked request主机不被允许，核对frontend/.env.local中的CLASSBRIDGE_ALLOWED_HOSTS为完整主机名（不带协议/端口/路径）并重启Vite；若出现请求来源不受信任，核对后端ALLOWED_ORIGINS中的https完整来源并重启API。

后端保持对API密钥的服务端读取。COOKIE_SECURE=false可兼容当前HTTP本地调试；统一切换到HTTPS后可设为true并重启后端。HTTPS只解决浏览器采音前置条件，不代表阿里云模型权限或课堂效果已通过。

关闭本次443入口：

```powershell
tailscale serve --https=443 off
```

Tailscale Serve HTTPS入口仅面向Tailnet，不等于公网部署，也不能保证阿里云文件转写服务器能读取该私有地址。会后文件转写需云端可访问的受控签名存储地址。

参考：[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve)、[getUserMedia安全上下文](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)。
