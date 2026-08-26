# backend 按域重构 · 迁移清单与执行方案（v1）

> 目标：让 AI「改一个模块」时只需读**一个域目录 + 核心契约**，而不是读整个项目，
> 从而降低每次改动的 token/context 开销。
> 手段：把当前「按层横切」的 `backend/app`（adapters / services / models / api）
> 重构为「按业务域纵切」的自包含目录。

> 状态：方案稿，待评审后分阶段执行。每个阶段保持「冒烟测试全绿」的无中间态原则。

---

## 一、现状与问题

当前四层横向铺开，一个功能横跨多个目录：

```
backend/app/{adapters, services, models, api}
```

典型例子——改「采集」要读：`adapters/*` + `services/ingest.py` + `services/validation.py`
+ `services/account_mapper.py` + `api/ingest.py` + `models/ods|dwd|dim.py`，
AI 为判断边界被迫读大半个项目。

**依赖现状（据实读代码核实）**：

| 模块 | 依赖 | 归属 |
|---|---|---|
| `services/audit.py` | models | 被 ingest/review/push 共用 → **共享** |
| `services/seed.py` | config、core.security、models | 启动播种 → **共享** |
| `services/account_mapper.py` | models、contract | 被 ingest 用 + review 读其常量 → **跨域** |
| `api/deps.py` | core.security | 所有 API 共用 → **共享** |
| `config/database/contract/core.*` | — | 全局基础设施 → **共享** |
| `services/ingest.py` | audit、account_mapper、validation、models | **采集域** |
| `services/validation.py` | config、contract | **采集域** |
| `adapters/*` | contract | **采集域** |
| `services/review.py` | audit、models | **复核域** |
| `services/push.py` | audit、kingdee | **推送域** |
| `services/kingdee.py` | config、models | **推送域** |
| `api/dashboard.py` | models | **看板域** |
| `api/settings.py` | adapters.api_adapter、config、database | **设置域** |
| `api/trace.py` | models | **溯源域** |
| `api/auth.py` | core.security、database、models.sys_user | **认证域** |

---

## 二、目标结构

```
backend/app/
├─ main.py                       # 组装：注册各域 router + 静态托管
├─ core/                         # ★ 共享基础设施（不属任何业务域）
│  ├─ config.py                  # ← app/config.py
│  ├─ contract.py                # ← app/contract.py（含 AUTO_SUBJECT_KEY 上提）
│  ├─ database.py                # ← app/database.py
│  ├─ deps.py                    # ← app/api/deps.py（get_db/get_current_user）
│  ├─ retry.py                   # → 原位（core/retry.py）
│  ├─ security.py                # → 原位
│  ├─ audit.py                   # ← app/services/audit.py（跨域审计）
│  └─ seed.py                    # ← app/services/seed.py（启动播种）
├─ models/                       # 中台数据模型（保留分层，不拆域）
│  ├─ ods.py dwd.py dim.py biz.py aud.py sys_user.py
├─ ingest/                       # 采集域（端到端自包含）
│  ├─ api.py                     # ← app/api/ingest.py
│  ├─ service.py                 # ← app/services/ingest.py
│  ├─ validation.py              # ← app/services/validation.py
│  ├─ mapper.py                  # ← app/services/account_mapper.py
│  └─ adapters/
│     ├─ base.py registry.py     # ← app/adapters/base.py, registry.py
│     ├─ mock_adapter.py         # ← 原位迁移
│     ├─ file_adapter.py         # ← 原位迁移
│     └─ api_adapter.py          # ← 原生保留 + 真实 API 接入点
├─ review/                       # 复核域
│  ├─ api.py                     # ← app/api/review.py
│  └─ service.py                 # ← app/services/review.py
├─ push/                         # 金蝶推送/制证域
│  ├─ api.py                     # ← app/api/push.py
│  ├─ service.py                 # ← app/services/push.py
│  └─ kingdee.py                 # ← app/services/kingdee.py
├─ dashboard/                    # 看板域
│  └─ api.py                     # ← app/api/dashboard.py
├─ settings/                     # 设置/对接状态域
│  └─ api.py                     # ← app/api/settings.py
├─ trace/                        # 溯源域
│  └─ api.py                     # ← app/api/trace.py
└─ auth/                         # 认证域
    └─ api.py                    # ← app/api/auth.py
```

