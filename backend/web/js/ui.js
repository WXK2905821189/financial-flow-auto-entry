// 通用 UI 工具：格式化、状态徽章、toast、弹窗、抽屉、HTML 转义
// 类名与静态容器（#modal-wrap/#modal、#mask/#drawer、#toast）对齐 UI 原型

export function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

export function fmtAmount(v, currency = "CNY") {
  const n = Number(v || 0);
  const sym = currency === "CNY" ? "¥" : currency + " ";
  return sym + n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function money(n) {
  return Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function fmtInt(n) {
  return Number(n || 0).toLocaleString("zh-CN");
}

export function fmtDate(s) {
  if (!s) return "—";
  return String(s).slice(0, 10);
}

export function fmtDateTime(s) {
  if (!s) return "—";
  return String(s).replace("T", " ").slice(0, 19);
}

export function dcFlagText(dc) {
  return dc === "C" ? "收" : dc === "D" ? "支" : (dc || "—");
}

// 处理状态徽章（对齐设计归档六态 + 原型色板）
const STATUS_MAP = {
  REVIEW_READY: ["b-wait", "待复核"],
  REVIEW_PASSED: ["b-pass", "自动通过"],
  KINGDEE_POSTED: ["b-push", "已推送"],
  PUSHED: ["b-push", "已推送"],
  REJECTED: ["b-reject", "已驳回"],
  LOADED: ["b-doing", "已入库"],
  VALIDATING: ["b-doing", "校验中"],
};

export function statusBadge(status) {
  const [cls, label] = STATUS_MAP[status] || ["b-reject", status || "—"];
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}

// 校验结果徽章（流水级 aggregation）
export function validationBadge(status) {
  const map = {
    PASS: ["b-pass", "校验通过"],
    WARN: ["b-wait", "需复核"],
    FAIL: ["b-err", "校验异常"],
    PENDING: ["b-reject", "待校验"],
  };
  const [cls, label] = map[status] || ["b-reject", status || "—"];
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}

export function ruleBadge(rule_code) {
  return `<span class="badge b-doing">${esc(rule_code)}</span>`;
}

// ---------- toast ----------
let _tt = null;
export function toast(msg, type = "info", ms = 2800) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.className = type === "success" ? "on ok" : type === "error" ? "on err" : "on info";
  clearTimeout(_tt);
  _tt = setTimeout(() => t.classList.remove("on"), ms);
}

// ---------- 弹窗（静态容器）----------
export function closeModal() {
  const w = document.getElementById("modal-wrap");
  if (w) w.classList.remove("on");
}

function openModal({ icon = "ok", title = "", sub = "", body = "", actions = "" }) {
  document.getElementById("mo-title").textContent = title;
  document.getElementById("mo-sub").textContent = sub || "";
  const ic = document.getElementById("mo-ic");
  const glyphs = { warn: "⚠", ok: "✓", danger: "!" };
  ic.className = "ic " + icon;
  ic.innerHTML = glyphs[icon] || "✓";
  document.getElementById("mo-body").innerHTML = body || "";
  document.getElementById("mo-ft").innerHTML = actions || "";
  document.getElementById("modal-wrap").classList.add("on");
  return { close: closeModal, el: document.getElementById("modal") };
}

export function confirmModal({ title, html, okText = "确认", danger = false, onOk }) {
  const okCls = danger ? "btn-danger" : "btn-pri";
  openModal({
    icon: danger ? "warn" : "ok",
    title,
    sub: danger ? "该操作为不可逆入账动作，请二次确认" : "",
    body: html || "",
    actions: `<button class="btn btn-ghost" data-cancel>取消</button><button class="btn ${okCls}" data-ok>${esc(okText)}</button>`,
  });
  const ft = document.getElementById("mo-ft");
  ft.querySelector("[data-cancel]").onclick = closeModal;
  ft.querySelector("[data-ok]").onclick = async () => {
    const okBtn = ft.querySelector("[data-ok]");
    okBtn.disabled = true;
    try {
      await onOk();
      closeModal();
    } catch (e) {
      okBtn.disabled = false;
      toast(e.message || "操作失败", "error");
    }
  };
}

export function promptModal({ title, placeholder, okText = "确认", danger = false }) {
  return new Promise((resolve) => {
    openModal({
      icon: danger ? "danger" : "ok",
      title,
      body: `<textarea class="field" data-input placeholder="${esc(placeholder)}"></textarea>`,
      actions: `<button class="btn btn-ghost" data-cancel>取消</button><button class="btn ${danger ? "btn-danger" : "btn-pri"}" data-ok>${esc(okText)}</button>`,
    });
    const ft = document.getElementById("mo-ft");
    const input = document.getElementById("mo-body").querySelector("[data-input]");
    ft.querySelector("[data-cancel]").onclick = () => { closeModal(); resolve(null); };
    ft.querySelector("[data-ok]").onclick = () => { const v = input.value.trim(); closeModal(); resolve(v); };
    input && input.focus();
  });
}

// ---------- 抽屉（静态容器）----------
export function closeDrawer() {
  document.getElementById("mask")?.classList.remove("on");
  document.getElementById("drawer")?.classList.remove("on");
}

export function openDrawer({ title = "流水详情", badge = "", body = "", footer = "" }) {
  document.getElementById("dw-title").textContent = title;
  document.getElementById("dw-badge").innerHTML = badge || "";
  document.getElementById("dw-body").innerHTML = body;
  document.getElementById("dw-foot").innerHTML = footer || "";
  document.getElementById("mask").classList.add("on");
  document.getElementById("drawer").classList.add("on");
  return { close: closeDrawer, el: document.getElementById("drawer") };
}

export function loadingHtml(text = "加载中…") {
  return `<div class="loading"><div class="spinner"></div>${esc(text)}</div>`;
}

export function emptyHtml(text = "暂无数据") {
  return `<div class="empty">${esc(text)}</div>`;
}

// 静态容器事件绑定（模块加载即绑定一次）
document.getElementById("dw-close")?.addEventListener("click", closeDrawer);
document.getElementById("mask")?.addEventListener("click", closeDrawer);
document.getElementById("modal-wrap")?.addEventListener("click", (e) => {
  if (e.target && e.target.id === "modal-wrap") closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeDrawer(); closeModal(); }
});
