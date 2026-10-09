-- 口径守恒(分摊): dws_model_day 每日 revenue_usd 之和必须回到当日实收现金。
-- 这条断言守住的是"收入按积分占比分摊"的口径 —— 若有人改了分摊公式(分母换错、
-- 漏 join 当日现金), 毛利率会静默漂移, 而看板上它只是"变了一点"。
-- 容差 0.05: 每模型 round(...,2) 最多偏 0.005, 8 个模型累计上限 0.04(实测最大 0.01)。
select m.dt, m.rev, c.cash_usd, m.rev - c.cash_usd as gap
from (select dt, sum(revenue_usd) as rev from {{ ref('dws_model_day') }} group by 1) m
join {{ ref('dws_cash_day') }} c using (dt)
where abs(m.rev - c.cash_usd) > 0.05
