-- 订单 + 触点数(线性归因分母): 无触点记录的用户按 1 处理(只被注册渠道触达过)
select o.*, coalesce(t.touch_cnt, 1) as touch_cnt
from {{ source('raw', 'orders') }} o
left join (select user_id, count(*) touch_cnt from {{ ref('dwd_touch') }} group by 1) t using (user_id)
