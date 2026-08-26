# -*- coding: utf-8 -*-
"""基于真实招商银行网银导出流水（36 列）重构模拟数据

- 将契约 JSON 的流水号升级为真实风格（15 位字母数字 C0947BT0000CQ2Z）
- 生成真实 36 列格式的「原始报文」JSON 与「网银导出」CSV
- 幂等：可重复运行，结果确定
"""
import csv
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.join(BASE, "..", "mock_bank_api")
sys.path.insert(0, API_DIR)

from cmb_enrich import (  # noqa: E402
    CMB_EXPORT_COLS,
    cmb_serial,
    enrich_flow,
    to_export_row,
)

ACCOUNT_NO = "7559123456789012"
ACCOUNT_NAME = "某某网络科技有限公司"
INIT_BALANCE = 3256480.50


def load_json(name):
    with open(os.path.join(BASE, name), encoding="utf-8") as f:
        return json.load(f)


def dump_json(name, obj):
    with open(os.path.join(BASE, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print("written:", name)


def enrich_flows(flows):
    """按日期分组计数生成流水号，返回 (新契约流, 增强流, 余额序列)。"""
    seq_by_date = {}
    new_flows = []
    enriched = []
    balances = []
    balance = INIT_BALANCE
    for f in sorted(flows, key=lambda x: (x["txn_date"], x["txn_time"])):
        d = f["txn_date"]
        seq_by_date[d] = seq_by_date.get(d, 0) + 1
        seq = seq_by_date[d]
        e = enrich_flow(f, seq)
        balance += f["amount"] if f["dc_flag"] == "C" else -f["amount"]
        nf = dict(f)
        nf["txn_no"] = e["txn_no"]
        new_flows.append(nf)
        enriched.append(e)
        balances.append(balance)
    return new_flows, enriched, balances


def write_raw_36col(enriched, balances):
    """真实 36 列原始报文 JSON（含需清洗样例）。"""
    rows = []
    for i, e in enumerate(enriched):
        row = to_export_row(e, ACCOUNT_NO, ACCOUNT_NAME, balances[i])
        rows.append(row)
    # 注入需清洗样例（覆盖适配层清洗逻辑）
    rows[0]["贷方金额"] = "156,800.00"          # 千分位金额
    rows[1]["币种"] = "CNY"                     # 币种代码（非中文）
    rows[3]["交易日"] = "2026/08/24"            # 斜杠日期
    rows[3]["起息日"] = "2026/08/24"
    rows[12]["币种"] = ""                        # 缺省币种
    dump_json("mock_cmb_raw_20260824.json", rows)


def write_csv_export(enriched, balances, name):
    with open(os.path.join(BASE, name), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CMB_EXPORT_COLS)
        w.writeheader()
        for e, b in zip(enriched, balances):
            w.writerow(to_export_row(e, ACCOUNT_NO, ACCOUNT_NAME, b))
    print("written:", name)


def update_contract_serials():
    """单日契约 JSON：仅升级流水号。"""
    flows = load_json("mock_cmb_flow_20260824.json")
    new_flows, _, _ = enrich_flows(flows)
    dump_json("mock_cmb_flow_20260824.json", new_flows)

    # 多日契约 JSON：按批次内日期分组升级流水号
    batches = load_json("mock_cmb_flow_20260824_28.json")
    for b in batches:
        new_b, _, _ = enrich_flows(b["flows"])
        b["flows"] = new_b
    dump_json("mock_cmb_flow_20260824_28.json", batches)


def sync_anomaly_serials():
    """异常版本：正常部分流水号与正常版本对齐；异常用例流水号重生成（新风格）。"""
    norm = load_json("mock_cmb_flow_20260824_28.json")
    norm_map = {}
    for b in norm:
        for f in b["flows"]:
            norm_map[(b["batch_no"], f["txn_date"], f["txn_time"])] = f["txn_no"]

    anom = load_json("mock_cmb_flow_20260824_28_anomaly.json")
    for b in anom:
        seq_by_date = {}
        for f in b["flows"]:
            if "_test_case" in f:
                if "txn_no" not in f:
                    continue  # R003 缺流水号：保持缺失
                key = (b["batch_no"], f["txn_date"], f["txn_time"])
                if key in norm_map:
                    f["txn_no"] = norm_map[key]  # R001 重复：与首条同号
                else:
                    d = f["txn_date"]
                    seq_by_date[d] = seq_by_date.get(d, 0) + 1
                    f["txn_no"] = cmb_serial(900000 + seq_by_date[d], d)
            else:
                key = (b["batch_no"], f["txn_date"], f["txn_time"])
                f["txn_no"] = norm_map[key]
    dump_json("mock_cmb_flow_20260824_28_anomaly.json", anom)


def main():
    # 单日：原始报文 + 导出 CSV
    flows = load_json("mock_cmb_flow_20260824.json")
    _, enriched, balances = enrich_flows(flows)
    write_raw_36col(enriched, balances)
    write_csv_export(enriched, balances, "mock_cmb_flow_20260824.csv")

    # 多日：导出 CSV（按日堆叠，与 README 口径一致）
    batches = load_json("mock_cmb_flow_20260824_28.json")
    all_flows = []
    for b in batches:
        all_flows.extend(b["flows"])
    _, enriched_all, balances_all = enrich_flows(all_flows)
    write_csv_export(enriched_all, balances_all, "mock_cmb_flow_20260824_28.csv")

    # 契约流水号升级
    update_contract_serials()

    # 异常版本流水号同步
    sync_anomaly_serials()
    print("done.")


if __name__ == "__main__":
    main()
