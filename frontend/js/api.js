// API 客户端：认证仅使用 HttpOnly Cookie，禁止在浏览器存储或读取 Token。
// 后端是权限的唯一裁决方；前端的角色信息仅用于收敛界面入口。
let refreshPromise = null;

function buildHeaders(headers = {}, json = true) {
  return json ? { "Content-Type": "application/json", ...headers } : { ...headers };
}

function csrfToken() {
  const hit = document.cookie.match(/(?:^|; )wf_csrf=([^;]*)/);
  return hit ? decodeURIComponent(hit[1]) : "";
}

function withCsrf(headers, method) {
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const token = csrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }
  return headers;
}

async function handle(res) {
  let data = null;
  try { data = await res.json(); } catch { /* noop */ }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || `请求失败（${res.status}）`;
    const error = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    error.status = res.status;
    throw error;
  }
  return data;
}

async function refreshSession() {
  if (!refreshPromise) {
    refreshPromise = fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
      headers: withCsrf(buildHeaders(), "POST"),
      body: "{}",
    }).then(handle).finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

async function request(path, {
  method = "GET",
  body,
  headers = {},
  json = true,
  refreshOnUnauthorized = true,
  notifyOnUnauthorized = true,
} = {}) {
  const res = await fetch(path, {
    method,
    credentials: "include",
    headers: withCsrf(buildHeaders(headers, json), method),
    body: body === undefined ? undefined : (json ? JSON.stringify(body) : body),
  });
  if (res.status === 401 && refreshOnUnauthorized) {
    try {
      await refreshSession();
      return request(path, { method, body, headers, json, refreshOnUnauthorized: false, notifyOnUnauthorized });
    } catch { /* 会话刷新失败后统一回到登录页 */ }
  }
  if (res.status === 401 && notifyOnUnauthorized) {
    if (window.__onUnauth) window.__onUnauth();
    const error = new Error("登录已过期，请重新登录");
    error.status = 401;
    throw error;
  }
  return handle(res);
}

function get(path, options = {}) {
  return request(path, options);
}

function post(path, body, options = {}) {
  return request(path, { method: "POST", body: body || {}, ...options });
}

// multipart 上传（文件导入）
async function upload(path, formData) {
  return request(path, { method: "POST", body: formData, json: false });
}

export const api = {
  // 认证
  login: (username, password) =>
    post("/api/auth/login", { username, password }, { refreshOnUnauthorized: false, notifyOnUnauthorized: false }),
  me: () => get("/api/auth/me", { notifyOnUnauthorized: false }),
  logout: () => post("/api/auth/logout", {}, { refreshOnUnauthorized: false, notifyOnUnauthorized: false }),
  changePassword: (current_password, new_password) =>
    post("/api/auth/password/change", { current_password, new_password }),
  sessions: () => get("/api/auth/sessions"),
  revokeSession: (sessionId) => request(`/api/auth/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
  revokeAllSessions: () => post("/api/auth/sessions/revoke-all"),

  // 账户与权限治理。仅系统管理员可用，后端必须再次校验权限和银行/账户范围。
  users: () => get("/api/auth/users"),
  createUser: (payload) => post("/api/auth/users", payload),
  updateUser: (userId, payload) => request(`/api/auth/users/${encodeURIComponent(userId)}`, { method: "PATCH", body: payload }),
  disableUser: (userId) => post(`/api/auth/users/${encodeURIComponent(userId)}/disable`),
  resetUserPassword: (userId, new_password) =>
    post(`/api/auth/users/${encodeURIComponent(userId)}/password/reset`, { new_password }),

  // 复核
  summary: () => get("/api/dashboard/summary"),
  pending: () => get("/api/review/pending?limit=500"),
  records: () => get("/api/review/records?limit=500"),
  decide: (record_id, result, matched_subject, comment) =>
    post("/api/review/decide", { record_id, result, matched_subject, comment }),
  decideBatch: (record_ids, result, comment) =>
    post("/api/review/decide-batch", { record_ids, result, comment }),

  // 推送
  pushRecord: (record_id) => post("/api/push/record", { record_id }),
  pushBatch: (batch_id) => post("/api/push/batch", { batch_id }),

  // 溯源
  traceByRecord: (record_id) => get(`/api/trace/by-record?record_id=${record_id}`),
  traceByVoucher: (voucher_no) => get(`/api/trace/by-voucher?voucher_no=${encodeURIComponent(voucher_no)}`),

  // 看板
  overview: () => get("/api/dashboard/overview"),
  bankDistribution: () => get("/api/dashboard/bank-distribution"),
  exceptions: () => get("/api/dashboard/exceptions?limit=500"),
  recon: () => get("/api/dashboard/recon"),

  // 系统对接状态（只读）
  settingsStatus: () => get("/api/settings/status"),

  // 采集（演示入口）
  ingestMock: (bank_code, account_no, count, begin_balance, end_balance) => {
    const qs = new URLSearchParams({ bank_code, account_no, count: String(count) });
    if (begin_balance !== null && begin_balance !== undefined && begin_balance !== "") qs.set("begin_balance", begin_balance);
    if (end_balance !== null && end_balance !== undefined && end_balance !== "") qs.set("end_balance", end_balance);
    return post(`/api/ingest/mock?${qs}`);
  },
  ingestFile: (file, bank_code, account_no, begin_balance, end_balance) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("bank_code", bank_code);
    fd.append("account_no", account_no);
    if (begin_balance !== null && begin_balance !== undefined && begin_balance !== "") fd.append("begin_balance", begin_balance);
    if (end_balance !== null && end_balance !== undefined && end_balance !== "") fd.append("end_balance", end_balance);
    return upload("/api/ingest/file", fd);
  },
};
