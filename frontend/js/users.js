// 用户与权限治理：界面只提供操作入口，实际权限由后端 require_permission 决定。
import { api } from "./api.js";
import * as ui from "./ui.js";

const esc = ui.esc;
const ROLE_LABEL = { SYSTEM_ADMIN: "系统管理员", ADMIN: "系统管理员（兼容）", FINANCE_MANAGER: "财务主管", REVIEWER: "复核员", INGEST_OPERATOR: "采集员", AUDITOR: "审计只读" };
const ROLES = ["SYSTEM_ADMIN", "FINANCE_MANAGER", "REVIEWER", "INGEST_OPERATOR", "AUDITOR"];

function roleOptions(selected = "REVIEWER") {
  return ROLES.map((role) => `<option value="${role}" ${role === selected ? "selected" : ""}>${ROLE_LABEL[role]}</option>`).join("");
}

function scopeValue(scopes = []) {
  return scopes.map((scope) => `${scope.bank_id == null ? "" : scope.bank_id}/${scope.account_id == null ? "" : scope.account_id}`).join("\n");
}

function parseScopes(value) {
  return value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean).map((item) => {
    const [bank, account] = item.split("/").map((v) => v.trim());
    const scope = {};
    if (bank) scope.bank_id = Number(bank);
    if (account) scope.account_id = Number(account);
    if (Object.values(scope).some((v) => !Number.isInteger(v) || v <= 0)) throw new Error("数据范围格式应为 bank_id/account_id，每行一项");
    return scope;
  });
}

function formHtml(user = null) {
  const editing = Boolean(user);
  return `<div class="form-grid">
    <label class="form-field">登录账号<input class="input" id="um-username" value="${esc(user?.username || "")}" ${editing ? "disabled" : ""} placeholder="至少 3 个字符" /></label>
    <label class="form-field">显示名称<input class="input" id="um-display" value="${esc(user?.display_name || "")}" placeholder="姓名或岗位名称" /></label>
    <label class="form-field">角色<select class="select" id="um-role">${roleOptions(user?.role)}</select></label>
    ${editing ? "" : "<label class=\"form-field\">初始密码<input class=\"input\" id=\"um-password\" type=\"password\" placeholder=\"至少 8 位，含字母和数字\" /></label>"}
  </div>
  <label class="form-field" style="margin-top:14px">银行 / 账户范围 <textarea class="field" id="um-scopes" placeholder="每行填写 bank_id/account_id；仅填 bank_id 表示该银行全部账户">${esc(scopeValue(user?.scopes))}</textarea></label>
  <div class="small-print">系统管理员默认拥有全量范围；其他角色没有授权范围时将看不到流水。账号停用或角色变更会立即撤销其有效会话。</div>`;
}

function row(user) {
  const status = user.is_active ? '<span class="badge b-pass">启用</span>' : '<span class="badge b-reject">停用</span>';
  const scope = user.role === "SYSTEM_ADMIN" || user.role === "ADMIN" ? "全量" : `${(user.scopes || []).length} 项`;
  return `<tr><td><b>${esc(user.display_name)}</b><div class="hint mono">${esc(user.username)}</div></td><td>${esc(ROLE_LABEL[user.role] || user.role)}</td><td>${scope}</td><td>${status}</td><td><div style="display:flex;gap:5px;flex-wrap:wrap"><button class="btn btn-ghost btn-sm" data-edit="${user.user_id}">编辑</button><button class="btn btn-ghost btn-sm" data-reset="${user.user_id}">重置密码</button>${user.is_active ? `<button class="btn btn-danger btn-sm" data-disable="${user.user_id}">停用</button>` : `<button class="btn btn-ghost btn-sm" data-enable="${user.user_id}">启用</button>`}</div></td></tr>`;
}

