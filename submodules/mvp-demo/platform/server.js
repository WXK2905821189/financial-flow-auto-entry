// 数据中台（一期 MVP 演示版）
// 职责：采集(测试银行) → 校验 → 落库(独立MySQL) → 人工复核 → 推送(测试金蝶) 全链路 + 审计留痕
const express = require('express');
const crypto = require('crypto');
const mysql = require('mysql2/promise');

const app = express();
app.use(express.json());
app.use(express.static('public'));

const PORT = process.env.PORT || 8000;
const DB = {
  host: process.env.MYSQL_HOST || '127.0.0.1',
  port: +(process.env.MYSQL_PORT || 3306),
  user: process.env.MYSQL_USER || 'root',
  password: process.env.MYSQL_PASSWORD || 'mvp_root_pw',
  database: process.env.MYSQL_DB || 'midvault',
  waitForConnections: true, connectionLimit: 10,
};
const BANK_URL = process.env.BANK_URL || 'http://127.0.0.1:8100';
const KINGDEE_URL = process.env.KINGDEE_URL || 'http://127.0.0.1:8200';
const AUDITOR = process.env.DEMO_AUDITOR || 'cnxiao';   // 演示复核账号（MVP 简版）

let pool = null;

async function connectDb() {
  // 等待 MySQL 就绪后建立连接池
  for (let i = 0; i < 30; i++) {
    try { pool = mysql.createPool(DB); await pool.query('SELECT 1'); return; }
    catch (e) { console.log(`[platform] db not ready (${i}), retry...`); await new Promise(r => setTimeout(r, 2000)); }
  }
  throw new Error('DB connect failed');
}

// ---- 审计：只追加写日志（不提供更新/删除） ----
async function audit(actor, action, detail) {
  try { await pool.query('INSERT INTO audit_log (`actor`,`action`,`detail`) VALUES (?,?,?)', [actor, action, detail]); }
  catch (e) { console.error('audit write failed', e.message); }
}

// ---- 采集：调用测试银行 → 校验 → 落库 ----
app.get('/api/bank', async (_req, res) => {
  try { const r = await fetch(`${BANK_URL}/transactions`); res.json(await r.json()); }
  catch (e) { res.status(502).json({ ok: false, error: e.message }); }
});
app.get('/api/bankStatus', async (_req, res) => {
  try { const r = await fetch(`${BANK_URL}/transactions`); const j = await r.json(); res.json({ ok: true, count: j.rawCount }); }
  catch (e) { res.json({ ok: false, count: -1 }); }
});

app.post('/api/collect', async (req, res) => {
  try {
    const bankRes = await fetch(`${BANK_URL}/transactions`);
    const bank = await bankRes.json();
    const batchId = `demo-batch-${Date.now()}`;
    const bankName = bank.items[0]?.bank || 'bank-mock';

    let validCount = 0;
    const seenUnique = new Set();
    const rows = [];
    const checks = [];

    for (const it of bank.items) {
      const recordId = crypto.randomUUID().slice(0, 36);
      let status = 'valid'; let reason = '校验通过';

      if (!(it.amount > 0)) { status = 'abnormal'; reason = '异常·金额非正'; }
      else if (!it.counterparty || !it.counterparty.trim()) { status = 'abnormal'; reason = '异常·对方户名缺失'; }
      else if (seenUnique.has(it.uniqueNo)) { status = 'abnormal'; reason = '异常·重复流水号'; }

      if (status === 'valid') { seenUnique.add(it.uniqueNo); validCount += 1; }
      rows.push([recordId, batchId, it.bank, it.account, it.date, it.amount, it.dir, it.counterparty, it.currency, it.memo, it.uniqueNo, status, reason]);
      checks.push({ uniqueNo: it.uniqueNo, status, reason, recordId });
    }

    await pool.query(
      'INSERT INTO batches (batch_id,bank,account,source,raw_count,valid_count) VALUES (?,?,?,?,?,?)',
      [batchId, bankName, bank.items[0]?.account || '-', 'bank-mock', bank.rawCount, validCount]
    );
    for (const r of rows) {
      await pool.query(
        'INSERT INTO transactions (record_id,batch_id,bank,account,tran_date,amount,direction,counterparty,currency,memo,unique_no,status,check_result) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        r
      );
    }
    await audit(AUDITOR, 'collect', `采集批次 ${batchId}，原始 ${bank.rawCount} 条，通过 ${validCount} 条`);
    res.json({ ok: true, batchId, rawCount: bank.rawCount, validCount, abnormalCount: bank.rawCount - validCount, checks });
  } catch (e) { res.status(500).json({ ok: false, error: e.message }); }
});

