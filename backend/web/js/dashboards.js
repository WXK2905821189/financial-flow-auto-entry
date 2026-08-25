// 四看板：流水总览 / 银行分布 / 异常预警 / 对账钩稽
import { api } from "./api.js";
import * as ui from "./ui.js";
import { openRecordDrawer } from "./trace.js";

const PALETTE = ["#2563eb", "#0e7490", "#6366f1", "#16a34a", "#d97706", "#dc2626", "#14b8a6", "#94a3b8"];
const RULE_META = {
  R001: ["重复流水", "高", "#dc2626"],
  R002: ["负金额/方向非法", "高", "#dc2626"],
  R003: ["缺字段", "中", "#f59e0b"],
  R004: ["超阈值", "中", "#f97316"],
  R005: ["币种异常", "中", "#f59e0b"],
};
const DASH_TITLE = { overview: "流水总览", bank: "银行分布", alert: "异常预警", recon: "对账钩稽" };

function wrapCard(title, inner, sub = "") {
  return `<div class="card">
    <div class="card-hd"><h3>${ui.esc(title)}</h3>${sub ? `<span class="sub">${sub}</span>` : ""}</div>
    <div class="card-bd">${inner}</div>
  </div>`;
}

function statCard(lbl, valHtml, deltaHtml, cls = "") {
  return `<div class="stat ${cls}"><div class="lbl">${lbl}</div><div class="val num">${valHtml}</div><div class="delta">${deltaHtml}</div>${cls ? `<div class="strip"></div>` : ""}</div>`;
}

// ---------- SVG icon 图 ----------
function lineChart(series, labels, opts = {}) {
  const w = opts.w || 620, h = opts.h || 240, p = 34;
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const n = Math.max(labels.length, 1);
  const px = (i) => p + i * (w - 2 * p) / Math.max(1, n - 1);
  const py = (v) => h - p - (v / max) * (h - 2 * p);
  let grid = "";
  for (const g of [0, 0.25, 0.5, 0.75, 1]) {
    const y = py(max * g);
    grid += `<line x1="${p}" y1="${y}" x2="${w - p}" y2="${y}" stroke="#eef2f7"/>`;
    grid += `<text x="${p - 8}" y="${y + 3}" font-size="10" fill="#94a3b8" text-anchor="end">${Math.round(max * g).toLocaleString()}</text>`;
  }
  let paths = "";
  series.forEach((s) => {
    const pts = s.values.map((v, i) => `${i ? "L" : "M"}${px(i).toFixed(1)} ${py(v).toFixed(1)}`).join(" ");
    const area = `M${px(0).toFixed(1)} ${h - p} ${pts} L${px(s.values.length - 1).toFixed(1)} ${h - p} Z`;
    paths += `<path d="${area}" fill="${s.color}18"/>`;
    paths += `<path d="${pts}" stroke="${s.color}" stroke-width="2.2" fill="none"/>`;
  });
  let lbls = "";
  if (n > 1) labels.forEach((lb, i) => { lbls += `<text x="${px(i)}" y="${h - 10}" font-size="10" fill="#94a3b8" text-anchor="middle">${ui.esc(lb)}</text>`; });
  return `<svg viewBox="0 0 ${w} ${h}" class="chart">${grid}${paths}${lbls}</svg>`;
}

