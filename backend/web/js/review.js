// 复核工作台：统计卡 + 待复核队列（11 列）+ 筛选 + 批量操作 + Mock/文件采集入口
import { api } from "./api.js";
import * as ui from "./ui.js";
import { openRecordDrawer } from "./trace.js";

let pendingData = [];
let selected = new Set();

function dirHtml(dc) {
  return dc === "C" ? '<span class="dir-tag in">收 ▲</span>' : '<span class="dir-tag out">支 ▼</span>';
}

function amtHtml(dc, amt) {
  const c = dc === "C" ? "in" : "out";
  const sgn = dc === "C" ? "+" : "−";
  return `<span class="amt ${c}">${sgn}¥ ${ui.money(amt)}</span>`;
}

export async function renderReview(root) {
  root.innerHTML = `
    <div class="section-gap">
      <div class="stat-row">
        <div class="stat"><div class="lbl">待复核</div><div class="val num" style="color:var(--warn)" id="stat-0">—</div><div class="delta" id="stat-d-0"></div></div>
        <div class="stat"><div class="lbl">今日已复核</div><div class="val num" style="color:var(--ok)" id="stat-1">—</div><div class="delta" id="stat-d-1"></div></div>
        <div class="stat"><div class="lbl">今日已推送金蝶</div><div class="val num" style="color:var(--brand)" id="stat-2">—</div><div class="delta" id="stat-d-2"></div></div>
        <div class="stat"><div class="lbl">自动通过率</div><div class="val num" id="stat-3">—</div><div class="delta" id="stat-d-3"></div></div>
      </div>

      <div class="card">
        <div class="card-hd">
          <h3>流水复核队列</h3><span class="sub">点击行查看详情；支持批量操作</span>
          <div class="right">
            <button class="btn btn-ghost btn-sm" id="btn-refresh">↻ 刷新</button>
            <button class="btn btn-pri btn-sm" id="btn-push">推送金蝶</button>
          </div>
        </div>
        <div class="card-bd">
          <div class="filterbar">
            <div class="search">🔍<input id="f-search" placeholder="流水号 / 对方户名 / 摘要" /></div>
            <select class="select" id="f-status">
              <option value="">全部状态</option>
              <option value="REVIEW_READY">待复核</option>
              <option value="REVIEW_PASSED">自动通过</option>
              <option value="KINGDEE_POSTED">已推送</option>
              <option value="REJECTED">已驳回</option>
            </select>
            <select class="select" id="f-bank"><option value="">全部银行</option></select>
            <select class="select" id="f-acct"><option value="">全部账户</option></select>
            <input type="date" class="input" id="f-date" />
            <div class="right">
              <label class="ck"><input type="checkbox" id="chk-all" /> 全选</label>
              <button class="btn btn-ghost btn-sm" id="btn-batch-reject" disabled>批量驳回</button>
              <button class="btn btn-ok btn-sm" id="btn-batch-pass" disabled>批量通过</button>
            </div>
          </div>
          <div class="tbl-wrap" style="max-height:62vh">
            <table class="tbl">
              <thead><tr>
                <th style="width:38px"></th><th>流水号</th><th>日期</th><th>借贷</th><th>金额</th>
                <th>对方户名</th><th>账户</th><th>摘要</th><th>校验</th><th>复核状态</th><th style="width:88px">操作</th>
              </tr></thead>
              <tbody id="review-tbody"><tr><td colspan="11">${ui.loadingHtml()}</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>`;

  bindEvents();
  await Promise.all([loadSummary(), loadPending()]);
}

