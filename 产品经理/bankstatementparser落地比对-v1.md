# bankstatementparser 落地比对 · 财务流水自动入账一期

> 比对日期：2026-08-25 · 产品经理
> 参考仓库：sebastienrousseau/bankstatementparser（main 分支，Apache-2.0/MIT 双许可）
> 比对对象：一期 backend `backend/app/`（contract.py / services / adapters 四层架构）
> 属主文件：`contract.py`、`services/ingest.py`、`services/validation.py`、`services/review.py`、`services/audit.py`

---

## 一、比对总览

| 能力维度 | bsp 实现 | 一期现状 | 结论 |
|---|---|---|---|
| 统一流水模型 | `Transaction`（含 normalized_description / transaction_hash / source_method / confidence） | `BankTransaction`（父子字段 + dc_flag + dedup_seed） | **一期领先**：dc_flag 分列优于正负号；borrow 归一化+occurrence 兜底去重 |
| 幂等去重 | 主 hash + occurrence 计数 + 模糊分层 | R001 + dedup_key 唯一索引 | **一期领先**（依赖银行 txn_no 更可靠）；可补 txn_no 缺失兜底 |
| 数据校验 | Golden Rule 批次勾稽 + 逐笔字段校验 | R001–R005 逐笔校验 | **一期缺口**：缺批次级余额勾稽 |
| 对方科目归类 | `account_mapper` 有序正则首条命中 | 仅复核人工 matched_subject | **一期缺口**：P1「规则命中自动预填」未实现 |
| 审计溯源 | captured source + 透明溯源 + PII 脱敏 | `append_audit` 哈希链 + verify_chain | **一期领先**：哈希链防篡改更强 |
| 采集/解析 | CAMT/OFX/MT940/CSV/PDF + LLM/vision | 三源适配器（Mock/文件/API） | 不引入 PDF/OCR/LLM |

---

## 二、六项落地比对

### 1. 统一流水模型（contract.py ↔ transaction_models.py）

- bsp `Transaction.transaction_hash` = `MD5(date|normalized_description|amount|id)`；`normalize_description()` 会**剥离日期、时间、长数字流水号等噪声 token 后统一小写**，使同一商户多日账单 hash 稳定。
- 一期 `dedup_seed` = `SHA256(bank|account|txn_no|txn_date|amount|dc_flag)`，依赖银行 `txn_no`。

**可借鉴**：一期 `summary` 尚无归一化。建议在适配层增加一次摘要清洗（去空白/统一大小写/剥离流水号），用途：① 幂等去重在 `txn_no` 缺失时的兜底；② 后续规则匹配（P1）的稳定性。

### 2. 幂等去重（ingest.py R001 ↔ transaction_deduplicator.py）

- bsp `dedupe_by_hash` 用 **occurrence-counted `<hash>:<n>`**，批内第 n 次出现匹配第 n 个已存键，既保证幂等、又**不把同一天同金额的两笔真单误丢**。
- 一期 `ingest._ingest_group` 以 `dedup_key in seen` + 全表去重；当一行 `txn_no` 为空时，`(bank|account|""|日期|金额|方向)` 会撞，可能静默丢单。

**可借鉴（小改）**：仅当 `txn_no` 缺失时为该行追加 `occurrence` 序号进 dedup_key（batch 内计数），避免无号真单被误判重复。

### 3. 数据校验（validation.py ↔ input_validator / hybrid.verification）

- bsp 提供**批次级 Golden Rule**：`期初余额 + Σ贷方 − Σ借方 = 期末余额`（借/贷按金额方向），逐币/逐账户勾稽，不平衡整批告警。
- 一期 R001–R005 全为**单笔**校验，`ingest` 虽写了 `batch.total_amount`，但**未做期初/期末余额勾稽**。

**可借鉴（一期缺口，推荐新增）**：报表含期初/期末余额时，新增一条**批次级校验（如 R006 批次勾稽）**：`期初 + Σ收入 − Σ支出 = 期末`；不平衡 → 批次 WARN/FAIL 转人工。这项工作需银行报表字段（period_begin_balance / period_end_balance）进契约，建议在 8/27 契约冻结前与数据工程师、财务顾问对齐字段。

### 4. 对方科目归类（review.py ↔ enrichment/account_mapper.py）

- bsp `account_mapper`：**有序正则规则、首条命中优先**，结果落到 Transaction.category。
- 一期 `ReviewResult.ADJUST` 仅保存人工 `matched_subject` 到 ext_json，**无自动预填**。

**可借鉴（一期缺口，直投 P1）**：建立规则表 `[{pattern关键词/正则, direction, subject_code, subject_name, priority}]`，入复核队列前做规则命中自动预填对方科目；未命中流入批量人工指定。规则表可落一张配置文件或 `dim` 表。与既有决策 P1（规则命中自动预填 + 其余批量人工）完全一致。

### 5. 审计溯源（audit.py ↔ Transaction.source 系列）

- bsp 靠 `source / source_index / source_method / raw_source_text` 做透明溯源（非篡改防御）。
- 一期 `append_audit` = **只追加 + 前/后 row_hash 链接 + verify_chain 回放**，防篡改能力更强。

**结论：一期保持，无需改。** 可选增强：审计 detail 中对手账号/户名做脱敏（对齐 bsp PII 脱敏思路）。

### 6. 采集/解析

- bsp 的 PDF/OCR/vision、LLM 提取、多币种续账属于其复杂解析能力，一期银行商行流水不涉及。

**结论：明确不引入**（理由见第三节）。

---

## 三、分三级落地

### ✅ 建议采纳（直投一期已有决策）
1. **R006 批次余额勾稽校验** —— 填补对账可靠性缺口（需契约补期初/期末余额字段，先对齐数据工程师与财务顾问）。
2. **规则式对方科目自动预填** —— 落地 P1「规则命中自动预填 + 其余批量人工指定」，借鉴 account_mapper 有序规则数据结构。
3. **摘要归一化** —— summary 清洗，服务去重兜底与规则匹配稳定性。

### 🟡 一期保持领先（不必改动）
- audit 哈希链（audit.py 已优于 bsp）。
- 依赖银行 txn_no 的主去重策略（比 bsp 模糊相似度更可靠，无需引入 SequenceMatcher 分层）。

### 🚫 明确不引入（防 scope 蔓延，P1 已定）
- PDF/OCR/vision、LLM/AI 智能匹配分类（P1 已定不做 AI）。
- 模糊相似度去重（probable/temporal）、多币种复杂勾稽。

**许可证**：bsb 为 Apache-2.0/MIT 双许可，规则数据结构、校验逻辑可参考/改写；不建议整包引入（其依赖 pandas/LiteLLM 与一期轻量栈不符）。

---

## 四、对契约冻结（8/27）的影响

若要推 R006 批次勾稽，需在契约冻结前确认是否引入银行报表期初/期末余额字段（由财务业务顾问判断银行流水是否带该数据）。此项为**可选增强**，不阻塞一期范围；若字段不可得，R006 在本期不启用，仅保留勾稽逻辑钩子。

其余两项（科目预填、摘要归一化）均落在现有契约/模型结构内，可于工作包联调期一并落地，无需变更已冻结字段口径。