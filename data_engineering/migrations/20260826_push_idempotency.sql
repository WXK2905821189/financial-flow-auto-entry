-- 金蝶推送幂等升级：每条流水只保留一条可重试的推送记录。
-- 执行前必须先处理下列查询返回的重复流水；脚本不会删除或合并业务数据。

SELECT record_id, COUNT(*) AS push_count
FROM biz_push_record
GROUP BY record_id
HAVING COUNT(*) > 1;

-- 确认上方查询为空后执行。若生产库已存在同名索引，请跳过此语句。
ALTER TABLE biz_push_record
  ADD UNIQUE KEY uk_push_record (record_id);
