# 模拟银行银企直连接口服务（Mock Bank API）

> **版本**：v0.2（招商返回按真实网银导出 36 列字段重构）　**所有者**：数据工程师 Agent　**用途**：模拟真实银行银企直连「流水查询」接口，供采集系统/适配层联调
> **技术**：Python 3 标准库（`http.server`），**零第三方依赖**
> **数据源**：`../mock_bank_flow_data/mock_{cmb,citic}_flow_20260824_28.json`（多日多账户正常版本）
> **真实格式参考**：招商返回字段与真实网银导出 36 列一致（流水号/交易类型/起息日/扩展摘要等），见 `../mock_bank_flow_data/README.md` 第九节

---

## 一、快速开始

```powershell
# 启动（默认端口 8080）
python mock_bank_api.py

# 指定端口
python mock_bank_api.py 9000
# 或用环境变量
$env:MOCK_BANK_PORT = 9000; python mock_bank_api.py
```

启动后输出：

```
模拟银行银企直连接口服务已启动
  地址: http://127.0.0.1:8080
  健康检查: GET  /api/health
  招商银行: POST /api/bank/CMB/query   账号 7559123456789012
  中信银行: POST /api/bank/CITIC/query  账号 8110901234567890
  数据范围: 2026-08-24 ~ 2026-08-28（招商 66 笔 / 中信 71 笔）
```

停止：`Ctrl+C`。

> 当前已在后台启动一个实例（端口 8080），可直接访问 `http://127.0.0.1:8080`。

---

## 二、接口文档

### 2.1 健康检查

```
GET /api/health
```

```json
{ "returnCode": "0000", "returnMsg": "OK", "data": { "status": "UP", "banks": ["CMB", "CITIC"] } }
```

### 2.2 流水查询

```
POST /api/bank/{bankCode}/query
```

**请求体**（JSON）：

| 参数 | 类型 | 必填 | 说明 |
|-|-|-|-|
| accountNo | string | 是 | 银行账号（见下表） |
| startDate | string | 否 | 起始日期 YYYY-MM-DD，默认 2026-08-24 |
| endDate | string | 否 | 结束日期 YYYY-MM-DD，默认 2026-08-28 |
| pageNo | int | 否 | 页码，默认 1 |
| pageSize | int | 否 | 每页条数，默认 20（上限 200） |
| sign | string | 否 | MD5 签名（见第四节），不带则跳过验签 |

**账号**：

| bankCode | 银行 | 账号 | 户名 |
|-|-|-|-|
| CMB | 招商银行 | 7559123456789012 | 某某网络科技有限公司 |
| CITIC | 中信银行 | 8110901234567890 | 某某网络科技有限公司 |

**响应体**（JSON，模拟银行返回码 + 数据）：

```json
{
  "returnCode": "0000",
  "returnMsg": "交易成功",
  "data": {
    "totalCount": 66,
    "pageNo": 1,
    "pageSize": 20,
    "totalPage": 4,
    "list": [
      {
        "流水号": "C0947BO000133AZ",
        "交易日期": "2026-08-24",
        "交易时间": "10:40:53",
        "币种": "人民币",
        "借贷标志": "借",
        "交易金额": "82400.00",
        "交易类型": "跨行转账支出",
        "起息日": "2026-08-24",
        "银行摘要": "采购款",
        "对方户名": "某某供应链管理有限公司",
        "对方账号": "1109xxxxxxxxxxxx",
        "收(付)方开户行名": "中信银行深圳分行",
        "扩展摘要": "",
        "交易分析码": "NPGATR",
        "信息标志": "",
        "账户余额": "3174080.50",
        "手续费": "0.00"
      }
    ]
  }
}
```

> **两家银行字段名刻意不同**（模拟真实多银行差异）：招商用「流水号/借贷标志/对方户名」并含交易类型/起息日/扩展摘要等（对齐真实网银导出），中信用「流水号/借贷方向/对方账户名」。适配层需分别映射到统一契约。

---

## 三、调用示例

### PowerShell

