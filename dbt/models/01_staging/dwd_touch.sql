-- 注册前触点(直通落地): 线性归因的分母。已知缺陷: 无时间戳, 无法做时效衰减
select * from {{ source('raw', 'touch') }}
