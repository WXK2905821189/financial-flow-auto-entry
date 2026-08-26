# -*- coding: utf-8 -*-
"""模拟银行银企直连接口服务（Mock Bank API）

- 零依赖：仅用 Python 标准库（http.server）
- 支持招商银行（CMB）/ 中信银行（CITIC）两家银行
- 返回格式模拟真实银行银企直连「流水查询」接口（银行侧原始字段名）
- 数据源：../mock_bank_flow_data 下的多日多账户正常版本 JSON
- 能力：日期范围过滤、分页、账号校验、MD5 签名校验（可选）、余额序列模拟

启动：python mock_bank_api.py [端口]   （默认 8080，可用环境变量 MOCK_BANK_PORT 覆盖）
"""
import hashlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from cmb_enrich import enrich_flow

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "mock_bank_flow_data")

# 模拟签名密钥（真实银行接口为商户密钥，此处固定便于联调）
SECRET = "mock-bank-secret"

# 账户配置：bank_code -> 账号 / 户名 / 初始余额（用于模拟余额序列）
ACCOUNTS = {
    "CMB": {
        "accountNo": "7559123456789012",
        "accountName": "某某网络科技有限公司",
        "initBalance": 3256480.50,
    },
    "CITIC": {
        "accountNo": "8110901234567890",
        "accountName": "某某网络科技有限公司",
        "initBalance": 2187350.00,
    },
}

# 银行字段映射：数据源契约字段 -> 银行原始字段名（体现两行差异，供适配层分别映射）
CMB_FIELDS = {
    "txn_no": "流水号",
    "txn_date": "交易日期",
    "txn_time": "交易时间",
    "currency": "币种",
    "dc_flag": "借贷标志",
    "amount": "交易金额",
    "counterparty_name": "对方户名",
    "counterparty_account": "对方账号",
    "summary": "摘要",
    "txn_type": "交易类型",
    "value_date": "起息日",
    "bank_summary": "银行摘要",
    "counterparty_bank": "收(付)方开户行名",
    "ext_summary": "扩展摘要",
    "analysis_code": "交易分析码",
    "info_flag": "信息标志",
}
CITIC_FIELDS = {
    "txn_no": "流水号",
    "txn_date": "交易日期",
    "txn_time": "交易时间",
    "currency": "币种",
    "dc_flag": "借贷方向",
    "amount": "交易金额",
    "counterparty_name": "对方账户名",
    "counterparty_account": "对方账号",
    "summary": "摘要",
}

DC_FLAG_MAP = {"C": "贷", "D": "借"}
CURRENCY_MAP = {"CNY": "人民币"}


def load_data():
    """加载多日多账户正常版本数据，按账户分组并按日期+时间排序。"""
    data = {}
    for code in ("CMB", "CITIC"):
        path = os.path.join(DATA_DIR, "mock_{}_flow_20260824_28.json".format(code.lower()))
        batches = json.load(open(path, encoding="utf-8"))
        flows = []
        for b in batches:
            flows.extend(b["flows"])
        flows.sort(key=lambda x: (x["txn_date"], x["txn_time"]))
        data[code] = flows
    return data


DATA = load_data()


def check_sign(body):
    """MD5 签名校验：sign = md5(accountNo + startDate + endDate + SECRET)。
    请求不带 sign 时放行（便于联调）；带 sign 则必须正确。"""
    if "sign" not in body:
        return True
    raw = "{}{}{}{}".format(body.get("accountNo", ""), body.get("startDate", ""),
                            body.get("endDate", ""), SECRET)
    return hashlib.md5(raw.encode("utf-8")).hexdigest() == body.get("sign", "")


