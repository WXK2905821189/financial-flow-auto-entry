# ingest（采集域）

需读文件  ：api.py service.py validation.py mapper.py adapters/
依赖契约 ：app.core.contract、app.core.audit、app.core.seed、app.models
入口示例 ：POST /api/ingest/mock|api|file
验证命令 ：python backend/tests/smoke_test.py、backend/tests/test_api_adapter.py
不依赖   ：review / push / dashboard / settings / trace / auth