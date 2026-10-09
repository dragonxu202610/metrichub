-- 用户宽表: 一次性派生活跃/付费/留存/TTFC 等"指标原料"(让语义层 expr 保持简单)。
-- 口径坑记录(从旧 ELT 原样搬运, 每条都是真实修过的):
--   · TTFC 用带分钟精度的 ts(此前用日期相减, 结果只有 0 或 1440, "分钟中位数"退化成布尔量)
--   · 次日留存必须是"次日当天"有活动。旧口径用 max(dt) >= signup+1, 那是"D1 或以后任意一天"
--     (无界滚动留存), 会把 14 天后才回来的人也算进次日留存 —— 实测 84.2%, 而真值只有 48.1%。
--   · age_days 的"今天"不用 current_date: 演示窗口锚定在 simulator.ANCHOR,
--     跟 runner 的时区/日期走会让产物漂移 —— 由 build.py 以 --vars 传入, 显式进模型。
with u as (select * from {{ source('raw', 'users') }}),
     first_ok as (
         select user_id, min(cast(ts as date)) as fd,
                min(cast(ts as timestamp)) as first_ts
         from {{ ref('dwd_task') }} where success group by 1),
     pay as (select user_id, count(*) as n from {{ ref('dwd_order') }} where not refund group by 1),
     d1 as (
         select distinct e.user_id
         from {{ ref('dwd_event') }} e join u on u.user_id = e.user_id
         where cast(e.dt as date) = cast(u.signup_dt as date) + 1)
select u.user_id, u.signup_dt, u.channel, u.channel_type, u.country, u.platform,
       cast(u.signup_dt as date) as signup_date,
       (f.fd = u.signup_dt)                                   as activated_1d,
       (f.fd <= cast(u.signup_dt as date) + 6)                as activated_7d,
       date_diff('minute', cast(u.signup_dt as date)::timestamp, f.first_ts) as ttfc_min,
       (d1.user_id is not null)                               as retained_d1,
       date_diff('day', cast(u.signup_dt as date), date '{{ var("anchor_date") }}') as age_days,
       (p.n is not null) as ever_paid
from u
left join first_ok f using (user_id)
left join d1 on d1.user_id = u.user_id
left join pay p on p.user_id = u.user_id
