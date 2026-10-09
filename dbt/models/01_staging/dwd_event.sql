-- 事件明细(直通落地): ODS JSONL → 具名物理表。
-- 落成表而不是每次现读 JSON: read_json_auto 的类型推断只发生一次, 下游引用的是稳定 schema。
select * from {{ source('raw', 'events') }}