// ---- 查已落库流水 ----
app.get('/api/transactions', async (_req, res) => {
  const [rows] = await pool.query('SELECT * FROM transactions ORDER BY id');
  res.json({ ok: true, items: rows });
});

// ---- 汇总统计 ----
app.get('/api/stats', async (_req, res) => {
  const [t] = await pool.query('SELECT COUNT(*) c, SUM(status="valid") valid, SUM(status="abnormal") abnormal, SUM(status="reviewed") reviewed, SUM(status="pushed") pushed FROM transactions');
  const [p] = await pool.query('SELECT COUNT(*) c FROM push_log');
  res.json({ tx: t[0], pushedVouchers: p[0].c, batches: (await pool.query('SELECT COUNT(*) c FROM batches'))[0][0].c });
});

// ---- 人工复核：把"有效"流水 复核通过（human-in-the-loop 兜底阀） ----
app.post('/api/review', async (req, res) => {
  const ids = (await pool.query(`SELECT record_id, batch_id FROM transactions WHERE status='valid'`))[0];
  if (ids.length === 0) return res.json({ ok: true, reviewed: 0 });
  for (const row of ids) {
    await pool.query(`UPDATE transactions SET status='reviewed' WHERE record_id=?`, [row.record_id]);
    await pool.query(`INSERT INTO review_log (batch_id,record_id,auditor,`action`) VALUES (?,?,?,'pass')`, [row.batch_id, row.record_id, AUDITOR]);
  }
  await audit(AUDITOR, 'review', `复核通过 ${ids.length} 条`);
  res.json({ ok: true, reviewed: ids.length });
});

// ---- 一键推送：复核通过 → 测试金蝶，回写凭证号，双向可溯 ----
app.post('/api/push', async (req, res) => {
  const items = (await pool.query(`SELECT * FROM transactions WHERE status='reviewed'`))[0];
  if (items.length === 0) return res.json({ ok: true, pushed: 0 });

  const payload = { batchId: items[0].batch_id, auditor: AUDITOR, items: items.map(i => ({ recordId: i.record_id, uniqueNo: i.unique_no, bank: i.bank, memo: i.memo })) };
  const kdRes = await fetch(`${KINGDEE_URL}/vouchers`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const kd = await kdRes.json();

  for (const v of kd.vouchers || []) {
    await pool.query(`UPDATE transactions SET status='pushed' WHERE record_id=?`, [v.recordId]);
    await pool.query(`INSERT INTO push_log (batch_id,record_id,voucher_no) VALUES (?,?,?)`, [payload.batchId, v.recordId, v.voucherNo]);
  }
  await audit(AUDITOR, 'push', `推送 ${kd.issuedCount || 0} 笔到金蝶，生成凭证`);
  res.json({ ok: true, pushed: kd.issuedCount || 0, vouchers: kd.vouchers });
});

// ---- 溯源回查 ----
app.get('/api/trace', async (req, res) => {
  const q = (req.query.q || '').trim();
  try {
    const [logs] = await pool.query(`SELECT p.record_id, t.unique_no, p.voucher_no, p.pushed_at FROM push_log p JOIN transactions t ON t.record_id=p.record_id WHERE ?='' OR CONCAT_WS(' ', p.voucher_no, t.unique_no, t.memo) LIKE ?`, [q, `%${q}%`]);
    res.json({ ok: true, items: logs });
  } catch (e) { res.status(500).json({ ok: false, error: e.message }); }
});

// ---- 查询金蝶已制证（演示对账/回查） ----
app.get('/api/kingdee/vouchers', async (_req, res) => {
  const r = await fetch(`${KINGDEE_URL}/vouchers`);
  res.json(await r.json());
});

// ---- 审计日志 ----
app.get('/api/audit', async (_req, res) => {
  const [rows] = await pool.query('SELECT * FROM audit_log ORDER BY id DESC LIMIT 50');
  res.json({ ok: true, items: rows });
});

(async () => {
  await connectDb();
  await audit('system', 'startup', '中台服务启动');
  app.listen(PORT, () => console.log(`[platform] listening :${PORT}, 演示入口 http://localhost:${PORT === 8000 ? 8080 : PORT}`));
})();