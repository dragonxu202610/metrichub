-- 模型日汇总(毛利指标的 basis): 成本=成功秒数×厂商单价; 收入=当日现金按消耗积分占比分摊
with base as (
  select t.dt, t.model, mc.api_cost_s,
         count(*) as calls, count(*) filter (where t.success) as success_calls,
         sum(t.credits) as credits_used,
         round(sum(t.seconds) * mc.api_cost_s, 2) as api_cost_usd
  from {{ ref('dwd_task') }} t left join {{ ref('dim_model_cost') }} mc using (model)
  group by t.dt, t.model, mc.api_cost_s
),
day_tot as (select dt, sum(credits_used) as tot from base group by dt)
select b.dt, b.model, b.calls, b.success_calls,
       round(coalesce(c.cash_usd, 0) * b.credits_used / greatest(d.tot, 1), 2) as revenue_usd,
       b.api_cost_usd
from base b
left join day_tot d on d.dt = b.dt
left join {{ ref('dws_cash_day') }} c on c.dt = cast(b.dt as date)
