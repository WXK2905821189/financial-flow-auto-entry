// 入口：登录门、Cookie 会话恢复、导航路由、顶栏时钟、侧栏用户信息
import { api } from "./api.js";
import * as ui from "./ui.js";
import { renderReview } from "./review.js";
import { renderDash } from "./dashboards.js";
import { renderSettings } from "./settings.js";
import { renderUsers } from "./users.js";
import { renderAccount } from "./account.js";

const CRUMB = {
  review: ["复核工作台", "待复核队列 · 规则内自动通过，低置信/异常转人工"],
  overview: ["可视化看板 · 流水总览", "MVP 四看板 · 自研轻量定制 · 取数可信"],
  bank: ["可视化看板 · 银行分布", "MVP 四看板 · 自研轻量定制 · 取数可信"],
  alert: ["可视化看板 · 异常预警", "MVP 四看板 · 自研轻量定制 · 取数可信"],
  recon: ["可视化看板 · 对账钩稽", "MVP 四看板 · 自研轻量定制 · 取数可信"],
  settings: ["系统设置", "只读 · 外部系统（银行/金蝶/数据库）对接状态"],
  users: ["用户与权限", "本地账号 · 角色、数据范围与会话治理"],
  account: ["账号安全", "密码与登录会话"],
};

let currentView = "review";
let currentTab = "overview";

const ROLE_LABEL = {
  SYSTEM_ADMIN: "系统管理员",
  ADMIN: "系统管理员",
  FINANCE_MANAGER: "财务主管",
  REVIEWER: "复核员",
  INGEST_OPERATOR: "采集员",
  AUDITOR: "审计只读",
};

function applyRoleVisibility(role) {
  document.querySelectorAll("[data-roles]").forEach((node) => {
    const roles = node.dataset.roles.split(",");
    node.classList.toggle("hidden", !roles.includes(role));
  });
}

function canAccessReview(role) {
  return ["SYSTEM_ADMIN", "ADMIN", "FINANCE_MANAGER", "REVIEWER"].includes(role);
}

function isSystemAdmin(role) {
  return role === "SYSTEM_ADMIN" || role === "ADMIN";
}

function showLogin({ message = "" } = {}) {
  document.getElementById("app").classList.remove("on");
  document.getElementById("login").style.display = "flex";
  document.getElementById("lg-pass").value = "";
  if (message) document.getElementById("lg-error").textContent = message;
}

function refreshEnvironment() {
  return api.settingsStatus().then((st) => {
    const envLabel = { prod: "生产", test: "测试", dev: "开发演示" }[st.environment] || st.environment || "未知环境";
    const channel = st.kingdee?.mode === "MOCK" ? "Mock" : st.kingdee?.mode === "REAL" ? "真实对接" : "未配置";
    const hasIssue = st.database?.ok === false || st.bank?.reachable === false || st.kingdee?.mode === "UNCONFIGURED";
    const tag = document.getElementById("env-tag");
    if (!tag) return;
    tag.textContent = `${envLabel} · ${channel}${hasIssue ? " · 待检查" : ""}`;
    tag.className = `env-tag ${hasIssue ? "attention" : "ready"}`;
  }).catch(() => {
    const tag = document.getElementById("env-tag");
    if (tag) {
      tag.textContent = "运行状态未知";
      tag.className = "env-tag attention";
    }
  });
}

function navigate(view, tab = "overview") {
  currentView = view;
  currentTab = tab;
  document.querySelectorAll(".nav-item[data-view]").forEach((n) => {
    const active = view === "dash"
      ? n.dataset.view === "dash" && n.dataset.tab === tab
      : n.dataset.view === view;
    n.classList.toggle("active", active);
  });
  const c = CRUMB[view === "dash" ? tab : view] || CRUMB.review;
  document.getElementById("crumb").textContent = c[0];
  document.getElementById("crumb-sub").textContent = c[1];
  const el = document.getElementById("view");
  el.innerHTML = ui.loadingHtml();
  if (view === "dash") renderDash(el, tab);
  else if (view === "settings") renderSettings(el);
  else if (view === "users") renderUsers(el);
  else if (view === "account") renderAccount(el);
  else renderReview(el);
}

function showApp(user) {
  document.getElementById("login").style.display = "none";
  document.getElementById("app").classList.add("on");
  const roleLabel = ROLE_LABEL[user.role] || user.role || "未分配角色";
  document.getElementById("side-name").textContent = `${user.display_name || user.username} · ${roleLabel}`;
  document.getElementById("side-role").textContent = "已按银行/账户范围授权";
  document.getElementById("side-avatar").textContent = (user.display_name || user.username).charAt(0);
  applyRoleVisibility(user.role);
  if (isSystemAdmin(user.role)) refreshEnvironment();
  if (canAccessReview(user.role)) window.__refreshNotifications?.();
  if (canAccessReview(user.role)) navigate("review");
  else navigate("dash", "overview");
}

