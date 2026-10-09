-- 渠道花费(直通落地): 只覆盖 5 个有投放的渠道, 其余渠道 ROAS 分母为 nullif 保护的空
select * from {{ source('raw', 'spend') }}
