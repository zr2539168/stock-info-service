# 微信云资源开通与部署清单

## 1. 创建基础资源

- 在微信开发者工具中导入 `wechat/`，确认 AppID 与 `project.config.json` 一致。
- 创建 CloudBase 环境并关联小程序，记录环境 ID。
- 开通 CloudBase MySQL，创建 `stock_info` 数据库及专用账号，并确保字符集为 `utf8mb4`。
- 将 MySQL、云托管服务和云函数放在同一环境/VPC，安全组只允许必要的内网访问。
- 在 `miniprogram/config.js`、`miniprogram/envList.js` 中填写环境 ID，服务名保持 `stock-api`。

## 2. 准备密钥和环境变量

生成至少 32 字节的随机值，分别用于 `USER_SECRET_MASTER_KEY`、`SESSION_SECRET` 和 `INTERNAL_API_TOKEN`。`USER_SECRET_MASTER_KEY` 建议使用 32 字节 URL-safe Base64；密钥一旦用于加密用户 DeepSeek Key，不可随意更换。

两个云托管服务共用以下变量：

- `DATABASE_URL`：`mysql+pymysql://用户:密码@内网地址:3306/stock_info?charset=utf8mb4`
- `WECHAT_APP_ID`、`CLOUDBASE_ENV_ID`
- `ADMIN_OPENIDS`：首位管理员 OpenID，多个值用逗号分隔
- `USER_SECRET_MASTER_KEY`、`SESSION_SECRET`、`INTERNAL_API_TOKEN`
- `ALERT_TEMPLATE_ID`、`BRIEF_TEMPLATE_ID`
- `ALLOWED_DEEPSEEK_MODELS`
- `WECHAT_QR_FUNCTION_URL`：`webLoginQr` HTTP 访问地址

`stock-api` 另外设置：

```text
APP_MODE=api
CLOUDBASE_SERVICE_NAME=stock-api
RUN_MIGRATIONS=true
COLLECTION_ENABLED=true
COLLECT_ALL_CRON=0 * * * *
```

`stock-admin` 另外设置：

```text
APP_MODE=admin
CLOUDBASE_SERVICE_NAME=stock-api
RUN_MIGRATIONS=false
```

不要在云端配置全局 DeepSeek Key；每位用户在小程序“我的 → DeepSeek 设置”中保存自己的 Key。

## 3. 部署两个云托管服务

以仓库根目录为构建上下文，Dockerfile 使用 `wechat/cloudrun/Dockerfile`。同一镜像部署两次：

- `stock-api`：关闭公网访问，最小实例数为 1，允许小程序和同环境云函数通过 `callContainer` 调用。
- `stock-admin`：开启 HTTPS 公网访问，最小实例数可为 0，不运行定时任务。

首次由 `stock-api` 启动时执行 `alembic upgrade head`。确认 `/healthz` 返回 `mode=api` 或 `mode=admin`，并确认只有 `stock-api` 执行数据库迁移。

## 4. 配置订阅消息和云函数

- 在小程序后台申请“股票提醒”和“简报”两个订阅消息模板，分别填写 `ALERT_TEMPLATE_ID`、`BRIEF_TEMPLATE_ID`。
- 部署 `cloudfunctions/messageDispatcher`，设置 `CLOUDBASE_SERVICE_NAME=stock-api`、与云托管一致的 `INTERNAL_API_TOKEN`、`MINIPROGRAM_STATE`。
- 如果模板字段不是 `thing1/thing2/time3`，设置 `TEMPLATE_DATA_MAPPING_JSON`，例如：

```json
{"alert":{"thing1":"title","thing2":"content","time3":"time"},"brief":{"thing1":"title","thing2":"content","time3":"time"}}
```

- 为 `messageDispatcher` 启用每分钟触发器。通知会先写入站内通知中心；有可用授权次数时才发送微信订阅消息，临时错误最多重试三次。
- 部署 `cloudfunctions/webLoginQr`，配置相同的 `INTERNAL_API_TOKEN` 和 `MINIPROGRAM_STATE`，开启 HTTP 访问并把地址写入 `WECHAT_QR_FUNCTION_URL`。

## 5. 迁移本地数据

先执行 dry-run：

```powershell
python scripts/migrate_sqlite_to_mysql.py `
  --source-sqlite data/stock_info.db `
  --target-dsn "mysql+pymysql://user:password@host:3306/stock_info?charset=utf8mb4" `
  --admin-openid "首位管理员OpenID" `
  --dry-run
```

核对数量后去掉 `--dry-run`。工具支持重复执行：共享证券和历史数据按原 ID/证券身份去重，本地私有数据归属首位管理员。旧 DeepSeek Key 和 PushDeer 配置只识别后丢弃。

## 6. 上线验收

- 首位管理员首次进入小程序后应直接激活；其他用户显示“等待审核”。
- 分别以两名普通用户验证自选、对话、简报、提醒、密钥和通知不可互访。
- 验证四类指数的 1 周、1 月、1 年、10 年、成立以来区间共用同一选择器，长周期图表可正常降采样。
- 申请一次提醒/简报订阅授权，确认站内通知、微信消息、授权次数消耗和详情跳转。
- 打开 `stock-admin`，扫码后在小程序中明确确认登录；验证过期、重复确认和非管理员确认均被拒绝。
- 同时触发两次采集，确认数据库租约只生成一条成功任务记录。
- 在真机验证前后台切换、弱网重试和订阅消息跳转。
