# review（复核域）

需读文件  ：api.py service.py
依赖契约 ：app.core.contract、app.core.audit、app.models（AUTO_SUBJECT_KEY 出自 core/contract）
入口示例 ：GET /api/review/pending、POST /api/review/decide、POST /api/review/decide-batch
验证命令 ：python backend/tests/smoke_test.py、backend/tests/verify_r003b_status.py、backend/tests/verify_review_push.py
复核门禁 ：仅 REVIEW_READY 可复核；通过需规则科目，人工调整需填写科目编码
不依赖   ：ingest（内部）/ push / dashboard / settings / trace / auth
