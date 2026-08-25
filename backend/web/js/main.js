// 入口：登录门、会话恢复、导航路由、顶栏时钟、侧栏用户信息
import { api, auth } from "./api.js";
import * as ui from "./ui.js";
import { renderReview } from "./review.js";
import { renderDash } from "./dashboards.js";

const CRUMB = {
  review: ["复核工作台", "待复核队列 · 规则内自动通过，低置信/异常转人工"],
  overview: ["可视化看板 · 流水总览", "MVP 四看板 · 自研轻量定制 · 取数可信"],
  bank: ["可视化看板 · 银行分布", "MVP 四看板 · 自研轻量定制 · 取数可信"],
  alert: ["可视化看板 · 异常预警", "MVP 四看板 · 自研轻量定制 · 取数可信"],
  recon: ["可视化看板 · 对账钩稽", "MVP 四看板 · 自研轻量定制 · 取数可信"],
};

let currentView = "review";
let currentTab = "overview";

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
  else renderReview(el);
}

function showApp(user) {
  document.getElementById("login").style.display = "none";
  document.getElementById("app").classList.add("on");
  document.getElementById("side-name").textContent = `${user.display_name || user.username} · ${user.role === "ADMIN" ? "管理员" : "复核员"}`;
  document.getElementById("side-avatar").textContent = (user.display_name || user.username).charAt(0);
  navigate("review");
}

window.__onUnauth = () => {
  document.getElementById("app").classList.remove("on");
  document.getElementById("login").style.display = "flex";
  ui.toast("会话已过期，请重新登录", "error");
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
      auth.set(data.access_token);
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
  document.getElementById("logout-btn").addEventListener("click", () => {
    auth.clear();
    document.getElementById("app").classList.remove("on");
    document.getElementById("login").style.display = "flex";
    ui.toast("已退出登录", "info");
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

  if (auth.token) refreshDot();
}

initLogin();
initNav();
initNotify();
startClock();

// 刷新页面：已有 token 则直接进入工作台（首页渲染若 401 会自动回退）
if (auth.token) {
  document.getElementById("login").style.display = "none";
  document.getElementById("app").classList.add("on");
  document.getElementById("side-name").textContent = "财务账号";
  document.getElementById("side-avatar").textContent = "财";
  navigate("review");
}
