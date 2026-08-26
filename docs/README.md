# 财务流水自动入账 · 一期

银行流水 → 数据中台 → 校验/复核 → 金蝶云星空自动制证 的端到端自动化系统（一期 MVP）。

## 产品需求文档

- [财务流水自动入账系统 PRD（一期 v1）](财务流水自动入账系统PRD-v1.md)
- [一期模块 PRD 目录](一期PRD/README.md)

## 一期范围

- **数据中台**：统一流水契约、批次落库、去重校验（R001–R005）、审计哈希链、账↔单双向溯源
- **采集适配层**：可插拔数据源（Mock 模拟银行 / 文件导入 CSV·Excel / 真实银企直联 API 预留）
- **内网 Web 复核工作台**：登录门、复核队列、批量通过/驳回、流水详情抽屉、四看板（总览/银行分布/异常预警/对账钩稽）
- **金蝶推送 + 自动制证**：复核通过后一键推送、凭证号回写、双向绑定（凭据未就绪时走 Mock）

## 技术栈

- 后端：Python 3.10 + FastAPI + SQLAlchemy 2.0 + MySQL 8.0（演示/测试用 SQLite）
- 前端：自包含 ES Module + 原生 JS（无构建步骤），由 FastAPI 直接托管
- 鉴权：JWT；审计：操作全程留痕 + 哈希链防篡改

## 目录结构

```
财务流水自动入账项目/
├── backend/                  # 数据中台 + 复核工作台（代码工程）
│   ├── app/
│   │   ├── adapters/         # 采集适配层（mock / file / api 预留）
│   │   ├── services/         # 入库 / 校验 / 复核 / 推送 / 审计 / 播种
│   │   ├── api/              # REST 接口（auth/ingest/review/push/trace/dashboard）
│   │   ├── models/           # ORM 模型（ods/dwd/dim/biz/aud/用户）
│   │   └── core/             # 安全（密码哈希/JWT）
│   ├── web/                  # 前端复核台（index.html + css + js）
│   ├── smoke_test.py         # 端到端冒烟测试（21 项，SQLite 覆盖）
│   └── requirements.txt
├── 产品经理/                  # 决策表 D1–D9 契约冻结等交付物
├── 数据工程/                  # 数据中间池建表 SQL、采集联调约定、Mock 报文样本
├── 财务业务顾问/              # 统一流水契约、记账复核核销规则、溯源字段清单
└── 一期* .md / .html / .csv   # 立项架构、执行方案、分工表、甘特图、UI 原型
```

## 快速启动（开发/预览）

```bash
cd backend
pip install -r requirements.txt
# 复制 .env.example 为 .env 并按需修改；演示默认走 SQLite + Mock 推送
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问 http://localhost:8000 ，账号 `admin` / `admin123`（演示账号，上线前须改）。

端到端自检：

```bash
cd backend
python smoke_test.py   # 全部 PASS 即链路打通
```

## 版本管理

- 当前版本：**v0.1.0**（一期 MVP 基线）
- 版本标记：`release/v0.1.0` 分支 + 带版本号的基线提交
- 回退方式：在 GitHub 仓库 `Commits`/`Branches`/`Tags` 中选择目标历史提交或 `release/vX.Y.Z` 分支即可恢复对应版本

## 里程碑

| 里程碑 | 目标日期 |
| --- | --- |
| 契约冻结 | 2026-08-27 |
| 链路打通 | 2026-09-16 |
| 一期上线 | 2026-09-30 |

## 遗留依赖（上线前须落实）

- 银企直联 API 凭据（决策 D3）：`backend/app/adapters/api_adapter.py` 预留切换点
- 金蝶云星空 OpenAPI 凭据（决策 D8）：`backend/app/services/kingdee.py` 预留切换点
- 银行存款科目映射表（中信&招商全账户→银行存款明细科目）：财务 UAT 前提供
