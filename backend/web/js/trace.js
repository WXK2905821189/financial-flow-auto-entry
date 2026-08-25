// 共享：流水详情抽屉（契约字段 / 校验 / 溯源 / 留痕）+ 状态机操作按钮
import { api } from "./api.js";
import * as ui from "./ui.js";

const RULE_LABEL = {
  R001: "重复流水", R002: "负金额/方向非法", R003: "缺字段",
  R004: "超阈值", R005: "币种异常",
};

function field(k, v) {
  return `<div class="field"><span class="k">${ui.esc(k)}</span><span class="v">${v}</span></div>`;
}

function amtSpan(dc, amount) {
  const c = dc === "C" ? "in" : "out";
  const sgn = dc === "C" ? "+" : "−";
  return `<span class="amt ${c}">${sgn}¥ ${ui.money(amount)}</span>`;
}

function renderTrace(tr) {
  const f = tr.flow || {};
  const bank = tr.bank || {};
  const account = tr.account || {};
  const batch = tr.batch || {};

  const dir = f.dc_flag === "C" ? "收（贷方）" : f.dc_flag === "D" ? "付（借方）" : "—";
  const fieldsHtml = [
    field("唯一流水号", `<span class="mono">${ui.esc(f.txn_no || "—")}</span>`),
    field("交易日期", ui.fmtDate(f.txn_date)),
    field("交易时间", ui.esc(f.txn_time || "—")),
    field("借贷方向", dir),
    field("金额", amtSpan(f.dc_flag, f.amount)),
    field("币种", ui.esc(f.currency || "CNY")),
    field("对方户名", ui.esc(f.counterparty_name || "—")),
    field("对方账号", ui.esc(f.counterparty_account || "—")),
    field("本方账户", ui.esc(account.account_name ? `${account.account_name}（${account.account_no}）` : (account.account_no || "—"))),
    field("摘要", f.summary ? ui.esc(f.summary) : '<span style="color:var(--muted)">缺失</span>'),
  ].join("");

  const validations = tr.validations || [];
  let vHtml;
  if (validations.length === 0) {
    vHtml = `<div class="muted" style="font-size:13px">无校验记录</div>`;
  } else {
    vHtml = validations.map((v) => {
      const map = { PASS: ["通过", "var(--ok)"], WARN: ["告警", "var(--warn)"], FAIL: ["异常", "var(--danger)"] };
      const [label, color] = map[v.rule_result] || ["—", "var(--muted)"];
      const rule = RULE_LABEL[v.rule_code] ? `${v.rule_code} · ${RULE_LABEL[v.rule_code]}` : v.rule_code;
      return `<div class="trace-item">
        <span class="t">${ui.esc(rule)}</span>
        <span class="c"><span style="color:${color};font-weight:600">${label}</span>${v.error_detail ? `<div class="muted" style="margin-top:3px;font-size:12px">${ui.esc(v.error_detail)}</div>` : ""}</span>
      </div>`;
    }).join("");
  }

  const traceHtml = [
    ["来源银行", bank.bank_name ? `${ui.esc(bank.bank_name)}（${ui.esc(bank.bank_code)}）` : "—"],
    ["来源账户", account.account_no ? `${ui.esc(account.account_name || "")} ${ui.esc(account.account_no)}` : "—"],
    ["采集批次", `${ui.esc(batch.batch_no || "—")} <span class="tag-mini">${ui.esc(batch.source_type || "")}</span>`],
    ["记录 ID", `<span class="mono">${ui.esc(String(f.record_id ?? "—"))}</span>`],
    ["去重指纹", `<span class="mono" style="font-size:12px;word-break:break-all">${ui.esc(f.dedup_key || "—")}</span>`],
  ].map(([k, v]) => `<div class="trace-item"><span class="t">${k}</span><span class="c">${v}</span></div>`).join("");

  // 操作留痕时间线
  const events = [];
  events.push({ cls: "green", who: "系统", act: `采集落库 · 校验预筛`, tm: batch.imported_at ? ui.fmtDateTime(batch.imported_at) : "—", desc: batch.source_type ? `源：${batch.source_type} · 批次 ${batch.batch_no || "—"}` : "" });
  (tr.reviews || []).forEach((rv) => {
    const cls = rv.review_result === "PASS" ? "green" : rv.review_result === "ADJUST" ? "" : "reject";
    events.push({ cls, who: rv.reviewer || "复核员", act: `人工复核 · ${rv.review_result}`, tm: ui.fmtDateTime(rv.review_time), desc: [rv.matched_subject, rv.comment].filter(Boolean).join(" · ") });
  });
  (tr.pushes || []).forEach((p) => {
    events.push({ cls: p.push_status === "SUCCESS" ? "green" : "", who: p.pushed_by || "系统", act: `推送金蝶 · ${p.push_status}`, tm: ui.fmtDateTime(p.pushed_at), desc: p.voucher_no ? `凭证号 ${p.voucher_no}` : (p.error_msg || "") });
  });
  events.sort((a, b) => (a.tm || "").localeCompare(b.tm || ""));
  const audit = events.map((e) => `
    <div class="it ${e.cls}">
      <div class="who">${ui.esc(e.who)}</div>
      <div class="act">${ui.esc(e.act)}</div>
      <div class="tm">${ui.esc(e.tm)}${e.desc ? " · " + ui.esc(e.desc) : ""}</div>
    </div>`).join("");

  return { fieldsHtml, vHtml, traceHtml, audit, flow: f };
}

