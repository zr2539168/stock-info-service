# Stock Info Service

本地股票信息服务 MVP：自选 A股/美股/港股，定时采集市场信息，使用 DeepSeek 生成中文简报和问答，并通过 PushDeer 推送到 iPhone。

> 仅用于个人信息聚合和分析辅助，不构成投资建议，也不提供自动交易能力。

## 功能

- 自选股管理：市场、代码、名称、标签、启停状态。
- 免费数据源优先：AKShare 为主，yfinance 补充美股/港股，RSS/官方披露源用于新闻和公告。
- 后台抓取：服务启动后默认每 1 小时抓取一次全部信息，可在 Settings 页面关闭，也可在任务页手动抓取。
- AI 简报：基于本地已采集数据生成中文摘要，带来源链接和风险提示。
- 开盘后简报推送：可在 Settings 页面开启/关闭，并分别设置 A 股/港股和美股的工作日推送时间；简报只使用对应市场的自选股资料。
- AI 对话：围绕已有资料回答问题，避免脱离本地数据编造结论。
- PushDeer：支持连接测试、开盘后简报推送、监控触发推送。
- 监控规则：股价阈值、涨跌幅、成交量、关键词提醒，支持冷却循环推送和一次性推送。
- Settings 页面可手动修改 DeepSeek 和 PushDeer 配置，数据库配置优先于 `.env`。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑 `.env`，填入本地密钥：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
PUSHDEER_PUSHKEY=your_pushdeer_pushkey
```

启动服务：

```powershell
uvicorn app.main:app --reload
```

打开浏览器访问：

```text
http://127.0.0.1:8000
```

## 配置优先级

1. Settings 页面保存的本地 SQLite 配置。
2. `.env` 环境变量。
3. 代码中的安全默认值。

后台抓取可在 Settings 页面显式开启/关闭，默认每 1 小时执行一次；开盘后简报可在 Settings 页面设置时间。保存到本地 SQLite 后会覆盖 `.env` 中的 `COLLECTION_ENABLED`、`MARKET_OPEN_BRIEFS_ENABLED`、`CN_OPEN_BRIEF_CRON` 和 `US_OPEN_BRIEF_CRON`。

密钥默认脱敏显示，不会写入日志；`.env` 已在 `.gitignore` 中排除。

## 测试

```powershell
pytest
```

## GitHub

首次实现完成后推送到：

```text
git@github.com:zr2539168/stock-info-service.git
```

