-- 把获取渠道挂到任务上: 否则北极星(创作者数)无法按渠道归因, 增长域看不到自己的动作
-- (原来 dwd_task 只有 model/platform 两个维度, 这是「北极星审计」点出的致命缺口)
select t.*, u.channel, u.channel_type, u.country
from {{ ref('dwd_task') }} t left join {{ ref('dwd_user') }} u using (user_id)