window.__onUnauth = () => {
  showLogin({ message: "会话已过期，请重新登录" });
};

function initLogin() {
  const btn = document.getElementById("lg-btn");
  const errEl = document.getElementById("lg-error");
  const submit = async () => {
    errEl.textContent = "";
    btn.disabled = true;
    btn.textContent = "登录中…";
    try {
      const data = await api.login(
        document.getElementById("lg-user").value.trim(),
        document.getElementById("lg-pass").value,
      );
      showApp(data);
    } catch (err) {
      errEl.textContent = err.message || "登录失败";
    } finally {
      btn.disabled = false;
      btn.textContent = "登 录";
    }
  };
  btn.addEventListener("click", submit);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && document.getElementById("login").style.display !== "none") submit();
  });
}

function initNav() {
  document.querySelectorAll(".nav-item[data-view]").forEach((n) => {
    n.addEventListener("click", () => navigate(n.dataset.view, n.dataset.tab || "overview"));
  });
  document.getElementById("logout-btn").addEventListener("click", async () => {
    try {
      await api.logout();
      showLogin();
      ui.toast("已退出登录", "info");
    } catch (error) {
      ui.toast(error.message || "退出失败，请稍后重试", "error");
    }
  });
}

function startClock() {
  const el = document.getElementById("clock");
  const tick = () => {
    const d = new Date();
    const pad = (x) => String(x).padStart(2, "0");
    el.textContent = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  };
  tick();
  setInterval(tick, 1000);
}

function initNotify() {
  const btn = document.getElementById("notify-btn");
  const pop = document.getElementById("notify-pop");
  const dot = document.getElementById("notify-dot");
  if (!btn || !pop || !dot) return;

  function itemHtml(icon, glyph, title, desc, view, tab) {
    return `<div class="notify-item" data-view="${view}" data-tab="${tab || ""}">
      <div class="ico ${icon}">${glyph}</div>
      <div class="tx"><div class="t">${ui.esc(title)}</div><div class="d">${ui.esc(desc)}</div></div>
    </div>`;
  }

  async function refreshDot() {
    try {
      const s = await api.summary();
      dot.style.display = (s.pending_review || 0) > 0 ? "block" : "none";
    } catch { /* 红点刷新失败可忽略 */ }
  }

  async function open() {
    pop.innerHTML = ui.loadingHtml();
    pop.classList.add("on");
    try {
      const [s, ex] = await Promise.all([api.summary(), api.exceptions()]);
      const pending = s.pending_review || 0;
      const exCount = Array.isArray(ex) ? ex.length : 0;
      dot.style.display = pending > 0 ? "block" : "none";
      const items = [
        itemHtml("warn", "⚠", `待复核 ${pending} 笔流水`, pending > 0 ? "金额超阈值或校验告警，需人工复核" : "当前无待复核流水", "review", ""),
        itemHtml(exCount > 0 ? "danger" : "brand", exCount > 0 ? "!" : "✓", `异常预警 ${exCount} 笔`, exCount > 0 ? "存在校验失败/告警，前往异常看板关注" : "当前无异常预警", "dash", "alert"),
        itemHtml("brand", "→", `今日已推送 ${s.today_pushed || 0} 笔`, `自动通过率 ${((s.auto_pass_rate || 0) * 100).toFixed(1)}%`, "review", ""),
      ];
      pop.innerHTML = `<div class="notify-head">通知<span class="hint">待复核 ${pending}</span></div>
        <div class="notify-list">${items.join("")}</div>`;
      pop.querySelectorAll(".notify-item").forEach((node) => {
        node.addEventListener("click", () => {
          pop.classList.remove("on");
          const v = node.dataset.view;
          navigate(v === "dash" ? "dash" : "review", node.dataset.tab || "overview");
        });
      });
    } catch (e) {
      pop.innerHTML = `<div class="notify-empty">加载失败：${ui.esc(e.message || e)}</div>`;
    }
  }

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (pop.classList.contains("on")) { pop.classList.remove("on"); return; }
    open();
  });
  document.addEventListener("click", (e) => {
    if (pop.classList.contains("on") && !pop.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
      pop.classList.remove("on");
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") pop.classList.remove("on");
  });

  window.__refreshNotifications = refreshDot;
}

initLogin();
initNav();
initNotify();
startClock();

// 刷新页面：只信任后端 /auth/me 返回的当前会话与实时角色，不读取浏览器 Token。
api.me().then(showApp).catch(() => showLogin());
