-- 渠道日表: 花费 × 新增注册对齐到同一张日表(ROAS 的两侧)
select s.dt, s.channel, s.spend, coalesce(n.new_users, 0) as new_users
from {{ ref('dwd_spend') }} s
left join (select cast(signup_dt as date) as dt, channel, count(*) as new_users
           from {{ ref('dwd_user') }} group by 1, 2) n
  on n.dt = cast(s.dt as date) and n.channel = s.channel
