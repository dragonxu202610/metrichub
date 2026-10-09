-- 渠道归因收入(首触): 订单按用户注册渠道归属, 供 roas 使用。
-- 双口径声明: 本表是首触归因; 线性归因在语义层另算(channel_revenue_linear), 40% 收入不归属
select cast(o.dt as date) as dt, coalesce(u.channel, o.channel) as channel,
       sum(o.amount) filter (where not o.refund) as revenue_attr
from {{ ref('dwd_order') }} o left join {{ ref('dwd_user') }} u using (user_id)
group by 1, 2
