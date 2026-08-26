# models（中台数据模型 · 跨域共享语言，保留分层不拆域）

- ods.py（原始流水，append-only）→ dwd.py（标准化主表/批次）→ dim.py（维度）→ biz.py（复核/推送状态）→ aud.py（追加式审计）→ sys_user.py
- 采集落 `dwd_trans_flow`，复核/推送/看板/溯源均读写同批表；硬拆会造成 ORM 重复与循环依赖，故整体保留。
- 主表含 ext_json / version 扩展位；aud_audit_log 用 hash 链防篡改。