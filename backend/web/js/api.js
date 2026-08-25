// API 客户端：统一封装 fetch + JWT 鉴权 + 401 处理
const TOKEN_KEY = "wf_token";

export const auth = {
  get token() { return localStorage.getItem(TOKEN_KEY) || ""; },
  set(token) { localStorage.setItem(TOKEN_KEY, token); },
  clear() { localStorage.removeItem(TOKEN_KEY); },
};

function buildHeaders(headers = {}) {
  return { "Content-Type": "application/json", Authorization: `Bearer ${auth.token}`, ...headers };
}

async function handle(res) {
  if (res.status === 401) {
    auth.clear();
    if (window.__onUnauth) window.__onUnauth();
    throw new Error("登录已过期，请重新登录");
  }
  let data = null;
  try { data = await res.json(); } catch { /* noop */ }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || `请求失败（${res.status}）`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

async function get(path) {
  const res = await fetch(path, { headers: buildHeaders() });
  return handle(res);
}

async function post(path, body) {
  const res = await fetch(path, { method: "POST", headers: buildHeaders(), body: JSON.stringify(body || {}) });
  return handle(res);
}

// multipart 上传（文件导入）
async function upload(path, formData) {
  const res = await fetch(path, {
    method: "POST",
    headers: { Authorization: `Bearer ${auth.token}` },
    body: formData,
  });
  return handle(res);
}

export const api = {
  // 认证
  login: (username, password) =>
    fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) }).then(handle),

  // 复核
  summary: () => get("/api/dashboard/summary"),
  pending: () => get("/api/review/pending?limit=500"),
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

  // 采集（演示入口）
  ingestMock: (bank_code, account_no, count) => {
    const qs = `bank_code=${encodeURIComponent(bank_code)}&account_no=${encodeURIComponent(account_no)}&count=${count}`;
    return post(`/api/ingest/mock?${qs}`);
  },
  ingestFile: (file, bank_code, account_no) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("bank_code", bank_code);
    fd.append("account_no", account_no);
    return upload("/api/ingest/file", fd);
  },
};
