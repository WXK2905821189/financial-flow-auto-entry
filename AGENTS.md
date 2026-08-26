# 导航（按业务域纵切，改一个模块只需读一个域 + 核心契约）

- 改「采集」→ `backend/app/ingest/`，只需读该目录 + `core/contract.py`
- 改「复核」→ `backend/app/review/`
- 改「金蝶推送/制证」→ `backend/app/push/`
- 改「看板 / 设置对接状态 / 溯源 / 认证」→ 对应 `dashboard` / `settings` / `trace` / `auth` 域目录
- 跨域共享（config / 契约 / 数据库 / 审计 / 播种 / 令牌 / 重试）→ `backend/app/core/`
- 数据模型（跨域共用表 ods/dwd/dim/biz/aud/sys_user）→ `backend/app/models/`
- 验证：`cd backend && python tests/smoke_test.py`；含 `test_api_adapter.py`、`verify_r003b_status.py`、`verify_r006_mapping.py`
- 完整域依赖矩阵见 `backend/app/module_manifest.json`

## 依赖纪律
- 每个域**只能依赖** `core/`＋`models/`，不得 import 其它业务域内部（单向，禁止回环）。
- 唯一例外：`settings/api.py` 可在健康检查里读 `ingest/adapters`（单向、函数级、不回传）。
- 若发现某个域要读别的域内部，先把共享常量上提到 `core/contract.py`（例：`AUTO_SUBJECT_KEY`）。