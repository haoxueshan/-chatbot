# 部署、迁移与备份

生产架构为 Nginx/静态 React → FastAPI（单进程 WebSocket）→ PostgreSQL + pgvector，Redis/Celery worker/beat 负责可靠后台处理。开发环境的 SQLite/进程内 outbox 执行器只是无需 Docker 的本地入口，不等于生产容器验证。

## Linux 服务器 / 宝塔 / 1Panel

1. 将 `classbridge/` 放在独立目录，安装 Docker Engine 和 Compose v2。复制 `.env.example` 为 `.env`，生成独立的 `SECRET_KEY`（至少32字符）和 URL 安全的 `POSTGRES_PASSWORD`。设置 `COOKIE_SECURE=true`、`ALLOWED_ORIGINS=https://你的域名`、`PUBLIC_BASE_URL=https://你的域名`。不要把 `.env` 放在静态站点根目录；权限 `chmod 600 .env`。模型密钥只在该文件或服务器密钥配置中提供。Compose 显式选择 PostgreSQL 和 Celery。
2. 在项目根目录运行 `docker compose --env-file .env -f deploy/compose.yaml up -d --build`。`migrate` 服务会先执行 `alembic upgrade head`；其成功后 API/worker 启动。运行 `docker compose --env-file .env -f deploy/compose.yaml exec api python -m app.cli create-admin --username admin` 并在终端交互设置密码。没有公开注册接口。
3. 在面板创建站点、配置证书和 HTTPS，将域名反向代理到 `http://127.0.0.1:8080`，开启 WebSocket，保留 `Origin`，传递 `Host`、`Upgrade`、`Connection`。上传上限至少40 MB，超时至少6600秒。只开放 443（80用于证书/跳转）；PostgreSQL/Redis/API不发布主机端口。访问 `/api/health`，登录后先进行模拟验收，再进行短样本真实测试。

容器端口默认只绑定回环。手机/iPad使用服务器的 HTTPS 域名，个人电脑可关机。手机访问 `localhost` 指手机本身，不能使用开发电脑的回环地址。HTTP 局域网地址通常不能获取麦克风；不要关闭浏览器安全限制。锁屏和后台录音不受保证，回到前台后检查缺口记录。

面板外层 Nginx 示例（TLS证书由面板管理）：

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 6600s;
    proxy_buffering off;
    client_max_body_size 50m;
}
```

Nginx的WebSocket头和超时依据[官方代理文档](https://nginx.org/en/docs/http/websocket.html)。Compose的依赖使用健康状态与迁移完成状态，依据[官方启动顺序文档](https://docs.docker.com/compose/how-tos/startup-order/)。

外层面板Nginx也应对 `/api/storage/signed` 单独配置 `access_log off` 并保留相同代理目标，避免短期文件访问令牌被写入访问日志。仓库内层Nginx已禁用该路径日志。不要把完整带签名的URL复制到公开日志或聊天。

## 升级与数据库

先备份，再更新源码并运行上述 `up -d --build`。手动迁移：

```sh
docker compose --env-file .env -f deploy/compose.yaml run --rm api alembic upgrade head
docker compose --env-file .env -f deploy/compose.yaml exec api alembic current
```

首次迁移创建业务表；数据库初始化脚本启用 `vector` 扩展。向量固定1024维，改变维度需新建索引/重建向量及数据库迁移，不能只更改环境变量。当前单用户规模采用精确向量召回；扩大规模前测量查询计划再建立HNSW索引。单API进程避免内存中的实时连接状态分裂，Celery worker可单独扩展。不要增加 Uvicorn workers 而不先引入跨进程实时连接协调。

## 备份和恢复

Linux运行 `bash deploy/backup.sh`；短暂停止写入服务，备份 PostgreSQL（包括向量、事件、任务、引用）与本地文件卷，再恢复服务。备份文件包含私人记录，应加密并复制到受控备份介质；`.env` 另存安全位置。S3/OSS后端应启用存储桶版本与独立备份，本地文件卷备份不能替代云对象备份。

先在隔离服务器演练恢复。启动空的同版本PostgreSQL/Redis服务后执行：

```sh
bash deploy/restore.sh backups/时间目录 --replace-database
```

该命令替换目标数据库内容。使用新的文件卷，避免历史孤立文件残留。恢复后检查管理员登录、文本搜索、文件下载、引用跳转和模型配置。Redis不是业务真相源，允许清空后从数据库 outbox 恢复任务；运行中的付费模型任务需检查任务状态，不能无上限自动重放。

本地SQLite备份需停止API后复制 `backend/data/`（默认）及设置的文件存储目录。生产禁止依赖浏览器localStorage备份。

## 本次环境限制

本机未安装可用 Docker Engine/CLI，WSL报告缺少Linux内核；没有可用服务器、域名和TLS证书。本仓库会执行本地启动、构建和自动测试，容器运行及公网部署的验证状态以 `TEST_RESULTS.md` 为准，不将静态配置检查写成容器启动成功。