export function openRecordDrawer(record_id, { onChanged } = {}) {
  ui.openDrawer({ title: "流水详情", body: ui.loadingHtml("加载详情…") });
  api.traceByRecord(record_id).then((tr) => {
    const f = tr.flow || {};
    const { fieldsHtml, vHtml, traceHtml, audit } = renderTrace(tr);

    document.getElementById("dw-title").textContent = `流水详情 · #${record_id}`;
    document.getElementById("dw-badge").innerHTML = ui.statusBadge(f.process_status);
    document.getElementById("dw-body").innerHTML = `
      <div class="section-title">契约字段 · 统一流水契约</div>
      <div class="field-grid">${fieldsHtml}</div>

      <div class="section-title">校验结果</div>
      ${vHtml}

      <div class="section-title">数据溯源</div>
      <div class="trace-list">${traceHtml}</div>

      <div class="section-title">操作留痕 · 审计日志</div>
      <div class="audit">${audit || '<div class="muted" style="font-size:13px">无记录</div>'}</div>`;

    bindFooter(f, record_id, onChanged);
  }).catch((e) => {
    document.getElementById("dw-body").innerHTML = ui.emptyHtml("加载失败：" + e.message);
    document.getElementById("dw-foot").innerHTML = `<button class="btn btn-ghost" id="dw-close-btn">关闭</button>`;
    document.getElementById("dw-close-btn").addEventListener("click", ui.closeDrawer);
  });
}

function bindFooter(f, record_id, onChanged) {
  const s = f.process_status;
  const foot = document.getElementById("dw-foot");
  const closeBtn = `<button class="btn btn-ghost" data-act="close">取消</button>`;

  const doPass = (andPush) => async () => {
    try {
      if (s === "REVIEW_READY") await api.decide(record_id, "PASS");
      ui.toast("已通过复核", "success");
      if (andPush) await doPushOnce(record_id, onChanged);
      else { ui.closeDrawer(); onChanged && onChanged(); }
    } catch (e) { ui.toast(e.message, "error"); }
  };
  const doReject = async () => {
    const reason = await ui.promptModal({ title: "驳回流水", placeholder: "请填写驳回原因（必填，用于审计留痕）", okText: "确认驳回", danger: true });
    if (reason === null) return;
    if (!reason) { ui.toast("驳回原因不能为空", "error"); return; }
    try {
      await api.decide(record_id, "REJECT", null, reason);
      ui.toast("已驳回", "info");
      ui.closeDrawer();
      onChanged && onChanged();
    } catch (e) { ui.toast(e.message, "error"); }
  };
  const doPush = async () => {
    if (s === "REVIEW_READY") {
      try { await api.decide(record_id, "PASS"); } catch (e) { ui.toast(e.message, "error"); return; }
    }
    await doPushOnce(record_id, onChanged);
  };

  if (s === "REVIEW_READY") {
    foot.innerHTML = `
      <button class="btn btn-danger" data-act="reject">驳回</button>
      ${closeBtn}
      <button class="btn btn-ok" data-act="pass-push">通过并入账</button>
      <button class="btn btn-pri" data-act="push">推送金蝶</button>`;
  } else if (s === "REVIEW_PASSED") {
    foot.innerHTML = `${closeBtn}<button class="btn btn-pri" data-act="push">推送金蝶</button>`;
  } else {
    foot.innerHTML = closeBtn;
  }

  foot.querySelector('[data-act="reject"]')?.addEventListener("click", doReject);
  foot.querySelector('[data-act="pass-push"]')?.addEventListener("click", doPass(true));
  foot.querySelector('[data-act="push"]')?.addEventListener("click", doPush);
  foot.querySelector('[data-act="close"]')?.addEventListener("click", ui.closeDrawer);
}

async function doPushOnce(record_id, onChanged) {
  const p = await api.pushRecord(record_id);
  ui.toast(`推送成功，凭证号 ${p.voucher_no || "—"}`", "success");
  ui.closeDrawer();
  onChanged && onChanged();
}
