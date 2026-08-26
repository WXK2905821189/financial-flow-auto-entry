# -*- coding: utf-8 -*-
"""招商银行流水「真实风格」字段增强（参考真实网银导出 36 列格式）

- 流水号：15 位字母数字，仿真实格式 C0947BT0000CQ2Z
- 交易类型 / 摘要 / 收付方开户行名 / 扩展摘要 / 交易分析码 / 信息标志
- 供 mock_bank_api.py（银企直连）与 mock 数据生成脚本共用，保证两处口径一致
"""
import hashlib

B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# 摘要关键词 -> (贷方交易类型, 借方交易类型)
TXN_TYPE_MAP = [
    ("平台结算", "网联付款申请收款", None),
    ("项目回款", "网联付款申请收款", None),
    ("货款", "银联TOKEN贷记对公户入账", "跨行转账支出"),
    ("服务费", "银联TOKEN贷记对公户入账", "跨行转账支出"),
    ("咨询费", "银联TOKEN贷记对公户入账", None),
    ("软件开发费", "银联TOKEN贷记对公户入账", None),
    ("广告", "银联TOKEN贷记对公户入账", "跨行转账支出"),
    ("采购", None, "跨行转账支出"),
    ("劳务", None, "代发工资"),
    ("云服务", None, "网上银行转账支出"),
    ("房租", None, "网上银行转账支出"),
    ("电费", None, "网上银行转账支出"),
    ("办公", None, "网上银行转账支出"),
    ("差旅", None, "网上银行转账支出"),
    ("手续费", None, "企业银行各项费用"),
]

# 收付方账号前缀 -> 开户行名
BANK_NAME_MAP = [
    ("1109", "中国工商银行北京分行"),
    ("622202", "中国工商银行北京分行"),
    ("6222", "中国建设银行北京分行"),
    ("7559", "招商银行深圳分行"),
    ("8110", "中信银行深圳分行"),
    ("6225", "招商银行北京分行"),
]

# 交易分析码池（真实样例：N6GATR / NPGATR / NEGATR）
ANALYSIS_CODE = {"网联": "N6GATR", "银联": "NPGATR", "费用": "NEGATR"}


def cmb_serial(seq, date_str):
    """生成 15 位字母数字流水号，仿 C0947BT0000CQ2Z（C + 0947B + 日字符 + 000X + 3 随机 + Z）。"""
    day_char = B36[int(date_str[8:10])]
    h = hashlib.md5("cmb-{}-{}".format(date_str, seq).encode("utf-8")).hexdigest().upper()
    return "C0947B{}000{}{}Z".format(day_char, B36[seq % 36], h[:3])


def txn_type(summary, dc_flag):
    for kw, c_type, d_type in TXN_TYPE_MAP:
        if kw in summary:
            return c_type if dc_flag == "C" else d_type
    return "银联TOKEN贷记对公户入账" if dc_flag == "C" else "跨行转账支出"


def bank_name(account):
    if not account:
        return ""
    for prefix, name in BANK_NAME_MAP:
        if account.startswith(prefix):
            return name
    return "中国银行"


def bank_summary(summary, txn_type, date_str):
    """真实风格摘要：网联/银联结算用短码，手续费用费用名，其余保留业务摘要。"""
    if "网联" in txn_type:
        return "{}{}_{}".format(date_str[5:7], date_str[8:10], "1720219225")
    if "银联" in txn_type:
        return "SA020008提现 {}".format(date_str)
    if "费用" in txn_type:
        return "网银支付-跨行-异地手续费" if summary == "手续费" else summary
    return summary


def ext_summary(txn_type, seq):
    """扩展摘要：网联 AN 开头 / 银联 TK 开头，其余为空。"""
    if "网联" in txn_type:
        return "AN{}{:0>4}X7BS0000S5MX0".format(B36[seq % 36], seq % 10000)
    if "银联" in txn_type:
        return "TK46Y9042T{:0>3}0001".format(seq % 1000)
    return ""


