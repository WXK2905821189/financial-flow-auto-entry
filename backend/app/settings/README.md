# settings（设置/对接状态域）

需读文件  ：api.py
依赖契约 ：app.core.config、app.core.deps、app.models
入口示例 ：GET /api/settings/*（对接状态健康检查）
验证命令 ：python backend/tests/smoke_test.py
依赖例外 ：健康检查需读 ingest/adapters（单向、函数级、不回传）
不依赖   ：review / push / dashboard / trace / auth