def handle_query(bank_code, body):
    """处理流水查询，返回银行风格响应。"""
    if bank_code not in ACCOUNTS:
        return {"returnCode": "E0002", "returnMsg": "不支持的银行代码", "data": None}

    account_no = body.get("accountNo")
    if account_no != ACCOUNTS[bank_code]["accountNo"]:
        return {"returnCode": "E0001", "returnMsg": "账号不存在或无权查询", "data": None}

    start = body.get("startDate", "2026-08-24")
    end = body.get("endDate", "2026-08-28")
    try:
        page_no = max(int(body.get("pageNo", 1)), 1)
        page_size = min(max(int(body.get("pageSize", 20)), 1), 200)
    except (TypeError, ValueError):
        return {"returnCode": "E0004", "returnMsg": "分页参数格式错误", "data": None}

    # 基于该账户全部流水计算余额序列（时间升序，贷加借减）
    balance = ACCOUNTS[bank_code]["initBalance"]
    enriched = []
    for f in DATA[bank_code]:
        balance += f["amount"] if f["dc_flag"] == "C" else -f["amount"]
        enriched.append((f, balance))

    filtered = [(f, b) for f, b in enriched if start <= f["txn_date"] <= end]
    total = len(filtered)
    total_page = (total + page_size - 1) // page_size
    page_items = filtered[(page_no - 1) * page_size: page_no * page_size]

    field_map = CMB_FIELDS if bank_code == "CMB" else CITIC_FIELDS
    list_data = []
    for idx, (f, b) in enumerate(page_items):
        if bank_code == "CMB":
            # 招商银行：用真实风格增强（流水号/交易类型/摘要/开户行/扩展摘要等）
            e = enrich_flow(f, idx + 1)
            item = {
                field_map["txn_no"]: e["txn_no"],
                field_map["txn_date"]: e["txn_date"],
                field_map["txn_time"]: e["txn_time"],
                field_map["currency"]: e["currency"],
                field_map["dc_flag"]: e["dc_flag"],
                field_map["amount"]: "{:.2f}".format(e["amount"]),
                field_map["txn_type"]: e["txn_type"],
                field_map["value_date"]: e["value_date"],
                field_map["bank_summary"]: e["bank_summary"],
                field_map["counterparty_name"]: e["counterparty_name"],
                field_map["counterparty_account"]: e["counterparty_account"],
                field_map["counterparty_bank"]: e["counterparty_bank"],
                field_map["ext_summary"]: e["ext_summary"],
                field_map["analysis_code"]: e["analysis_code"],
                field_map["info_flag"]: e["info_flag"],
                "账户余额": "{:.2f}".format(b),
                "手续费": "0.00",
            }
        else:
            item = {
                field_map["txn_no"]: f["txn_no"],
                field_map["txn_date"]: f["txn_date"],
                field_map["txn_time"]: f["txn_time"],
                field_map["currency"]: CURRENCY_MAP.get(f["currency"], f["currency"]),
                field_map["dc_flag"]: DC_FLAG_MAP.get(f["dc_flag"], f["dc_flag"]),
                field_map["amount"]: "{:.2f}".format(f["amount"]),
                field_map["counterparty_name"]: f["counterparty_name"],
                field_map["counterparty_account"]: f["counterparty_account"],
                field_map["summary"]: f["summary"],
                "账户余额": "{:.2f}".format(b),
                "手续费": "0.00",
            }
        list_data.append(item)

    return {
        "returnCode": "0000",
        "returnMsg": "交易成功",
        "data": {
            "totalCount": total,
            "pageNo": page_no,
            "pageSize": page_size,
            "totalPage": total_page,
            "list": list_data,
        },
    }


