-- 付费留存(周环比): 上周付费的人里, 本周仍付费的比例。
-- 分子必须是"两周都付费"的用户(paid_cur AND paid_prev)。若误写成"本周所有付费用户",
-- 增长期该比率会 >100% —— 护栏把坏消息吃掉是最不能犯的错。
-- 按套餐分列, 否则该指标没有任何维度、语义层页展开会是空壳。
-- 注意: 该表是"按 plan 聚合后的单日快照", 不再支持逐日序列(窗口粒度), 故 series_grain=none。
-- "本周/上周"的锚同样用 var(anchor_date), 不用 current_date(理由同 dwd_user.age_days)。
{% set anchor %}date '{{ var("anchor_date") }}'{% endset %}
with orders as (select user_id, plan, cast(dt as date) as d
                from {{ ref('dwd_order') }} where not refund),
     cur_plan as (select user_id, arg_max(plan, d) as plan from orders group by 1),
     flags as (select user_id,
                      max(case when d > {{ anchor }} - 7 then 1 else 0 end) as paid_cur,
                      max(case when d > {{ anchor }} - 14 and d <= {{ anchor }} - 7 then 1 else 0 end) as paid_prev
               from orders group by 1)
select {{ anchor }} as dt, p.plan,
       count(*) filter (where f.paid_cur = 1 and f.paid_prev = 1) as retained,
       count(*) filter (where f.paid_prev = 1) as prev_payers
from flags f join cur_plan p using (user_id)
group by p.plan