function view(items) {
  const active = items.filter((item) => item.is_active).length;
  return `<div class="section-gap"><div class="stat-row"><div class="stat cnt"><div class="strip"></div><div class="lbl">账号总数</div><div class="val">${items.length}</div><div class="delta">仅限财务小组使用</div></div><div class="stat gain"><div class="strip"></div><div class="lbl">当前启用</div><div class="val">${active}</div><div class="delta">停用即时失效</div></div><div class="stat net"><div class="strip"></div><div class="lbl">角色类型</div><div class="val">5</div><div class="delta">固定角色，默认拒绝</div></div></div><div class="card"><div class="card-hd"><h3>用户与权限</h3><div class="right"><span class="sub">本地账号 · 后端强制授权</span><button class="btn btn-pri btn-sm" id="um-create">新增用户</button></div></div><div class="card-bd"><div class="tbl-wrap"><table class="tbl"><thead><tr><th>用户</th><th>角色</th><th>数据范围</th><th>状态</th><th>操作</th></tr></thead><tbody>${items.length ? items.map(row).join("") : `<tr><td colspan="5">${ui.emptyHtml("暂无用户")}</td></tr>`}</tbody></table></div></div></div><div class="card"><div class="card-hd"><h3>权限边界</h3><span class="sub">系统管理员不自动获得业务审批权</span></div><div class="card-bd"><div class="set-meta"><span class="kv">复核与推送：财务主管</span><span class="kv">采集：采集员</span><span class="kv">只读审计：审计只读</span><span class="kv">用户治理：系统管理员</span></div></div></div></div>`;
}

function openUserForm(user, reload) {
  ui.formModal({ title: user ? "编辑用户" : "新增用户", sub: "变更会写入审计日志", html: formHtml(user), okText: user ? "保存变更" : "创建账号", onOk: async () => {
    const display_name = document.getElementById("um-display").value.trim();
    const role = document.getElementById("um-role").value;
    const scopes = parseScopes(document.getElementById("um-scopes").value);
    if (!display_name) throw new Error("请填写显示名称");
    if (user) await api.updateUser(user.user_id, { display_name, role, scopes });
    else {
      const username = document.getElementById("um-username").value.trim();
      const password = document.getElementById("um-password").value;
      if (!username || !password) throw new Error("请填写账号和初始密码");
      await api.createUser({ username, display_name, password, role, scopes });
    }
    await reload(); ui.toast(user ? "用户已更新" : "用户已创建", "success");
  } });
}

function openReset(user, reload) {
  ui.formModal({ title: `重置 ${user.username} 的密码`, sub: "重置后该用户的其他会话会立即失效", html: '<label class="form-field">新密码<input class="input" id="um-reset-password" type="password" placeholder="至少 8 位，含字母和数字" /></label>', okText: "确认重置", danger: true, onOk: async () => {
    const password = document.getElementById("um-reset-password").value;
    if (!password) throw new Error("请填写新密码");
    await api.resetUserPassword(user.user_id, password); await reload(); ui.toast("密码已重置", "success");
  } });
}

function bind(items, reload) {
  document.getElementById("um-create")?.addEventListener("click", () => openUserForm(null, reload));
  document.querySelectorAll("[data-edit]").forEach((button) => button.addEventListener("click", () => { const user = items.find((item) => String(item.user_id) === button.dataset.edit); if (user) openUserForm(user, reload); }));
  document.querySelectorAll("[data-reset]").forEach((button) => button.addEventListener("click", () => { const user = items.find((item) => String(item.user_id) === button.dataset.reset); if (user) openReset(user, reload); }));
  document.querySelectorAll("[data-disable],[data-enable]").forEach((button) => button.addEventListener("click", () => {
    const user = items.find((item) => String(item.user_id) === (button.dataset.disable || button.dataset.enable)); if (!user) return;
    const enabled = Boolean(button.dataset.enable);
    ui.confirmModal({ title: enabled ? `启用 ${user.username}` : `停用 ${user.username}`, html: `<div class="sum">${enabled ? "该账号将可以重新登录。" : "该账号的现有会话将立即失效，且无法继续访问流水数据。"}</div>`, okText: enabled ? "启用账号" : "停用账号", danger: !enabled, onOk: async () => { await api.updateUser(user.user_id, { is_active: enabled }); await reload(); ui.toast(enabled ? "账号已启用" : "账号已停用", "success"); } });
  }));
}

export async function renderUsers(el) {
  el.innerHTML = ui.loadingHtml("正在加载用户与权限…");
  const reload = async () => { const data = await api.users(); const items = data.items || []; el.innerHTML = view(items); bind(items, reload); };
  try { await reload(); } catch (error) { el.innerHTML = ui.emptyHtml(`加载失败：${esc(error.message || error)}`); }
}
