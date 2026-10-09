-- 高成本档任务占比: 按模型采购单价分档。
-- 阈值 $0.03/秒 是**经验运营阈值**, 不是从定价推导的。
-- 现金口径下本演示的平衡点 = 实收 $2,829 / 130,566 成功秒 ≈ $0.0217/秒 —— 所以 $0.03 偏保守:
-- Kling 2.5($0.022) 与 Runway($0.025) 其实已经负毛利, 却不在这条线以上(本指标只声明"高档位占比",
-- 不声明"负毛利占比")。若厂商调价或积分单价变化必须重算(生产应改为动态 break_even = 收入/成功秒数)。
-- 分母只算成功任务 —— 失败任务在模拟器里 seconds=0, 不产生厂商成本, 不应计入。
select dt,
       count(*) filter (where success and mc.api_cost_s >= 0.03) as success_high_cost,
       count(*) filter (where success and mc.api_cost_s <  0.03) as success_low_cost
from {{ ref('dwd_task') }} t join {{ ref('dim_model_cost') }} mc using (model)
group by dt
