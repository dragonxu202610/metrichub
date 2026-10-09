# -*- coding: utf-8 -*-
"""
MetricHub 一键构建
==================
python build.py            # 数据→dbt 数仓(模型+行级测试)→语义层查询→静态站导出 out/
python build.py --fresh    # 强制重放模拟数据
产出:
  data/metrichub.duckdb    轻量仓(dbt: staging/DWD/DWS 模型 + 测试, 幂等, 单线程可复现)
  out/                     可部署静态站(GitHub Pages): api/*.json + 页面
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb

import simulator
from semantic import SemanticLayer
from streaming.replay import replay as stream_replay

ROOT = Path(__file__).parent
OUT = ROOT / "out"


def _finite(obj):
    """递归把 inf / nan 压成 None。"""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


def write_json(path, obj, indent=1):
    """写产物 JSON 前先把 inf/nan 压成 null。

    json.dumps 默认**允许** inf/nan 并写出 `Infinity` / `NaN` —— 那是非法 JSON,
    前端 fetch().json() 会直接抛错(整页白屏)。比率类指标的分母为 0 时 DuckDB 返回 inf,
    所以这不是理论风险: arppu 在窗口内没有付费用户时就会命中。
    真正的修法是每个比率都写 nullif(分母, 0)(见 metrics.yaml); 这里是第二道防线,
    保证无论哪个指标将来漏了, 产物也不会变成非法 JSON。
    """
    path.write_text(json.dumps(_finite(obj), ensure_ascii=False, indent=indent, default=str),
                    encoding="utf-8")

# 可加性声明: 只有"按天相加 == 窗口聚合"的指标才允许把逐日点求和成窗口值。
# 比率类(30% + 40% = 70% 显然错)与去重类(DAU 求和无意义)一律走窗口内聚合。
# 权威来源是 metrics.yaml 的 additivity 字段(DERIVED 只是兼容兜底, 供新指标接入前使用)。
DERIVED_ADDITIVE = {
    "weekly_successful_creations", "daily_successful_creations", "weekly_minutes_generated",
    "minutes_generated", "first_day_creations", "new_users", "revenue_daily",
    "channel_revenue_first_touch", "channel_revenue_linear", "balance_capped_revenue_gap",
}
ADDITIVE_METRICS = DERIVED_ADDITIVE      # main() 里会用 YAML 覆盖
# 窗口口径指标要画逐日形态时, 用哪个日粒度指标做基础
DAILY_BASE = {
    "weekly_successful_creations": "daily_successful_creations",
    "weekly_minutes_generated": "minutes_generated",
}
WINDOWS = {"1d": 1, "7d": 7, "14d": 14, "30d": 30}


def _daily_base(name):
    return DAILY_BASE.get(name, name)


def series_for(sl, name, metric, window="14d"):
    """同一指标名的"序列形态"。关键: **可加性决定画法**, 不是 grain 决定画法 ——
      - 日粒度指标            → 逐日值
      - 窗口粒度 + 可加(流量类) → 按日重算的滚动窗口**求和**(如周成功创作数 = 滚动 7 日累计)
      - 窗口粒度 + 不可加(比率) → 按日重算的滚动窗口**均值**(比率求和无意义: 40%×14=560% 是错的)
      - 去重类(rolling_distinct_on) → 用窗口函数按日重算滚动去重(逐日点不可相加)
    返回 (rows, note)。看板与语义层页共用, 保证两处算法一致。"""
    m = metric or sl.metrics[name]
    additive = m.get("additivity", "non_additive") == "additive"
    if m.get("rolling_distinct_on"):
        return _rolling_distinct(sl, name, m, window)
    if m.get("grain", "window") == "daily":
        return sl.query(name, window=window, granularity="daily")["rows"], "逐日值"
    daily = sl.query(_daily_base(name), window=window, granularity="daily")["rows"]
    w = WINDOWS.get(m.get("default_time", "14d"), 7)
    run, out = [], []
    for r in daily:
        run.append(r["value"] or 0)
        seg = run[-w:]
        out.append({"dt": r["dt"], "value": (sum(seg) if additive else round(sum(seg) / len(seg), 2))})
    kind = "求和" if additive else "均值"
    return out, f"滚动 {m.get('default_time', '14d')} 窗口{kind}（按日重算）"


def _rolling_distinct(sl, name, m, window="14d"):
    """去重类指标的逐日形态: **每个输出日都重算"过去 w 天内的去重人数"**。
    不能先按日去重、再把每天的人头相加 —— 那是"人·天"不是人数:
    实测会把北极星 4,278 人显示成 7,142, 同一份 dashboard.json 里 KPI 与折线自相矛盾。
    逐日点相加没有意义(DAU 求和无意义), 但"每天各是多少"正是趋势图要的。"""
    dc = m.get("date_field", "dt")
    col = m["rolling_distinct_on"]
    w = WINDOWS.get(m.get("default_time", "7d"), 7)
    end = simulator.ANCHOR
    start = end - timedelta(days=WINDOWS.get(window, 14) - 1)
    cond = "WHERE success" if "FILTER (WHERE success)" in m["expr"] else ""
    # ① person_day: (日期, 用户) 去重 —— 同一人一天只算一次;
    # ② spine: 有活动的日期序列;
    # ③ 每个输出日回看 w 天, 对 uid 做 count(DISTINCT): 去重发生在窗口上, 不是把人头相加。
    sql = (f"WITH person_day AS (SELECT DISTINCT CAST({dc} AS DATE) AS dt, {col} AS uid "
           f"FROM {m['basis']} {cond}), "
           f"spine AS (SELECT DISTINCT dt FROM person_day) "
           f"SELECT s.dt AS dt, count(DISTINCT p.uid) AS value "
           f"FROM spine s JOIN person_day p "
           f"ON p.dt BETWEEN s.dt - INTERVAL {w - 1} DAY AND s.dt "
           f"WHERE s.dt BETWEEN DATE '{start}' AND DATE '{end}' "
           f"GROUP BY s.dt ORDER BY s.dt")
    rows = sl.con.execute(sql).fetchall()
    out = [{"dt": r[0], "value": int(r[1])} for r in rows]
    return out, f"滚动 {m.get('default_time', '7d')} 窗口去重（按输出日重算, 非逐日相加）"


# ---------- ELT: 原始 JSONL → DWD/DWS ----------
# 数仓层已 dbt 化(见 dbt/ 目录): 模型文件化(staging/DWD/DWS)、行级测试(schema.yml)、
# 血缘(ref() DAG)。旧版是本文件里一段 SQL 字符串常量 —— 无模型级测试、血缘靠人脑记,
# 迁移原则是**等价替换**: 表名/口径/注释原样搬运, 迁移前后 out/api/*.json 必须逐字节一致。
def run_dbt(anchor):
    """dbt build = seed + 全部模型 + 全部行级测试。测试不过返回非零 → 构建失败(门禁前移到构建期)。
    anchor 以 --vars 显式传入, 取代旧版 "ELT.replace('current_date', ...)" 的跑前字符串替换 ——
    口径参数进模型文本, 而不是运行时偷偷改 SQL。确定性由 profiles.yml 的两处 threads=1 保证。"""
    cmd = [sys.executable, "-m", "dbt.cli.main", "build",
           "--project-dir", str(ROOT / "dbt"), "--profiles-dir", str(ROOT / "dbt"),
           "--vars", json.dumps({"anchor_date": anchor.isoformat()}),
           "--no-use-colors"]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    done = [ln for ln in r.stdout.splitlines() if "PASS" in ln or "DONE" in ln]
    print(f"[dbt] {len(done)} 项 seed/模型/测试通过")
    if r.returncode != 0:
        print(r.stdout[-6000:])
        print(r.stderr[-2000:])
        raise RuntimeError("dbt build 失败(模型编译或行级测试未过) —— 见上方日志")

AI_DEMO = [
    {"q": "上周有多少付费用户？",
     "metric": "paying_users", "dims": [], "window": "7d",
     "bare_sql_risk": "裸 text-to-SQL 会猜: payers? subscribers? 含不含退款? 含不含 App? —— 四种口径四个数"},
    {"q": "哪个模型在亏钱？",
     "metric": "model_gross_margin", "dims": ["model"], "window": "14d",
     "bare_sql_risk": "裸 SQL 不知道收入要按积分折算、成本按厂商单价 —— 会漏掉分摊规则, 毛利算错"},
    {"q": "SEO 带来的注册占比是多少？",
     "metric": "seo_signup_share", "dims": [], "window": "7d",
     "bare_sql_risk": "SEO 的定义(哪些渠道算 seo?)不在 schema 里, LLM 只能猜渠道清单"},
    {"q": "最近两周按国家看付费用户人均收入",
     "metric": "arppu", "dims": ["country"], "window": "14d",
     "bare_sql_risk": "默认时间窗/退款口径/去重逻辑全是隐式默认, 每次生成的 SQL 都可能不同"},
    {"q": "次留怎么样？",
     "metric": "retention_d1", "dims": [], "window": "14d",
     "bare_sql_risk": "『次日』的分母要排除不满 1 天的新 cohort —— 这类陷阱 LLM 不知道"},
]


def run_dbt_docs():
    """dbt docs generate --static: 自包含单文件血缘图(模型 DAG/列级文档/测试挂载), 发布到 out/dbt-docs/。
    旧版血缘隐含在 ELT 的书写顺序里(要靠人脑排依赖), 现在是 ref() 声明的显式 DAG, 可点开验证。"""
    cmd = [sys.executable, "-m", "dbt.cli.main", "docs", "generate", "--static",
           "--project-dir", str(ROOT / "dbt"), "--profiles-dir", str(ROOT / "dbt"),
           "--no-use-colors"]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-2000:])
        raise RuntimeError("dbt docs generate 失败 —— 见上方日志")
    dst = OUT / "dbt-docs" / "index.html"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "dbt" / "target" / "static_index.html", dst)
    print(f"[dbt] 血缘图(可点 DAG) → {dst.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    if args.fresh or not (ROOT / "data" / "users.jsonl").exists():
        simulator.main()

    # 数仓层交给 dbt(模型 + 行级测试, 测试不过直接失败); 单线程确定性在 profiles.yml 里钉死
    run_dbt(simulator.ANCHOR)
    con = duckdb.connect(str(ROOT / "data" / "metrichub.duckdb"))
    # 语义层查询同样单线程: DuckDB 默认按 CPU 核数并行做 hash 聚合, 而浮点加法不满足结合律 ——
    # 同一份数据、同一份 SQL, 求和顺序随线程调度变化, round(...,1) 就会在边界上翻
    # (实测 model_gross_margin 的日序列在 -8.6 / -8.7 之间跳)。产物必须逐字节可复现:
    # 页面上的数字是随源码提交的, 产物漂移会让"每个数字可复现"这句话不成立。
    con.execute("SET threads TO 1")
    sl = SemanticLayer(con=con, anchor=simulator.ANCHOR)
    # 可加性以 YAML 为准(单一事实源); DERIVED_ADDITIVE 仅作兼容兜底
    ADDITIVE_METRICS = {n for n, mm in sl.metrics.items()
                        if mm.get("additivity", "additive" if n in DERIVED_ADDITIVE else "non_additive")
                        == "additive"}

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "api").mkdir(parents=True)

    # 1) 指标目录(语义层页渲染用) —— 含 grain 语义(窗口内单值 / 逐日值), 消费端据此解释数字
    write_json(OUT / "api" / "catalog.json", sl.catalog())

    # 1.5) 流批对账(流式最小样例, 演示级): 三口径同一份重放数据, 守恒断言在 replay() 内部。
    #      页面 headline 数字以占位符渲染进 realtime.html, 与产物同源不漂移。
    stream_cmp = stream_replay()
    write_json(OUT / "api" / "stream_compare.json", stream_cmp)

    # 2) 每指标: 序列 + 各维度分解(语义层页"试一试"控制台的数据源)
    #    粒度规则(修掉的口径缺陷): grain=daily 的指标序列 = 逐日值;
    #    grain=window 且 sequence 需要日期的指标 = 按日重算窗口值(滚动), 例如"周成功创作数"
    #    的逐日形态就是滚动 7 日累计, 而不是"14 天里每个窗口名一个数".
    #    series_grain=none 的去重/比率类不做逐日拆分: 拆分在语义上就是错的.
    for name, m in sl.metrics.items():
        sgrain = m.get("series_grain", "daily")
        mwin = m.get("default_time", "14d")
        if sgrain == "none":
            # 去重/比率类不给日序列, 但维度分解照给(窗口内聚合)—— 两者是独立能力
            series, series_note = [], "不提供（窗口内聚合/去重口径，逐日拆分语义不成立）"
            notice = "该指标为窗口内聚合或去重/比率口径, 逐日拆分在语义上不成立, 故不提供日序列。"
        else:
            series, series_note = series_for(sl, name, m)
            notice = ""
        by_dim = {}
        by_dim_sums_daily = name in ADDITIVE_METRICS and sgrain != "none"   # 与下方查询同一判据
        for dim in m.get("dimensions", [])[:3]:
            # 维度分解 = 窗口内单值; 对非可加指标(比率/去重)直接取窗口聚合, 不做逐日求和
            if by_dim_sums_daily:
                agg = {}
                for r in sl.query(name, dims=[dim], window="14d", granularity="daily")["rows"]:
                    agg[str(r[dim])] = agg.get(str(r[dim]), 0) + (r["value"] or 0)
            else:
                agg = {str(r[dim]): (r["value"] or 0)
                       for r in sl.query(name, dims=[dim], window="14d", granularity="window")["rows"]}
            by_dim[dim] = [{"key": k, "value": round(v, 2)}
                           for k, v in sorted(agg.items(), key=lambda x: -x[1])[:8]]
        write_json(OUT / "api" / f"metric_{name}.json",
                   {"name": name, "grain": m.get("grain", "window"), "series_grain": sgrain,
                    "series_window": mwin, "series_note": series_note, "notice": notice,
                    "by_dim_window": "14d",
                    "by_dim_basis": "逐日求和" if by_dim_sums_daily else "窗口内聚合",
                    "series": series, "by_dim": by_dim}, indent=None)

    # 3) 看板视图模型
    #    角色标注: 北极星 = 周活跃创作者数(人); 次数/分钟数是配对与消耗口径(见「北极星审计」页)
    KPI_ROLES = {
        "active_creators": "北极星",
        "creations_per_active_user": "配对·深度",
        "weekly_successful_creations": "消耗·次数",
        "weekly_minutes_generated": "消耗·分钟",
        "retention_d1": "队列质量",
        "payer_retention_wow": "护栏·续费",
        "company_gross_margin": "护栏·毛利",
        "balance_capped_revenue_gap": "护栏·收入缺口",
        "high_cost_exposure": "护栏·成本档",
    }

    def kpi(name, win):
        m = sl.metrics[name]
        k = {"metric": name, "title": m["title"], "unit": m.get("unit"),
             "value": round(sl.scalar(name, win), 1), "window": win}
        if name in KPI_ROLES:
            k["role"] = KPI_ROLES[name]
        # 队列成熟度: 窗口末日的 cohort 尚未走完观察期 → 显式标注, 避免"无数据"被读成"暴跌"
        if m.get("cohort_maturity_days"):
            k["immature_last_cohort"] = True
            k["maturity_note"] = f"末日 Cohort 观察期未满 {m['cohort_maturity_days']} 天"
        return k

    dash = {
        "generated_at": str(simulator.ANCHOR),
        # as_of: 有些指标(如付费留存)是"构建日快照", 页面必须同时展示 as-of, 否则"近14天"会失真
        "as_of": str(simulator.ANCHOR),
        "kpis": [kpi("active_creators", "7d"), kpi("creations_per_active_user", "7d"),
                 kpi("weekly_successful_creations", "7d"), kpi("weekly_minutes_generated", "7d"),
                 kpi("payer_retention_wow", "14d"), kpi("company_gross_margin", "14d"),
                 kpi("balance_capped_revenue_gap", "14d"), kpi("high_cost_exposure", "14d")],
        "charts": {
            # 北极星趋势: 优先用北极星的滚动去重序列 —— "人"必须有线, 不能只有一个点
            "creators_7d": (series_for(sl, "active_creators", None)[0]
                            if sl.metrics["active_creators"].get("rolling_distinct_on") else []),
            # 消耗口径: 逐日成功创作数(日粒度) + 滚动 7 日累计(窗口粒度)
            "creations": series_for(sl, "daily_successful_creations", None)[0],
            "creations_7d": series_for(sl, "weekly_successful_creations", None)[0],
            "minutes": series_for(sl, "minutes_generated", None)[0],
            "minutes_7d": series_for(sl, "weekly_minutes_generated", None)[0],
            "dau": series_for(sl, "dau", None)[0],
            "new_users": series_for(sl, "new_users", None)[0],
            "revenue": series_for(sl, "revenue_daily", None)[0],
        },
        "tables": {
            # 表口径是"窗口内单值": 显式 granularity=window, 不能吃指标默认粒度
            "model_margin": sl.query("model_gross_margin", dims=["model"], window="14d", granularity="window")["rows"],
            "model_success": sl.query("model_success_rate", dims=["model"], window="14d", granularity="window")["rows"],
        },
    }
    ft = {r["channel"]: r["value"] for r in sl.query("channel_revenue_first_touch", dims=["channel"], window="14d", granularity="window")["rows"]}
    ln = {r["channel"]: r["value"] for r in sl.query("channel_revenue_linear", dims=["channel"], window="14d", granularity="window")["rows"]}
    cac = {r["channel"]: r["value"] for r in sl.query("cac", dims=["channel"], window="14d", granularity="window")["rows"]}
    nu = {r["channel"]: r["value"] for r in sl.query("new_users", dims=["channel"], window="14d", granularity="window")["rows"]}
    # 北极星按渠道拆: 让"哪个渠道带来更多创作者"出现在决策页面, 而不是只躺在语义层页
    ac = {r["channel"]: r["value"] for r in sl.query("active_creators", dims=["channel"], window="14d", granularity="window")["rows"]}
    dash["tables"]["channels"] = [
        {"channel": c, "new_users": round(nu.get(c, 0)), "active_creators": round(ac.get(c, 0)),
         "first_touch": round(ft.get(c, 0)),
         "linear": round(ln.get(c, 0)), "cac": round(cac.get(c, 0), 1)}
        for c in sorted(set(ft) | set(nu) | set(ac))]
    write_json(OUT / "api" / "dashboard.json", dash)

    # 4) AI 演示(L1上下文 + L2工具调用 预计算)
    demo = []
    for item in AI_DEMO:
        r = sl.query(item["metric"], dims=item["dims"], window=item["window"], granularity="window")
        demo.append({**item, "context": sl.ai_context([item["metric"]]),
                     "tool_call": {"tool": "query_metric", "arguments": {
                         "metric": item["metric"], "dimensions": item["dims"],
                         "time_range": item["window"], "granularity": "window"}},
                     "sql": r["sql"], "rows": r["rows"][:8]})
    write_json(OUT / "api" / "ai_demo.json", demo)

    con.close()

    # 5) 静态站页面 —— 复制并把 __METRIC_COUNT__ 之类占位符渲染成真实数字,
    #    避免"加了指标忘了改文案"这类漂移(此前 20 这个数字硬编码在 3 个页面里).
    shutil.copytree(ROOT / "site", OUT, dirs_exist_ok=True)
    run_dbt_docs()
    ss = stream_cmp["stats"]
    tokens = {"__METRIC_COUNT__": str(len(sl.metrics)),
              "__STREAM_BATCH__": f"{ss['batch_total']:,}",
              "__STREAM_DROPPED__": str(ss["wm_dropped"]),
              "__STREAM_MISPLACED__": str(ss["misplaced"])}
    # 占位符渲染范围: 交付目录的 html + 仓库级 README(README 不发布, 但指标数是给人看的门面)。
    # README 的源就是仓库里的 README.md 本身, 所以渲染时把"字面量"回写成占位符形态再渲染 ——
    # 既保持源码里始终是 __METRIC_COUNT__(避免下次改指标数时源码与产物不一致), 又不必来回改写文件。
    for page in list(OUT.glob("*.html")) + [ROOT / "README.md"]:
        raw = page.read_text(encoding="utf-8")
        text = re.sub(r"\d+(\s*)(?=个业务指标|个指标目录|指标定义)", r"__METRIC_COUNT__\1", raw)
        for token, value in tokens.items():
            text = text.replace(token, value)
        if text != raw:
            page.write_text(text, encoding="utf-8")
    # 渲染后必须不留占位符(替换前检查"有没有 token"是反的: 那会在成功时报错、失败时沉默)
    leftover = []
    for page in list(OUT.glob("*.html")) + [ROOT / "README.md"]:
        found = re.findall(r"__[A-Z][A-Z_]*__", page.read_text(encoding="utf-8"))
        if found:
            leftover.append(f"{page.name}:{sorted(set(found))}")
    if leftover:
        # 占位符没渲染 = 页面会漏出 __METRIC_COUNT__ 这种东西, 必须让 CI 失败而不是只打日志
        raise RuntimeError(f"存在未渲染占位符: {leftover}")
    print(f"[build] 指标{len(sl.metrics)}个 → {OUT}/ (api + 页面)")
    print(f"[build] 本地预览: python -m http.server 8898 --directory {OUT}")


if __name__ == "__main__":
    main()