> **为什么 `models/` 不拆进域**：中台数据模型是跨域共享语言（采集落 `dwd_trans_flow`，
> 复核/推送/看板/溯源均读写同批表）。硬拆会造成同一 ORM 类在多处重复 + 循环依赖，
> 收益低于成本。故作为独立共享层保留，各域仅依赖它。
> 同样，`audit`、`seed`、`deps`、`config`、`database`、`contract` 为横切共享，统一收进 `core/`。

---

## 三、作用域边界（单向依赖，禁止回环）

```
auth ─┐
ingest ─┤
review ─∧─→ core/(config,contract,database,deps,retry,security,audit,seed) ＋ models
push  ─┤
dashboard/settings/trace ─┘

允许的域间依赖（不反向）：
  ingest.mapper ← review/api.py 仅读核心常量（见 AUTO_SUBJECT_KEY 上提，见 §五.3）
  settings.api   → ingest.adapters（健康检查），单向，不回传
```

写入各域 `README.md` 的「依赖」栏，并向 AI 声明：**本域只依赖 core 契约与管理层，不得 import 其它域内部。**

---

## 四、文件级迁移清单

> 一律用 `git mv` 保留历史。每完成一批立即跑冒烟，禁止长时间停留在「拷贝一半」的中间态。

### 4.1 共享层（阶段 1，先行）

| 源 | 目标 |
|---|---|
| `app/config.py` | `app/core/config.py` |
| `app/contract.py` | `app/core/contract.py` |
| `app/database.py` | `app/core/database.py` |
| `app/api/deps.py` | `app/core/deps.py` |
| `app/services/audit.py` | `app/core/audit.py` |
| `app/services/seed.py` | `app/core/seed.py` |
| `app/core/retry.py` | 原位 |
| `app/core/security.py` | 原位 |

### 4.2 采集域（阶段 2a）

| 源 | 目标 |
|---|---|
| `app/adapters/base.py` | `app/ingest/adapters/base.py` |
| `app/adapters/registry.py` | `app/ingest/adapters/registry.py` |
| `app/adapters/mock_adapter.py` | `app/ingest/adapters/mock_adapter.py` |
| `app/adapters/file_adapter.py` | `app/ingest/adapters/file_adapter.py` |
| `app/adapters/api_adapter.py` | `app/ingest/adapters/api_adapter.py` |
| `app/services/ingest.py` | `app/ingest/service.py` |
| `app/services/validation.py` | `app/ingest/validation.py` |
| `app/services/account_mapper.py` | `app/ingest/mapper.py` |
| `app/api/ingest.py` | `app/ingest/api.py` |

### 4.3 复核 / 推送 / 展示域（阶段 2b）

| 源 | 目标 |
|---|---|
| `app/services/review.py` | `app/review/service.py` |
| `app/api/review.py` | `app/review/api.py` |
| `app/services/kingdee.py` | `app/push/kingdee.py` |
| `app/services/push.py` | `app/push/service.py` |
| `app/api/push.py` | `app/push/api.py` |
| `app/api/dashboard.py` | `app/dashboard/api.py` |
| `app/api/settings.py` | `app/settings/api.py` |
| `app/api/trace.py` | `app/trace/api.py` |
| `app/api/auth.py` | `app/auth/api.py` |

### 4.4 组装与收尾（阶段 2c）

- `app/main.py`：路由注册改为 import 各域 `*.api` 的 `router`；删除对 `app.services.seed` 的引用改为 `app.core.seed`。
- 删除 `app/api/__init__.py`、`app/services/__init__.py`、`app/adapters/__init__.py` 的旧汇总逻辑（或其职责并入各域 `__init__`，只做轻量汇集不承载业务）。

