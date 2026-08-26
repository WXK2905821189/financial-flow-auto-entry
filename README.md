# 财务流水自动入账项目

银行流水 → 数据中台 → 金蝶自动制证 → 对账留痕的一体化财务流水自动入账系统（一期）。

## 目录结构（整理后 · 前后端分离）

```
财务流水自动入账项目/
├─ backend/                 # 后端数据中台（FastAPI · 四层架构 · 分层五库）
│  ├─ app/                  #   adapters 采集适配 / services 业务 / api 接口 / core 基础设施 / models 模型
│  ├─ tests/                #   冒烟 + 专项验证脚本（smoke / R006 / R003b / API 联通）
│  ├─ scripts/              #   联调诊断脚本
│  ├─ requirements.txt / .env / .env.example
├─ frontend/                # 前端 Web 复核台（自包含 ES Module + 原生 JS，零构建，
│  │                        #   由 FastAPI 静态托管；login/复核/溯源/四看板/系统设置）
├─ docs/                    # 全部文档（按子域归类）
│  ├─ 产品经理/ 财务业务顾问/ 数据工程/   # 角色文档
│  ├─ 一期PRD/              # 模块 PRD（M1–M8）+ 技术架构图
│  ├─ 参考资料集成汇总.md · 金蝶真实对接落地要点.md · …
│  └─ (立项 / 执行方案 v3 / 部署隔离方案 / UI 原型 / 甘特图 / README-theme 等)
├─ data_engineering/        # 数据工程：schema.sql / sp.sql / mock 银行服务与流水数据
└─ submodules/              # 附带的第三方/演示
   ├─ mvp-demo/             # 独立演示（bank-mock / kingdee-mock / platform + docker-compose）
   └─ bankstatementparser-reference/   # 开源库参照树（本项目 R006/科目映射借鉴基准）
```

## 快速启动
```bash
cd backend
pip install -r requirements.txt
# 配置 .env（演示默认 SQLite；生产见 .env.example 走 MySQL 8.0）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
访问 `http://localhost:8000`，账号 `admin` / `admin123`。

## 运行测试
```bash
cd backend
python tests/smoke_test.py             # 端到端冒烟 21 项
python tests/verify_r006_mapping.py    # R006 勾稽 + 科目预填
python tests/verify_r003b_status.py    # 无户名→WARN→进复核 / FAIL→LOADED
python tests/test_api_adapter.py       # 银企 API 采集联通 10 项
```

## 一期里程碑
- 契约冻结：08-27 · 金蝶链路打通：09-16 · 一期上线：09-30

> 完整文档入口见 `docs/`；架构总览见 `docs/一期PRD/00-技术架构.svg`。