-- 渠道一致性(字典收口): 全部事实表的 channel 只允许 dim_channel 字典内的值。
-- 意义: 渠道清单曾经散落三处(sources.yml accepted_values / 模拟器常量 / 各表字段)各自维护 ——
-- 新增渠道时漏改任何一处就会出现"投放表里有、字典里没有"的孤儿渠道, ROAS/归因静默漏算。
-- 这条断言把"清单一致"从人肉核对变成构建期硬门禁(配合 check.py 的 seed×模拟器断言形成闭环)。
select 'dwd_user' as src, channel from {{ ref('dwd_user') }}
  where channel not in (select channel from {{ ref('dim_channel') }})
union all
select 'dwd_spend', channel from {{ ref('dwd_spend') }}
  where channel not in (select channel from {{ ref('dim_channel') }})
union all
select 'dwd_order', channel from {{ ref('dwd_order') }}
  where channel not in (select channel from {{ ref('dim_channel') }})
union all
select 'dwd_touch', channel from {{ ref('dwd_touch') }}
  where channel not in (select channel from {{ ref('dim_channel') }})