---

## 五、import 改写映射（同步执行，逐项核对）

> 不允许全库盲文本替换。先 `grep -rn` 定位每条旧路径，改一处、随跑随验；
> `from app.services import X, Y` 这种多目标行更要逐 import 拆分。

| 旧 | 新 |
|---|---|
| `from app.config import settings` | `from app.core.config import settings` |
| `from app.contract import ...` | `from app.core.contract import ...` |
| `from app.database import get_db / SessionLocal / Base / engine` | `from app.core.database import ...` |
| `from app.api.deps import get_current_user` | `from app.core.deps import get_current_user` |
| `from app.core.security import ...` | 不变 |
| `from app.adapters import get_adapter` | `from app.ingest.adapters import get_adapter` |
| `from app.adapters.api_adapter import ...` | `from app.ingest.adapters.api_adapter import ...` |
| `from app.adapters.base import BaseAdapter` | `from app.ingest.adapters.base import BaseAdapter` |
| `from app.services import ingest as ingest_svc` | `from app.ingest import service as ingest_svc` |
| `from app.services import review as review_svc` | `from app.review import service as review_svc` |
| `from app.services import push as push_svc` | `from app.push import service as push_svc` |
| `from app.services import validation as validation_svc` | `from app.ingest import validation as validation_svc` |
| `from app.services import account_mapper as mapper_svc` | `from app.ingest import mapper as mapper_svc`（仅读业务逻辑处） |
| `from app.services import audit as audit_svc` | `from app.core import audit as audit_svc` |
| `from app.services.kingdee import get_kingdee_client` | `from app.push.kingdee import get_kingdee_client` |
| `from app.services.seed import ensure_seed` | `from app.core.seed import ensure_seed` |
| `from app.models import ...` | 不变（models 保留原位） |

### 5.1 需要同步改的后端入口与测试

- `backend/app/main.py`
- `backend/tests/smoke_test.py`
- `backend/tests/test_api_adapter.py`
- `backend/tests/verify_r003b_status.py`
- `backend/tests/verify_r006_mapping.py`（`from app.services import ingest as ingest_svc` → 同理）

> 前端 `frontend/` 与静态托管路径不变，不受本次重构影响。

### 5.2 兼容层（可选，降低风险）

若想分两次验证而非一次性大爆炸，可先保留旧路径作为「重导出桩」：

```python
# 临时 app/services/__init__.py
from app.ingest.service import ingres      # 等等——此例仅示意：注意命名冲突
```

> 建议用显式模块别名而非裸 re-export，避免 `from app.services import ingest` 与 `app.ingest` 包名冲突。
> 阶段 3 稳定后即删除全部兼容桩。

### 5.3 `AUTO_SUBJECT_KEY` 上提（消除跨域耦合）

`account_mapper.AUTO_SUBJECT_KEY = "auto_subject"` 被 `api/review.py` 读取透出到复核台。
迁移时把它**上提到 `core/contract.py`**，`ingest/mapper.py` 与 `review/api.py` 统一
`from app.core.contract import AUTO_SUBJECT_KEY`，使 review 域不必 import ingest 内部。

---

## 六、模块上下文资产（让 AI 最小化读取）

### 6.1 根目录 `AGENTS.md`（极简导航，一两屏）

```markdown
# 导航
- 改「采集」→ backend/app/ingest/，只需读该目录 + core/contract.py
- 改「复核」→ backend/app/review/
- 改「金蝶推送」→ backend/app/push/
- 改「看板/设置/溯源/认证」→ 对应域目录
- 跨域共享（config/契约/审计/播种/DB）→ backend/app/core/
- 数据模型（共用表）→ backend/app/models/
- 验证：cd backend && python -m pytest tests/（含 smoke、verify_*）
- 完整域依赖矩阵见 module_manifest.json
```

### 6.2 每域 `README.md`（固定四项模板）

