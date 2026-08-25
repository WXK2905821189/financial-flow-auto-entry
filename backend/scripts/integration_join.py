"""采集适配层联调脚本：消费数据工程师 mock 数据源，验证适配层映射与落库链路。

覆盖三类数据源（契约 JSON 平铺/批次数组、银行原始报文、CSV），
并对异常样例做「实际行为 vs 数据工程师预期」口径诊断。

用法：cd backend && python scripts/integration_join.py
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
from collections import Counter

_here = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_here.parents[1]))  # backend 目录

_tmp = pathlib.Path(tempfile.mkdtemp(prefix="wf_join_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'join.db'}"
os.environ["JWT_SECRET"] = "join_test_secret"
os.environ["ENVIRONMENT"] = "test"
os.environ["AUTO_PASS_ENABLED"] = "false"  # 对齐联调约定第七节：PASS/WARN → REVIEW_READY

from sqlalchemy import create_engine, func, select, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.adapters import get_adapter  # noqa: E402
from app.core.contract import SourceType  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.models import FlowValidation, TransFlow  # noqa: E402
from app.services import ingest as ingest_svc  # noqa: E402
from app.core import seed  # noqa: E402

DATA_DIR = _here.parents[2] / "数据工程" / "mock_bank_flow_data"

CMB = ("CMB", "7559123456789012")
CITIC = ("CITIC", "8110901234567890")

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), name, detail)


def load(path: pathlib.Path, bank_code: str, account_no: str):
    with open(path, "rb") as fh:
        content = fh.read()
    adapter = get_adapter(SourceType.FILE)
    return adapter.fetch(content=content, filename=path.name, bank_code=bank_code, account_no=account_no)


def make_db(name: str):
    eng = create_engine(f"sqlite:///{_tmp / f'{name}.db'}")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    with Sess() as db:
        seed.ensure_seed(db)
    return Sess


# ============ PART 1 · 适配层字段映射（不落库） ============
def part1_adapter_mapping() -> None:
    print("\n" + "=" * 62)
    print("PART 1 · 适配层字段映射（FileAdapter.fetch → 统一契约）")
    print("=" * 62)

    # 1.1 契约 JSON（平铺数组）
    cmb = load(DATA_DIR / "mock_cmb_flow_20260824.json", *CMB)
    check("map.json_cmb.count", len(cmb) == 20, f"={len(cmb)}")
    check("map.json_cmb.fields", all(t.currency == "CNY" and t.amount > 0 and t.txn_no for t in cmb), "字段口径")
    citic = load(DATA_DIR / "mock_citic_flow_20260824.json", *CITIC)
    check("map.json_citic.count", len(citic) == 15, f"={len(citic)}")

    # 1.2 CSV 与 JSON 映射等价性（同一批数据的 dedup 种子一致）
    csv_txns = load(DATA_DIR / "mock_cmb_flow_20260824.csv", *CMB)
    json_keys = {t.dedup_seed(1, 1) for t in cmb}
    csv_keys = {t.dedup_seed(1, 1) for t in csv_txns}
    check("map.csv.count", len(csv_txns) == 20, f"={len(csv_txns)}")
    check("map.csv_equiv_json", json_keys == csv_keys, f"共同 {len(json_keys & csv_keys)} 笔")

    # 1.3 银行原始报文（中文字段映射 + 值清洗）
    raw = load(DATA_DIR / "mock_cmb_raw_20260824.json", *CMB)
    check("map.raw.count", len(raw) > 0, f"={len(raw)}")
    if raw:
        check("map.raw.currency_cleaned", all(t.currency == "CNY" for t in raw), "『人民币』→CNY")
        check("map.raw.dc_valid", all(t.dc_flag.value in ("C", "D") for t in raw), "『贷/借』→C/D")
        check("map.raw.amount_cleaned", all(t.amount > 0 for t in raw), "千分位金额已清洗")

    # 1.4 多日多账户（批次数组）
    cmb28 = load(DATA_DIR / "mock_cmb_flow_20260824_28.json", *CMB)
    citic28 = load(DATA_DIR / "mock_citic_flow_20260824_28.json", *CITIC)
    check("map.multi_cmb.count", len(cmb28) == 66, f"={len(cmb28)}")
    check("map.multi_citic.count", len(citic28) == 71, f"={len(citic28)}")


# ============ PART 2 · 落库链路（正常数据） ============
def part2_ingest_pipeline() -> None:
    print("\n" + "=" * 62)
    print("PART 2 · 落库链路（正常数据 → R002–R005 校验 → 状态机）")
    print("=" * 62)

    Sess = make_db("normal")
    with Sess() as db:
        cmb = load(DATA_DIR / "mock_cmb_flow_20260824.json", *CMB)
        s1 = ingest_svc.ingest(db, transactions=cmb, source_type=SourceType.MOCK, source_ref="join/cmb")
        check("ingest.cmb_loaded", s1.loaded == 20 and s1.failed == 0 and s1.warned == 0,
              f"loaded={s1.loaded} failed={s1.failed} warned={s1.warned}")

        citic = load(DATA_DIR / "mock_citic_flow_20260824.json", *CITIC)
        s2 = ingest_svc.ingest(db, transactions=citic, source_type=SourceType.MOCK, source_ref="join/citic")
        check("ingest.citic_loaded", s2.loaded == 15 and s2.failed == 0 and s2.warned == 0,
              f"loaded={s2.loaded} failed={s2.failed} warned={s2.warned}")

        # 状态机：正常数据应全 REVIEW_READY（AUTO_PASS=false）
        rr = db.execute(select(func.count()).select_from(TransFlow)
                        .where(TransFlow.process_status == "REVIEW_READY")).scalar_one()
        check("ingest.status_review_ready", rr == 35, f"REVIEW_READY={rr}")

    # CSV 与 JSON 同一批重导 → dedup 命中（证明映射等价）
    with Sess() as db:
        cmb = load(DATA_DIR / "mock_cmb_flow_20260824.json", *CMB)
        ingest_svc.ingest(db, transactions=cmb, source_type=SourceType.MOCK, source_ref="join/cmb")
        csv_txns = load(DATA_DIR / "mock_cmb_flow_20260824.csv", *CMB)
        s3 = ingest_svc.ingest(db, transactions=csv_txns, source_type=SourceType.FILE, source_ref="join/cmb.csv")
        check("ingest.csv_switch_dedup", s3.duplicated == 20 and s3.loaded == 0,
              f"duplicated={s3.duplicated} loaded={s3.loaded}（Mock→File 切换等价）")

    # 多日多账户：137 笔全部落库、零异常
    with make_db("multi")() as db:
        cmb28 = load(DATA_DIR / "mock_cmb_flow_20260824_28.json", *CMB)
        citic28 = load(DATA_DIR / "mock_citic_flow_20260824_28.json", *CITIC)
        s4 = ingest_svc.ingest(db, transactions=cmb28 + citic28, source_type=SourceType.MOCK, source_ref="join/multi")
        check("ingest.multi_total", s4.loaded == 137 and s4.failed == 0 and s4.warned == 0,
              f"loaded={s4.loaded} failed={s4.failed} warned={s4.warned}")


# ============ PART 3 · 异常口径诊断（不硬断言，如实输出差异） ============
def part3_anomaly_diagnosis() -> None:
    print("\n" + "=" * 62)
    print("PART 3 · 异常口径诊断（实际行为 vs 数据工程师预期）")
    print("=" * 62)

    # 3.1 单条异常样例集：逐条暴露行为
    print("\n> 单条异常样例集 mock_anomaly_samples.json（逐条）")
    samples = load(DATA_DIR / "mock_anomaly_samples.json", *CMB)
    print(f"  输入样例 {len(samples)} 条 → 适配层成功映射 {len(samples)} 条？")
    # 适配层 fetch 会静默跳过部分非法值，需从原始 JSON 对比缺口
    import json
    with open(DATA_DIR / "mock_anomaly_samples.json", "rb") as fh:
        raw_samples = json.loads(fh.read().decode("utf-8-sig"))
    print(f"  原始样例 {len(raw_samples)} 条，适配层映射出 {len(samples)} 条，缺口 {len(raw_samples) - len(samples)} 条")

    Sess = make_db("anomaly")
    with Sess() as db:
        s = ingest_svc.ingest(db, transactions=samples, source_type=SourceType.MOCK, source_ref="join/anomaly_samples")
        print(f"  落库：loaded={s.loaded} duplicated={s.duplicated} failed={s.failed} warned={s.warned}")

        rules = Counter(db.execute(select(FlowValidation.rule_code)).scalars())
        print(f"  校验留痕 rule_code 计数: {dict(rules)}")
        status = Counter(db.execute(select(TransFlow.process_status)).scalars())
        print(f"  process_status 计数: {dict(status)}")

    # 3.2 异常批次（多日注入版）
    print("\n> 异常批次（多日注入版）实际 vs README §8.4 预期")
    for fname, bc, label in [
        ("mock_cmb_flow_20260824_28_anomaly.json", CMB, "招商 5批"),
        ("mock_citic_flow_20260824_28_anomaly.json", CITIC, "中信 5批"),
    ]:
        with make_db(f"anomaly_{fname[:8]}")() as db:
            txns = load(DATA_DIR / fname, *bc)
            s = ingest_svc.ingest(db, transactions=txns, source_type=SourceType.MOCK, source_ref=f"join/{fname}")
            rules = Counter(db.execute(select(FlowValidation.rule_code)).scalars())
            print(f"  [{label}] 输入 {len(txns)} 笔 → loaded={s.loaded} dup={s.duplicated} "
                  f"failed={s.failed} warned={s.warned} | 留痕={dict(rules)}")

    print("\n  ⚠ 口径对齐说明（已随 A1/A2/R006 落地）：")
    print("    1. 负金额 / dc_flag=X / 缺流水号 / 缺金额 / 金额=0 被适配层强契约拦截（跳过或 abs 清洗），R002/R003 不触发")
    print("    2. 校验 FAIL 的 process_status=A2 已置 LOADED（先落库留痕），REJECTED 仅留给人工驳回")
    print("    3. R003b 已落地（A1）：对方户名缺失 → WARN 降级转人工复核，不阻塞入库")
    print("    4. R006 批次余额勾稽：银行报表提供期初/期末余额时启用，缺省 SKIP")


def main() -> None:
    part1_adapter_mapping()
    part2_ingest_pipeline()
    part3_anomaly_diagnosis()

    print("\n" + "=" * 62)
    failed = [s for s in _results if not s[1]]
    print(f"断言汇总：共 {len(_results)} 项，PASS {len(_results) - len(failed)}，FAIL {len(failed)}")
    for name, _, detail in failed:
        print("  X", name, detail)
    print("PART 3 为口径诊断，不参与 FAIL 判定（差异需人工对齐）")


if __name__ == "__main__":
    main()