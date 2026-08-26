# dashboard（看板域）

需读文件  ：api.py
依赖契约 ：app.core.contract、app.core.deps、app.models
入口示例 ：GET /api/dashboard/summary、/overview、/bank-distribution、/exceptions、/recon
验证命令 ：python backend/tests/smoke_test.py
不依赖   ：ingest / review / push / settings / trace / auth