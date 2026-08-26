# GitHub 同步续传指引（本会话写工具不可用，新会话执行）

> 说明：本会话中 GitHub 连接器的**读工具**可用，但**写工具**报框架错「MCP server '' not found」——这是官方限制，
> GitHub 写授权已成功授予，但须在**新会话**中才生效，因此当前**未产生任何提交，远端未被改动**。
> 本文件承载完成本次「同步 backend + frontend 项目主体到 GitHub」所需的全部上下文，请粘贴到新会话。

---

## 任务
把本地 `backend/` + `frontend/` 项目主体同步到 GitHub 仓库，目标仓库：
`WXK2905821189/financial-flow-auto-entry`，分支 `main`。

## 执行方式
- 用 GitHub 连接器（run_mcp，server_name = `mcp_plugin_GitHub_github`）的 **`push_files`** 一次性多文件单提交。
- 每次提交参数：`{"owner": "WXK2905821189", "repo": "financial-flow-auto-entry", "branch": "main", "message": "...", "files": [{"path": "backend/xxx | frontend/xxx", "content": "..."}]}`。
- `path` 相对仓库根、用正斜杠；`content` 以**本地磁盘当前内容**为准（用 Read 逐文件读取，原样放入）。

## 范围边界（硬性）
- **只推 `backend/` + `frontend/`**。其余顶层目录（docs / data_engineering / submodules / archive）一律不传。
- **排除**：任何 `.env`（仅允许 `backend/.env.example`）、`waterflow.db` / `*.db` / `*.sqlite`、`__pycache__`、`*.pyc`、二进制文件。
- `backend/vendor/` 为金蝶官方 SDK 轮子（第三方参考），**不传**。
- `backend/scripts/integration_join.py` 的 §PART3 口径注释已按 A1/A2/R006 更新
  （校验 FAIL→LOADED、R003b 已落地转人工、R006 缺省 SKIP），务必以磁盘当前内容为准，勿用旧版。

## 建议的 4 个提交分组（可自行按需微调）
1. `backend/` 根 + `backend/tests/` + `backend/scripts/`：
   - `backend/.env.example`、`backend/requirements.txt`
   - `backend/tests/smoke_test.py`、`backend/tests/test_api_adapter.py`、`backend/tests/verify_r003b_status.py`、`backend/tests/verify_r006_mapping.py`
   - `backend/scripts/integration_join.py`
   - message：`feat(backend): 同步入口脚本/测试/联调诊断`
2. `backend/app/` 的 adapters + core + api：
   - `app/__init__.py`、`app/config.py`、`app/contract.py`、`app/database.py`、`app/main.py`
   - `app/core/__init__.py`、`app/core/retry.py`、`app/core/security.py`
   - `app/adapters/__init__.py`、`base.py`、`registry.py`、`mock_adapter.py`、`file_adapter.py`、`api_adapter.py`
   - `app/api/__init__.py`、`auth.py`、`deps.py`、`ingest.py`、`review.py`、`push.py`、`trace.py`、`dashboard.py`、`settings.py`
   - message：`feat(backend/app): 同步采集适配/API路由/校验入库/设置页`
3. `backend/app/` 的 models + services：
   - `app/models/__init__.py`、`aud.py`、`biz.py`、`dim.py`、`dwd.py`、`ods.py`、`sys_user.py`
   - `app/services/__init__.py`、`seed.py`、`validation.py`、`ingest.py`、`account_mapper.py`、`audit.py`、`push.py`、`review.py`、`kingdee.py`
   - message：`feat(backend/app): 同步模型/服务（R001–R006 校验、科目预填、金蝶推送）`
4. `frontend/` 前端复核台（由原 backend/web 前后端分离而来）：
   - `frontend/index.html`、`frontend/css/app.css`、`frontend/js/api.js`、`main.js`、`review.js`、`trace.js`、`dashboards.js`、`settings.js`、`ui.js`
   - message：`feat(frontend): 同步内网复核台（含系统设置页）`

## 完成后回执
- 逐组回报：提交是否成功、推送文件数、git commit 详情；以及失败/跳过的文件清单。
- 全部成功后核验：`https://github.com/WXK2905821189/financial-flow-auto-entry` 的 `backend/` 与 `frontend/` 与本地一致。