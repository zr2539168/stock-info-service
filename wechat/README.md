# Stock Info 微信小程序

目录结构：

- `miniprogram/`：原生微信小程序，包含概览、自选股、信息库、指数、简报、AI 对话、提醒、通知、个人设置和管理员页面。
- `cloudfunctions/messageDispatcher/`：每分钟发送待处理的微信订阅消息。
- `cloudfunctions/webLoginQr/`：为 Web 管理台生成一次性登录小程序码。
- `cloudrun/`：FastAPI 云托管镜像与双服务部署说明。
- `DEPLOYMENT.md`：从创建云资源到真机验收的完整开通清单。

## 首次配置

1. 在微信云开发控制台创建环境并关联当前小程序 AppID。
2. 开通 CloudBase MySQL 和 VPC，部署 `stock-api` 与 `stock-admin`。
3. 修改 `miniprogram/config.js` 和 `envList.js` 中的环境 ID。
4. 申请提醒和简报订阅消息模板，将模板 ID 配置到云托管环境变量。
5. 分别上传并部署两个云函数，为 `messageDispatcher` 设置一分钟定时触发器。
6. 在 `ADMIN_OPENIDS` 中配置首位管理员的 OpenID。

订阅消息模板字段由 `messageDispatcher` 的 `TEMPLATE_DATA_MAPPING_JSON` 控制。默认使用 `thing1=标题`、`thing2=内容`、`time3=时间`；如果申请到的模板字段不同，需要按实际模板修改映射。

所有源码和中文文本均使用 UTF-8。密钥、OpenID、数据库连接和模板真实配置不得写入小程序源码。

详细部署步骤见 [DEPLOYMENT.md](DEPLOYMENT.md)。