function donut(items) {
  const size = 200, stroke = 30, r = (size - stroke) / 2, c = size / 2;
  const total = items.reduce((a, b) => a + b.value, 0) || 1;
  const circ = 2 * Math.PI * r;
  let off = 0, segs = "";
  items.forEach((it) => {
    const len = it.value / total * circ;
    segs += `<circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${it.color}" stroke-width="${stroke}" stroke-dasharray="${len} ${circ - len}" stroke-dashoffset="${-off}" transform="rotate(-90 ${c} ${c})"><title>${ui.esc(it.name)}: ${ui.fmtAmount(it.value)}</title></circle>`;
    off += len;
  });
  const center = total >= 10000 ? (total / 10000).toFixed(1) + "万" : ui.fmtInt(total);
  const legend = items.map((it) => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid var(--line-2)">
      <span class="legend"><i style="background:${it.color}"></i>${ui.esc(it.name)}</span>
      <b class="mono">${(it.value / total * 100).toFixed(1)}%</b>
    </div>`).join("");
  return `<div style="display:flex;align-items:center;gap:26px;flex-wrap:wrap">
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${segs}
      <text x="${c}" y="${c - 4}" text-anchor="middle" font-size="20" font-weight="700" fill="#0f172a">${center}</text>
      <text x="${c}" y="${c + 16}" text-anchor="middle" font-size="11" fill="#64748b">总流水(元)</text>
    </svg>
    <div style="flex:1;min-width:160px">${legend}</div>
  </div>`;
}

function hBars(items, opts = {}) {
  const max = opts.max || Math.max(1, ...items.map((i) => i.value));
  return items.map((it) => `
    <div class="bar-m">
      <div class="nm">${it.label}</div>
      <div class="tr"><i style="width:${Math.max(2, (it.value / max * 100).toFixed(1))}%;background:${it.color}"></i></div>
      <div class="vv mono">${it.valueText || ui.fmtAmount(it.value)}</div>
    </div>`).join("");
}

// ---------- 壳：tab + 面板 ----------
export async function renderDash(root, tab = "overview") {
  const tabs = ["overview", "bank", "alert", "recon"];
  root.innerHTML = `
    <div class="tabs" id="dash-tabs">${tabs.map((t) => `<button class="${t === tab ? "active" : ""}" data-tab="${t}">${DASH_TITLE[t]}</button>`).join("")}</div>
    <div class="dash on" id="dash-panel"></div>`;
  const panel = () => root.querySelector("#dash-panel");

  async function load(t) {
    root.querySelectorAll("#dash-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
    document.getElementById("crumb").textContent = "可视化看板 · " + DASH_TITLE[t];
    const el = panel();
    el.innerHTML = ui.loadingHtml();
    const renderers = { overview: renderOverview, bank: renderBank, alert: renderAlert, recon: renderRecon };
    await renderers[t](el);
  }

  root.querySelectorAll("#dash-tabs button").forEach((b) => {
    b.addEventListener("click", () => load(b.dataset.tab));
  });

  await load(tab in { overview: 1, bank: 1, alert: 1, recon: 1 } ? tab : "overview");
}

// ---------- 1. 流水总览 ----------
async function renderOverview(root) {
  const rows = await api.overview();
  if (!rows.length) { root.innerHTML = ui.emptyHtml("暂无流水数据，可先在复核工作台 Mock 采集"); return; }

  let credit = 0, debit = 0, totalCnt = 0;
  const dateMap = new Map();
  const acctMap = new Map();
  rows.forEach((r) => {
    const amt = Number(r.amount), cnt = r.cnt;
    if (r.dc_flag === "C") credit += amt; else debit += amt;
    totalCnt += cnt;
    const d = dateMap.get(r.txn_date) || { c: 0, d: 0 };
    if (r.dc_flag === "C") d.c += amt; else d.d += amt;
    dateMap.set(r.txn_date, d);
    const a = acctMap.get(r.account_name) || { bank: r.bank_name, c: 0, d: 0, cnt: 0 };
    if (r.dc_flag === "C") a.c += amt; else a.d += amt;
    a.cnt += cnt;
    acctMap.set(r.account_name, a);
  });
  const net = credit - debit;

  const kpis = `
    ${statCard("本期收入", `<span style="color:var(--in)">${ui.fmtAmount(credit)}</span>`, "本期累计收入", "gain")}
    ${statCard("本期支出", `<span style="color:var(--out)">${ui.fmtAmount(debit)}</span>`, "本期累计支出", "pay")}
    ${statCard("净流入", `<span style="color:${net >= 0 ? "var(--in)" : "var(--out)"}">${(net >= 0 ? "+" : "−") + ui.fmtAmount(Math.abs(net))}</span>`, "净额 = 收 − 支", "net")}
    ${statCard("流水总笔数", `${ui.fmtInt(totalCnt)}<small> 笔</small>`, "覆盖 ≥80% 流水", "cnt")}`;

  const dateKeys = Array.from(dateMap.keys()).sort();
  const labels = dateKeys.map((d) => d.slice(5));
  const series = [
    { name: "收入", color: "#059669", values: dateKeys.map((d) => dateMap.get(d).c) },
    { name: "支出", color: "#dc2626", values: dateKeys.map((d) => dateMap.get(d).d) },
  ];

  const acctItems = Array.from(acctMap.entries()).map(([label, v], i) => ({ label, value: v.c + v.d, color: PALETTE[i % PALETTE.length] }));
  const acctMax = Math.max(1, ...acctItems.map((i) => i.value));

  const acctRows = Array.from(acctMap.entries()).sort((a, b) => (b[1].c + b[1].d) - (a[1].c + a[1].d)).map(([label, v]) => `
    <tr>
      <td>${ui.esc(label)}</td><td>${ui.esc(v.bank)}</td>
      <td class="amt in">${ui.money(v.c)}</td><td class="amt out">${ui.money(v.d)}</td>
      <td class="num">${ui.fmtInt(v.cnt)}</td>
      <td class="amt ${v.c - v.d >= 0 ? "in" : "out"}">${v.c - v.d >= 0 ? "+" : "−"}${ui.money(Math.abs(v.c - v.d))}</td>
    </tr>`).join("");

  root.innerHTML = `
    <div class="section-gap">
      <div class="stat-row">${kpis}</div>
      <div class="grid-2-1">
        ${wrapCard("收支趋势", lineChart(series, labels) + `<div class="legend" style="margin-top:10px"><span><i style="background:#059669"></i>收入（收）</span><span><i style="background:#dc2626"></i>支出（付）</span></div>`, "按日聚合")}
        ${wrapCard("账户收支构成", hBars(acctItems, { max: acctMax }), "金额 Top 5")}
      </div>
      ${wrapCard("账户流水明细", `
        <div class="tbl-wrap"><table class="tbl">
          <thead><tr><th>账户</th><th>银行</th><th>收入(元)</th><th>支出(元)</th><th>笔数</th><th>净额(元)</th></tr></thead>
          <tbody>${acctRows}</tbody>
        </table></div>`, "本期聚合")}
    </div>`;
}

// ---------- 2. 银行分布 ----------
async function renderBank(root) {
  const rows = await api.bankDistribution();
  if (!rows.length) { root.innerHTML = ui.emptyHtml("暂无流水数据"); return; }

  const byBank = new Map();
  rows.forEach((r) => {
    const amt = Number(r.credit_amount) + Number(r.debit_amount);
    byBank.set(r.bank_name, (byBank.get(r.bank_name) || 0) + amt);
  });
  const bankItems = Array.from(byBank.entries()).map(([name, value], i) => ({ name, value, color: PALETTE[i % PALETTE.length] }));
  const total = bankItems.reduce((a, b) => a + b.value, 0) || 1;

  const acctItems = rows.map((r, i) => ({ label: `${r.bank_name} · ${r.account_name}`, value: Number(r.credit_amount) + Number(r.debit_amount), color: PALETTE[i % PALETTE.length] }));
  const acctMax = Math.max(1, ...acctItems.map((i) => i.value));

  const detailRows = rows.map((r) => {
    const amount = Number(r.credit_amount) + Number(r.debit_amount);
    return `<tr>
      <td>${ui.esc(r.bank_name)}</td><td>${ui.esc(r.account_name)}</td>
      <td class="num">${ui.money(amount)}</td>
      <td class="num">${(amount / total * 100).toFixed(1)}%</td>
      <td class="num">${ui.fmtInt(r.cnt)}</td>
    </tr>`;
  }).join("");

  root.innerHTML = `
    <div class="section-gap">
      <div class="grid-2-1">
        ${wrapCard("银行流水占比", donut(bankItems), "按金额")}
        ${wrapCard("账户占比", hBars(acctItems, { max: acctMax }), "按金额 · 收付加权")}
      </div>
      ${wrapCard("银行 / 账户分布明细", `
        <div class="tbl-wrap"><table class="tbl">
          <thead><tr><th>银行</th><th>账户</th><th>流水金额(元)</th><th>占比</th><th>笔数</th></tr></thead>
          <tbody>${detailRows}
            <tr style="background:#f8fafc"><td colspan="2"><b>合计</b></td><td class="num"><b>${ui.money(total)}</b></td><td><b>100%</b></td><td class="num"><b>${ui.fmtInt(rows.reduce((s, r) => s + r.cnt, 0))}</b></td></tr>
          </tbody>
        </table></div>`)}
    </div>`;
}

// ---------- 3. 异常预警 ----------
async function renderAlert(root) {
  const rows = await api.exceptions();
  if (!rows.length) { root.innerHTML = ui.emptyHtml("暂无异常/预警流水"); return; }

  const failCount = rows.filter((r) => r.rule_result === "FAIL").length;
  const warnCount = rows.length - failCount;
  const ruleSet = new Set(rows.map((r) => r.rule_code));

  const byRule = new Map();
  rows.forEach((r) => byRule.set(r.rule_code, (byRule.get(r.rule_code) || 0) + 1));
  const bars = Array.from(byRule.entries()).map(([code, value]) => {
    const [label, sev, color] = RULE_META[code] || [code, ruleSev(code, value), "#94a3b8"];
    return { label: `${label}<span class="tag-mini">${sev}</span>`, value, color, valueText: `${value} 笔` };
  });
  const barMax = Math.max(1, ...bars.map((b) => b.value));

  const listRows = rows.map((r) => {
    const [label, sev] = RULE_META[r.rule_code] || [r.rule_code, ruleSev(r.rule_code)];
    const sevCls = sev === "高" ? "b-err" : "b-low";
    const amt = r.dc_flag === "C" ? `<span class="amt in">+¥ ${ui.money(r.amount)}</span>` : `<span class="amt out">−¥ ${ui.money(r.amount)}</span>`;
    return `<tr data-id="${r.record_id}">
      <td><span class="badge ${sevCls}">${sev}</span></td>
      <td>${ui.esc(label)}</td>
      <td class="mono">${ui.esc(r.txn_no)}</td>
      <td class="num">${amt}</td>
      <td>${ui.esc(r.counterparty_name || "—")}</td>
      <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${ui.esc(r.error_detail || "")}">${ui.esc(r.error_detail || "—")}</td>
      <td><button class="link-btn row-open" data-id="${r.record_id}">去复核</button></td>
    </tr>`;
  }).join("");

  const b = document.getElementById("nav-badge-alert");
  if (b) b.textContent = rows.length > 0 ? ui.fmtInt(rows.length) : "";

  root.innerHTML = `
    <div class="section-gap">
      <div class="stat-row">
        ${statCard("异常合计", `<span style="color:var(--danger)">${ui.fmtInt(rows.length)}</span>`, "需人工处理")}
        ${statCard("校验失败(FAIL)", `<span style="color:var(--danger)">${ui.fmtInt(failCount)}</span>`, "重复/负额/缺字段/币种")}
        ${statCard("需人工复核(WARN)", `<span style="color:var(--warn)">${ui.fmtInt(warnCount)}</span>`, "超阈值转人工")}
        ${statCard("覆盖规则类型", `<span style="color:var(--info)">${ui.fmtInt(ruleSet.size)}</span>`, "R002–R005")}
      </div>
      <div class="grid-2">
        ${wrapCard("异常类型分布", hBars(bars, { max: barMax }), "采集校验结果 · 按严重度")}
        ${wrapCard("规则说明", `<div class="muted" style="line-height:2;font-size:13px">
          <div>· <b>重复流水 / 负金额 / 缺字段 / 币种非法</b>：自动驳回待处理（FAIL）。</div>
          <div>· <b>单笔金额超阈值</b>：转人工复核（WARN）。</div>
          <div>· 点击清单任意行可进入复核详情。</div>
        </div>`)}
      </div>
      ${wrapCard("异常流水清单", `
        <div class="tbl-wrap"><table class="tbl">
          <thead><tr><th>严重度</th><th>类型</th><th>流水号</th><th>金额</th><th>对方户名</th><th>问题描述</th><th style="width:88px">操作</th></tr></thead>
          <tbody>${listRows}</tbody>
        </table></div>`, "点击「去复核」跳转复核详情")}
    </div>`;

  root.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest(".row-open")) return;
      openRecordDrawer(Number(tr.dataset.id));
    });
  });
  root.querySelectorAll(".row-open").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openRecordDrawer(Number(btn.dataset.id));
    });
  });
}

function ruleSev(code, result) {
  if (result === "WARN") return "中";
  if (result === "FAIL") return "高";
  return "中";
}

// ---------- 4. 对账钩稽 ----------
async function renderRecon(root) {
  const rows = await api.recon();
  const diffRows = rows.filter((r) => r.count_diff !== 0);
  const diffAmount = rows.reduce((s, r) => s + (Number(r.expected_amount) - Number(r.loaded_amount)), 0);

  const tableRows = rows.map((r) => {
    const hasDiff = r.count_diff !== 0;
    const aDiff = Number(r.expected_amount) - Number(r.loaded_amount);
    return `<tr>
      <td class="mono">${ui.esc(r.batch_no)}</td>
      <td>${ui.esc(r.source_type)}</td>
      <td class="num">${ui.fmtInt(r.loaded_count)}</td>
      <td class="num">${ui.money(r.loaded_amount)}</td>
      <td class="num">${ui.fmtInt(r.expected_count)}</td>
      <td class="num">${ui.money(r.expected_amount)}</td>
      <td class="num" style="color:${hasDiff ? "var(--danger)" : "inherit"}">${hasDiff ? "−" + ui.fmtInt(Math.abs(r.count_diff)) : "0"}</td>
      <td class="num" style="color:${aDiff !== 0 ? "var(--danger)" : "inherit"}">${aDiff !== 0 ? (aDiff < 0 ? "+" : "−") + ui.money(Math.abs(aDiff)) : "¥0"}</td>
      <td>${hasDiff ? '<span class="badge b-err">差异</span>' : '<span class="badge b-pass">一致</span>'}</td>
      <td>${!hasDiff && r.loaded_count > 0 ? `<button class="link-btn" data-push="${r.batch_id}">推送批次</button>` : ""}</td>
    </tr>`;
  }).join("");

  const diffDetail = diffRows.length ? diffRows.map((r) => `
    <div class="trace-item"><span class="t">批次</span><span class="c mono">${ui.esc(r.batch_no)}（${ui.esc(r.source_type)}）</span></div>
    <div class="trace-item"><span class="t">笔数差</span><span class="c" style="color:var(--danger)">−${ui.fmtInt(Math.abs(r.count_diff))} 笔（导入 ${ui.fmtInt(r.loaded_count)} / 预期 ${ui.fmtInt(r.expected_count)}）</span></div>
    <div class="trace-item"><span class="t">金额差</span><span class="c" style="color:var(--danger)">${Number(r.expected_amount) - Number(r.loaded_amount) < 0 ? "+" : "−"}${ui.money(Math.abs(Number(r.expected_amount) - Number(r.loaded_amount)))}</span></div>
    <div class="trace-item"><span class="t">建议</span><span class="c">核对源文件 → 重新导入 → 再次勾稽</span></div>`).join('<div style="height:6px"></div>') : `<div class="muted" style="font-size:13px">当前无差异批次</div>`;

  root.innerHTML = `
    <div class="section-gap">
      <div class="stat-row">
        ${statCard("批次总数", `<span style="color:var(--brand)">${ui.fmtInt(rows.length)}</span>`, "近 7 天")}
        ${statCard("对账一致", `<span style="color:var(--ok)">${ui.fmtInt(rows.length - diffRows.length)}</span>`, "笔数 + 金额全平")}
        ${statCard("存在差异", `<span style="color:var(--warn)">${ui.fmtInt(diffRows.length)}</span>`, "需核对")}
        ${statCard("差异金额", `<span style="color:var(--danger)">${diffAmount < 0 ? "+" : "−"}${ui.money(Math.abs(diffAmount))}</span>`, "差额待追平")}
      </div>
      ${wrapCard("批次对账状态", `
        <div class="tbl-wrap"><table class="tbl">
          <thead><tr><th>批次号</th><th>来源</th><th>导入笔数</th><th>导入金额(元)</th><th>预期笔数</th><th>预期金额(元)</th><th>笔差</th><th>额差</th><th>状态</th><th></th></tr></thead>
          <tbody>${tableRows || `<tr><td colspan="10"><div class="muted" style="padding:20px">暂无批次</div></td></tr>`}</tbody>
        </table></div>
        <div class="small-print">※ 勾稽规则：导入笔数 / 金额须与「预期值」完全一致；不一致批次会被置顶并阻断批量推送。</div>`, "导入 vs 预期 · 笔数/金额勾稽")}
      <div class="grid-2">
        ${wrapCard("差异批次 · 明细跟踪", diffDetail)}
        ${wrapCard("凭证 ↔ 流水 双向钩稽", `
          <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end">
            <div style="flex:1;min-width:200px"><span class="hint">按金蝶凭证号回溯（账 → 单）</span><input class="input" id="recon-voucher" placeholder="如 KV2026-..." style="width:100%;margin-top:4px"/></div>
            <button class="btn btn-pri btn-sm" id="recon-byvoucher">凭证回溯</button>
            <div style="flex:1;min-width:140px"><span class="hint">按记录号回溯（单 → 账）</span><input class="input" id="recon-record" placeholder="record_id" style="width:100%;margin-top:4px"/></div>
            <button class="btn btn-ghost btn-sm" id="recon-byrecord">流水回溯</button>
          </div>
          <div style="margin-top:14px">
            <div class="trace-item"><span class="t">正向追溯</span><span class="c" style="color:var(--ok)">凭证 → 流水 ✓ 可回查</span></div>
            <div class="trace-item"><span class="t">反向追溯</span><span class="c" style="color:var(--ok)">流水 → 凭证 ✓ 可回查</span></div>
          </div>`, "溯源一致性检查")}
      </div>
    </div>`;

  root.querySelectorAll("[data-push]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const batchId = Number(btn.dataset.push);
      ui.confirmModal({
        title: "推送整批到金蝶",
        danger: true,
        okText: "确认推送",
        html: `<p>将批次 <b>#${batchId}</b> 中所有「已通过复核」的流水推送至金蝶并自动制证。</p>
               <p class="muted" style="font-size:12px;margin-top:6px">不可逆操作，请二次确认。</p>`,
        onOk: async () => {
          const r = await api.pushBatch(batchId);
          ui.toast(`已推送 ${r.pushed} 笔`, "success");
          renderRecon(root);
        },
      });
    });
  });

  document.getElementById("recon-byvoucher").addEventListener("click", async () => {
    const v = document.getElementById("recon-voucher").value.trim();
    if (!v) { ui.toast("请输入凭证号", "error"); return; }
    try {
      const tr = await api.traceByVoucher(v);
      openRecordDrawer(tr.flow.record_id);
    } catch (e) { ui.toast(e.message, "error"); }
  });
  document.getElementById("recon-byrecord").addEventListener("click", () => {
    const v = document.getElementById("recon-record").value.trim();
    if (!v) { ui.toast("请输入记录号", "error"); return; }
    openRecordDrawer(Number(v));
  });
}