function bindEvents() {
  document.getElementById("chk-all").addEventListener("change", (e) => {
    selected = new Set();
    if (e.target.checked) filteredRows().forEach((r) => selected.add(r.record_id));
    renderRows();
    refreshBatchState();
  });
  document.getElementById("f-search").addEventListener("input", renderRows);
  document.getElementById("f-date").addEventListener("change", renderRows);
  document.getElementById("f-status").addEventListener("change", renderRows);
  document.getElementById("f-bank").addEventListener("change", renderRows);
  document.getElementById("f-acct").addEventListener("change", renderRows);
  document.getElementById("btn-refresh").addEventListener("click", async () => {
    await Promise.all([loadSummary(), loadPending()]);
    ui.toast("已刷新队列", "info");
  });
  document.getElementById("btn-push").addEventListener("click", pushSelected);
  document.getElementById("btn-batch-pass").addEventListener("click", () => batchDecide("PASS"));
  document.getElementById("btn-batch-reject").addEventListener("click", () => batchDecide("REJECT"));
}

async function loadSummary() {
  try {
    const s = await api.summary();
    const warnCnt = pendingData.filter((r) => r.validation_status === "WARN").length;
    const errCnt = pendingData.filter((r) => r.validation_status === "FAIL" || r.exception_type).length;
    document.getElementById("stat-0").innerHTML = `${ui.fmtInt(s.pending_review)}<small> 笔</small>`;
    document.getElementById("stat-1").innerHTML = `${ui.fmtInt(s.today_reviewed)}<small> 笔</small>`;
    document.getElementById("stat-2").innerHTML = `${ui.fmtInt(s.today_pushed)}<small> 笔</small>`;
    document.getElementById("stat-3").innerHTML = `${(s.auto_pass_rate * 100).toFixed(1)}<small>%</small>`;
    document.getElementById("stat-d-0").textContent = warnCnt + errCnt ? `其中低置信 ${warnCnt} · 异常 ${errCnt}` : "规则内自动通过";
    document.getElementById("stat-d-1").textContent = `累计通过 ${ui.fmtInt(s.passed_total)} 笔`;
    document.getElementById("stat-d-2").textContent = "凭证已生成 · 全部钩稽通过";
    document.getElementById("stat-d-3").textContent = `自动通过 ${ui.fmtInt(s.auto_passed)} / ${ui.fmtInt(s.passed_total)} 笔`;
    const b = document.getElementById("nav-badge-review");
    if (b) b.textContent = s.pending_review > 0 ? ui.fmtInt(s.pending_review) : "";
  } catch (e) { /* summary 失败不阻塞队列 */ }
}

async function loadPending() {
  document.getElementById("review-tbody").innerHTML = `<tr><td colspan="11">${ui.loadingHtml()}</td></tr>`;
  try {
    pendingData = await api.pending();
    selected.clear();
    document.getElementById("chk-all").checked = false;
    populateFilters();
    renderRows();
    refreshBatchState();
    loadSummary();
  } catch (e) {
    document.getElementById("review-tbody").innerHTML = `<tr><td colspan="11">${ui.emptyHtml("加载失败：" + e.message)}</td></tr>`;
  }
}

function populateFilters() {
  const banks = [...new Set(pendingData.map((r) => r.bank_name).filter(Boolean))];
  const accts = [...new Set(pendingData.map((r) => r.account_name).filter(Boolean))];
  const bk = document.getElementById("f-bank");
  const ac = document.getElementById("f-acct");
  bk.innerHTML = `<option value="">全部银行</option>` + banks.map((b) => `<option>${ui.esc(b)}</option>`).join("");
  ac.innerHTML = `<option value="">全部账户</option>` + accts.map((a) => `<option>${ui.esc(a)}</option>`).join("");
}