TEST_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>模拟银行接口测试台</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "Microsoft YaHei", Arial, sans-serif; background: #f4f6f9; color: #1f2937; padding: 24px; }
  .wrap { max-width: 1080px; margin: 0 auto; }
  h1 { font-size: 22px; margin-bottom: 6px; }
  .sub { color: #6b7280; font-size: 13px; margin-bottom: 18px; }
  .card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; }
  .card h2 { font-size: 15px; margin-bottom: 12px; color: #374151; }
  .health { display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 13px; font-weight: 600; }
  .health.up { background: #d1fae5; color: #065f46; }
  .health.down { background: #fee2e2; color: #991b1b; }
  .row { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
  .field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: #374151; }
  .field input, .field select { height: 34px; padding: 0 10px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 13px; min-width: 170px; }
  .btn { height: 34px; padding: 0 22px; border: 0; border-radius: 6px; background: #2563eb; color: #fff; font-size: 14px; cursor: pointer; }
  .btn:hover { background: #1d4ed8; }
  .meta { font-size: 13px; color: #374151; margin-top: 12px; }
  .meta b { color: #2563eb; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 10px; }
  th, td { border: 1px solid #e5e7eb; padding: 7px 8px; text-align: left; white-space: nowrap; }
  th { background: #f9fafb; color: #374151; position: sticky; top: 0; }
  tr:nth-child(even) td { background: #fafbfc; }
  .scroll { max-height: 460px; overflow: auto; border: 1px solid #e5e7eb; border-radius: 8px; }
  .err { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-top: 10px; }
  .ok { background: #ecfdf5; border: 1px solid #a7f3d0; color: #065f46; padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-top: 10px; }
  .empty { color: #9ca3af; text-align: center; padding: 30px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>模拟银行银企直连接口测试台</h1>
  <div class="sub">Mock Bank API · 零依赖 · 数据范围 2026-08-24 ~ 2026-08-28 · 查询接口为 POST（本页通过 fetch 调用）</div>

  <div class="card">
    <h2>服务健康检查 <span id="health" class="health">检测中…</span></h2>
  </div>

  <div class="card">
    <h2>流水查询</h2>
    <div class="row">
      <div class="field"><label>银行</label>
        <select id="bank">
          <option value="CMB">招商银行（CMB）</option>
          <option value="CITIC">中信银行（CITIC）</option>
        </select>
      </div>
      <div class="field"><label>账号</label><input id="account" value="7559123456789012"></div>
      <div class="field"><label>开始日期</label><input id="start" type="date" value="2026-08-24"></div>
      <div class="field"><label>结束日期</label><input id="end" type="date" value="2026-08-28"></div>
      <button class="btn" id="queryBtn">查询流水</button>
    </div>
    <div id="msg"></div>
    <div class="meta" id="meta"></div>
    <div class="scroll"><table id="tbl"><thead></thead><tbody></tbody></table></div>
  </div>
</div>

<script>
var ACCOUNTS = {CMB: "7559123456789012", CITIC: "8110901234567890"};
var bankSel = document.getElementById("bank");
var accountInput = document.getElementById("account");
var msg = document.getElementById("msg");
var meta = document.getElementById("meta");
var tbl = document.getElementById("tbl");

bankSel.addEventListener("change", function () {
  accountInput.value = ACCOUNTS[bankSel.value];
});

function setMsg(html, cls) { msg.innerHTML = html; msg.className = cls || ""; }

function renderTable(headers, rows) {
  var thead = tbl.querySelector("thead");
  var tbody = tbl.querySelector("tbody");
  thead.innerHTML = "<tr>" + headers.map(function (h) { return "<th>" + h + "</th>"; }).join("") + "</tr>";
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="' + headers.length + '" class="empty">无数据</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(function (r) {
    return "<tr>" + headers.map(function (h) { return "<td>" + (r[h] == null ? "" : r[h]) + "</td>"; }).join("") + "</tr>";
  }).join("");
}

function query() {
  var body = {
    accountNo: accountInput.value.trim(),
    startDate: document.getElementById("start").value,
    endDate: document.getElementById("end").value
  };
  setMsg("查询中…", "");
  fetch("/api/bank/" + bankSel.value + "/query", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.returnCode !== "0000") {
      setMsg("返回码 " + d.returnCode + "：" + d.returnMsg, "err");
      meta.textContent = "";
      renderTable([], []);
      return;
    }
    setMsg("查询成功（returnCode=0000）", "ok");
    var list = d.data.list || [];
    meta.innerHTML = "共 <b>" + d.data.totalCount + "</b> 笔，本页 <b>" + list.length + "</b> 笔，共 <b>" + d.data.totalPage + "</b> 页";
    renderTable(Object.keys(list[0] || {}), list);
  }).catch(function (e) {
    setMsg("请求失败：" + e.message, "err");
  });
}

document.getElementById("queryBtn").addEventListener("click", query);
document.querySelector("form") || null;

fetch("/api/health").then(function (r) { return r.json(); }).then(function (d) {
  var el = document.getElementById("health");
  if (d.returnCode === "0000") {
    el.textContent = "UP · 银行 " + d.data.banks.join(" / ");
    el.className = "health up";
  } else {
    el.textContent = "DOWN";
    el.className = "health down";
  }
}).catch(function () {
  var el = document.getElementById("health");
  el.textContent = "DOWN";
  el.className = "health down";
});
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send({"returnCode": "0000", "returnMsg": "OK",
                        "data": {"status": "UP", "banks": list(ACCOUNTS.keys())}})
        elif path in ("/", "/test", "/index.html"):
            self._send_html(TEST_PAGE)
        else:
            self._send({"returnCode": "E0003", "returnMsg": "接口不存在", "data": None}, 404)

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "bank"] and parts[3] == "query":
            bank_code = parts[2].upper()
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except (ValueError, json.JSONDecodeError):
                self._send({"returnCode": "E0004", "returnMsg": "请求体 JSON 格式错误", "data": None}, 400)
                return
            if not check_sign(body):
                self._send({"returnCode": "E0005", "returnMsg": "签名校验失败", "data": None})
                return
            self._send(handle_query(bank_code, body))
        else:
            self._send({"returnCode": "E0003", "returnMsg": "接口不存在", "data": None}, 404)

    def log_message(self, fmt, *args):
        print("[MockBankAPI] {} {}".format(self.address_string(), fmt % args))


def main():
    port = int(os.environ.get("MOCK_BANK_PORT", sys.argv[1] if len(sys.argv) > 1 else 8080))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("=" * 60)
    print("模拟银行银企直连接口服务已启动")
    print("  地址: http://127.0.0.1:{}".format(port))
    print("  健康检查: GET  /api/health")
    print("  招商银行: POST /api/bank/CMB/query   账号 {}".format(ACCOUNTS["CMB"]["accountNo"]))
    print("  中信银行: POST /api/bank/CITIC/query  账号 {}".format(ACCOUNTS["CITIC"]["accountNo"]))
    print("  数据范围: 2026-08-24 ~ 2026-08-28（招商 {} 笔 / 中信 {} 笔）".format(
        len(DATA["CMB"]), len(DATA["CITIC"])))
    print("  签名密钥: {}（sign = md5(accountNo+startDate+endDate+secret)）".format(SECRET))
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()


if __name__ == "__main__":
    main()
