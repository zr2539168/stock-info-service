# CloudBase Run 部署

使用仓库根目录作为 Docker 构建上下文：

```powershell
docker build -f wechat/cloudrun/Dockerfile -t stock-info-cloud .
```

同一镜像部署两次：

- `stock-api`：`APP_MODE=api`、`RUN_MIGRATIONS=true`，关闭公网访问，最小实例数设为 1；小程序通过 `wx.cloud.callContainer` 调用。
- `stock-admin`：`APP_MODE=admin`、`RUN_MIGRATIONS=false`，开启 HTTPS 公网访问，最小实例数可设为 0；只提供扫码登录后的管理页面。

两个服务必须处于同一 CloudBase 环境和 VPC，并使用同一个 MySQL。首次部署前创建数据库账号，将 `env.example` 中的所有占位值配置为云托管环境变量。只允许 `stock-api` 在启动时执行 `alembic upgrade head`，避免两个服务并发迁移。

不要把真实 OpenID、数据库密码、DeepSeek Key、会话密钥或内部调用令牌提交到仓库。