```
# ingest（采集域）
需读文件  ：api.py service.py validation.py mapper.py adapters/
依赖契约 ：app.core.contract、app.core.audit、app.core.seed、app.models
入口示例 ：POST /api/ingest/mock|api|file
验证命令 ：python backend/tests/smoke_test.py
不依赖   ：review / push / dashboard / settings / trace / auth
```

### 6.3 `module_manifest.json`（机器可读，供未来 MCP/工具只暴露目标域）

```json
{
  "root": "backend/app",
  "shared": ["core", "models"],
  "domains": {
    "ingest":     {"path": "ingest",     "deps": ["core", "models"]},
    "review":     {"path": "review",     "deps": ["core", "models", "ingest(mapper 常量)"]},
    "push":       {"path": "push",       "deps": ["core", "models"]},
    "dashboard":  {"path": "dashboard",  "deps": ["core", "models"]},
    "settings":   {"path": "settings",   "deps": ["core", "models", "ingest(健康检查)"]},
    "trace":      {"path": "trace",      "deps": ["core", "models"]},
    "auth":       {"path": "auth",       "deps": ["core", "models"]}
  }
}
```

---

## 七、分阶段执行方案（每阶段跑通冒烟才进下一步）

| 阶段 | 内容 | 验证门禁 |
|---|---|---|
| 0 基线 | `git checkout -b feature/refactor-ddd`；跑全部测试存档 | 〈基线全绿〉 |
| 1 共享层 | 迁 `core/`（4.1）+ §五 对应 import | `smoke_test.py` 绿 |
| 2a 采集域 | 迁 `ingest/`（4.2） | `smoke_test.py`＋`test_api_adapter.py` 绿 |
| 2b 其余域 | 迁 `review/push/dashboard/settings/trace/auth`（4.3） | `smoke_test.py` 绿 |
| 2c 组装 | 改 `main.py`、删旧汇总 `__init__`（4.4） | 页面可开 + `/api/health` 200 |
| 3 收尾 | `verify_r003b_status.py`＋`verify_r006_mapping.py` 全绿；删兼容桩 | 全部测试绿 |
| 4 资产 | 根 `AGENTS.md`、各域 `README.md`、`module_manifest.json` | 抽查导航可读 |

验收标准（未达到即为失败，回滚阶段）：
1. `backend/tests/` 下 smoke / test_api / verify_r003b / verify_r006 全部通过。
2. 服务启动无 import 错误，`/api/health` 200，前端页面正常打开。
3. 域间依赖呈树状单向，`module_manifest.json` 与实际 import 一致（可用 `grep -rn "from app\.\|import app\."` 事后校验：非 core/models 的域间 import 若有跨域即违规）。

---

## 八、风险与权衡

| 项 | 说明 | 缓解 |
|---|---|---|
| 大范围 import 改动易错 | 20+ 文件路径变更 | 兼容层两阶段迁移、逐项 grep、无中间态 |
| `account_mapper` 跨域 | ingest 用逻辑、review 读常量 | `AUTO_SUBJECT_KEY` 上提 `core/contract` 解耦 |
| 循环导入 | 域间双向引用会炸 | 强制单向依赖 core/models；manifest 回扫校验 |
| settings→ingest 依赖 | 健康检查必然引用适配器 | 单向声明，不回传；README 注明 |
| git 历史断裂 | 硬搬家丢历史 | 全程 `git mv` |
| token 收益兑现 | 文档/结构只是前提，真正收益在工具与 AGENTS 是否引导 AI 小步读取 | 每个域 README 写明「只需读本域+契约」 |

**收益预估**：以「改采集」为例，读取范围由当前 ~6 个分散目录收敛为 `app/ingest/` + `app/core/contract.py`（+`models`），单次改动需要加载的 token 显著下降；`module_manifest.json` 未来可接 MCP/插件做「只向模型暴露目标域」。

---

*本方案为执行性文档；具体落地请逐阶段按 §七 执行，并以 §七「验收标准」作为每个阶段是否可继续的唯一判据。*