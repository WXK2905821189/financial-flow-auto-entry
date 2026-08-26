// 测试银行 Mock —— 模拟银行网银导出/银企直联返回的收付款流水
// 故意埋了 2 类"脏数据"（负金额 / 缺对方户名 / 重复流水号），供中台校验环节演示拦截
const express = require('express');

const app = express();
const PORT = process.env.PORT || 8100;

const banks = [
  { bank: '中信银行', account: 'CMB-622208-8801', currency: 'CNY' },
  { bank: '招商银行', account: 'CITIC-8110-3302', currency: 'CNY' },
];

// 模拟本批次原始流水
const raw = [
  // 中信：正常收款
  { bank: '中信银行', account: 'CMB-622208-8801', date: '2026-08-18', amount: 32800.00, dir: 'in', counterparty: '上海启明科技', currency: 'CNY', memo: '合同回款 AG-2026-071', uniqueNo: 'CITIC-20260818-001' },
  // 中信：正常付款（供应商货款）
  { bank: '中信银行', account: 'CMB-622208-8801', date: '2026-08-18', amount: 15300.00, dir: 'out', counterparty: '杭州证大供应链', currency: 'CNY', memo: '采购付款 PO-8251', uniqueNo: 'CITIC-20260818-002' },
  // 招商：正常收款
  { bank: '招商银行', account: 'CITIC-8110-3302', date: '2026-08-19', amount: 1260.00, dir: 'in', counterparty: '北京维度传媒', currency: 'CNY', memo: '广告收入 JUL-042', uniqueNo: 'CMB-20260819-001' },
  // 异常1：金额为负（应拦截）
  { bank: '招商银行', account: 'CITIC-8110-3302', date: '2026-08-19', amount: -500.00, dir: 'in', counterparty: '深圳云创网络', currency: 'CNY', memo: '可疑负金额', uniqueNo: 'CMB-20260819-002' },
  // 异常2：缺对方户名（应拦截）
  { bank: '中信银行', account: 'CMB-622208-8801', date: '2026-08-20', amount: 9999.00, dir: 'in', counterparty: '', currency: 'CNY', memo: '对方户名缺失', uniqueNo: 'CITIC-20260820-001' },
];

// 重复一条（重复流水号，应拦截）
raw.push({ ...raw[0], date: '2026-08-20', memo: '重复流水号(同一来源)', uniqueNo: 'CITIC-20260818-001' });

app.get('/healthz', (_req, res) => res.json({ ok: true }));

// 中台采集按批次拉取：每次返回本批原始流水 + 来源说明
app.get('/transactions', (_req, res) => {
  res.json({
    source: 'bank-mock',
    batchHint: `demo-batch-${Date.now()}`,
    rawCount: raw.length,
    items: raw,
  });
});

app.listen(PORT, () => console.log(`[bank-mock] listening :${PORT}`));