-- 积分台账(直通落地): 已知缺陷见 metrics.yaml —— 台账只记发放/消耗, 无"资金来源"字段
select * from {{ source('raw', 'credits') }}
