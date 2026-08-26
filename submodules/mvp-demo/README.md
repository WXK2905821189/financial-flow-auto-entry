# 一期 MVP 演示栈 · 一键启动说明

在**本机 Docker** 上跑通「测试银行 → 数据中台（采集/校验/复核）→ 测试金蝶」的完整数据流动闭环，
并用一个**可视化页面**让非技术人员也能看清每笔流水如何从银行流到凭证。

> 性质：**演示脚手架**，非生产。真实契约 / 字段映射 / 金蝶凭据待数据与全栈输出后替换（对应方案 O2/O3），本目录只用于先「让人能看到跑通」。

---

## 一、目录结构

```
mvp-demo/
├── docker-compose.yml      # 一键编排 4 服务 + MySQL
├── bank-mock/              # 测试银行 Mock：返回模拟流水（含 2 类脏数据供校验演示）
├── platform/               # 数据中台：采集/校验/落库/复核/推送 + 审计；内含可视化演示页
├── kingdee-mock/           # 测试金蝶 Mock：接收推送，生成凭证号并回显
└── platform/init.sql       # MySQL 初始化：独立中间池库表（批次/流水/复核/推送/审计）
```

| 服务 | 角色 | 说明 |
|-|-|-|
| `mysql:8.0` | 数据中间池 | 独立容器，承载 batches / transactions / review_log / push_log / audit_log |
| `bank-mock` | 测试银行 | `GET /transactions` 返回一批原始流水，故意埋**负金额 / 缺户名 / 重复流水号** |
| `platform` | 数据中台 | `:8080` 对外演示入口；执行校验、复核、推送 |
| `kingdee-mock` | 测试金蝶 | `POST /vouchers` 生成测试凭证号，供溯源回查 |

---

## 二、前置：安装 Docker Desktop

本机已有则跳过；未安装请先看同目录《安装 Docker Desktop 指引（本机）.md》。

## 三、一键启动

```powershell
cd "c:\Users\王小棵\Documents\财务流水自动化\财务流水自动入账项目\mvp-demo"
docker compose up --build -d

# 查看是否全部起来
docker compose ps

# 打开演示入口（http://localhost:8080）
start http://localhost:8080
```

首次拉起会构建镜像并初始化数据库，等 `mvp-platform`、`mvp-mysql` 状态为 `Up`（healthy）即可。

## 四、演示动线（页面上从左到右点三步）

> 页面底部 Tab 可切换 原始流水 / 中台落库&校验 / 复核&推送留痕 / 金蝶凭证 / 溯源&审计。

1. **① 采集&校验（银行→中台）**
   从测试银行拉取流水 → 中台逐一校验 → 独立 MySQL 落库。
   ⚠️ 能看到 6 条中 **3 条有效、3 条被拦截**（负金额 / 缺户名 / 重复流水号），演示"防错校验"真实拦下脏数据。

2. **② 人工复核通过**
   对"有效"流水执行人工复核兜底（human-in-the-loop），记录复核人与时间留痕。

3. **③ 一键推送金蝶制证**
   复核通过的流水经 OpenAPI 式调用推到测试金蝶，生成测试凭证号并回显——至此 **银行→中台→金蝶数据流动完成**。

4. **溯源 & 审计**（右上 Tab）
   用凭证号/流水号/摘要回查 **流水 ⇄ 凭证** 双向来源；审计日志只追加，记录 采集/复核/推送 全程操作。

## 五、停止 / 清库重演

```powershell
# 停止（保留数据）
docker compose down

# 彻底重置（清空 MySQL 数据卷，可重新演示）
docker compose down -v
docker compose up --build -d
```

## 六、其它

| 事项 | 说明 |
|-|-|
| 演示复核账号 | `DEMO_AUDITOR=cnxiao`（见 compose，MVP 简版角色占位） |
| 端口占用 | 对外仅 `8080`（演示页）与 `33061`（按需连 MySQL）；如冲突可在 compose 改映射 |
| 生产部署 | 本目录定位演示；正式部署回落到《部署与安全隔离方案（v1）》第 9–10 章 |