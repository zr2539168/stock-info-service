const config = require("../config");

async function request(path, method = "GET", data = undefined) {
  if (!wx.cloud) {
    throw new Error("当前微信版本不支持云开发能力");
  }
  if (!config.envId || config.envId.startsWith("your-")) {
    throw new Error("请先在 miniprogram/config.js 中配置 CloudBase 环境 ID");
  }
  const response = await wx.cloud.callContainer({
    config: { env: config.envId },
    path,
    method,
    data,
    header: {
      "X-WX-SERVICE": config.serviceName,
      "Content-Type": "application/json; charset=utf-8",
    },
  });
  if (response.statusCode >= 400) {
    const payload = response.data || {};
    const error = new Error(payload.message || `请求失败（${response.statusCode}）`);
    error.code = payload.code || "REQUEST_FAILED";
    error.statusCode = response.statusCode;
    error.requestId = payload.request_id || (response.header || {})["x-cloudbase-request-id"] || "";
    throw error;
  }
  return response.data;
}

module.exports = {
  request,
  get(path) {
    return request(path, "GET");
  },
  post(path, data) {
    return request(path, "POST", data || {});
  },
  put(path, data) {
    return request(path, "PUT", data || {});
  },
  patch(path, data) {
    return request(path, "PATCH", data || {});
  },
  delete(path) {
    return request(path, "DELETE");
  },
};
