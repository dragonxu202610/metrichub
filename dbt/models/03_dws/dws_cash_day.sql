-- 收入口径: **只认当期实收现金**(非退款订单), 再按各模型当日"消耗积分占比"分摊到模型。
-- 旧口径 revenue = 消耗积分 × $0.04 把"白送额度的燃烧"也记成了收入(14 天消耗 92,185,
-- 而已售发放只有 65,900), 使公司毛利率虚高到 33.1%, 现金口径只有 12.9% —— 护栏本身失效。
-- 改后毛利率的分母与 revenue_daily 完全对齐, 两个 unit=usd 的"收入"不再互相矛盾。
select cast(dt as date) as dt, round(sum(amount) filter (where not refund), 2) as cash_usd
from {{ ref('dwd_order') }} group by 1
