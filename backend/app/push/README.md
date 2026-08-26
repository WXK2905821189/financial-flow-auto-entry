# push（金蝶推送/制证域）

需读文件  ：api.py service.py kingdee.py
依赖契约 ：app.core.contract、app.core.audit、app.models
入口示例 ：POST /api/push/record、POST /api/push/batch
验证命令 ：python backend/tests/smoke_test.py、backend/tests/verify_review_push.py
数据约束 ：每条流水仅一条 push 记录；失败重试更新同一记录，UNCERTAIN 必须先查单确认
不依赖   ：ingest / review / dashboard / settings / trace / auth
