# Stock Info Service

面向微信小程序与 Web 管理台的多用户股票信息服务：跟踪 A 股、美股和港股，定时采集市场信息，使用用户自己的 DeepSeek Key 生成中文简报和问答，并通过微信订阅消息与站内通知发送提醒。

> 仅用于个人信息聚合和分析辅助，不构成投资建议，也不提供自动交易能力。

## 功能

- 自选股管理：市场、代码、名称、标签、启停状态。
- 免费数据源优先：AKShare 为主，yfinance 补充美股/港股，RSS/官方披露源用于新闻和公告。
- 多用户隔离：自选股、提醒、简报、AI 对话、密钥和通知按微信 OpenID 隔离；行情、新闻和指数历史共享。
- 后台抓取：云端默认每 1 小时抓取所有用户启用自选股的并集，可由管理员关闭或手动执行。
- AI 简报：基于本地已采集数据生成中文摘要，带来源链接和风险提示。
- 开盘后简报推送：每位用户可以分别设置 A 股/港股和美股的工作日简报时间；简报只使用该用户对应市场的自选股资料。
- AI 对话：围绕已有资料回答问题，避免脱离本地数据编造结论。
- 市场指数：跟踪恐贪指数、VIX、MOVE 和美国 10 年期国债收益率，共享一周至成立以来的走势图区间并支持 AI 综合分析。
- 微信通知：所有提醒进入站内通知中心，有订阅授权额度时再发送微信订阅消息。
- 监控规则：股价阈值、涨跌幅、成交量、关键词提醒，支持冷却循环推送和一次性推送。
- DeepSeek Key 使用 AES-256-GCM 在云端加密保存，小程序和 API 不返回明文。
- Web 管理台通过小程序扫码确认登录，提供用户审核、共享数据管理、采集设置和任务记录。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

本地开发默认使用 SQLite 和旧 Web 界面：

```env
APP_MODE=local
DATABASE_URL=sqlite:///./data/stock_info.db
```

启动服务：

```powershell
uvicorn app.main:app --reload
```

打开浏览器访问：

```text
http://127.0.0.1:8000
```

## 微信小程序与云托管

- 小程序工程和云函数位于 `wechat/`。
- 云托管镜像说明见 `wechat/cloudrun/README.md`。
- 创建 CloudBase 环境后，修改 `wechat/miniprogram/config.js` 中的环境 ID。
- `stock-api` 使用 `APP_MODE=api` 并关闭公网访问；`stock-admin` 使用 `APP_MODE=admin` 并开启 HTTPS。

生产环境使用 CloudBase MySQL，并在启动时执行：

```powershell
alembic upgrade head
```

迁移现有本地数据：

```powershell
python scripts/migrate_sqlite_to_mysql.py `
  --source-sqlite data/stock_info.db `
  --target-dsn "mysql+pymysql://user:password@host:3306/stock_info?charset=utf8mb4" `
  --admin-openid "首位管理员OpenID" `
  --dry-run
```

确认统计结果后去掉 `--dry-run` 正式迁移。PushDeer 配置和旧 DeepSeek Key 不会迁移。

## 配置与安全

云端敏感配置只保存为环境变量，包括数据库连接、`ADMIN_OPENIDS`、用户密钥加密主密钥、Web 会话密钥和内部调用令牌。不要把真实值提交到 Git。

后台抓取可由 Web 管理台或小程序管理员开启/关闭；个人简报计划在小程序“个人设置”中维护。

每名用户的 DeepSeek Key 由本人在小程序中配置，Base URL 固定为 DeepSeek 官方地址，模型受管理员白名单限制。

## 测试

```powershell
pytest
```

## GitHub

首次实现完成后推送到：

```text
git@github.com:zr2539168/stock-info-service.git
```

