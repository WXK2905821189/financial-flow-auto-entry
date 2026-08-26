# -*- coding: utf-8 -*-
"""Mock 银行接口自测脚本：启动服务（随机端口）并验证核心功能。"""
import hashlib
import json
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

from mock_bank_api import Handler, ACCOUNTS, DATA, SECRET

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:{}".format(port)

passed, failed = 0, 0


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(BASE + path) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS | {}".format(name))
    else:
        failed += 1
        print("FAIL | {} | {}".format(name, detail))


def sign(account_no, start, end):
    raw = "{}{}{}{}".format(account_no, start, end, SECRET)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# 1. 健康检查
r = get("/api/health")
check("健康检查", r["returnCode"] == "0000" and r["data"]["status"] == "UP", r)

# 2. 招商全量查询
r = post("/api/bank/CMB/query", {"accountNo": ACCOUNTS["CMB"]["accountNo"]})
check("招商全量 66 笔", r["returnCode"] == "0000" and r["data"]["totalCount"] == 66,
      "totalCount={}".format(r["data"]["totalCount"] if r["data"] else None))
if r["data"] and r["data"]["list"]:
    first = r["data"]["list"][0]
    check("招商返回银行字段（流水号/借贷标志/对方户名/交易类型/起息日）",
          "流水号" in first and "借贷标志" in first and "对方户名" in first
          and "账户余额" in first and "交易类型" in first and "起息日" in first,
          str(list(first.keys())))
    check("招商借贷标志为中文（贷/借）", first["借贷标志"] in ("贷", "借"), first["借贷标志"])
    check("招商币种为人民币", first["币种"] == "人民币", first["币种"])

# 3. 中信全量查询
r = post("/api/bank/CITIC/query", {"accountNo": ACCOUNTS["CITIC"]["accountNo"]})
check("中信全量 71 笔", r["returnCode"] == "0000" and r["data"]["totalCount"] == 71,
      "totalCount={}".format(r["data"]["totalCount"] if r["data"] else None))
if r["data"] and r["data"]["list"]:
    first = r["data"]["list"][0]
    check("中信返回银行字段（流水号/借贷方向/对方账户名）",
          "流水号" in first and "借贷方向" in first and "对方账户名" in first,
          str(list(first.keys())))

# 4. 日期过滤（招商单日 08-24 = 12 笔）
r = post("/api/bank/CMB/query", {"accountNo": ACCOUNTS["CMB"]["accountNo"],
                                 "startDate": "2026-08-24", "endDate": "2026-08-24"})
check("招商单日 08-24 共 12 笔", r["returnCode"] == "0000" and r["data"]["totalCount"] == 12,
      "totalCount={}".format(r["data"]["totalCount"] if r["data"] else None))

# 5. 分页（招商 pageSize=10, pageNo=2）
r = post("/api/bank/CMB/query", {"accountNo": ACCOUNTS["CMB"]["accountNo"],
                                 "pageNo": 2, "pageSize": 10})
d = r["data"]
check("分页：totalPage=7 / 第2页10条", r["returnCode"] == "0000" and d["totalPage"] == 7 and len(d["list"]) == 10,
      "totalPage={} len={}".format(d["totalPage"], len(d["list"])))

# 6. 余额序列（首条余额 = 初始 ± 首条金额，基于数据源首条动态断言）
r = post("/api/bank/CMB/query", {"accountNo": ACCOUNTS["CMB"]["accountNo"],
                                 "startDate": "2026-08-24", "endDate": "2026-08-24"})
first = r["data"]["list"][0]
first_src = DATA["CMB"][0]
expected_bal = ACCOUNTS["CMB"]["initBalance"] + (first_src["amount"] if first_src["dc_flag"] == "C" else -first_src["amount"])
check("余额序列模拟（首条余额 = 初始 ± 首条金额）",
      abs(float(first["账户余额"]) - expected_bal) < 0.01,
      "余额={} 期望={}".format(first["账户余额"], expected_bal))

# 7. 错误账号
r = post("/api/bank/CMB/query", {"accountNo": "9999999999999999"})
check("错误账号返回 E0001", r["returnCode"] == "E0001", r)

# 8. 不支持的银行
r = post("/api/bank/ABC/query", {"accountNo": "x"})
check("不支持银行返回 E0002", r["returnCode"] == "E0002", r)

# 9. 签名校验：错误签名
r = post("/api/bank/CMB/query", {"accountNo": ACCOUNTS["CMB"]["accountNo"], "sign": "wrong"})
check("错误签名返回 E0005", r["returnCode"] == "E0005", r)

# 10. 签名校验：正确签名（签名串须与请求体参数一致）
good = sign(ACCOUNTS["CMB"]["accountNo"], "2026-08-24", "2026-08-28")
r = post("/api/bank/CMB/query", {"accountNo": ACCOUNTS["CMB"]["accountNo"],
                                 "startDate": "2026-08-24", "endDate": "2026-08-28", "sign": good})
check("正确签名返回 0000", r["returnCode"] == "0000", r)

# 11. 接口不存在
try:
    post("/api/nothing", {})
    check("未知接口返回 404", False, "未抛错")
except urllib.error.HTTPError as e:
    check("未知接口返回 404", e.code == 404, str(e.code))

server.shutdown()
print("\n结果: {} 通过 / {} 失败".format(passed, failed))
raise SystemExit(1 if failed else 0)
