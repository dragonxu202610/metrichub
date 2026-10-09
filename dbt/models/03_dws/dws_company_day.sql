-- 公司级毛利: 全模型汇总(模型域/CEO 视角, 口径与 model_gross_margin 完全一致, 只是不按模型分组)
select dt, sum(revenue_usd) as revenue_usd, sum(api_cost_usd) as api_cost_usd
from {{ ref('dws_model_day') }} group by dt