```powershell
$body = @{ accountNo = "7559123456789012"; startDate = "2026-08-24"; endDate = "2026-08-28"; pageNo = 1; pageSize = 20 } | ConvertTo-Json
$r = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/bank/CMB/query" -Method Post -Body $body -ContentType "application/json; charset=utf-8"
$r.data.list | Format-Table 流水号, 交易日期, 借贷标志, 交易金额, 交易类型, 对方户名
```

### curl

```bash
curl -X POST http://127.0.0.1:8080/api/bank/CITIC/query \
  -H "Content-Type: application/json" \
  -d '{"accountNo":"8110901234567890","startDate":"2026-08-24","endDate":"2026-08-28","pageNo":1,"pageSize":20}'
```

### Python（采集适配层对接参考）

```python
import json, urllib.request

def query_bank(bank_code, account_no, start, end, page=1, size=20):
    body = json.dumps({"accountNo": account_no, "startDate": start,
                       "endDate": end, "pageNo": page, "pageSize": size}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:8080/api/bank/{bank_code}/query",
        data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

r = query_bank("CMB", "7559123456789012", "2026-08-24", "2026-08-28")
print(r["returnCode"], r["data"]["totalCount"])
```

---

## 四、签名校验（模拟真实银行验签）

- 算法：`sign = MD5(accountNo + startDate + endDate + SECRET)`，`SECRET = "mock-bank-secret"`
- 请求**不带 sign** 时放行（便于联调）；**带 sign** 则必须与算法一致，否则返回 `E0005 签名校验失败`
- 注意：签名串必须与请求体中的 `startDate`/`endDate` 实际值一致

```python
import hashlib
secret = "mock-bank-secret"
raw = "7559123456789012" + "2026-08-24" + "2026-08-28" + secret
sign = hashlib.md5(raw.encode("utf-8")).hexdigest()
```

---

## 五、错误码

| returnCode | 含义 |
|-|-|
| 0000 | 交易成功 |
| E0001 | 账号不存在或无权查询 |
| E0002 | 不支持的银行代码 |
| E0003 | 接口不存在（HTTP 404） |
| E0004 | 请求体/参数格式错误（HTTP 400） |
| E0005 | 签名校验失败 |

---

## 六、能力与数据

| 能力 | 说明 |
|-|-|
| 日期范围过滤 | `startDate`/`endDate` 过滤流水 |
| 分页 | `pageNo`/`pageSize`，返回 `totalCount`/`totalPage` |
| 余额序列 | 按账户初始余额 + 流水顺序（贷加借减）模拟每条后的账户余额 |
| 账号校验 | 非本行账号返回 E0001 |
| 签名校验 | MD5 验签（可选） |
| 多银行差异 | 招商/中信字段名不同，模拟真实多银行适配场景 |
| 招商字段增强 | 流水号 15 位字母数字（仿真实）、交易类型/起息日/银行摘要/收付方开户行名/扩展摘要/交易分析码/信息标志（对齐真实网银导出 36 列） |

**数据范围**：2026-08-24 ~ 08-28（5 个工作日），招商 66 笔 / 中信 71 笔，含周期性交易（工资代发/房租/物业费/贷款还款）。

---

## 七、与采集适配层的关系

```
模拟银行接口（本服务）          采集适配层                   数据中台
┌──────────────────┐    ┌──────────────────────┐    ┌────────────────┐
│ POST /api/bank/  │    │ 按银行映射字段 → 统一契约 │    │ sp_ingest_flow  │
│ CMB|CITIC/query  │───▶│ 清洗（千分位/中文借贷）  │───▶│ 落库+校验+留痕   │
│ 返回银行原始格式   │    │ 分页拉取 → 批次组装      │    │ v_recon_balance │
└──────────────────┘    └──────────────────────┘    └────────────────┘
```

- 本服务返回**银行侧原始字段**（非统一契约），正是适配层要映射/清洗的对象。
- 适配层按 `source_type=API`、`source_ref=mock://cmb/2026-08-24` 组装批次，调用 `sp_ingest_flow` 落库。
- 联调自测清单见《采集适配层联调接口约定（v0.1）》第八节。

---

## 八、自测

```powershell
python test_mock_api.py
```

覆盖：健康检查、两行全量/单日查询、分页、余额序列、错误账号、不支持银行、错误/正确签名、未知接口（15 项断言）。
