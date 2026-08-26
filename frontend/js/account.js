// 当前用户的密码与会话管理。
import { api } from "./api.js";
import * as ui from "./ui.js";

const esc = ui.esc;
function view(sessions) {
  return `<div class="section-gap"><div class="card"><div class="card-hd"><h3>账号安全</h3><span class="sub">本地账号 · Cookie 会话</span></div><div class="card-bd"><div class="filterbar"><button class="btn btn-pri" id="change-password">修改密码</button><button class="btn btn-danger" id="revoke-all">退出其他设备</button></div><div class="small-print">密码修改后，其他设备上的会话会立即失效；当前会话保持有效。</div></div></div><div class="card"><div class="card-hd"><h3>登录会话</h3><span class="sub">可逐个撤销异常设备</span></div><div class="card-bd"><div class="tbl-wrap"><table class="tbl"><thead><tr><th>会话</th><th>创建时间</th><th>来源地址</th><th>状态</th><th></th></tr></thead><tbody>${sessions.length ? sessions.map((s) => `<tr><td class="mono">${esc(s.session_id.slice(0, 12))}… ${s.is_current ? '<span class="badge b-pass">当前</span>' : ''}</td><td>${esc(ui.fmtDateTime(s.created_at))}</td><td class="mono">${esc(s.created_ip || "未知")}</td><td>${s.is_active ? '<span class="badge b-pass">有效</span>' : '<span class="badge b-reject">已撤销</span>'}</td><td>${s.is_active && !s.is_current ? `<button class="btn btn-danger btn-sm" data-revoke="${esc(s.session_id)}">撤销</button>` : ""}</td></tr>`).join("") : `<tr><td colspan="5">${ui.emptyHtml("暂无会话")}</td></tr>`}</tbody></table></div></div></div></div>`;
}

export async function renderAccount(el) {
  el.innerHTML = ui.loadingHtml("正在加载账号安全信息…");
  try {
    const sessions = await api.sessions(); el.innerHTML = view(sessions || []);
    document.getElementById("change-password").onclick = () => ui.formModal({ title: "修改密码", sub: "新密码至少 8 位，并同时包含字母和数字", html: '<div class="form-grid"><label class="form-field">当前密码<input class="input" id="account-current" type="password" /></label><label class="form-field">新密码<input class="input" id="account-next" type="password" /></label></div>', okText: "保存密码", onOk: async () => { await api.changePassword(document.getElementById("account-current").value, document.getElementById("account-next").value); ui.toast("密码已更新", "success"); } });
    document.getElementById("revoke-all").onclick = () => ui.confirmModal({ title: "退出其他设备", html: '<div class="sum">其他设备将立即退出，当前浏览器保持登录。</div>', okText: "确认退出", danger: true, onOk: async () => { await api.revokeAllSessions(); ui.toast("其他会话已撤销", "success"); await renderAccount(el); } });
    el.querySelectorAll("[data-revoke]").forEach((button) => button.addEventListener("click", async () => { try { await api.revokeSession(button.dataset.revoke); ui.toast("会话已撤销", "success"); await renderAccount(el); } catch (error) { ui.toast(error.message || "操作失败", "error"); } }));
  } catch (error) { el.innerHTML = ui.emptyHtml(`加载失败：${esc(error.message || error)}`); }
}
