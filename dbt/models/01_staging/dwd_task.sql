-- 生成任务明细(直通落地), 模型毛利与北极星体系的事实底座
select * from {{ source('raw', 'tasks') }}
