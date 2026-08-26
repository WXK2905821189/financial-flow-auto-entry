// 测试金蝶 Mock —— 模拟金蝶云星空 OpenAPI 凭证推送：接收复核通过后的流水，自动"生成凭证"并回显凭证号
const express = require('express');
const app = express();
const PORT = process.env.PORT || 8200;
app.use(express.json());

let seq = 1000;
const issued = []; // 已"制证"记录，本演示保留在内存，供 /vouchers 查询回显

app.get('/healthz', (_req, res) => res.json({ ok: true }));

// OpenAPI 凭证推送入口：中台复核通过后调用
app.post('/vouchers', (req, res) => {
  const { batchId, items, auditor } = req.body || {};
  if (!Array.isArray(items)) {
    return res.status(400).json({ ok: false, message: '缺少 items 载荷' });
  }
  const created = items.map((it) => {
    seq += 1;
    const voucherNo = `KD-${it.bank === '中信银行' ? 'ZX' : 'ZS'}-2026-${seq}`;
    const entry = { recordId: it.recordId, uniqueNo: it.uniqueNo, voucherNo, auditor, memo: it.memo };
    issued.push(entry);
    return entry;
  });
  res.json({ ok: true, batchId, issuedCount: created.length, vouchers: created });
});

// 已被金蝶入账的凭证（用于演示溯源回查）
app.get('/vouchers', (_req, res) => res.json({ ok: true, issued }));
app.get('/issuedCount', (_req, res) => res.json({ ok: true, count: issued.length }));

app.listen(PORT, () => console.log(`[kingdee-mock] listening :${PORT}`));