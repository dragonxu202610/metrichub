# -*- coding: utf-8 -*-
"""
MetricHub 语义层引擎(项目的灵魂, 约 116 行)
==========================================
职责: metrics.yaml → 可执行查询 + AI 可读上下文. 三件事:
  1. compile()  : 指标名 + 维度 + 时间窗 + 粒度 → SQL(口径从 YAML 编译, 不靠人记)
  2. query()    : 执行并返回结果(即 AI 的 query_metric 工具的底层)
  3. ai_context(): 生成注入 LLM prompt 的结构化上下文(L1)——
                   消灭同义词歧义/隐式默认/时间语义三类 text-to-SQL 失败根因,
                    并显式注入已知缺陷(否则会出现『人知道不可信、AI 却当结论』)
生产对应物: dbt MetricFlow(指标即代码) / Cube(语义层+API+MCP).
"""
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
WINDOWS = {"1d": 1, "7d": 7, "14d": 14, "30d": 30}


class SemanticLayer:
    def __init__(self, yaml_path=None, con=None):
        with open(yaml_path or ROOT / "metrics.yaml", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        self.metrics = {m["name"]: m for m in doc["metrics"]}
        self.con = con

    # ---------- ① 编译: 口径的唯一出口 ----------
    def compile(self, name, dims=None, window=None, end=None, extra_where=None,
                time_series=False, granularity=None):
        """granularity: 'window'(默认) = 整个窗口聚合成单值; 'daily' = 按 date_field 逐日聚合.
        二者是同一个指标名的两种语义, 消费端必须显式选择 —— 默认值取指标自身声明的 grain."""
        m = self.metrics[name]
        asked = list(dims or [])
        allowed = m.get("dimensions", [])
        # 非法维度必须报错而不是静默丢弃: 静默丢弃会让消费端拿到"没分组的总值"当成分组结果,
        # 这是架构层最危险的失败模式(错了但看起来对)。AI 调用同理。
        bad = [d for d in asked if d not in allowed]
        if bad:
            raise ValueError(f"{name}: 不支持的维度 {bad}; 可选维度={allowed or '无'}")
        dims = asked
        window = window or m.get("default_time", "14d")
        if window not in WINDOWS:
            raise ValueError(f"{name}: 不支持的时间窗 {window!r}; 可选={sorted(WINDOWS)}")
        end = end or date.today()
        start = end - timedelta(days=WINDOWS[window] - 1)
        dc = m.get("date_field", "dt")
        # 兼容历史开关: time_series=True 等价于 granularity='daily'
        g = granularity or ("daily" if time_series else m.get("grain", "window"))
        if g not in ("window", "daily"):
            raise ValueError(f"{name}: granularity={g!r} 不合法, 只能是 'window' 或 'daily'")
        if g == "daily" and m.get("series_grain") == "none":
            # 去重/比率类指标的逐日拆分语义不成立(如 DAU 求和无意义), 在引擎层拒绝
            raise ValueError(f"{name}: 该指标声明 series_grain=none(去重/比率口径), "
                             f"不支持逐日拆分; 若确需趋势请注册专门的序列指标")
        if g == "daily":
            sel = f"{dc} AS dt, " + (", ".join(dims) + ", " if dims else "")
            group = f" GROUP BY {dc}" + (f", {', '.join(dims)}" if dims else "")
            order = f"{dc}" + (f", {', '.join(dims)}" if dims else "")
        else:
            sel = (", ".join(dims) + ", ") if dims else ""
            group = f" GROUP BY {', '.join(dims)}" if dims else ""
            order = ", ".join(dims) if dims else "value DESC"
        where = f"{dc} BETWEEN DATE '{start}' AND DATE '{end}'"
        if extra_where:
            where += f" AND ({extra_where})"
        return f"SELECT {sel}{m['expr']} AS value FROM {m['basis']} WHERE {where}{group} ORDER BY {order}"

    def grain_of(self, name):
        """指标声明的默认粒度(消费端应据此解释数字, 而不是猜)"""
        return self.metrics[name].get("grain", "window")

    # ---------- ② 查询: query_metric 工具的底层 ----------
    def query(self, name, dims=None, window=None, time_series=False, granularity=None):
        sql = self.compile(name, dims, window, time_series=time_series, granularity=granularity)
        cur = self.con.execute(sql)
        cols = [d[0] for d in cur.description]
        return {"metric": name, "dimensions": dims or [],
                "granularity": granularity or ("daily" if time_series else self.grain_of(name)),
                "sql": sql, "rows": [dict(zip(cols, r)) for r in cur.fetchall()]}

    def scalar(self, name, window=None):
        """单值便捷取数(看板 KPI 用) —— 显式按窗口聚合, 不依赖指标的默认粒度"""
        rows = self.query(name, window=window, granularity="window")["rows"]
        return float(rows[0]["value"]) if rows and rows[0]["value"] is not None else 0.0

    # ---------- ③ AI 上下文: L1 注入(LM 读的是口径, 不是猜) ----------
    def ai_context(self, names=None):
        """注入给 LLM 的指标上下文。**必须带上已知缺陷**: 人在语义层页能看到 notes,
        如果 AI 看不到, 就会出现"人知道这个数不可信、AI 却拿它当结论"的分裂。"""
        picks = [self.metrics[n] for n in names] if names else list(self.metrics.values())
        lines = ["## 可用指标(调用 query_metric 工具查询, 禁止自行编写业务 SQL):"]
        for m in picks:
            lines.append(
                f"- {m['name']} | {m['title']} | {m['desc']} | "
                f"单位:{m.get('unit','count')} | 默认时间窗:{m.get('default_time','14d')}"
                f" | 粒度:{m.get('grain','window')}(window=窗口内单值/daily=逐日值, 二者不可混用)"
                f"{' | 逐日趋势:不可用(去重/比率口径)' if m.get('series_grain') == 'none' else ''}"
                f" | 可选维度:{','.join(m.get('dimensions', [])) or '无'}"
                f" | 口径版本:v{m.get('version', 1)}")
            if m.get("north_star_status") == "approved":
                lines.append("  ★ 当前公司北极星(唯一)；回答『公司北极星』类问题必须用它")
            if m.get("cohort_maturity_days"):
                lines.append(f"  ⚠ 队列成熟度: 时间窗末段尚未走完 {m['cohort_maturity_days']} 天观察期, "
                             f"末点会被系统性低估, 不得解读为下跌")
            # 已知缺陷显式注入: 关键词命中即整行带入(与人在页面上看到的 notes 同源)
            bad = [ln.strip() for ln in str(m.get("notes", "")).splitlines()
                   if any(k in ln for k in ("已知缺陷", "未实现", "退化", "失真", "不可用于", "仍缺失",
                                            "不代表", "不能直接读作", "循环", "口径争议"))]
            if bad:
                lines.append("  ⚠ 已知缺陷/争议(引用该指标前必须一起说明): " + " / ".join(bad))
        return "\n".join(lines)

    def catalog(self):
        """目录(讲解站'语义层'页渲染用)"""
        return list(self.metrics.values())
