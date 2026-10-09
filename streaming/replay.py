# -*- coding: utf-8 -*-
"""
MetricHub 流式最小样例(演示级, 纯 Python 标准库)
================================================
目的: 把"流式口径 vs 批口径"的偏差做成**可量化、可复现**的实验, 而不是一句"大致相同"。
这回答的是 JD 里实时计算(Flink)那条职责最容易被追问的问题:
窗口/乱序/迟到不是概念名词, 它们各自对应一种**具体的数字偏差**。

做法: 把任务流(tasks.jsonl, 带分钟级 ts)中锚定日前 3 天的部分重放为加速事件流。
  · 到达时间 = 事件时间 + 注入延迟: 大多数 30 秒内; 6% 排队堆积 5~45 分钟; 0.3% 边缘重试 2~6 小时
    (真实流里"秒级抖动 + 少量堆积 + 极端重试"是常见形态, 全局乱序反而少见)
  · 同一份数据, 三种口径各算一遍:
      batch    批精确: 按事件时间分桶 —— 数仓离线口径, 全量可见、永远正确
      wm       事件时间 + 有界乱序 watermark(45 分钟): 窗口在 watermark 越过末端时关闭,
               已关窗口的迟到事件不进任何窗口, 计入 dropped_too_late(Flink: 侧输出)
      arrival  纯到达序: 事件计入**到达时刻**所在窗口(无事件时间语义的处理时间窗口)
  · 两种偏差模式不同: watermark 语义下是"丢弃"(总数少), 到达序是"错配"(总数不变但放错窗口)。

产出 dict(窗口级三口径 + 汇总), 由 build.py 落盘 out/api/stream_compare.json。
守恒断言(在本模块内 assert): wm_total + dropped == batch_total; arrival_total == batch_total。

为什么不用真 Flink: 本样例的目的是把口径问题讲清楚并量化偏差, 不是假装有一条生产流。
同一逻辑到 Flink 的原语映射表见 site/realtime.html; 生产链路(Kafka→Flink→OLAP)设计在 PLAN-90D。
确定性: 延迟注入用固定种子, 任何机器重放结果逐字段一致(与全站"可复现"纪律一致)。
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
SEED = 20261008
SCOPE_DAYS = 3          # 取锚定日前 3 天(72 个小时窗口, 够画图且不稀释重点)
WINDOW_MIN = 60         # 滚动窗口 1 小时(tumbling window)
LATENESS_MIN = 45       # watermark 的有界乱序容忍(对应 forBoundedOutOfOrderness)
BACKLOG_SHARE = 0.06    # 排队堆积延迟占比(5~45 分钟) —— watermark 容忍范围内, 不丢
BACKLOG_MIN, BACKLOG_MAX = 5, 45
EDGE_SHARE = 0.003      # 边缘重试延迟占比(2~6 小时) —— 超出容忍, 必然迟到被丢
EDGE_MIN, EDGE_MAX = 120, 360


def _arrival_delay_sec(rng):
    """到达延迟(秒): 三段式。全部用同一 rng, 消费顺序即重放顺序, 保证确定性。"""
    r = rng.random()
    if r < EDGE_SHARE:
        return rng.uniform(EDGE_MIN, EDGE_MAX) * 60
    if r < EDGE_SHARE + BACKLOG_SHARE:
        return rng.uniform(BACKLOG_MIN, BACKLOG_MAX) * 60
    return rng.uniform(0, 30)


def _load_scope_events():
    import simulator
    days = {(simulator.ANCHOR - timedelta(days=i)).isoformat() for i in range(SCOPE_DAYS)}
    events = []
    with open(ROOT / "data" / "tasks.jsonl", encoding="utf-8") as f:
        for ln in f:
            t = json.loads(ln)
            if t["dt"] in days:
                events.append(datetime.fromisoformat(t["ts"]))
    return events


def replay():
    """单遍重放三口径。返回可直接 json 化的 dict(守恒断言在内)。"""
    events = _load_scope_events()
    rng = random.Random(SEED)
    tagged = [{"ts": ts, "arrival": ts + timedelta(seconds=_arrival_delay_sec(rng))}
              for ts in events]
    # 流按到达时间过(排队语义); 同刻按事件时间稳定排序, 保证任何机器上顺序一致
    stream = sorted(tagged, key=lambda e: (e["arrival"], e["ts"]))

    def wkey(dt):   # 窗口起点: 整点
        return dt.replace(minute=0, second=0, microsecond=0)

    batch, wm, arrival = {}, {}, {}
    dropped = 0
    wm_clock = None                                  # watermark = 已见最大事件时间 - 容忍
    for e in stream:
        k = wkey(e["ts"])
        batch[k] = batch.get(k, 0) + 1
        cand = e["ts"] - timedelta(minutes=LATENESS_MIN)
        if wm_clock is None or cand > wm_clock:      # 水位单调推进(迟到事件不拉低水位)
            wm_clock = cand
        if k + timedelta(minutes=WINDOW_MIN) <= wm_clock:
            dropped += 1                             # 窗口已关 → 侧输出, 不进任何窗口
        else:
            wm[k] = wm.get(k, 0) + 1
        ka = wkey(e["arrival"])
        arrival[ka] = arrival.get(ka, 0) + 1

    keys = sorted(set(batch) | set(wm) | set(arrival))
    b_tot, w_tot, a_tot = sum(batch.values()), sum(wm.values()), sum(arrival.values())
    # 守恒: watermark 语义"要么计数要么显式丢弃", 到达序"不丢但可能错窗"
    assert w_tot + dropped == b_tot, f"wm 口径不守恒: {w_tot}+{dropped}!={b_tot}"
    assert a_tot == b_tot, f"arrival 口径不守恒: {a_tot}!={b_tot}"
    # 错窗数: 两口径总数相同, 每条错窗事件造成一增一减 → 差值绝对值之和的一半
    misplaced = sum(abs(batch.get(k, 0) - arrival.get(k, 0)) for k in keys) // 2
    return {
        "windows": [{"win": k.isoformat(), "batch": batch.get(k, 0),
                     "wm": wm.get(k, 0), "arrival": arrival.get(k, 0)} for k in keys],
        "stats": {"scope_days": SCOPE_DAYS, "window_min": WINDOW_MIN,
                  "lateness_min": LATENESS_MIN, "backlog_share": BACKLOG_SHARE,
                  "edge_share": EDGE_SHARE, "batch_total": b_tot, "wm_total": w_tot,
                  "wm_dropped": dropped, "arrival_total": a_tot, "misplaced": misplaced},
    }


if __name__ == "__main__":
    r = replay()
    print(json.dumps(r["stats"], ensure_ascii=False, indent=2))
