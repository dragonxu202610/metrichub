-- 口径守恒(现金): dws_cash_day 必须精确等于订单表的非退款聚合(同一表达式, 无容差)。
-- 意义: 现金是毛利与 ARPPU 的共同分母, 它若与订单明细脱钩, 所有收入类指标同时失真。
select c.dt, c.cash_usd, o.rev
from {{ ref('dws_cash_day') }} c
join (select cast(dt as date) as dt, sum(amount) filter (where not refund) as rev
      from {{ ref('dwd_order') }} group by 1) o using (dt)
where c.cash_usd is distinct from round(o.rev, 2)