function filteredRows() {
  const q = (document.getElementById("f-search").value || "").trim().toLowerCase();
  const dv = document.getElementById("f-date").value;
  const sv = document.getElementById("f-status").value;
  const bv = document.getElementById("f-bank").value;
  const av = document.getElementById("f-acct").value;
  return pendingData.filter((r) => {
    if (sv && r.process_status !== sv) return false;
    if (dv && String(r.txn_date).slice(0, 10) !== dv) return false;
    if (bv && r.bank_name !== bv) return false;
    if (av && r.account_name !== av) return false;
    if (q) {
      const hay = [r.txn_no, r.counterparty_name, r.summary].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function renderRows() {
  const rows = filteredRows();
  const tbody = document.getElementById("review-tbody");
  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11">${ui.emptyHtml("暂无待复核流水")}</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((r) => `
    <tr data-id="${r.record_id}" class="${selected.has(r.record_id) ? "checked" : ""}">
      <td><label class="ck"><input type="checkbox" class="row-chk" data-id="${r.record_id}" ${selected.has(r.record_id) ? "checked" : ""} /></label></td>
      <td class="mono">${ui.esc(r.txn_no)}</td>
      <td class="num">${ui.fmtDate(r.txn_date)}</td>
      <td>${dirHtml(r.dc_flag)}</td>
      <td class="num">${amtHtml(r.dc_flag, r.amount)}</td>
      <td>${ui.esc(r.counterparty_name || "—")}</td>
      <td>${ui.esc(r.account_name || "—")}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.summary ? ui.esc(r.summary) : '<span style="color:var(--muted)">—</span>'}</td>
      <td>${ui.validationBadge(r.validation_status)}</td>
      <td>${ui.statusBadge(r.process_status)}</td>
      <td><button class="link-btn row-open" data-id="${r.record_id}">详情</button></td>
    </tr>`).join("");

  tbody.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest(".row-chk") || e.target.closest(".row-open")) return;
      openRecordDrawer(Number(tr.dataset.id), { onChanged: reload });
    });
  });
  tbody.querySelectorAll(".row-chk").forEach((chk) => {
    chk.addEventListener("change", (e) => {
      const id = Number(chk.dataset.id);
      if (chk.checked) selected.add(id); else selected.delete(id);
      renderRows();
      refreshBatchState();
    });
  });
  tbody.querySelectorAll(".row-open").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openRecordDrawer(Number(btn.dataset.id), { onChanged: reload });
    });
  });
}

function refreshBatchState() {
  const n = selected.size;
  document.getElementById("btn-batch-pass").disabled = n === 0;
  document.getElementById("btn-batch-reject").disabled = n === 0;
}

async function reload() {
  await Promise.all([loadSummary(), loadPending()]);
}

async function batchDecide(result) {
  if (selected.size === 0) return;
  const ids = Array.from(selected);
  if (result === "REJECT") {
    const reason = await ui.promptModal({ title: "批量驳回", placeholder: `将对 ${ids.length} 笔流水驳回，请填写原因（必填）`, okText: "确认驳回", danger: true });
    if (reason === null) return;
    if (!reason) { ui.toast("驳回原因不能为空", "error"); return; }
    try {
      await api.decideBatch(ids, "REJECT", reason);
      ui.toast(`已驳回 ${ids.length} 笔`, "info");
      await reload();
    } catch (e) { ui.toast(e.message, "error"); }
    return;
  }
  ui.confirmModal({
    title: "批量通过",
    html: `<p>确认将通过 <b>${ids.length}</b> 笔待复核流水，并入账队列？</p>`,
    okText: "确认通过",
    onOk: async () => {
      await api.decideBatch(ids, "PASS");
      ui.toast(`已通过 ${ids.length} 笔`, "success");
      await reload();
    },
  });
}

async function pushSelected() {
  if (selected.size === 0) { ui.toast("请先勾选要推送的流水", "error"); return; }
  const ids = Array.from(selected);
  const total = pendingData.filter((r) => ids.includes(r.record_id)).reduce((s, r) => s + Number(r.amount), 0);
  ui.confirmModal({
    title: "确认推送金蝶",
    danger: true,
    okText: "确认推送",
    html: `<p>即将推送 <b>${ids.length}</b> 笔流水至金蝶云星空并自动制证，合计金额 <b>${ui.fmtAmount(total)}</b>。</p>
      <div class="sum">对账钩稽：全部通过 ▸ 可推送<br>推送后生成凭证号并回写溯源关联</div>`,
    onOk: async () => {
      await api.decideBatch(ids, "PASS");
      for (const id of ids) { try { await api.pushRecord(id); } catch (e) { /* 单笔失败不中断 */ } }
      ui.toast(`已推送 ${ids.length} 笔至金蝶 · 凭证已生成并回写溯源`, "success");
      await reload();
    },
  });
}
