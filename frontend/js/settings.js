// 系统设置：只读展示银行 / 金蝶 / 数据库 / 复核规则对接状态（不含任何密钥）
import { api } from "./api.js";
import * as ui from "./ui.js";

const esc = ui.esc;

function row(icon, title, badgeCls, badgeText, desc, metas) {
  const metaHtml = (metas || [])
    .map(([k, v]) => `<span class="kv">${esc(k)}<b>${esc(v)}</b></span>`)
    .join("");
  return `<div class="set-row">
    <div class="ic">${esc(icon)}</div>
    <div class="set-main">
      <div class="set-title">${esc(title)}<span class="badge ${badgeCls}">${esc(badgeText)}</span></div>
      <div class="set-desc">${esc(desc)}</div>
      ${metas ? `<div class="set-meta">${metaHtml}</div>` : ""}
    </div>
  </div>`;
}

function envBadge(env) {
  if (env === "prod") return ["b-push", "生产"];
  if (env === "test") return ["b-pass", "测试"];
  return ["b-wait", "开发演示"];
}

function view(st) {
  const b = st.bank, k = st.kingdee, d = st.database, r = st.rules;
  const [eCls, eLabel] = envBadge(st.environment);
  return `<div class="section-gap">
    <div class="card">
      <div class="card-hd"><h3>系统对接状态</h3>
        <div class="right"><span class="badge ${eCls}">${eLabel}</span><span class="sub">只读 · 不落库 · 不显示密钥</span></div>
      </div>
      <div class="card-bd">
        ${row("银", b.label, b.badge, b.status, `采集模式：${esc(b.mode)}${b.signed ? " · 验签已启用" : " · 未配置验签"}`, [["模式", b.mode], ["服务地址", b.base_url], ["验签", b.signed ? "已启用" : "未配置"]])}
        ${row("金", k.label, k.badge, k.status, esc(k.mock_enabled ? "当前走 Mock 推送（金蝶凭据未就绪前的演示通道）" : k.configured ? "真实 OpenAPI 已配置，连通性将在实际推送时确认" : "未配置真实对接"), [["模式", k.mode], ["服务地址", k.base_url], ["凭据", k.configured ? "已配置" : "未配置"]])}
        ${row("库", "数据中台 · 中间池", d.badge, d.status, "生产独立 MySQL 8.0（隔离网段），演示为 SQLite", [["类型", d.kind === "mysql" ? "MySQL 8.0" : "SQLite"], ["连接", d.display]])}
      </div>
    </div>
    <div class="card">
      <div class="card-hd"><h3>复核规则（只读）</h3><span class="sub">决策已锁定 · 修改需走契约变更</span></div>
      <div class="card-bd">
        ${row("规", "复核阈值（R004）", "b-doing", "已锁定", "超过阈值的单笔流水自动转人工复核", [["单笔金额阈值", `¥${ui.money(r.review_amount_threshold)}`], ["自动通过", r.auto_pass_enabled ? "开启" : "关闭"]])}
      </div>
    </div>
  </div>`;
}

export async function renderSettings(el) {
  el.innerHTML = ui.loadingHtml("正在检查系统对接状态…");
  try {
    const st = await api.settingsStatus();
    el.innerHTML = view(st);
  } catch (e) {
    el.innerHTML = ui.emptyHtml("加载失败：" + esc(e.message || e));
  }
}