def analysis_code(txn_type):
    if "网联" in txn_type:
        return ANALYSIS_CODE["网联"]
    if "银联" in txn_type:
        return ANALYSIS_CODE["银联"]
    if "费用" in txn_type:
        return ANALYSIS_CODE["费用"]
    return "NPGATR"


def info_flag(txn_type):
    return "1" if "费用" in txn_type else ""


def enrich_flow(f, seq):
    """把统一契约流水增强为招商银行侧字段（含 36 列导出所需信息）。"""
    t_type = txn_type(f["summary"], f["dc_flag"])
    return {
        "txn_no": cmb_serial(seq, f["txn_date"]),
        "txn_date": f["txn_date"],
        "txn_time": f["txn_time"],
        "currency": "人民币",
        "dc_flag": "贷" if f["dc_flag"] == "C" else "借",
        "amount": f["amount"],
        "counterparty_name": f["counterparty_name"],
        "counterparty_account": f["counterparty_account"],
        "summary": f["summary"],
        "txn_type": t_type,
        "value_date": f["txn_date"],
        "bank_summary": bank_summary(f["summary"], t_type, f["txn_date"]),
        "counterparty_bank": bank_name(f["counterparty_account"]),
        "ext_summary": ext_summary(t_type, seq),
        "analysis_code": analysis_code(t_type),
        "info_flag": info_flag(t_type),
    }


# 招商银行网银导出 36 列（真实表头，参考真实流水文件）
CMB_EXPORT_COLS = [
    "账号", "账号名称", "币种", "交易日", "交易时间", "起息日", "交易类型",
    "借方金额", "贷方金额", "余额", "摘要", "流水号", "流程实例号", "业务名称",
    "用途", "业务参考号", "业务摘要", "其它摘要", "收(付)方分行名", "收(付)方名称",
    "收(付)方账号", "收(付)方开户行行号", "收(付)方开户行名", "收(付)方开户行地址",
    "母(子)公司账号分行名", "母(子)公司账号", "母(子)公司名称", "信息标志",
    "有否附件信息", "冲账标志", "扩展摘要", "交易分析码", "票据号", "商务支付订单号",
    "内部编号", "公司一卡通号",
]


def to_export_row(e, account_no, account_name, balance):
    """增强流水 -> 36 列导出行（dict，键为真实表头）。"""
    debit = "{:.2f}".format(e["amount"]) if e["dc_flag"] == "借" else ""
    credit = "{:.2f}".format(e["amount"]) if e["dc_flag"] == "贷" else ""
    return {
        "账号": account_no,
        "账号名称": account_name,
        "币种": e["currency"],
        "交易日": e["txn_date"],
        "交易时间": e["txn_time"],
        "起息日": e["value_date"],
        "交易类型": e["txn_type"],
        "借方金额": debit,
        "贷方金额": credit,
        "余额": "{:.2f}".format(balance),
        "摘要": e["bank_summary"],
        "流水号": e["txn_no"],
        "流程实例号": "",
        "业务名称": "",
        "用途": e["summary"] if e["dc_flag"] == "借" else "",
        "业务参考号": "",
        "业务摘要": "",
        "其它摘要": "",
        "收(付)方分行名": "",
        "收(付)方名称": e["counterparty_name"],
        "收(付)方账号": e["counterparty_account"],
        "收(付)方开户行行号": "",
        "收(付)方开户行名": e["counterparty_bank"],
        "收(付)方开户行地址": "",
        "母(子)公司账号分行名": "",
        "母(子)公司账号": "",
        "母(子)公司名称": "",
        "信息标志": e["info_flag"],
        "有否附件信息": "",
        "冲账标志": "",
        "扩展摘要": e["ext_summary"],
        "交易分析码": e["analysis_code"],
        "票据号": "",
        "商务支付订单号": "",
        "内部编号": "",
        "公司一卡通号": "",
    }
