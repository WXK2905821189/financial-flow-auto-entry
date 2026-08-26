# core（共享基础设施 · 横切，不属于任何业务域）

- config.py（环境配置）、contract.py（统一流水契约＋跨域常量，如 AUTO_SUBJECT_KEY）
- database.py、deps.py（get_db / get_current_user）、security.py、retry.py
- audit.py（跨域审计）、seed.py（启动播种维表/初始管理员）

依赖纪律：core 与 models 是所有域的**唯一**公共依赖，不允许反过来依赖业务域。