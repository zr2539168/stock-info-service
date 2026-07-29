const cloud = require("wx-server-sdk");

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

exports.main = async (event) => {
  const headers = lowerHeaders(event.headers || event.header || {});
  const expectedToken = process.env.INTERNAL_API_TOKEN || "";
  if (!expectedToken || headers["x-internal-token"] !== expectedToken) {
    return { statusCode: 401, error: "内部调用认证失败" };
  }
  const payload = parseBody(event);
  const challenge = String(payload.challenge || "");
  if (!/^[A-Za-z0-9_-]{16,32}$/.test(challenge)) {
    return { statusCode: 422, error: "challenge 格式无效" };
  }
  const result = await cloud.openapi.wxacode.getUnlimited({
    scene: challenge,
    page: "pages/web-login/index",
    checkPath: false,
    envVersion: process.env.MINIPROGRAM_STATE || "formal",
  });
  return {
    statusCode: 200,
    image_base64: result.buffer.toString("base64"),
  };
};

function parseBody(event) {
  if (event.body && typeof event.body === "string") {
    try {
      return JSON.parse(event.body);
    } catch (error) {
      return {};
    }
  }
  return event.body || event;
}

function lowerHeaders(headers) {
  return Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]));
}
