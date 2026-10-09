-- ROAS 视图: 收入归因 + 花费对齐到同一张日表(FULL JOIN: 有花费无收入、有收入无花费都保留)
select coalesce(a.dt, s.dt) as dt, coalesce(a.channel, s.channel) as channel,
       coalesce(s.spend, 0) as spend, coalesce(a.revenue_attr, 0) as revenue_attr
from {{ ref('dws_channel_attr') }} a full join {{ ref('dws_channel_day') }} s
  on cast(s.dt as date) = a.dt and s.channel = a.channel
