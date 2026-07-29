const tcb = require("@cloudbase/node-sdk");
const wxCloud = require("wx-server-sdk");

wxCloud.init({ env: wxCloud.DYNAMIC_CURRENT_ENV });

const serviceName = process.env.CLOUDBASE_SERVICE_NAME || "stock-api";
const internalToken = process.env.INTERNAL_API_TOKEN || "";

exports.main = async (event, context) => {
  if (!internalToken) {
    throw new Error("INTERNAL_API_TOKEN 未配置");
  }
  const app = tcb.init({ context });
  const claimed = await callApi(app, "/internal/notifications/claim?limit=20", "POST");
  const items = (claimed && claimed.items) || [];
  const results = [];
  for (const item of items) {
    try {
      await wxCloud.openapi.subscribeMessage.send({
        touser: item.openid,
        templateId: item.template_id,
        page: item.page || "pages/notifications/index",
        data: templateData(item),
        miniprogramState: process.env.MINIPROGRAM_STATE || "formal",
        lang: "zh_CN",
      });
      await callApi(app, `/internal/notifications/${item.id}/result`, "POST", {
        success: true,
      });
      results.push({ id: item.id, success: true });
    } catch (error) {
      const message = String(error && (error.errMsg || error.message || error));
      const transient = isTransient(error);
      await callApi(app, `/internal/notifications/${item.id}/result`, "POST", {
        success: false,
        error: message,
        transient,
      });
      results.push({ id: item.id, success: false, transient, error: message });
    }
  }
  return { claimed: items.length, results };
};

async function callApi(app, path, method, data) {
  const response = await app.callContainer(
    {
      name: serviceName,
      method,
      path,
      header: {
        "Content-Type": "application/json; charset=utf-8",
        "X-Internal-Token": internalToken,
      },
      data: data || {},
    },
    { timeout: 30000 }
  );
  if (response.statusCode && response.statusCode >= 400) {
    throw new Error(`stock-api ${response.statusCode}: ${JSON.stringify(response.data)}`);
  }
  return response.data || {};
}

function templateData(item) {
  const configured = parseMapping(process.env.TEMPLATE_DATA_MAPPING_JSON);
  const typeMapping = configured[item.template_type] || defaultMapping(item.template_type);
  const data = {};
  for (const [wechatField, sourceField] of Object.entries(typeMapping)) {
    const raw = sourceField === "time" ? item.created_at : item[sourceField];
    data[wechatField] = { value: normalizeValue(wechatField, raw) };
  }
  return data;
}

function defaultMapping(type) {
  if (type === "brief") {
    return { thing1: "title", thing2: "content", time3: "time" };
  }
  return { thing1: "title", thing2: "content", time3: "time" };
}

function normalizeValue(field, value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (field.startsWith("time")) {
    return text.replace("T", " ").slice(0, 16);
  }
  if (field.startsWith("thing")) {
    return text.slice(0, 20) || "请进入小程序查看";
  }
  return text.slice(0, 32);
}

function parseMapping(value) {
  if (!value) return {};
  try {
    return JSON.parse(value);
  } catch (error) {
    throw new Error("TEMPLATE_DATA_MAPPING_JSON 不是有效 JSON");
  }
}

function isTransient(error) {
  const code = Number(error && (error.errCode || error.code));
  return code === -1 || code === 45009 || code === 50002 || !Number.isFinite(code);
}
