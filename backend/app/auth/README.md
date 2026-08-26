# auth（认证域）

需读文件  ：api.py
依赖契约 ：app.core.security、app.core.database、app.models.sys_user
入口示例 ：POST /api/auth/login（签发 JWT）
验证命令 ：python backend/tests/smoke_test.py
不依赖   ：ingest / review / push / dashboard / settings / trace